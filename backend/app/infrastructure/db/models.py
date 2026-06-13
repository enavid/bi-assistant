from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

# Renders as JSONB on PostgreSQL (production) and falls back to JSON on SQLite (tests).
_JSONB = JSON().with_variant(JSONB(), "postgresql")
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class WorkspaceORM(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String, nullable=False, default="Default Workspace")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list[ProjectORM]] = relationship(
        "ProjectORM", back_populates="workspace", cascade="all, delete-orphan"
    )


class ProjectORM(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[WorkspaceORM] = relationship("WorkspaceORM", back_populates="projects")
    sections: Mapped[list[SectionORM]] = relationship(
        "SectionORM",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SectionORM.order",
    )
    experiments: Mapped[list[ExperimentORM]] = relationship(
        "ExperimentORM", back_populates="project", cascade="all, delete-orphan"
    )


class SectionORM(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[ProjectORM] = relationship("ProjectORM", back_populates="sections")


class ExperimentORM(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql_output: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[ProjectORM] = relationship("ProjectORM", back_populates="experiments")


class ChatSessionORM(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[MessageORM]] = relationship(
        "MessageORM",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MessageORM.created_at",
    )


class MessageORM(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSessionORM] = relationship("ChatSessionORM", back_populates="messages")


class OllamaConnectionORM(Base):
    __tablename__ = "ollama_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelConfigORM(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    model_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    config_json: Mapped[dict] = mapped_column(_JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QueryDatabaseORM(Base):
    __tablename__ = "query_databases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=5432)
    db_name: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EvalQuestionSetORM(Base):
    __tablename__ = "eval_question_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    questions: Mapped[list[EvalQuestionORM]] = relationship(
        "EvalQuestionORM",
        back_populates="question_set",
        cascade="all, delete-orphan",
        order_by="EvalQuestionORM.question_id",
    )
    runs: Mapped[list[EvalRunORM]] = relationship(
        "EvalRunORM",
        back_populates="question_set",
        cascade="all, delete-orphan",
    )


class EvalQuestionORM(Base):
    __tablename__ = "eval_questions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    set_id: Mapped[str] = mapped_column(
        String, ForeignKey("eval_question_sets.id", ondelete="CASCADE")
    )
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_route: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_status: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question_set: Mapped[EvalQuestionSetORM] = relationship(
        "EvalQuestionSetORM", back_populates="questions"
    )


class EvalRunORM(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    set_id: Mapped[str] = mapped_column(
        String, ForeignKey("eval_question_sets.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_question_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_ids_ordered: Mapped[list | None] = mapped_column(_JSONB, nullable=True)

    question_set: Mapped[EvalQuestionSetORM] = relationship(
        "EvalQuestionSetORM", back_populates="runs"
    )
    results: Mapped[list[EvalRunResultORM]] = relationship(
        "EvalRunResultORM",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvalRunResultORM(Base):
    __tablename__ = "eval_run_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uid)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("eval_runs.id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_route: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_status: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    model_called: Mapped[str | None] = mapped_column(String, nullable=True)
    template_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sql_validator_status: Mapped[str | None] = mapped_column(String, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visualization: Mapped[str | None] = mapped_column(String, nullable=True)
    total_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    trace_steps: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[EvalRunORM] = relationship("EvalRunORM", back_populates="results")
