from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.api.schemas.eval import (
    BulkImportResult,
    EvalQuestionIn,
    EvalQuestionOut,
    EvalQuestionSetCreate,
    EvalQuestionSetOut,
    EvalRunOut,
)
from app.infrastructure.db.models import (
    EvalQuestionORM,
    EvalQuestionSetORM,
    EvalRunORM,
    EvalRunResultORM,
)
from app.infrastructure.db.session import AsyncSessionLocal, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["eval"])


# ---------------------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------------------


@router.get("/question-sets", response_model=list[EvalQuestionSetOut])
async def list_question_sets(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(EvalQuestionSetORM))).scalars().all()
    result = []
    for qs in rows:
        count = (
            await db.execute(select(func.count()).where(EvalQuestionORM.set_id == qs.id))
        ).scalar_one()
        out = EvalQuestionSetOut.model_validate(qs)
        out.question_count = count
        result.append(out)
    return result


@router.post(
    "/question-sets", response_model=EvalQuestionSetOut, status_code=status.HTTP_201_CREATED
)
async def create_question_set(body: EvalQuestionSetCreate, db: AsyncSession = Depends(get_db)):
    qs = EvalQuestionSetORM(name=body.name, description=body.description)
    db.add(qs)
    await db.flush()
    out = EvalQuestionSetOut.model_validate(qs)
    out.question_count = 0
    return out


