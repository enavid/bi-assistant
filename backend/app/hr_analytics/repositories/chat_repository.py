from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models import ChatSessionORM, MessageORM

_SESSION_OPTS = [selectinload(ChatSessionORM.messages)]


class ChatRepository:
    """SQLAlchemy implementation of IChatRepository."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_sessions(self) -> list[ChatSessionORM]:
        result = await self._db.execute(
            select(ChatSessionORM)
            .options(*_SESSION_OPTS)
            .order_by(ChatSessionORM.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_session(self, session_id: str) -> ChatSessionORM | None:
        result = await self._db.execute(
            select(ChatSessionORM).options(*_SESSION_OPTS).where(ChatSessionORM.id == session_id)
        )
        return result.scalar_one_or_none()

    async def create_session(
        self, title: str, project_id: str | None, model_name: str
    ) -> ChatSessionORM:
        session = ChatSessionORM(title=title, project_id=project_id, model_name=model_name)
        self._db.add(session)
        await self._db.flush()
        await self._db.refresh(session, ["messages"])
        return session

    async def update_session(self, session_id: str, **fields: Any) -> ChatSessionORM | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(session, key):
                setattr(session, key, value)
        session.updated_at = datetime.now(UTC)
        await self._db.flush()
        return session

    async def delete_session(self, session_id: str) -> bool:
        session = await self.get_session(session_id)
        if session is None:
            return False
        await self._db.delete(session)
        return True

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sql: str | None,
        error: str | None,
        query_result: dict | None,
    ) -> ChatSessionORM | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        message = MessageORM(
            session_id=session_id,
            role=role,
            content=content,
            sql=sql,
            error=error,
            query_result=query_result,
        )
        self._db.add(message)
        session.updated_at = datetime.now(UTC)
        await self._db.flush()
        await self._db.refresh(session, ["messages"])
        return session
