"""Tests for eval run trigger and background execution — TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_set_with_questions(client, n: int = 3) -> dict:
    qs = client.post("/eval/question-sets", json={"name": "Test Set"}).json()
    questions = [
        {"question_id": f"q{i:03d}", "question": f"سوال {i}", "category": "demographics"}
        for i in range(1, n + 1)
    ]
    client.post(f"/eval/question-sets/{qs['id']}/questions", json=questions)
    return qs


# ---------------------------------------------------------------------------
# Trigger endpoint
# ---------------------------------------------------------------------------


def test_trigger_run_returns_201_with_pending_status(client):
    qs = _seed_set_with_questions(client)
    with patch("app.api.routes.eval._run_evaluation_background"):
        resp = client.post(f"/eval/question-sets/{qs['id']}/run")
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["set_id"] == qs["id"]
    assert "id" in data


def test_trigger_run_nonexistent_set(client):
    resp = client.post("/eval/question-sets/nonexistent-id/run")
    assert resp.status_code == 404


def test_trigger_run_empty_set_returns_400(client):
    qs = client.post("/eval/question-sets", json={"name": "Empty"}).json()
    resp = client.post(f"/eval/question-sets/{qs['id']}/run")
    assert resp.status_code == 400


def test_trigger_run_appears_in_list(client):
    qs = _seed_set_with_questions(client)
    with patch("app.api.routes.eval._run_evaluation_background"):
        client.post(f"/eval/question-sets/{qs['id']}/run")
    runs = client.get(f"/eval/question-sets/{qs['id']}/runs").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Background execution unit tests
# ---------------------------------------------------------------------------


def _make_mock_response(route: str = "SQL", status: str = "NOT_EXECUTED") -> MagicMock:
    response = MagicMock()
    response.to_dict.return_value = {
        "route": route,
        "status": status,
        "detected_intent": "employee_count",
        "errors": [],
        "warnings": [],
        "context": {
            "traces": [{"step": "domain_classifier", "status": "ok", "duration_ms": 10, "details": {}}],
            "sql_plan": {"source": "template", "template_id": "t1", "metadata": {"model": "llama3"}},
            "query_result": {},
            "sql_validation": {},
            "visualization_plan": {},
        },
    }
    return response


@pytest.mark.asyncio
async def test_execute_run_sets_status_to_done(db_engine):
    from app.api.routes.eval import _run_evaluation_background

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        qs = EvalQuestionSetORM(name="bg test")
        session.add(qs)
        await session.flush()
        q = EvalQuestionORM(set_id=qs.id, question_id="q001", question="سوال اول")
        session.add(q)
        await session.flush()
        run = EvalRunORM(set_id=qs.id, status="pending", total=1)
        session.add(run)
        await session.commit()
        run_id = run.id
        question_ids = [q.id]

    mock_orchestrator = AsyncMock()
    mock_orchestrator.arun.return_value = _make_mock_response()

    await _run_evaluation_background(run_id=run_id, question_ids=question_ids, session_factory=factory, orchestrator=mock_orchestrator)

    async with factory() as session:
        updated = (await session.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))).scalar_one()
        assert updated.status == "done"
        assert updated.total == 1
        assert updated.passed == 1
        assert updated.failed == 0


@pytest.mark.asyncio
async def test_execute_run_saves_results(db_engine):
    from app.api.routes.eval import _run_evaluation_background

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        qs = EvalQuestionSetORM(name="results test")
        session.add(qs)
        await session.flush()
        q = EvalQuestionORM(
            set_id=qs.id, question_id="q001", question="سوال",
            category="demographics", expected_route="SQL",
        )
        session.add(q)
        await session.flush()
        run = EvalRunORM(set_id=qs.id, status="pending", total=1)
        session.add(run)
        await session.commit()
        run_id = run.id
        question_ids = [q.id]

    mock_orchestrator = AsyncMock()
    mock_orchestrator.arun.return_value = _make_mock_response(route="SQL", status="NOT_EXECUTED")

    await _run_evaluation_background(run_id=run_id, question_ids=question_ids, session_factory=factory, orchestrator=mock_orchestrator)

    async with factory() as session:
        results = (
            await session.execute(select(EvalRunResultORM).where(EvalRunResultORM.run_id == run_id))
        ).scalars().all()
        assert len(results) == 1
        r = results[0]
        assert r.actual_route == "SQL"
        assert r.category == "demographics"
        assert r.source == "template"


@pytest.mark.asyncio
async def test_execute_run_sets_failed_on_error(db_engine):
    from app.api.routes.eval import _run_evaluation_background

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        qs = EvalQuestionSetORM(name="error test")
        session.add(qs)
        await session.flush()
        q = EvalQuestionORM(set_id=qs.id, question_id="q001", question="سوال")
        session.add(q)
        await session.flush()
        run = EvalRunORM(set_id=qs.id, status="pending", total=1)
        session.add(run)
        await session.commit()
        run_id = run.id
        question_ids = [q.id]

    mock_orchestrator = AsyncMock()
    mock_orchestrator.arun.side_effect = RuntimeError("LLM unavailable")

    await _run_evaluation_background(run_id=run_id, question_ids=question_ids, session_factory=factory, orchestrator=mock_orchestrator)

    async with factory() as session:
        updated = (await session.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))).scalar_one()
        assert updated.status == "done"
        assert updated.failed == 1
        results = (
            await session.execute(select(EvalRunResultORM).where(EvalRunResultORM.run_id == run_id))
        ).scalars().all()
        assert results[0].error == "LLM unavailable"
        assert results[0].passed is False
