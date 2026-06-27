from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import CredentialCipher, get_credential_cipher
from app.infrastructure.db.models import QueryDatabaseORM

logger = logging.getLogger(__name__)


class QueryDatabaseRepository:
    def __init__(self, db: AsyncSession, cipher: CredentialCipher | None = None) -> None:
        self._db = db
        self._cipher = cipher or get_credential_cipher()

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
            password=self._cipher.encrypt(password),
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
        if fields.get("password") is not None:
            fields["password"] = self._cipher.encrypt(fields["password"])
        for key, value in fields.items():
            if hasattr(conn, key) and value is not None:
                setattr(conn, key, value)
        await self._db.flush()
        await self._db.refresh(conn)
        return conn

    async def get_decrypted_password(self, row: QueryDatabaseORM) -> str:
        """Return the plaintext password for an active connection.

        Lazily upgrades legacy plaintext rows to ciphertext on first use so the
        store converges to encrypted-at-rest without a blocking migration.
        """
        stored = row.password
        if not self._cipher.is_encrypted(stored):
            row.password = self._cipher.encrypt(stored)
            await self._db.flush()
            logger.info("Encrypted legacy plaintext credential for connection %s", row.id)
            return stored
        return self._cipher.decrypt(stored)

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
