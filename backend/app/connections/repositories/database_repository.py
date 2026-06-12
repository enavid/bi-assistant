from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import QueryDatabaseORM


class QueryDatabaseRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list(self) -> list[QueryDatabaseORM]:
        result = await self._db.execute(
            select(QueryDatabaseORM).order_by(QueryDatabaseORM.created_at)
        )
        return list(result.scalars().all())

    async def get(self, id: str) -> QueryDatabaseORM | None:
        result = await self._db.execute(select(QueryDatabaseORM).where(QueryDatabaseORM.id == id))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        host: str,
        port: int,
        db_name: str,
        username: str,
        password: str,
    ) -> QueryDatabaseORM:
        conn = QueryDatabaseORM(
            name=name,
            host=host,
            port=port,
            db_name=db_name,
            username=username,
            password=password,
            is_active=False,
        )
        self._db.add(conn)
        await self._db.flush()
        await self._db.refresh(conn)
        return conn

    async def update(self, id: str, **fields) -> QueryDatabaseORM | None:
        conn = await self.get(id)
        if not conn:
            return None
        for key, value in fields.items():
            if hasattr(conn, key) and value is not None:
                setattr(conn, key, value)
        await self._db.flush()
        await self._db.refresh(conn)
        return conn

    async def delete(self, id: str) -> bool:
        conn = await self.get(id)
        if not conn:
            return False
        await self._db.delete(conn)
        await self._db.flush()
        return True

    async def activate(self, id: str) -> QueryDatabaseORM | None:
        conn = await self.get(id)
        if not conn:
            return None
        await self._db.execute(update(QueryDatabaseORM).values(is_active=False))
        conn.is_active = True
        await self._db.flush()
        await self._db.refresh(conn)
        return conn

    async def deactivate_all(self) -> None:
        await self._db.execute(update(QueryDatabaseORM).values(is_active=False))
        await self._db.flush()

    async def get_active(self) -> QueryDatabaseORM | None:
        result = await self._db.execute(
            select(QueryDatabaseORM).where(QueryDatabaseORM.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()
