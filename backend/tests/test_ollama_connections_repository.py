"""Tests for OllamaConnectionRepository — TDD."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.connections.repositories.ollama_repository import OllamaConnectionRepository
from app.infrastructure.db.models import Base, OllamaConnectionORM

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_TABLES = [OllamaConnectionORM.__table__]


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
    return OllamaConnectionRepository(db_session)


@pytest.mark.asyncio
async def test_create_and_list(repo):
    conn = await repo.create(name="Local", base_url="http://localhost:11434")
    assert conn.id
    assert conn.name == "Local"
    assert conn.base_url == "http://localhost:11434"
    assert conn.is_active is False

    items = await repo.list()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_get_by_id(repo):
    conn = await repo.create(name="Remote", base_url="http://remote:11434")
    fetched = await repo.get(conn.id)
    assert fetched is not None
    assert fetched.name == "Remote"


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(repo):
    assert await repo.get("ghost") is None


@pytest.mark.asyncio
async def test_update(repo):
    conn = await repo.create(name="Old", base_url="http://old:11434")
    updated = await repo.update(conn.id, name="New", base_url="http://new:11434")
    assert updated.name == "New"
    assert updated.base_url == "http://new:11434"


@pytest.mark.asyncio
async def test_delete(repo):
    conn = await repo.create(name="Del", base_url="http://x:11434")
    assert await repo.delete(conn.id) is True
    assert await repo.get(conn.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(repo):
    assert await repo.delete("ghost") is False


@pytest.mark.asyncio
async def test_activate_sets_only_one_active(repo):
    c1 = await repo.create(name="A", base_url="http://a:11434")
    c2 = await repo.create(name="B", base_url="http://b:11434")

    await repo.activate(c1.id)
    items = await repo.list()
    assert sum(c.is_active for c in items) == 1
    assert next(c for c in items if c.id == c1.id).is_active is True

    await repo.activate(c2.id)
    items = await repo.list()
    assert sum(c.is_active for c in items) == 1
    assert next(c for c in items if c.id == c2.id).is_active is True


@pytest.mark.asyncio
async def test_activate_nonexistent_returns_none(repo):
    assert await repo.activate("ghost") is None


@pytest.mark.asyncio
async def test_deactivate_all(repo):
    c = await repo.create(name="X", base_url="http://x:11434")
    await repo.activate(c.id)
    await repo.deactivate_all()
    items = await repo.list()
    assert all(not c.is_active for c in items)


@pytest.mark.asyncio
async def test_get_active(repo):
    c = await repo.create(name="X", base_url="http://x:11434")
    assert await repo.get_active() is None
    await repo.activate(c.id)
    active = await repo.get_active()
    assert active is not None
    assert active.id == c.id
