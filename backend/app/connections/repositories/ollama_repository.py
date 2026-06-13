from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import OllamaConnectionORM


class OllamaConnectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list(self) -> list[OllamaConnectionORM]:
        result = await self._db.execute(
            select(OllamaConnectionORM).order_by(OllamaConnectionORM.created_at)
        )
        return list(result.scalars().all())

    async def get(self, id: str) -> OllamaConnectionORM | None:
        result = await self._db.execute(
            select(OllamaConnectionORM).where(OllamaConnectionORM.id == id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, name: str, base_url: str) -> OllamaConnectionORM:
        row = OllamaConnectionORM(name=name, base_url=base_url, is_active=False)
        self._db.add(row)
        await self._db.flush()
        await self._db.refresh(row)
        return row

    async def update(self, id: str, **fields) -> OllamaConnectionORM | None:
        row = await self.get(id)
        if not row:
            return None
        for key, value in fields.items():
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)
        await self._db.flush()
        await self._db.refresh(row)
        return row

    async def delete(self, id: str) -> bool:
        row = await self.get(id)
        if not row:
            return False
        await self._db.delete(row)
        await self._db.flush()
        return True

    async def activate(self, id: str) -> OllamaConnectionORM | None:
        row = await self.get(id)
        if not row:
            return None
        await self._db.execute(update(OllamaConnectionORM).values(is_active=False))
        row.is_active = True
        await self._db.flush()
        await self._db.refresh(row)
        return row

    async def deactivate_all(self) -> None:
        await self._db.execute(update(OllamaConnectionORM).values(is_active=False))
        await self._db.flush()

    async def get_active(self) -> OllamaConnectionORM | None:
        result = await self._db.execute(
            select(OllamaConnectionORM).where(OllamaConnectionORM.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()
