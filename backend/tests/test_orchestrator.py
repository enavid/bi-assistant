from __future__ import annotations

import asyncio

import pytest

from app.use_cases.hr_analytics.orchestrator import LLMOrchestrator

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
