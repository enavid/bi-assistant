from __future__ import annotations

import asyncio

import pytest

from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator

pytestmark = pytest.mark.integration


def _run(orchestrator, question: str) -> dict:
    result = orchestrator.run(question)
    return result.to_dict() if hasattr(result, "to_dict") else result


def test_orchestrator_generates_sql_for_total_employee_count(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    assert payload["route"] == "SQL"
    assert payload["status"] in {"OK", "VALID", "SQL_READY", "NOT_EXECUTED"}
    assert "hr_mvp.vw_hr_employee_analytics" in (payload.get("generated_sql") or "")


def test_orchestrator_returns_gap_for_city_level_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کارکنان شهر تهران چند نفر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == "DATA_GAP"


def test_orchestrator_rejects_personal_information(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "نام و کد ملی کارکنان را بده")
    assert payload["route"] == "REJECT"
    assert payload["status"] == "ACCESS_DENIED"


def test_orchestrator_rejects_out_of_scope_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "قیمت دلار امروز چقدر است؟")
    assert payload["route"] == "REJECT"
    assert payload["status"] in {"OUT_OF_SCOPE", "REJECT"}


def test_orchestrator_handles_empty_question_gracefully(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "")
    assert payload["route"] in {"REJECT", "NEEDS_CLARIFICATION"}
    assert "request_id" in payload


def test_orchestrator_handles_whitespace_only_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "   ")
    assert payload["route"] in {"REJECT", "NEEDS_CLARIFICATION"}


def test_orchestrator_gender_breakdown_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "درصد کارکنان زن و مرد چقدر است؟")
    assert payload["route"] == "SQL"
    assert payload.get("generated_sql") is not None


def test_orchestrator_response_has_required_fields(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    for field in ("route", "status", "message_fa", "request_id", "warnings", "errors"):
        assert field in payload, f"Missing field: {field}"


def test_orchestrator_fallback_mode_without_steps(metadata_service):
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        domain_classifier=None,
        question_validator=None,
    )
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    assert payload["route"] in {"SQL", "GAP", "REJECT", "NEEDS_CLARIFICATION"}
    assert "request_id" in payload


def test_orchestrator_arun_is_consistent_with_run(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    question = "تعداد کل کارکنان چند نفر است؟"
    sync_result = orchestrator.run(question)
    async_result = asyncio.run(orchestrator.arun(question))
    sync_payload = sync_result.to_dict() if hasattr(sync_result, "to_dict") else sync_result
    async_payload = async_result.to_dict() if hasattr(async_result, "to_dict") else async_result
    assert sync_payload["route"] == async_payload["route"]
    assert sync_payload["status"] == async_payload["status"]


# ---------------------------------------------------------------------------
# BUG-002 — LLMOrchestrator must accept and store ollama_client
# ---------------------------------------------------------------------------


def test_orchestrator_accepts_ollama_client_param(metadata_service):
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_client,
    )
    assert orchestrator.ollama_client is mock_client


def test_orchestrator_ollama_client_defaults_to_none(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    assert orchestrator.ollama_client is None


@pytest.mark.asyncio
async def test_orchestrator_calls_ollama_when_model_in_runtime_params(metadata_service):
    """When model is set in runtime_params, OllamaClient must be called for valid SQL questions."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) AS employee_count"
        " FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()

    mock_ollama.generate.assert_called_once()
    call_kwargs = mock_ollama.generate.call_args.kwargs
    assert call_kwargs.get("model") == "llama3.1:8b"
    assert payload["route"] == "SQL"
    assert "employee_count" in (payload.get("generated_sql") or "").lower()


@pytest.mark.asyncio
async def test_orchestrator_does_not_call_ollama_when_no_model(metadata_service):
    """Without model in runtime_params, OllamaClient must not be called."""
    from unittest.mock import AsyncMock

    mock_ollama = AsyncMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun("تعداد کارکنان چند نفر است؟")

    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_ollama_not_called_for_rejected_question(metadata_service):
    """Rejected questions (ACCESS_DENIED, OUT_OF_SCOPE) must never reach OllamaClient."""
    from unittest.mock import AsyncMock

    mock_ollama = AsyncMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun(
        "نام و کد ملی کارکنان را بده",
        runtime_params={"model": "llama3.1:8b"},
    )

    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_model_called_appears_in_response(metadata_service):
    """model_called field in sql_plan metadata must reflect the selected model."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()
    sql_plan = (payload.get("context") or {}).get("sql_plan") or {}
    model_in_meta = (sql_plan.get("metadata") or {}).get("model")
    assert model_in_meta == "llama3.1:8b"


@pytest.mark.asyncio
async def test_orchestrator_skips_sql_generator_when_model_set(metadata_service):
    """When model is set, sql_generator must NOT be called — LLM primary path handles it."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun("تعداد کارکنان؟", runtime_params={"model": "llama3.1:8b"})

    mock_generator.arun.assert_not_called()
    mock_ollama.generate.assert_called_once()
