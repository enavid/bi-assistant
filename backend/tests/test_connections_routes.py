"""Tests for connections API routes — TDD."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, QueryDatabaseORM
from app.infrastructure.db.session import get_db
from app.main import app

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
def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_conn(client, **kwargs):
    payload = {
        "name": "Test DB",
        "host": "localhost",
        "port": 5432,
        "db_name": "hr",
        "username": "user",
        "password": "pass",
    }
    payload.update(kwargs)
    return client.post("/connections/databases", json=payload)


def test_system_databases_returns_app_db_only(client):
    resp = client.get("/connections/system-databases")
    assert resp.status_code == 200
    data = resp.json()
    assert "app_db" in data
    assert "hr_db" not in data


def test_list_databases_empty(client):
    resp = client.get("/connections/databases")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_database(client):
    resp = _create_conn(client, name="HR Prod")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "HR Prod"
    assert data["is_active"] is False
    assert "password" not in data


def test_create_and_list(client):
    _create_conn(client, name="DB1")
    _create_conn(client, name="DB2")
    resp = client.get("/connections/databases")
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()]
    assert "DB1" in names
    assert "DB2" in names


def test_get_database(client):
    created = _create_conn(client).json()
    resp = client.get(f"/connections/databases/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_nonexistent_returns_404(client):
    resp = client.get("/connections/databases/nonexistent")
    assert resp.status_code == 404


def test_update_database(client):
    created = _create_conn(client, name="Old").json()
    resp = client.patch(
        f"/connections/databases/{created['id']}", json={"name": "New", "port": 5433}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New"
    assert data["port"] == 5433


def test_delete_database(client):
    created = _create_conn(client).json()
    resp = client.delete(f"/connections/databases/{created['id']}")
    assert resp.status_code == 204
    resp2 = client.get(f"/connections/databases/{created['id']}")
    assert resp2.status_code == 404


def test_delete_nonexistent_returns_404(client):
    resp = client.delete("/connections/databases/ghost")
    assert resp.status_code == 404


def test_activate_database(client):
    c1 = _create_conn(client, name="DB1").json()
    c2 = _create_conn(client, name="DB2").json()

    resp = client.post(f"/connections/databases/{c1['id']}/activate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    all_conns = client.get("/connections/databases").json()
    active = [c for c in all_conns if c["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == c1["id"]

    resp2 = client.post(f"/connections/databases/{c2['id']}/activate")
    assert resp2.status_code == 200
    all_conns = client.get("/connections/databases").json()
    active = [c for c in all_conns if c["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == c2["id"]


def test_deactivate_all(client):
    c = _create_conn(client).json()
    client.post(f"/connections/databases/{c['id']}/activate")
    resp = client.post("/connections/databases/deactivate")
    assert resp.status_code == 200
    all_conns = client.get("/connections/databases").json()
    assert all(not conn["is_active"] for conn in all_conns)


def test_test_connection_bad_host_returns_error(client):
    payload = {
        "host": "totally-nonexistent-host-12345.invalid",
        "port": 5432,
        "db_name": "hr",
        "username": "user",
        "password": "pass",
    }
    resp = client.post("/connections/databases/test", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"]


def test_response_never_includes_password(client):
    resp = _create_conn(client, password="supersecret")
    assert "supersecret" not in resp.text
