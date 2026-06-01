from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(
        String, nullable=False, default="Default Workspace")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list[Project]] = relationship(
        "Project", back_populates="workspace", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey(
        "workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace: Mapped[Workspace] = relationship(
        "Workspace", back_populates="projects")
    sections: Mapped[list[Section]] = relationship(
        "Section", back_populates="project", cascade="all, delete-orphan", order_by="Section.order")
    experiments: Mapped[list[Experiment]] = relationship(
        "Experiment", back_populates="project", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey(
        "projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(
        "Project", back_populates="sections")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey(
        "projects.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql_output: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[bool] = mapped_column(Boolean, default=True)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(
        "Project", back_populates="experiments")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, default="New chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String, ForeignKey(
        "chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(
        "ChatSession", back_populates="messages")
