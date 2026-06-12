"""Tests for POST /eval/seed-defaults — TDD."""

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


def test_seed_defaults_creates_set(client):
    resp = client.post("/eval/seed-defaults")
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["question_count"] > 0


def test_seed_defaults_imports_all_questions(client):
    resp = client.post("/eval/seed-defaults")
    assert resp.status_code == 201
    data = resp.json()
    # phase2 has 240 questions
    assert data["question_count"] >= 10


def test_seed_defaults_idempotent(client):
    client.post("/eval/seed-defaults")
    resp2 = client.post("/eval/seed-defaults")
    # second call returns existing set (200) not duplicate (201)
    assert resp2.status_code in (200, 201)
    sets = client.get("/eval/question-sets").json()
    default_sets = [s for s in sets if s.get("is_default")]
    assert len(default_sets) == 1


def test_seed_defaults_has_categories(client):
    resp = client.post("/eval/seed-defaults")
    assert resp.status_code == 201
    set_id = resp.json()["id"]
    questions = client.get(f"/eval/question-sets/{set_id}/questions").json()
    categories = {q["category"] for q in questions if q.get("category")}
    assert len(categories) >= 5
