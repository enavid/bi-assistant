from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
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
)
from app.infrastructure.db.session import get_db

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
