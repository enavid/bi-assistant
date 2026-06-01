from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models.domain import ChatSession, ExperimentEntry
from app.schemas.requests import (
    GenerateRequest,
    GenerateResponse,
    QueryRequest,
    QueryResponse,
    SessionCreateRequest,
    SessionUpdateRequest,
)
from app.services import db_service, llm_service, storage_service
from app.services.prompt_service import assemble_prompt

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions")
async def list_sessions():
    return storage_service.list_sessions()


@router.post("/sessions", response_model=ChatSession)
async def create_session(body: SessionCreateRequest) -> ChatSession:
    session = ChatSession(
        title=body.title,
        project_id=body.project_id,
        model_name=body.model_name,
    )
    return storage_service.save_session(session)


@router.get("/sessions/{session_id}", response_model=ChatSession)
async def get_session(session_id: str) -> ChatSession:
    session = storage_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/sessions/{session_id}", response_model=ChatSession)
async def update_session(session_id: str, body: SessionUpdateRequest) -> ChatSession:
    session = storage_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.title is not None:
        session.title = body.title
    if body.project_id is not None:
        session.project_id = body.project_id
    if body.model_name is not None:
        session.model_name = body.model_name
    session.updated_at = datetime.now().isoformat()
    return storage_service.save_session(session)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    if not storage_service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/generate", response_model=GenerateResponse)
async def generate(body: GenerateRequest) -> GenerateResponse:
    project = None
    if body.project_id:
        project = storage_service.get_project(body.project_id)

    if project:
        prompt = assemble_prompt(project, body.question)
    else:
        prompt = f"Generate a PostgreSQL SELECT query for: {body.question}\n\nSQL:"

    result = await llm_service.generate_sql(prompt, body.model_name)
    return GenerateResponse(sql=result.sql, success=result.success, error=result.error)


@router.post("/query", response_model=QueryResponse)
async def run_query(body: QueryRequest) -> QueryResponse:
    result = db_service.run_query(body.sql)

    if result.success and body.session_id and body.question and body.project_id:
        project = storage_service.get_project(body.project_id)
        if project:
            entry = ExperimentEntry(
                question=body.question,
                sql_output=body.sql,
                correct=True,
                elapsed_ms=result.elapsed_ms,
            )
            project.experiments.append(entry)
            storage_service.update_project(project)

    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        elapsed_ms=result.elapsed_ms,
        success=result.success,
        error=result.error,
    )
