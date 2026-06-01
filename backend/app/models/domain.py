from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Prompt / Project models
# ---------------------------------------------------------------------------

class Section(BaseModel):
    """A named, free-form block of text inside a Project."""

    id: str = Field(default_factory=_uid)
    name: str
    content: str = ""
    order: int = 0


class ExperimentEntry(BaseModel):
    """Auto-logged after a successful DB query run."""

    id: str = Field(default_factory=_uid)
    date: str = Field(default_factory=_now)
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float = 0.0
    comment: str = ""


class Project(BaseModel):
    """
    A prompt engineering project owned by a Workspace.
    Sections are assembled in order using output_format as the glue template.
    output_format references sections by variable name: {section_id}.
    """

    id: str = Field(default_factory=_uid)
    name: str
    description: str = ""
    notes: str = ""
    sections: list[Section] = []
    output_format: str = ""
    experiments: list[ExperimentEntry] = []
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class Workspace(BaseModel):
    """
    Top-level container. Single workspace for now.
    When auth is added, each user gets their own workspace_id resolved from JWT.
    """

    id: str = Field(default_factory=_uid)
    name: str = "Default Workspace"
    projects: list[Project] = []
    created_at: str = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    id: str = Field(default_factory=_uid)
    role: str
    content: str
    sql: str | None = None
    error: str | None = None
    query_result: dict | None = None
    created_at: str = Field(default_factory=_now)


class ChatSession(BaseModel):
    id: str = Field(default_factory=_uid)
    title: str = "New chat"
    project_id: str | None = None
    model_name: str
    messages: list[ChatMessage] = []
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
