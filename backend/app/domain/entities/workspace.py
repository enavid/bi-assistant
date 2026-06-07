from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Section:
    name: str
    content: str = ""
    order: int = 0
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class ExperimentEntry:
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float = 0.0
    comment: str = ""
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class Project:
    name: str
    workspace_id: str
    description: str = ""
    notes: str = ""
    output_format: str = ""
    sections: list[Section] = field(default_factory=list)
    experiments: list[ExperimentEntry] = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Workspace:
    name: str = "Default Workspace"
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class Message:
    role: str
    session_id: str
    content: str = ""
    sql: str | None = None
    error: str | None = None
    query_result: dict | None = None
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class ChatSession:
    model_name: str
    title: str = "New chat"
    project_id: str | None = None
    messages: list[Message] = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
