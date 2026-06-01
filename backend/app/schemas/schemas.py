from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------

class SectionOut(BaseModel):
    id: str
    name: str
    content: str
    order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SectionCreate(BaseModel):
    name: str
    content: str = ""
    order: int = 0


class SectionUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    order: int | None = None


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

class ExperimentOut(BaseModel):
    id: str
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float
    comment: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ExperimentCreate(BaseModel):
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float = 0.0
    comment: str = ""


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    notes: str
    output_format: str
    sections: list[SectionOut] = []
    experiments: list[ExperimentOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    output_format: str | None = None


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sql: str | None = None
    error: str | None = None
    query_result: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ChatSession
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Chat actions
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    question: str
    project_id: str | None = None
    model_name: str | None = None


class GenerateResponse(BaseModel):
    sql: str
    success: bool
    error: str | None = None


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


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

class OllamaModel(BaseModel):
    name: str
    size: str = ""


class OllamaHealthResponse(BaseModel):
    online: bool
    models: list[OllamaModel]
    message: str
