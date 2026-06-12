"""Tests for HRBIOrchestrationUseCase and _derive_source — TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.use_cases.hr_analytics.orchestrate import HRBIOrchestrationUseCase, _derive_source


def _make_orchestrator(payload: dict) -> AsyncMock:
    response = MagicMock()
    response.to_dict.return_value = payload
    orch = AsyncMock()
    orch.arun.return_value = response
    return orch


def _base_payload(**kwargs) -> dict:
    base = {
        "generated_sql": "SELECT COUNT(*) FROM employees",
        "status": "NOT_EXECUTED",
        "route": "SQL",
        "errors": [],
        "warnings": [],
        "message_fa": None,
        "detected_intent": "employee_count",
        "context": {
            "traces": [{"step": "domain_classifier", "status": "ok", "duration_ms": 10}],
            "sql_plan": {
                "source": "template",
                "template_id": "tmpl_001",
                "metadata": {"model": "llama3"},
            },
            "query_result": {},
        },
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# generate() — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success_returns_result():
    uc = HRBIOrchestrationUseCase(_make_orchestrator(_base_payload()))
    result = await uc.generate("تعداد کارکنان؟")
    assert result.success is True
    assert result.sql == "SELECT COUNT(*) FROM employees"
    assert result.route == "SQL"
    assert result.status == "NOT_EXECUTED"


@pytest.mark.asyncio
async def test_generate_passes_question_to_orchestrator():
    orch = _make_orchestrator(_base_payload())
    uc = HRBIOrchestrationUseCase(orch)
    await uc.generate("سوال تست", user_id="u1", user_role="admin", execute_sql=True)
    orch.arun.assert_called_once_with(
        "سوال تست", user_id="u1", user_role="admin", execute_sql=True
    )


@pytest.mark.asyncio
async def test_generate_extracts_template_id_and_model():
    uc = HRBIOrchestrationUseCase(_make_orchestrator(_base_payload()))
    result = await uc.generate("سوال")
    assert result.template_id == "tmpl_001"
    assert result.model_called == "llama3"


@pytest.mark.asyncio
async def test_generate_extracts_traces():
    uc = HRBIOrchestrationUseCase(_make_orchestrator(_base_payload()))
    result = await uc.generate("سوال")
    assert len(result.traces) == 1
    assert result.traces[0]["step"] == "domain_classifier"


@pytest.mark.asyncio
async def test_generate_source_from_sql_plan():
    uc = HRBIOrchestrationUseCase(_make_orchestrator(_base_payload()))
    result = await uc.generate("سوال")
    assert result.source == "template"


# ---------------------------------------------------------------------------
# generate() — rejected statuses → success=False
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rej_status", [
    "ACCESS_DENIED", "OUT_OF_SCOPE", "DATA_GAP",
    "ANALYTICAL_GAP", "SQL_VALIDATION_FAILED", "METADATA_ERROR",
])
@pytest.mark.asyncio
async def test_generate_rejected_status_sets_success_false(rej_status):
    payload = _base_payload(status=rej_status, generated_sql="SELECT 1")
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال")
    assert result.success is False


@pytest.mark.asyncio
async def test_generate_no_sql_sets_success_false():
    payload = _base_payload(generated_sql="")
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال")
    assert result.success is False


@pytest.mark.asyncio
async def test_generate_error_uses_message_fa():
    payload = _base_payload(generated_sql="", status="OUT_OF_SCOPE", message_fa="خارج از حوزه")
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال")
    assert result.error == "خارج از حوزه"


@pytest.mark.asyncio
async def test_generate_error_falls_back_to_errors_list():
    payload = _base_payload(generated_sql="", status="DATA_GAP", errors=["داده موجود نیست"])
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال")
    assert result.error == "داده موجود نیست"


@pytest.mark.asyncio
async def test_generate_error_falls_back_to_status():
    payload = _base_payload(generated_sql="", status="METADATA_ERROR", errors=[])
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال")
    assert result.error == "METADATA_ERROR"


# ---------------------------------------------------------------------------
# generate() — executed SQL with row_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_executed_sql_sets_row_count():
    payload = _base_payload()
    payload["context"]["query_result"] = {
        "execution_status": "SUCCESS",
        "rows": [[1], [2], [3]],
    }
    uc = HRBIOrchestrationUseCase(_make_orchestrator(payload))
    result = await uc.generate("سوال", execute_sql=True)
    assert result.executed is True
    assert result.row_count == 3


@pytest.mark.asyncio
async def test_generate_not_executed_row_count_is_none():
    uc = HRBIOrchestrationUseCase(_make_orchestrator(_base_payload()))
    result = await uc.generate("سوال")
    assert result.executed is False
    assert result.row_count is None


# ---------------------------------------------------------------------------
# _derive_source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,route,expected", [
    ("ACCESS_DENIED", "SQL", "reject"),
    ("OUT_OF_SCOPE", "SQL", "reject"),
    ("NOT_EXECUTED", "REJECT", "reject"),
    ("DATA_GAP", "SQL", "gap"),
    ("ANALYTICAL_GAP", "SQL", "gap"),
    ("NOT_EXECUTED", "GAP", "gap"),
    ("NEEDS_CLARIFICATION", "SQL", "clarification"),
    ("NOT_EXECUTED", "NEEDS_CLARIFICATION", "clarification"),
    ("NOT_EXECUTED", "SQL", "unknown"),
    ("", "", "unknown"),
])
def test_derive_source(status, route, expected):
    assert _derive_source(route, status) == expected
