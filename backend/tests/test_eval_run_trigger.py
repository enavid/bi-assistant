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
    with patch("app.evaluation.api.routes._run_evaluation_background"):
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
    with patch("app.evaluation.api.routes._run_evaluation_background"):
        client.post(f"/eval/question-sets/{qs['id']}/run")
    runs = client.get(f"/eval/question-sets/{qs['id']}/runs").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "pending"


def test_trigger_run_with_question_ids_runs_only_those(client):
    qs = _seed_set_with_questions(client, n=5)
    questions = client.get(f"/eval/question-sets/{qs['id']}/questions").json()
    first_id = questions[0]['id']

    with patch("app.evaluation.api.routes._run_evaluation_background"):
        resp = client.post(
            f"/eval/question-sets/{qs['id']}/run",
            json={"question_ids": [first_id]},
        )
    assert resp.status_code == 201
    assert resp.json()["total"] == 1


def test_trigger_run_with_empty_question_ids_returns_400(client):
    qs = _seed_set_with_questions(client)
    resp = client.post(
        f"/eval/question-sets/{qs['id']}/run",
        json={"question_ids": []},
    )
    assert resp.status_code == 400


def test_trigger_run_with_nonexistent_question_ids_returns_400(client):
    qs = _seed_set_with_questions(client)
    resp = client.post(
        f"/eval/question-sets/{qs['id']}/run",
        json={"question_ids": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert resp.status_code == 400


def test_trigger_run_blocked_when_pending_run_exists(client):
    qs = _seed_set_with_questions(client)
    with patch("app.evaluation.api.routes._run_evaluation_background"):
        first = client.post(f"/eval/question-sets/{qs['id']}/run")
        assert first.status_code == 201
        second = client.post(f"/eval/question-sets/{qs['id']}/run")
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()


def test_trigger_run_blocked_when_running_run_exists(client, db_session):
    import asyncio
    qs = _seed_set_with_questions(client)
    with patch("app.evaluation.api.routes._run_evaluation_background"):
        first = client.post(f"/eval/question-sets/{qs['id']}/run")
    run_id = first.json()["id"]

    async def _set_running():
        from sqlalchemy import update
        await db_session.execute(
            update(EvalRunORM).where(EvalRunORM.id == run_id).values(status="running")
        )
        await db_session.commit()

    asyncio.get_event_loop().run_until_complete(_set_running())

    with patch("app.evaluation.api.routes._run_evaluation_background"):
        second = client.post(f"/eval/question-sets/{qs['id']}/run")
    assert second.status_code == 409


def test_trigger_run_allowed_after_done(client, db_session):
    import asyncio
    qs = _seed_set_with_questions(client)
    with patch("app.evaluation.api.routes._run_evaluation_background"):
        first = client.post(f"/eval/question-sets/{qs['id']}/run")
    run_id = first.json()["id"]

    async def _set_done():
        from sqlalchemy import update
        await db_session.execute(
            update(EvalRunORM).where(EvalRunORM.id == run_id).values(status="done")
        )
        await db_session.commit()

    asyncio.get_event_loop().run_until_complete(_set_done())

    with patch("app.evaluation.api.routes._run_evaluation_background"):
        second = client.post(f"/eval/question-sets/{qs['id']}/run")
    assert second.status_code == 201


# ---------------------------------------------------------------------------
# Startup orphan reset tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_orphaned_runs_sets_failed(db_engine):
    from app.main import _reset_orphaned_eval_runs

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        qs = EvalQuestionSetORM(name="orphan test")
        session.add(qs)
        await session.flush()
        pending_run = EvalRunORM(set_id=qs.id, status="pending", total=5)
        running_run = EvalRunORM(set_id=qs.id, status="running", total=5)
        done_run = EvalRunORM(set_id=qs.id, status="done", total=5)
        session.add_all([pending_run, running_run, done_run])
        await session.commit()
        pending_id = pending_run.id
        running_id = running_run.id
        done_id = done_run.id

    await _reset_orphaned_eval_runs(factory)

    async with factory() as session:
        rows = {
            r.id: r.status
            for r in (await session.execute(select(EvalRunORM))).scalars().all()
        }

    assert rows[pending_id] == "failed"
    assert rows[running_id] == "failed"
    assert rows[done_id] == "done"


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
            "traces": [
                {"step": "domain_classifier", "status": "ok", "duration_ms": 10, "details": {}}
            ],
            "sql_plan": {
                "source": "template",
                "template_id": "t1",
                "metadata": {"model": "llama3"},
            },
            "query_result": {},
            "sql_validation": {},
            "visualization_plan": {},
        },
    }
    return response


@pytest.mark.asyncio
async def test_execute_run_sets_status_to_done(db_engine):
    from app.evaluation.api.routes import _run_evaluation_background

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

    await _run_evaluation_background(
        run_id=run_id,
        question_ids=question_ids,
        session_factory=factory,
        orchestrator=mock_orchestrator,
    )

    async with factory() as session:
        updated = (
            await session.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))
        ).scalar_one()
        assert updated.status == "done"
        assert updated.total == 1
        assert updated.passed == 1
        assert updated.failed == 0


@pytest.mark.asyncio
async def test_execute_run_saves_results(db_engine):
    from app.evaluation.api.routes import _run_evaluation_background

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        qs = EvalQuestionSetORM(name="results test")
        session.add(qs)
        await session.flush()
        q = EvalQuestionORM(
            set_id=qs.id,
            question_id="q001",
            question="سوال",
            category="demographics",
            expected_route="SQL",
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

    await _run_evaluation_background(
        run_id=run_id,
        question_ids=question_ids,
        session_factory=factory,
        orchestrator=mock_orchestrator,
    )

    async with factory() as session:
        results = (
            (
                await session.execute(
                    select(EvalRunResultORM).where(EvalRunResultORM.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(results) == 1
        r = results[0]
        assert r.actual_route == "SQL"
        assert r.category == "demographics"
        assert r.source == "template"


@pytest.mark.asyncio
async def test_execute_run_sets_failed_on_error(db_engine):
    from app.evaluation.api.routes import _run_evaluation_background

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

    await _run_evaluation_background(
        run_id=run_id,
        question_ids=question_ids,
        session_factory=factory,
        orchestrator=mock_orchestrator,
    )

    async with factory() as session:
        updated = (
            await session.execute(select(EvalRunORM).where(EvalRunORM.id == run_id))
        ).scalar_one()
        assert updated.status == "done"
        assert updated.failed == 1
        results = (
            (
                await session.execute(
                    select(EvalRunResultORM).where(EvalRunResultORM.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        assert results[0].error == "LLM unavailable"
        assert results[0].passed is False
