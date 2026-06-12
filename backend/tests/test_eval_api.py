"""Tests for eval API endpoints — written before implementation (TDD)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import (
    Base,
    EvalQuestionORM,
    EvalQuestionSetORM,
    EvalRunORM,
    EvalRunResultORM,
)
from app.infrastructure.db.session import get_db
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_EVAL_TABLES = [
    EvalQuestionSetORM.__table__,
    EvalQuestionORM.__table__,
    EvalRunORM.__table__,
    EvalRunResultORM.__table__,
]


@pytest.fixture()
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_EVAL_TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_EVAL_TABLES))
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
# Question sets
# ---------------------------------------------------------------------------


def test_list_question_sets_empty(client):
    resp = client.get("/eval/question-sets")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_question_set(client):
    resp = client.post(
        "/eval/question-sets", json={"name": "Phase 2", "description": "Consultant batch"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Phase 2"
    assert data["description"] == "Consultant batch"
    assert "id" in data
    assert "created_at" in data


def test_create_question_set_name_required(client):
    resp = client.post("/eval/question-sets", json={"description": "no name"})
    assert resp.status_code == 422


def test_list_question_sets_returns_created(client):
    client.post("/eval/question-sets", json={"name": "Set A"})
    client.post("/eval/question-sets", json={"name": "Set B"})
    resp = client.get("/eval/question-sets")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert "Set A" in names
    assert "Set B" in names


def test_delete_question_set(client):
    created = client.post("/eval/question-sets", json={"name": "To Delete"}).json()
    resp = client.delete(f"/eval/question-sets/{created['id']}")
    assert resp.status_code == 204
    resp2 = client.get("/eval/question-sets")
    assert all(s["id"] != created["id"] for s in resp2.json())


def test_delete_question_set_not_found(client):
    resp = client.delete("/eval/question-sets/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Questions within a set
# ---------------------------------------------------------------------------


def test_bulk_import_questions(client):
    qs = client.post("/eval/question-sets", json={"name": "Bulk Test"}).json()
    questions = [
        {"question_id": "q001", "question": "تعداد کارکنان؟", "category": "demographics"},
        {
            "question_id": "q002",
            "question": "درآمد چقدر است؟",
            "category": "access_control",
            "expected_route": "REJECT",
            "expected_status": "ACCESS_DENIED",
        },
    ]
    resp = client.post(f"/eval/question-sets/{qs['id']}/questions", json=questions)
    assert resp.status_code == 201
    data = resp.json()
    assert data["imported"] == 2


def test_list_questions_in_set(client):
    qs = client.post("/eval/question-sets", json={"name": "List Test"}).json()
    questions = [{"question_id": f"q{i:03d}", "question": f"سوال {i}"} for i in range(3)]
    client.post(f"/eval/question-sets/{qs['id']}/questions", json=questions)
    resp = client.get(f"/eval/question-sets/{qs['id']}/questions")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_delete_question_from_set(client):
    qs = client.post("/eval/question-sets", json={"name": "Del Q Test"}).json()
    client.post(
        f"/eval/question-sets/{qs['id']}/questions",
        json=[{"question_id": "q001", "question": "سوال اول"}],
    )
    resp = client.delete(f"/eval/question-sets/{qs['id']}/questions/q001")
    assert resp.status_code == 204
    remaining = client.get(f"/eval/question-sets/{qs['id']}/questions").json()
    assert all(q["question_id"] != "q001" for q in remaining)


def test_bulk_import_to_nonexistent_set(client):
    resp = client.post(
        "/eval/question-sets/bad-id/questions", json=[{"question_id": "q001", "question": "test"}]
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_list_runs_for_set_empty(client):
    qs = client.post("/eval/question-sets", json={"name": "Run Test"}).json()
    resp = client.get(f"/eval/question-sets/{qs['id']}/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_run_not_found(client):
    resp = client.get("/eval/runs/nonexistent-id")
    assert resp.status_code == 404
