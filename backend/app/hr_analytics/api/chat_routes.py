from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_hr_bi_orchestrator, get_run_query_use_case
from app.hr_analytics.api.schemas import (
    ChatSessionCreate,
    ChatSessionOut,
    ChatSessionUpdate,
    GenerateRequest,
    GenerateResponse,
    QueryRequest,
    QueryResponse,
)
from app.hr_analytics.repositories.chat_repository import ChatRepository
from app.hr_analytics.use_cases.orchestrate import HRBIOrchestrationUseCase
from app.infrastructure.db.models import ExperimentORM, ProjectORM
from app.infrastructure.db.session import get_db
from app.workspace.use_cases.run_query import RunQueryUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _repo(db: AsyncSession = Depends(get_db)) -> ChatRepository:
    return ChatRepository(db)


async def _require_session(session_id: str, repo: ChatRepository) -> object:
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions", response_model=list[ChatSessionOut], summary="List chat sessions")
async def list_sessions(repo: ChatRepository = Depends(_repo)) -> list:
    return await repo.list_sessions()


@router.post(
    "/sessions", response_model=ChatSessionOut, status_code=201, summary="Create chat session"
)
async def create_session(body: ChatSessionCreate, repo: ChatRepository = Depends(_repo)) -> object:
    return await repo.create_session(
        title=body.title, project_id=body.project_id, model_name=body.model_name
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionOut, summary="Get chat session")
async def get_session(session_id: str, repo: ChatRepository = Depends(_repo)) -> object:
    return await _require_session(session_id, repo)


@router.patch(
    "/sessions/{session_id}", response_model=ChatSessionOut, summary="Update chat session"
)
async def update_session(
    session_id: str, body: ChatSessionUpdate, repo: ChatRepository = Depends(_repo)
) -> object:
    session = await repo.update_session(
        session_id,
        title=body.title,
        project_id=body.project_id,
        model_name=body.model_name,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=204, summary="Delete chat session")
async def delete_session(session_id: str, repo: ChatRepository = Depends(_repo)) -> None:
    deleted = await repo.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatSessionOut,
    summary="Add message to session",
)
async def add_message(session_id: str, body: dict, repo: ChatRepository = Depends(_repo)) -> object:
    session = await repo.add_message(
        session_id=session_id,
        role=body.get("role", "user"),
        content=body.get("content", ""),
        sql=body.get("sql"),
        error=body.get("error"),
        query_result=body.get("query_result"),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/generate", response_model=GenerateResponse, summary="Generate SQL from question")
async def generate(body: GenerateRequest) -> GenerateResponse:
    try:
        orchestrator = get_hr_bi_orchestrator()
        uc = HRBIOrchestrationUseCase(orchestrator)
        result = await uc.generate(
            body.question,
            model=body.model_name,
            execute_sql=bool(body.execute_sql),
        )
        if not result.success:
            logger.warning(
                "generate returned non-success route=%s status=%s", result.route, result.status
            )
        return GenerateResponse(
            sql=result.sql,
            success=result.success,
            error=result.error,
            message_fa=result.message,
            route=result.route,
            status=result.status,
            detected_intent=result.detected_intent,
            warnings=result.warnings,
            traces=result.traces,
            source=result.source,
            template_id=result.template_id,
            executed=result.executed,
            row_count=result.row_count,
            model_called=result.model_called,
        )
    except Exception as exc:
        logger.error("generate failed: %s", exc, exc_info=True)
        raise


@router.post("/query", response_model=QueryResponse, summary="Execute SQL against HR database")
async def run_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    use_case: RunQueryUseCase = Depends(get_run_query_use_case),
) -> QueryResponse:
    logger.debug("run_query sql_chars=%d session_id=%s", len(body.sql), body.session_id)
    if settings.validate_sql_before_execution:
        orchestrator = get_hr_bi_orchestrator()
        validator = getattr(orchestrator, "sql_validator", None)
        if validator is not None:
            validation = validator.validate(sql=body.sql)
            vd = validation.to_dict() if hasattr(validation, "to_dict") else dict(validation)
            if not (vd.get("is_valid") and vd.get("can_execute_sql")):
                violations = vd.get("violations") or []
                msg = ", ".join(str(v) for v in violations) or vd.get("status", "invalid")
                return QueryResponse(
                    columns=[],
                    rows=[],
                    row_count=0,
                    elapsed_ms=0,
                    success=False,
                    error=f"SQL blocked: {msg}",
                )

    result = use_case.execute(body.sql)

    experiment_id = None
    if result.success and body.project_id and body.question:
        exp = use_case.build_experiment(body.question, body.sql, result)
        if exp:
            r = await db.execute(select(ProjectORM).where(ProjectORM.id == body.project_id))
            if r.scalar_one_or_none():
                orm_exp = ExperimentORM(
                    project_id=body.project_id,
                    question=exp.question,
                    sql_output=exp.sql_output,
                    correct=exp.correct,
                    elapsed_ms=exp.elapsed_ms,
                )
                db.add(orm_exp)
                await db.flush()
                experiment_id = orm_exp.id

    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        elapsed_ms=result.elapsed_ms,
        success=result.success,
        error=result.error,
        experiment_id=experiment_id,
    )
