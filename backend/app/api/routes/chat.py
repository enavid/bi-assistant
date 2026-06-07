from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.db.session import get_db
from app.use_cases.chat.run_query import RunQueryUseCase
from app.use_cases.chat.generate_sql import GenerateSQLUseCase
from app.use_cases.hr_bi.orchestrate import HRBIOrchestrationUseCase
from app.infrastructure.db.models import ChatSessionORM, ExperimentORM, MessageORM, ProjectORM
from app.api.dependencies import get_generate_sql_use_case, get_hr_bi_orchestrator, get_run_query_use_case
from app.api.schemas import ChatSessionCreate, ChatSessionOut, ChatSessionUpdate, GenerateRequest, GenerateResponse, QueryRequest, QueryResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_SESSION_OPTS = [selectinload(ChatSessionORM.messages)]


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


async def _require_session(session_id: str, db: AsyncSession) -> ChatSessionORM:
    result = await db.execute(
        select(ChatSessionORM).options(*_SESSION_OPTS).where(ChatSessionORM.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions", response_model=list[ChatSessionOut], summary="List chat sessions")
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[ChatSessionORM]:
    result = await db.execute(
        select(ChatSessionORM).options(*_SESSION_OPTS).order_by(ChatSessionORM.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/sessions", response_model=ChatSessionOut, status_code=201, summary="Create chat session")
async def create_session(body: ChatSessionCreate, db: AsyncSession = Depends(get_db)) -> ChatSessionORM:
    session = ChatSessionORM(title=body.title, project_id=body.project_id, model_name=body.model_name)
    db.add(session)
    await db.flush()
    await db.refresh(session, ["messages"])
    return session


@router.get("/sessions/{session_id}", response_model=ChatSessionOut, summary="Get chat session")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> ChatSessionORM:
    return await _require_session(session_id, db)


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut, summary="Update chat session")
async def update_session(session_id: str, body: ChatSessionUpdate, db: AsyncSession = Depends(get_db)) -> ChatSessionORM:
    session = await _require_session(session_id, db)
    if body.title is not None:
        session.title = body.title
    if body.project_id is not None:
        session.project_id = body.project_id
    if body.model_name is not None:
        session.model_name = body.model_name
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session


@router.delete("/sessions/{session_id}", status_code=204, summary="Delete chat session")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> None:
    session = await _require_session(session_id, db)
    await db.delete(session)


@router.post("/sessions/{session_id}/messages", response_model=ChatSessionOut, summary="Add message to session")
async def add_message(session_id: str, body: dict, db: AsyncSession = Depends(get_db)) -> ChatSessionORM:
    session = await _require_session(session_id, db)
    message = MessageORM(
        session_id=session_id,
        role=body.get("role", "user"),
        content=body.get("content", ""),
        sql=body.get("sql"),
        error=body.get("error"),
        query_result=body.get("query_result"),
    )
    db.add(message)
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(session, ["messages"])
    return session


@router.post("/generate", response_model=GenerateResponse, summary="Generate SQL from question")
async def generate(
    body: GenerateRequest,
) -> GenerateResponse:
    orchestrator = get_hr_bi_orchestrator()
    uc = HRBIOrchestrationUseCase(orchestrator)
    result = await uc.generate(body.question, model=body.model_name)
    return GenerateResponse(
        sql=result.sql, success=result.success, error=result.error,
        message_fa=result.message,
        route=result.route, status=result.status,
        detected_intent=result.detected_intent, warnings=result.warnings,
    )


@router.post("/generate-legacy", response_model=GenerateResponse, summary="Generate SQL via prompt template")
async def generate_legacy(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    use_case: GenerateSQLUseCase = Depends(get_generate_sql_use_case),
) -> GenerateResponse:
    project = None
    if body.project_id:
        r = await db.execute(
            select(ProjectORM).options(selectinload(ProjectORM.sections)).where(ProjectORM.id == body.project_id)
        )
        project = r.scalar_one_or_none()

    from app.domain.entities import Project, Section
    domain_project = None
    if project:
        domain_project = Project(
            name=project.name,
            workspace_id=project.workspace_id,
            description=project.description,
            notes=project.notes,
            output_format=project.output_format,
            sections=[Section(name=s.name, content=s.content, order=s.order, id=s.id) for s in project.sections],
            id=project.id,
        )

    result = await use_case.execute(body.question, domain_project, body.model_name)
    return GenerateResponse(sql=result.sql, success=result.success, error=result.error)


@router.post("/generate-v2", response_model=GenerateResponse, summary="Generate SQL via Phase 2 pipeline")
async def generate_v2(body: GenerateRequest) -> GenerateResponse:
    orchestrator = get_hr_bi_orchestrator()
    uc = HRBIOrchestrationUseCase(orchestrator)
    result = await uc.generate(body.question, model=body.model_name)
    return GenerateResponse(
        sql=result.sql, success=result.success, error=result.error,
        route=result.route, status=result.status,
        detected_intent=result.detected_intent, warnings=result.warnings,
    )


@router.post("/query", response_model=QueryResponse, summary="Execute SQL against HR database")
async def run_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    use_case: RunQueryUseCase = Depends(get_run_query_use_case),
) -> QueryResponse:
    if _env_bool("HR_BI_VALIDATE_QUERY_V2", default=True):
        orchestrator = get_hr_bi_orchestrator()
        validator = getattr(orchestrator, "sql_validator", None)
        if validator is not None:
            validation = validator.validate(sql=body.sql)
            vd = validation.to_dict() if hasattr(validation, "to_dict") else dict(validation)
            if not (vd.get("is_valid") and vd.get("can_execute_sql")):
                violations = vd.get("violations") or []
                msg = ", ".join(str(v) for v in violations) or vd.get("status", "invalid")
                return QueryResponse(columns=[], rows=[], row_count=0, elapsed_ms=0, success=False, error=f"SQL blocked: {msg}")

    result = use_case.execute(body.sql)

    if result.success and body.project_id and body.question:
        exp = use_case.build_experiment(body.question, body.sql, result)
        if exp:
            r = await db.execute(select(ProjectORM).where(ProjectORM.id == body.project_id))
            if r.scalar_one_or_none():
                db.add(ExperimentORM(
                    project_id=body.project_id,
                    question=exp.question,
                    sql_output=exp.sql_output,
                    correct=exp.correct,
                    elapsed_ms=exp.elapsed_ms,
                ))

    return QueryResponse(
        columns=result.columns, rows=result.rows, row_count=result.row_count,
        elapsed_ms=result.elapsed_ms, success=result.success, error=result.error,
    )
