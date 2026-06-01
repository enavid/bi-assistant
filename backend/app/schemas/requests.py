from __future__ import annotations

from pydantic import BaseModel

from app.models.domain import Section


# ---------------------------------------------------------------------------
# Workspace / Project
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    sections: list[Section] | None = None
    output_format: str | None = None


class SectionCreateRequest(BaseModel):
    name: str
    content: str = ""
    order: int = 0


class SectionUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None
    order: int | None = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class SessionCreateRequest(BaseModel):
    title: str = "New chat"
    project_id: str | None = None
    model_name: str


class SessionUpdateRequest(BaseModel):
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


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

class ExperimentCreateRequest(BaseModel):
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float = 0.0
    comment: str = ""
