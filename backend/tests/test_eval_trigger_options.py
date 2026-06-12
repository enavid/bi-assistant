"""Tests for trigger_run with category filter and model_name — TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
async def db_engine():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_EVAL_TABLES))
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_EVAL_TABLES))
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture()
def client(db_engine, db_session):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with patch("app.api.routes.eval.AsyncSessionLocal", new=factory):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def _make_set_with_questions(client) -> str:
    set_id = client.post("/eval/question-sets", json={"name": "Test"}).json()["id"]
    client.post(
        f"/eval/question-sets/{set_id}/questions",
        json=[
            {"question_id": "q1", "question": "سوال ۱", "category": "demographics"},
            {"question_id": "q2", "question": "سوال ۲", "category": "demographics"},
            {"question_id": "q3", "question": "سوال ۳", "category": "education"},
        ],
    )
    return set_id


def test_trigger_run_with_category_filter(client):
    set_id = _make_set_with_questions(client)
    mock_orch = AsyncMock()
    mock_orch.arun.return_value = AsyncMock(to_dict=lambda: {
        "route": "SQL", "status": "NOT_EXECUTED", "detected_intent": "",
        "context": {}, "errors": [], "warnings": [],
    })
    with patch("app.api.routes.eval.build_orchestrator", return_value=mock_orch):
        resp = client.post(
            f"/eval/question-sets/{set_id}/run",
            json={"category": "demographics"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 2


def test_trigger_run_stores_model_name(client):
    set_id = _make_set_with_questions(client)
    mock_orch = AsyncMock()
    mock_orch.arun.return_value = AsyncMock(to_dict=lambda: {
        "route": "SQL", "status": "NOT_EXECUTED", "detected_intent": "",
        "context": {}, "errors": [], "warnings": [],
    })
    with patch("app.api.routes.eval.build_orchestrator", return_value=mock_orch):
        resp = client.post(
            f"/eval/question-sets/{set_id}/run",
            json={"model_name": "qwen2.5-coder"},
        )
    assert resp.status_code == 201
    assert resp.json()["model_name"] == "qwen2.5-coder"


def test_trigger_run_no_body_uses_all_questions(client):
    set_id = _make_set_with_questions(client)
    mock_orch = AsyncMock()
    mock_orch.arun.return_value = AsyncMock(to_dict=lambda: {
        "route": "SQL", "status": "NOT_EXECUTED", "detected_intent": "",
        "context": {}, "errors": [], "warnings": [],
    })
    with patch("app.api.routes.eval.build_orchestrator", return_value=mock_orch):
        resp = client.post(f"/eval/question-sets/{set_id}/run", json={})
    assert resp.status_code == 201
    assert resp.json()["total"] == 3


def test_trigger_run_unknown_category_returns_400(client):
    set_id = _make_set_with_questions(client)
    resp = client.post(
        f"/eval/question-sets/{set_id}/run",
        json={"category": "nonexistent_category"},
    )
    assert resp.status_code == 400
