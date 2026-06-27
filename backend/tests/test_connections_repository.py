"""Tests for QueryDatabaseRepository — TDD."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.connections.repositories.database_repository import QueryDatabaseRepository
from app.infrastructure.db.models import Base, QueryDatabaseORM

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_TABLES = [QueryDatabaseORM.__table__]


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
    return QueryDatabaseRepository(db_session)


@pytest.mark.asyncio
async def test_create_and_list(repo):
    conn = await repo.create(
        name="Prod HR",
        host="db.company.com",
        port=5432,
        db_name="hr",
        username="hr_user",
        password="secret",
    )
    assert conn.id
    assert conn.name == "Prod HR"
    assert conn.is_active is False

    connections = await repo.list()
    assert len(connections) == 1
    assert connections[0].id == conn.id


@pytest.mark.asyncio
async def test_get_by_id(repo):
    conn = await repo.create(
        name="Dev", host="localhost", port=5432, db_name="hr_dev", username="dev", password="dev"
    )
    fetched = await repo.get(conn.id)
    assert fetched is not None
    assert fetched.name == "Dev"


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(repo):
    result = await repo.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_update(repo):
    conn = await repo.create(
        name="Old Name", host="localhost", port=5432, db_name="hr", username="user", password="pass"
    )
    updated = await repo.update(conn.id, name="New Name", port=5433)
    assert updated is not None
    assert updated.name == "New Name"
    assert updated.port == 5433


@pytest.mark.asyncio
async def test_delete(repo):
    conn = await repo.create(
        name="To Delete", host="localhost", port=5432, db_name="hr", username="u", password="p"
    )
    deleted = await repo.delete(conn.id)
    assert deleted is True
    assert await repo.get(conn.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(repo):
    result = await repo.delete("ghost-id")
    assert result is False


@pytest.mark.asyncio
async def test_activate_sets_one_active(repo):
    c1 = await repo.create(
        name="DB1", host="h1", port=5432, db_name="db1", username="u", password="p"
    )
    c2 = await repo.create(
        name="DB2", host="h2", port=5432, db_name="db2", username="u", password="p"
    )

    await repo.activate(c1.id)
    connections = await repo.list()
    active = [c for c in connections if c.is_active]
    assert len(active) == 1
    assert active[0].id == c1.id

    await repo.activate(c2.id)
    connections = await repo.list()
    active = [c for c in connections if c.is_active]
    assert len(active) == 1
    assert active[0].id == c2.id


@pytest.mark.asyncio
async def test_activate_nonexistent_returns_none(repo):
    result = await repo.activate("ghost-id")
    assert result is None


@pytest.mark.asyncio
async def test_deactivate_all(repo):
    c = await repo.create(
        name="DB1", host="h1", port=5432, db_name="db1", username="u", password="p"
    )
    await repo.activate(c.id)

    await repo.deactivate_all()
    connections = await repo.list()
    assert all(not conn.is_active for conn in connections)


@pytest.mark.asyncio
async def test_get_active_returns_active_connection(repo):
    c = await repo.create(
        name="Active DB", host="h", port=5432, db_name="d", username="u", password="p"
    )
    await repo.activate(c.id)
    active = await repo.get_active()
    assert active is not None
    assert active.id == c.id


@pytest.mark.asyncio
async def test_get_active_returns_none_when_none_active(repo):
    await repo.create(name="Inactive", host="h", port=5432, db_name="d", username="u", password="p")
    active = await repo.get_active()
    assert active is None


# ---------------------------------------------------------------------------
# Credential encryption at rest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_is_encrypted_at_rest(repo):
    conn = await repo.create(
        name="Secret DB", host="h", port=5432, db_name="d", username="u", password="s3cr3t"
    )
    # The stored value must be ciphertext, never the plaintext.
    assert conn.password != "s3cr3t"
    assert conn.password.startswith("enc:v1:")


@pytest.mark.asyncio
async def test_get_decrypted_password_roundtrips(repo):
    conn = await repo.create(
        name="DB", host="h", port=5432, db_name="d", username="u", password="orig-pass"
    )
    assert await repo.get_decrypted_password(conn) == "orig-pass"


@pytest.mark.asyncio
async def test_update_reencrypts_password(repo):
    conn = await repo.create(
        name="DB", host="h", port=5432, db_name="d", username="u", password="old"
    )
    updated = await repo.update(conn.id, password="new-pass")
    assert updated is not None
    assert updated.password.startswith("enc:v1:")
    assert await repo.get_decrypted_password(updated) == "new-pass"


@pytest.mark.asyncio
async def test_legacy_plaintext_is_lazily_encrypted(repo):
    # Simulate a row written before encryption was introduced.
    conn = await repo.create(
        name="Legacy", host="h", port=5432, db_name="d", username="u", password="x"
    )
    conn.password = "legacy-plain"  # bypass create() encryption to mimic an old row
    await repo._db.flush()

    plaintext = await repo.get_decrypted_password(conn)
    assert plaintext == "legacy-plain"
    # After first use it must be upgraded to ciphertext.
    assert conn.password.startswith("enc:v1:")
