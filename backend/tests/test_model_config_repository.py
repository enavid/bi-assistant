"""Tests for ModelConfigRepository — TDD."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.connections.repositories.model_config_repository import ModelConfigRepository
from app.infrastructure.db.models import Base, ModelConfigORM

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_TABLES = [ModelConfigORM.__table__]


@pytest.fixture()
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_TABLES))
    await engine.dispose()


@pytest.fixture()
def repo(db_session):
    return ModelConfigRepository(db_session)


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(repo):
    assert await repo.get("llama3") is None


@pytest.mark.asyncio
async def test_upsert_creates_new(repo):
    config = {"temperature": 0.7, "top_p": 0.9, "think": False}
    row = await repo.upsert("llama3", config)
    assert row.model_name == "llama3"
    assert row.config_json == config


@pytest.mark.asyncio
async def test_upsert_updates_existing(repo):
    await repo.upsert("llama3", {"temperature": 0.5})
    updated = await repo.upsert("llama3", {"temperature": 0.9, "think": True})
    assert updated.config_json == {"temperature": 0.9, "think": True}


@pytest.mark.asyncio
async def test_get_after_upsert(repo):
    await repo.upsert("qwen3", {"temperature": 0.6})
    row = await repo.get("qwen3")
    assert row is not None
    assert row.config_json["temperature"] == 0.6


@pytest.mark.asyncio
async def test_delete_existing(repo):
    await repo.upsert("llama3", {"temperature": 0.5})
    assert await repo.delete("llama3") is True
    assert await repo.get("llama3") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(repo):
    assert await repo.delete("ghost") is False


@pytest.mark.asyncio
async def test_list_all(repo):
    await repo.upsert("model-a", {"temperature": 0.5})
    await repo.upsert("model-b", {"temperature": 0.8})
    rows = await repo.list_all()
    names = [r.model_name for r in rows]
    assert "model-a" in names
    assert "model-b" in names
