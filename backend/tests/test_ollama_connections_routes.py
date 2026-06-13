"""Tests for Ollama connections + model config API routes — TDD."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, ModelConfigORM, OllamaConnectionORM
from app.infrastructure.db.session import get_db
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_TABLES = [OllamaConnectionORM.__table__, ModelConfigORM.__table__]


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


def _create_ollama(client, **kwargs):
    payload = {"name": "Local", "base_url": "http://localhost:11434"}
    payload.update(kwargs)
    return client.post("/connections/ollama", json=payload)


# ---------------------------------------------------------------------------
# Ollama connection CRUD
# ---------------------------------------------------------------------------


def test_list_ollama_empty(client):
    resp = client.get("/connections/ollama")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_ollama_connection(client):
    resp = _create_ollama(client, name="Remote")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Remote"
    assert data["is_active"] is False


def test_get_ollama_connection(client):
    created = _create_ollama(client).json()
    resp = client.get(f"/connections/ollama/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_nonexistent_ollama_returns_404(client):
    resp = client.get("/connections/ollama/ghost")
    assert resp.status_code == 404


def test_update_ollama_connection(client):
    created = _create_ollama(client, name="Old").json()
    resp = client.patch(f"/connections/ollama/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_ollama_connection(client):
    created = _create_ollama(client).json()
    resp = client.delete(f"/connections/ollama/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/connections/ollama/{created['id']}").status_code == 404


def test_activate_ollama_connection(client):
    c1 = _create_ollama(client, name="A").json()
    c2 = _create_ollama(client, name="B").json()

    resp = client.post(f"/connections/ollama/{c1['id']}/activate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    all_conns = client.get("/connections/ollama").json()
    assert sum(c["is_active"] for c in all_conns) == 1

    client.post(f"/connections/ollama/{c2['id']}/activate")
    all_conns = client.get("/connections/ollama").json()
    active = [c for c in all_conns if c["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == c2["id"]


def test_deactivate_ollama(client):
    c = _create_ollama(client).json()
    client.post(f"/connections/ollama/{c['id']}/activate")
    resp = client.post("/connections/ollama/deactivate")
    assert resp.status_code == 200
    all_conns = client.get("/connections/ollama").json()
    assert all(not c["is_active"] for c in all_conns)


def test_test_ollama_bad_url(client):
    resp = client.post(
        "/connections/ollama/test",
        json={"base_url": "http://totally-nonexistent-host-99999.invalid:11434"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"]


# ---------------------------------------------------------------------------
# Model config CRUD
# ---------------------------------------------------------------------------


def test_get_model_config_nonexistent(client):
    resp = client.get("/connections/model-configs/llama3")
    assert resp.status_code == 404


def test_save_and_get_model_config(client):
    config = {"temperature": 0.7, "top_p": 0.9, "think": False}
    resp = client.put("/connections/model-configs/llama3", json={"config_json": config})
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_name"] == "llama3"
    assert data["config_json"] == config


def test_update_model_config(client):
    client.put("/connections/model-configs/qwen3", json={"config_json": {"temperature": 0.5}})
    resp = client.put(
        "/connections/model-configs/qwen3",
        json={"config_json": {"temperature": 0.9, "think": True}},
    )
    assert resp.status_code == 200
    assert resp.json()["config_json"] == {"temperature": 0.9, "think": True}


def test_delete_model_config(client):
    client.put("/connections/model-configs/llama3", json={"config_json": {"temperature": 0.5}})
    resp = client.delete("/connections/model-configs/llama3")
    assert resp.status_code == 204
    assert client.get("/connections/model-configs/llama3").status_code == 404


def test_list_model_configs(client):
    client.put("/connections/model-configs/model-a", json={"config_json": {"temperature": 0.5}})
    client.put("/connections/model-configs/model-b", json={"config_json": {"temperature": 0.8}})
    resp = client.get("/connections/model-configs")
    assert resp.status_code == 200
    names = [r["model_name"] for r in resp.json()]
    assert "model-a" in names
    assert "model-b" in names


# ---------------------------------------------------------------------------
# Models list per connection
# ---------------------------------------------------------------------------


def test_get_ollama_models_nonexistent_connection(client):
    resp = client.get("/connections/ollama/ghost-id/models")
    assert resp.status_code == 404


def test_get_ollama_models_unreachable(client):
    conn = _create_ollama(client, base_url="http://totally-nonexistent.invalid:11434").json()
    resp = client.get(f"/connections/ollama/{conn['id']}/models")
    assert resp.status_code == 502
