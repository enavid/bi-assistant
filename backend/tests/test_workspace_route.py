"""Tests for workspace API routes — TDD."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import (
    Base,
    ExperimentORM,
    ProjectORM,
    SectionORM,
    WorkspaceORM,
)
from app.infrastructure.db.session import get_db
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_WS_TABLES = [
    WorkspaceORM.__table__,
    ProjectORM.__table__,
    SectionORM.__table__,
    ExperimentORM.__table__,
]


@pytest.fixture()
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_WS_TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_WS_TABLES))
    await engine.dispose()


@pytest.fixture()
def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_list_projects_empty(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_project(client):
    resp = client.post("/projects", json={"name": "HR Analysis", "description": "Test project"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "HR Analysis"
    assert data["description"] == "Test project"
    assert "id" in data
    assert data["sections"] == []
    assert data["experiments"] == []


def test_create_project_name_required(client):
    resp = client.post("/projects", json={"description": "no name"})
    assert resp.status_code == 422


def test_list_projects_returns_created(client):
    client.post("/projects", json={"name": "P1"})
    client.post("/projects", json={"name": "P2"})
    resp = client.get("/projects")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "P1" in names
    assert "P2" in names


def test_get_project(client):
    created = client.post("/projects", json={"name": "MyProject"}).json()
    resp = client.get(f"/projects/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "MyProject"


def test_get_project_not_found(client):
    resp = client.get("/projects/nonexistent-id")
    assert resp.status_code == 404


def test_update_project(client):
    created = client.post("/projects", json={"name": "Old Name"}).json()
    resp = client.patch(
        f"/projects/{created['id']}", json={"name": "New Name", "notes": "some notes"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New Name"
    assert data["notes"] == "some notes"


def test_delete_project(client):
    created = client.post("/projects", json={"name": "To Delete"}).json()
    resp = client.delete(f"/projects/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/projects/{created['id']}").status_code == 404


def test_delete_project_not_found(client):
    resp = client.delete("/projects/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def test_create_section(client):
    project = client.post("/projects", json={"name": "P"}).json()
    resp = client.post(
        f"/projects/{project['id']}/sections",
        json={"name": "Intro", "content": "HR context", "order": 0},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["sections"]) == 1
    assert data["sections"][0]["name"] == "Intro"


def test_create_section_project_not_found(client):
    resp = client.post("/projects/bad-id/sections", json={"name": "S", "content": ""})
    assert resp.status_code == 404


def test_update_section(client):
    project = client.post("/projects", json={"name": "P"}).json()
    project = client.post(
        f"/projects/{project['id']}/sections",
        json={"name": "S1", "content": "old"},
    ).json()
    section_id = project["sections"][0]["id"]
    resp = client.patch(
        f"/projects/{project['id']}/sections/{section_id}",
        json={"content": "updated content"},
    )
    assert resp.status_code == 200
    assert resp.json()["sections"][0]["content"] == "updated content"


def test_update_section_not_found(client):
    project = client.post("/projects", json={"name": "P"}).json()
    resp = client.patch(
        f"/projects/{project['id']}/sections/nonexistent",
        json={"content": "x"},
    )
    assert resp.status_code == 404


def test_delete_section(client):
    project = client.post("/projects", json={"name": "P"}).json()
    project = client.post(
        f"/projects/{project['id']}/sections",
        json={"name": "S", "content": "c"},
    ).json()
    section_id = project["sections"][0]["id"]
    resp = client.delete(f"/projects/{project['id']}/sections/{section_id}")
    assert resp.status_code == 200
    assert resp.json()["sections"] == []


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def test_add_experiment(client):
    project = client.post("/projects", json={"name": "P"}).json()
    resp = client.post(
        f"/projects/{project['id']}/experiments",
        json={"question": "تعداد کارکنان؟", "sql_output": "SELECT COUNT(*) FROM emp"},
    )
    assert resp.status_code == 201
    assert len(resp.json()["experiments"]) == 1
    assert resp.json()["experiments"][0]["question"] == "تعداد کارکنان؟"


def test_set_experiment_feedback(client):
    project = client.post("/projects", json={"name": "P"}).json()
    project = client.post(
        f"/projects/{project['id']}/experiments",
        json={"question": "سوال", "sql_output": "SELECT 1"},
    ).json()
    exp_id = project["experiments"][0]["id"]
    resp = client.patch(f"/experiments/{exp_id}/feedback", json={"correct": True})
    assert resp.status_code == 200
    assert resp.json()["correct"] is True


def test_set_experiment_feedback_not_found(client):
    resp = client.patch("/experiments/nonexistent-id/feedback", json={"correct": True})
    assert resp.status_code == 404
