from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import ModelConfigORM


class ModelConfigRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_all(self) -> list[ModelConfigORM]:
        result = await self._db.execute(select(ModelConfigORM).order_by(ModelConfigORM.model_name))
        return list(result.scalars().all())

    async def get(self, model_name: str) -> ModelConfigORM | None:
        result = await self._db.execute(
            select(ModelConfigORM).where(ModelConfigORM.model_name == model_name)
        )
        return result.scalar_one_or_none()

    async def upsert(self, model_name: str, config_json: dict) -> ModelConfigORM:
        row = await self.get(model_name)
        if row:
            row.config_json = config_json
        else:
            row = ModelConfigORM(model_name=model_name, config_json=config_json)
            self._db.add(row)
        await self._db.flush()
        await self._db.refresh(row)
        return row

    async def delete(self, model_name: str) -> bool:
        row = await self.get(model_name)
        if not row:
            return False
        await self._db.delete(row)
        await self._db.flush()
        return True
