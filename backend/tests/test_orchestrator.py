from __future__ import annotations

from app.services.hr_bi.llm_orchestrator import LLMOrchestrator


def test_orchestrator_generates_sql_for_total_employee_count(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("تعداد کل کارکنان چند نفر است؟")
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    assert payload["route"] == "SQL"
    assert payload["status"] in {"OK", "VALID", "SQL_READY", "NOT_EXECUTED"}
    assert "hr_mvp.vw_hr_employee_analytics" in (payload.get("generated_sql") or "")


def test_orchestrator_returns_gap_for_city_level_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("تعداد کارکنان شهر تهران چند نفر است؟")
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    assert payload["route"] == "GAP"
    assert payload["status"] == "DATA_GAP"


def test_orchestrator_rejects_personal_information(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("نام و کد ملی کارکنان را بده")
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    assert payload["route"] == "REJECT"
    assert payload["status"] == "ACCESS_DENIED"