@router.delete("/question-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question_set(set_id: str, db: AsyncSession = Depends(get_db)):
    qs = (
        await db.execute(select(EvalQuestionSetORM).where(EvalQuestionSetORM.id == set_id))
    ).scalar_one_or_none()
    if not qs:
        raise HTTPException(status_code=404, detail="Question set not found")
    await db.delete(qs)


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


@router.get("/question-sets/{set_id}/questions", response_model=list[EvalQuestionOut])
async def list_questions(set_id: str, db: AsyncSession = Depends(get_db)):
    qs = (
        await db.execute(select(EvalQuestionSetORM).where(EvalQuestionSetORM.id == set_id))
    ).scalar_one_or_none()
    if not qs:
        raise HTTPException(status_code=404, detail="Question set not found")
    rows = (
        (await db.execute(select(EvalQuestionORM).where(EvalQuestionORM.set_id == set_id)))
        .scalars()
        .all()
    )
    return [EvalQuestionOut.model_validate(r) for r in rows]


@router.post(
    "/question-sets/{set_id}/questions",
    response_model=BulkImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_import_questions(
    set_id: str,
    questions: list[EvalQuestionIn],
    db: AsyncSession = Depends(get_db),
):
    qs = (
        await db.execute(select(EvalQuestionSetORM).where(EvalQuestionSetORM.id == set_id))
    ).scalar_one_or_none()
    if not qs:
        raise HTTPException(status_code=404, detail="Question set not found")
    for q in questions:
        db.add(
            EvalQuestionORM(
                set_id=set_id,
                question_id=q.question_id,
                question=q.question,
                category=q.category,
                expected_route=q.expected_route,
                expected_status=q.expected_status,
                expected_intent=q.expected_intent,
            )
        )
    await db.flush()
    return BulkImportResult(imported=len(questions))


@router.delete(
    "/question-sets/{set_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(set_id: str, question_id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(EvalQuestionORM).where(
                EvalQuestionORM.set_id == set_id,
                EvalQuestionORM.question_id == question_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Question not found")
    await db.delete(row)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.get("/question-sets/{set_id}/runs", response_model=list[EvalRunOut])
async def list_runs(set_id: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(EvalRunORM).where(EvalRunORM.set_id == set_id))).scalars().all()
    return [EvalRunOut.model_validate(r) for r in rows]


@router.post(
    "/question-sets/{set_id}/run",
    response_model=EvalRunOut,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_run(
    set_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    qs = (
        await db.execute(select(EvalQuestionSetORM).where(EvalQuestionSetORM.id == set_id))
    ).scalar_one_or_none()
    if not qs:
        raise HTTPException(status_code=404, detail="Question set not found")

    questions = (
        (await db.execute(select(EvalQuestionORM).where(EvalQuestionORM.set_id == set_id)))
        .scalars()
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="Question set has no questions")

    run = EvalRunORM(set_id=set_id, status="pending", total=len(questions))
    db.add(run)
    await db.flush()

    from app.api.dependencies import get_hr_bi_orchestrator

    background_tasks.add_task(
        _run_evaluation_background,
        run_id=run.id,
        session_factory=AsyncSessionLocal,
        orchestrator=get_hr_bi_orchestrator(),
    )

    return EvalRunOut.model_validate(run)


@router.get("/runs/{run_id}", response_model=EvalRunOut)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = (
        await db.execute(
            select(EvalRunORM)
            .where(EvalRunORM.id == run_id)
            .options(selectinload(EvalRunORM.results))
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return EvalRunOut.model_validate(run)


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------


async def _run_evaluation_background(
    run_id: str,
    session_factory: async_sessionmaker,
    orchestrator: Any,
) -> None:
    async with session_factory() as db:
        run = (await db.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))).scalar_one()
        questions = (
            (await db.execute(select(EvalQuestionORM).where(EvalQuestionORM.set_id == run.set_id)))
            .scalars()
            .all()
        )
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await db.commit()

    passed = failed = 0

    for q in questions:
        t0 = time.perf_counter()
        error: str | None = None
        result_row: dict = {}

        try:
            response = await orchestrator.arun(q.question, execute_sql=False)
            elapsed = (time.perf_counter() - t0) * 1000
            payload = response.to_dict() if hasattr(response, "to_dict") else dict(response)
            result_row = _extract_result(payload, q, elapsed)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            error = str(exc)
            result_row = {
                "question_id": q.question_id,
                "question": q.question,
                "category": q.category,
                "actual_route": None,
                "actual_status": None,
                "actual_intent": None,
                "source": None,
                "model_called": None,
                "template_id": None,
                "sql_validator_status": None,
                "executed": False,
                "row_count": None,
                "visualization": None,
                "total_duration_ms": round(elapsed, 2),
                "passed": False,
                "trace_steps": [],
                "error": error,
                "warnings": [],
            }

        if result_row.get("passed"):
            passed += 1
        else:
            failed += 1

        async with session_factory() as db:
            db.add(EvalRunResultORM(run_id=run_id, **result_row))
            await db.commit()

    async with session_factory() as db:
        run = (await db.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))).scalar_one()
        run.status = "done"
        run.passed = passed
        run.failed = failed
        run.finished_at = datetime.now(UTC)
        await db.commit()

    logger.info("eval run %s done: passed=%d failed=%d", run_id, passed, failed)


def _extract_result(payload: dict, q: EvalQuestionORM, elapsed_ms: float) -> dict:
    ctx = payload.get("context") or {}
    traces_raw: list = ctx.get("traces") or []
    sql_plan: dict = ctx.get("sql_plan") or {}
    query_result: dict = ctx.get("query_result") or {}
    sql_validation: dict = ctx.get("sql_validation") or {}
    viz_plan: dict = ctx.get("visualization_plan") or {}

    actual_route = payload.get("route") or ""
    actual_status = payload.get("status") or ""
    actual_intent = payload.get("detected_intent") or ""

    source = sql_plan.get("source") or ""
    template_id = sql_plan.get("template_id") or sql_plan.get("report_id") or ""
    llm_meta = sql_plan.get("metadata") or {}
    model_called = llm_meta.get("model") if isinstance(llm_meta, dict) else None

    sql_validator_status = sql_validation.get("status") or ""
    if not sql_validator_status:
        for t in traces_raw:
            if t.get("step") == "sql_validator":
                sql_validator_status = t.get("status", "")
                break

    execution_status = str(query_result.get("execution_status") or "")
    executed = execution_status == "SUCCESS"
    rows = query_result.get("rows") or []
    row_count = len(rows) if executed else None

    visualization = viz_plan.get("primary_visualization") or viz_plan.get("visualization") or ""

    trace_steps = [
        {
            "step": t.get("step"),
            "status": t.get("status"),
            "duration_ms": t.get("duration_ms"),
            "decision_by": (t.get("details") or {}).get("decision_by"),
        }
        for t in traces_raw
    ]

    total_ms = sum(t.get("duration_ms", 0) for t in traces_raw)
    total_duration_ms = round(total_ms or elapsed_ms, 2)

    route_match = (actual_route == q.expected_route) if q.expected_route else None
    status_match = (actual_status == q.expected_status) if q.expected_status else None
    intent_match = (actual_intent == q.expected_intent) if q.expected_intent else None
    passed = all(v is not False for v in [route_match, status_match, intent_match])

    errors = payload.get("errors") or []

    return {
        "question_id": q.question_id,
        "question": q.question,
        "category": q.category,
        "actual_route": actual_route or None,
        "actual_status": actual_status or None,
        "actual_intent": actual_intent or None,
        "source": source or None,
        "model_called": model_called,
        "template_id": template_id or None,
        "sql_validator_status": sql_validator_status or None,
        "executed": executed,
        "row_count": row_count,
        "visualization": visualization or None,
        "total_duration_ms": total_duration_ms,
        "passed": passed,
        "trace_steps": trace_steps,
        "error": errors[0] if errors else None,
        "warnings": payload.get("warnings") or [],
    }
