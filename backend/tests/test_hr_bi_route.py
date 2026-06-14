"""Tests for /hr-bi routes — TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _mock_response(payload: dict) -> MagicMock:
    r = MagicMock()
    r.to_dict.return_value = payload
    return r


# ---------------------------------------------------------------------------
# GET /hr-bi/health
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    mock_meta = MagicMock()
    mock_meta.health_check.return_value.to_dict.return_value = {"ok": True}
    with patch("app.infrastructure.metadata.loader.get_metadata", return_value=mock_meta):
        resp = client.get("/hr-bi/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "metadata" in data


def test_health_returns_metadata_warning_when_not_ok(client):
    mock_meta = MagicMock()
    mock_meta.health_check.return_value.to_dict.return_value = {"ok": False}
    with patch("app.infrastructure.metadata.loader.get_metadata", return_value=mock_meta):
        resp = client.get("/hr-bi/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "metadata_warning"


def test_health_returns_500_on_exception(client):
    with patch(
        "app.infrastructure.metadata.loader.get_metadata", side_effect=RuntimeError("db down")
    ):
        resp = client.get("/hr-bi/health")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /hr-bi/chat
# ---------------------------------------------------------------------------


def _chat_payload(**kwargs) -> dict:
    base = {
        "request_id": "req-001",
        "route": "SQL",
        "status": "NOT_EXECUTED",
        "message_fa": "",
        "generated_sql": "SELECT 1",
        "context": {},
    }
    base.update(kwargs)
    return base


def test_chat_returns_orchestrator_response(client):
    mock_orch = AsyncMock()
    mock_orch.arun.return_value = _mock_response(_chat_payload())
    with patch("app.hr_analytics.api.routes.get_hr_bi_orchestrator", return_value=mock_orch):
        resp = client.post("/hr-bi/chat", json={"question": "تعداد کارکنان؟"})
    assert resp.status_code == 200
    assert resp.json()["route"] == "SQL"


def test_chat_passes_question_to_orchestrator(client):
    mock_orch = AsyncMock()
    mock_orch.arun.return_value = _mock_response(_chat_payload())
    with patch("app.hr_analytics.api.routes.get_hr_bi_orchestrator", return_value=mock_orch):
        client.post("/hr-bi/chat", json={"question": "سوال تست", "user_role": "admin"})
    call_kwargs = mock_orch.arun.call_args
    assert call_kwargs.args[0] == "سوال تست"
    assert call_kwargs.kwargs.get("user_role") == "admin"


def test_chat_returns_500_on_exception(client):
    mock_orch = AsyncMock()
    mock_orch.arun.side_effect = RuntimeError("LLM down")
    with patch("app.hr_analytics.api.routes.get_hr_bi_orchestrator", return_value=mock_orch):
        resp = client.post("/hr-bi/chat", json={"question": "سوال"})
    assert resp.status_code == 500


def test_chat_question_required(client):
    resp = client.post("/hr-bi/chat", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# BUG-004 — /chat/generate must pass execute_sql to uc.generate()
# ---------------------------------------------------------------------------


@pytest.fixture()
def chat_client():
    with TestClient(app) as c:
        yield c


def _make_generate_result():
    from app.hr_analytics.domain.entities import GenerationResult

    return GenerationResult(sql="SELECT 1", success=True, route="SQL", status="NOT_EXECUTED")


def _chat_generate_patches(mock_uc_instance):
    """Context managers that isolate /chat/generate from real orchestrator construction."""
    from unittest.mock import MagicMock

    return (
        patch("app.hr_analytics.api.chat_routes.get_hr_bi_orchestrator", return_value=MagicMock()),
        patch(
            "app.hr_analytics.api.chat_routes.HRBIOrchestrationUseCase",
            return_value=mock_uc_instance,
        ),
    )


def test_generate_route_passes_execute_sql_true(chat_client):
    """BUG-004: execute_sql=true in request body must be forwarded to uc.generate()."""
    mock_uc_instance = AsyncMock()
    mock_uc_instance.generate.return_value = _make_generate_result()

    p1, p2 = _chat_generate_patches(mock_uc_instance)
    with p1, p2:
        resp = chat_client.post(
            "/chat/generate",
            json={"question": "تعداد کارکنان؟", "execute_sql": True},
        )

    assert resp.status_code == 200
    mock_uc_instance.generate.assert_called_once()
    call_kwargs = mock_uc_instance.generate.call_args.kwargs
    assert call_kwargs.get("execute_sql") is True


def test_generate_route_passes_execute_sql_false_by_default(chat_client):
    """BUG-004: when execute_sql is omitted, uc.generate() must receive execute_sql=False."""
    mock_uc_instance = AsyncMock()
    mock_uc_instance.generate.return_value = _make_generate_result()

    p1, p2 = _chat_generate_patches(mock_uc_instance)
    with p1, p2:
        resp = chat_client.post(
            "/chat/generate",
            json={"question": "تعداد کارکنان؟"},
        )

    assert resp.status_code == 200
    mock_uc_instance.generate.assert_called_once()
    call_kwargs = mock_uc_instance.generate.call_args.kwargs
    assert call_kwargs.get("execute_sql") is False
