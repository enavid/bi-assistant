from __future__ import annotations

from app.use_cases.hr_analytics.orchestrator import LLMOrchestrator, ValidationStatus
from app.use_cases.hr_analytics.steps.decision_router import DecisionRouter
from app.use_cases.hr_analytics.steps.question_validator import QuestionValidator


def _run(orchestrator, question: str) -> dict:
    result = orchestrator.run(question)
    return result.to_dict() if hasattr(result, "to_dict") else result


# ---------------------------------------------------------------------------
# 1. Trace: context and traces present in response
# ---------------------------------------------------------------------------


def test_trace_context_present_in_response(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    assert "context" in payload
    ctx = payload["context"]
    assert isinstance(ctx, dict)
    assert "traces" in ctx
    assert isinstance(ctx["traces"], list)
    assert len(ctx["traces"]) > 0


def test_trace_steps_named(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    step_names = [t["step"] for t in payload["context"]["traces"]]
    assert "normalize_question" in step_names
    assert "domain_classifier" in step_names
    assert "response_builder" in step_names


# ---------------------------------------------------------------------------
# 2. ANALYTICAL_GAP: contractor productivity and workload alignment
# ---------------------------------------------------------------------------


def test_analytical_gap_for_contractor_productivity(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بهره وری پیمانکار در هر حوزه چقدر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.ANALYTICAL_GAP.value


def test_analytical_gap_for_workload_alignment(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "آیا جذب نیرو با حجم کار سازمان هماهنگ بوده؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.ANALYTICAL_GAP.value


def test_data_gap_still_works_for_city(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کارکنان شهر تهران چند نفر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


def test_analytical_gap_message_is_specific(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بهره وری پیمانکار در هر حوزه چقدر است؟")
    assert payload["status"] == "ANALYTICAL_GAP"
    assert "تحلیل" in payload["message_fa"] or "شاخص" in payload["message_fa"]


# ---------------------------------------------------------------------------
# 3. Routing bugs
# ---------------------------------------------------------------------------


def test_most_hiring_year_not_rejected(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بیشترین جذب")
    assert payload["route"] == "SQL"
    assert payload.get("detected_intent") == "most_or_least_hiring_year"


def test_low_education_expert_roles_not_least_common(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد افراد با مدرک پایین‌تر از نیاز پست چقدر است؟")
    assert payload["route"] == "SQL"
    assert payload.get("detected_intent") == "low_education_in_expert_roles"


def test_list_with_identifier_is_access_denied(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "لیست افراد بالای ۶۰ سال با شناسه")
    assert payload["route"] == "REJECT"
    assert payload["status"] == "ACCESS_DENIED"


def test_domain_classifier_passes_list_with_identifier_as_hr():
    from app.use_cases.hr_analytics.steps.domain_classifier import DomainClassifier

    clf = DomainClassifier()
    result = clf.classify("لیست افراد بالای ۶۰ سال با شناسه‌شان را بده")
    assert result["is_hr"] is True, f"Expected HR but got: {result}"


# ---------------------------------------------------------------------------
# 4. Status templates in decision router
# ---------------------------------------------------------------------------


def test_decision_router_status_template_routes_to_reject(metadata_service):
    router = DecisionRouter(metadata_service=metadata_service)

    class FakeContext:
        domain_result = {"status": "OK", "is_hr": True}
        validation_result = {"status": "OK", "is_valid": True}
        semantic_result = {"status": "OK"}
        intent_result = {
            "intent_id": "individual_employee_info",
            "intent": "individual_employee_info",
            "route": "SQL",
            "status": "supported",
            "confidence": 0.95,
            "sql_template_id": "TPL_ACCESS_DENIED",
            "required_columns": [],
        }
        user_role = "demo_user"

    decision = router.route("نام کارکنان را بده", context=FakeContext())
    assert decision["route"] == "REJECT"
    assert decision["status"] == "ACCESS_DENIED"
    assert decision.get("sql_template_id") is None


def test_decision_router_status_template_data_gap(metadata_service):
    router = DecisionRouter(metadata_service=metadata_service)

    class FakeContext:
        domain_result = {"status": "OK", "is_hr": True}
        validation_result = {"status": "OK", "is_valid": True}
        semantic_result = {"status": "OK"}
        intent_result = {
            "intent_id": "city_level_analysis",
            "intent": "city_level_analysis",
            "route": "SQL",
            "status": "supported",
            "confidence": 0.9,
            "sql_template_id": "TPL_DATA_GAP",
            "required_columns": [],
        }
        user_role = "demo_user"

    decision = router.route("تعداد کارکنان شهر تهران", context=FakeContext())
    assert decision["route"] == "GAP"
    assert decision["status"] == "DATA_GAP"


# ---------------------------------------------------------------------------
# 5. Question validator: analytical gap rules
# ---------------------------------------------------------------------------


def test_question_validator_analytical_gap_contractor():
    validator = QuestionValidator()
    result = validator.validate("بهره وری پیمانکار چقدر است؟")
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


def test_question_validator_standard_data_gap_city():
    validator = QuestionValidator()
    result = validator.validate("تعداد کارکنان هر شهر چقدر است؟")
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"


def test_question_validator_access_denied_list_with_identifier():
    validator = QuestionValidator()
    result = validator.validate("لیست افراد بالای ۶۰ سال با شناسه")
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"


def test_question_validator_access_denied_list_of_people():
    validator = QuestionValidator()
    result = validator.validate("لیست افراد دپارتمان مالی را بده")
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"
