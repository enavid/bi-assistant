from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sql: str | None = None
    error: str | None = None
    query_result: dict | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatSessionOut(BaseModel):
    id: str
    title: str
    project_id: str | None
    model_name: str
    messages: list[MessageOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ChatSessionCreate(BaseModel):
    title: str = "New chat"
    project_id: str | None = None
    model_name: str


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    project_id: str | None = None
    model_name: str | None = None


class GenerateRequest(BaseModel):
    question: str
    project_id: str | None = None
    model_name: str | None = None


class GenerateResponse(BaseModel):
    sql: str
    success: bool
    error: str | None = None
    message_fa: str | None = None
    route: str | None = None
    status: str | None = None
    detected_intent: str | None = None
    warnings: list[str] = Field(default_factory=list)
    traces: list[dict] = Field(default_factory=list)
    source: str | None = None
    template_id: str | None = None
    executed: bool = False
    row_count: int | None = None
    model_called: str | None = None


class QueryRequest(BaseModel):
    sql: str
    session_id: str | None = None
    question: str | None = None
    project_id: str | None = None


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    elapsed_ms: float
    success: bool
    error: str | None = None
