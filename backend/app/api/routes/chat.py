from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import get_db
from app.db.models import ChatSession, Experiment, Message, Project
from app.schemas.schemas import (
    ChatSessionCreate,
    ChatSessionOut,
    ChatSessionUpdate,
    GenerateRequest,
    GenerateResponse,
    QueryRequest,
    QueryResponse,
)
from app.services import db_service, llm_service
from app.services.prompt_service import assemble_prompt

router = APIRouter(prefix="/chat", tags=["chat"])

_SESSION_LOAD = [selectinload(ChatSession.messages)]


async def _require_session(session_id: str, db: AsyncSession) -> ChatSession:
    result = await db.execute(
        select(ChatSession).options(*_SESSION_LOAD).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession).options(*_SESSION_LOAD).order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(body: ChatSessionCreate, db: AsyncSession = Depends(get_db)) -> ChatSession:
    session = ChatSession(title=body.title, project_id=body.project_id, model_name=body.model_name)
    db.add(session)
    await db.flush()
    await db.refresh(session, ["messages"])
    return session


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> ChatSession:
    return await _require_session(session_id, db)


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut)
async def update_session(session_id: str, body: ChatSessionUpdate, db: AsyncSession = Depends(get_db)) -> ChatSession:
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


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    session = await _require_session(session_id, db)
    await db.delete(session)
    return {"deleted": True}


@router.post("/sessions/{session_id}/messages", response_model=ChatSessionOut)
async def add_message(session_id: str, body: dict, db: AsyncSession = Depends(get_db)) -> ChatSession:
    session = await _require_session(session_id, db)
    message = Message(
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


# ── Generate + Query ──────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateResponse)
async def generate(body: GenerateRequest, db: AsyncSession = Depends(get_db)) -> GenerateResponse:
    project = None
    if body.project_id:
        result = await db.execute(
            select(Project).options(selectinload(Project.sections)).where(Project.id == body.project_id)
        )
        project = result.scalar_one_or_none()

    prompt = (
        assemble_prompt(project, body.question)
        if project
        else f"Generate a PostgreSQL SELECT query for: {body.question}\n\nSQL:"
    )

    gen = await llm_service.generate_sql(prompt, body.model_name)
    return GenerateResponse(sql=gen.sql, success=gen.success, error=gen.error)


@router.post("/query", response_model=QueryResponse)
async def run_query(body: QueryRequest, db: AsyncSession = Depends(get_db)) -> QueryResponse:
    result = db_service.run_query(body.sql)

    if result.success and body.project_id and body.question:
        proj_result = await db.execute(select(Project).where(Project.id == body.project_id))
        project = proj_result.scalar_one_or_none()
        if project:
            exp = Experiment(
                project_id=body.project_id,
                question=body.question,
                sql_output=body.sql,
                correct=True,
                elapsed_ms=result.elapsed_ms,
            )
            db.add(exp)

    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        elapsed_ms=result.elapsed_ms,
        success=result.success,
        error=result.error,
    )
