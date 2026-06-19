from __future__ import annotations

import pytest

from app.hr_analytics.adapters.response_builder import ResponseBuilder
from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator, ValidationStatus
from app.hr_analytics.use_cases.sql.template_engine import SQLTemplateEngine
from app.hr_analytics.use_cases.sql.validator import SQLValidator
from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
from app.hr_analytics.use_cases.steps.gap_service import GapService
from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator
from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper


class _SpySQLGenerator:
    """Minimal sql_generator stub that records calls and returns a fixed SQL."""

    def __init__(self, sql: str = "SELECT 1 AS spy_result;"):
        self.called = False
        self.sql = sql

    def run(self, **_kwargs):
        self.called = True
        return {"status": "OK", "sql": self.sql, "can_execute_sql": True, "source": "spy_generator"}

    # support call_component's multi-name lookup
    generate = run
    __call__ = run


def _run(orchestrator, question: str) -> dict:
    result = orchestrator.run(question)
    return result.to_dict() if hasattr(result, "to_dict") else result


def _full_orch(metadata_service) -> LLMOrchestrator:
    """Full orchestrator with all components wired — exercises real intent_parser logic."""
    return LLMOrchestrator(
        metadata_service=metadata_service,
        question_validator=QuestionValidator(),
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        router=DecisionRouter(metadata_service=metadata_service),
        sql_template_engine=SQLTemplateEngine(metadata_service=metadata_service),
        sql_validator=SQLValidator(metadata_service=metadata_service),
        gap_service=GapService(metadata_service=metadata_service),
        response_builder=ResponseBuilder(metadata_service=metadata_service),
        default_execute_sql=False,
    )


# ---------------------------------------------------------------------------
# 1. Trace: context and traces present in response
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trace_context_present_in_response(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    assert "context" in payload
    ctx = payload["context"]
    assert isinstance(ctx, dict)
    assert "traces" in ctx
    assert isinstance(ctx["traces"], list)
    assert len(ctx["traces"]) > 0


@pytest.mark.integration
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


@pytest.mark.integration
def test_analytical_gap_for_contractor_productivity(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بهره وری پیمانکار در هر حوزه چقدر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.ANALYTICAL_GAP.value


@pytest.mark.integration
def test_analytical_gap_for_workload_alignment(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "آیا جذب نیرو با حجم کار سازمان هماهنگ بوده؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.ANALYTICAL_GAP.value


@pytest.mark.integration
def test_data_gap_still_works_for_city(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کارکنان شهر تهران چند نفر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


@pytest.mark.integration
def test_analytical_gap_message_is_specific(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بهره وری پیمانکار در هر حوزه چقدر است؟")
    assert payload["status"] == "ANALYTICAL_GAP"
    assert "تحلیل" in payload["message_fa"] or "شاخص" in payload["message_fa"]


# ---------------------------------------------------------------------------
# 3. Routing bugs
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_most_hiring_year_not_rejected(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "بیشترین جذب")
    assert payload["route"] == "SQL"
    assert payload.get("detected_intent") == "most_or_least_hiring_year"


@pytest.mark.integration
def test_low_education_expert_roles_not_least_common(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد افراد با مدرک پایین‌تر از نیاز پست چقدر است؟")
    assert payload["route"] == "SQL"
    assert payload.get("detected_intent") == "low_education_in_expert_roles"


@pytest.mark.integration
def test_list_with_identifier_is_access_denied(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "لیست افراد بالای ۶۰ سال با شناسه")
    assert payload["route"] == "REJECT"
    assert payload["status"] == "ACCESS_DENIED"


def test_domain_classifier_passes_list_with_identifier_as_hr():
    from app.hr_analytics.use_cases.steps.domain_classifier import DomainClassifier

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


# ---------------------------------------------------------------------------
# BUG-011 — terminated / retired employees must route to DATA_GAP
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_terminated_employees_routes_to_data_gap(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کارکنان اخراج شده چند نفر است؟")
    assert payload["route"] == "GAP", f"Expected GAP, got '{payload['route']}'"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


@pytest.mark.integration
def test_resigned_employees_routes_to_data_gap(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "چند نفر ترک خدمت کرده‌اند؟")
    assert payload["route"] == "GAP", f"Expected GAP, got '{payload['route']}'"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


@pytest.mark.integration
def test_retired_employees_routes_to_data_gap(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کارکنان بازنشسته چند نفر است؟")
    assert payload["route"] == "GAP", f"Expected GAP, got '{payload['route']}'"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


@pytest.mark.integration
def test_inactive_employees_routes_to_data_gap(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "لیست کارکنان غیرفعال را بده")
    assert payload["route"] == "GAP", f"Expected GAP, got '{payload['route']}'"
    assert payload["status"] == ValidationStatus.DATA_GAP.value


def test_intent_parser_maps_ekhraj_to_data_gap_intent(metadata_service):
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser

    parser = IntentParser(metadata_service=metadata_service)
    result = parser.parse(
        question="تعداد کارکنان اخراج شده چند نفر است؟",
        semantic_result={},
        metadata=metadata_service,
    )
    assert result.get("route") == "GAP" or result.get("status") in {
        "DATA_GAP",
        "ANALYTICAL_GAP",
    }, f"Expected GAP/DATA_GAP route, got: {result}"


def test_intent_parser_maps_bazneshastan_to_data_gap_intent(metadata_service):
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser

    parser = IntentParser(metadata_service=metadata_service)
    result = parser.parse(
        question="کارکنان بازنشسته چند نفرند؟",
        semantic_result={},
        metadata=metadata_service,
    )
    assert result.get("route") == "GAP" or result.get("status") in {
        "DATA_GAP",
        "ANALYTICAL_GAP",
    }, f"Expected GAP/DATA_GAP route, got: {result}"


# ---------------------------------------------------------------------------
# data_gap_flags in semantic_mapper output
# ---------------------------------------------------------------------------


def test_semantic_mapper_output_has_data_gap_flags_field(metadata_service):
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    mapper = SemanticMapper(metadata_service=metadata_service)
    result = mapper.map(question="تعداد کارکنان زن چند نفرند؟")
    assert "data_gap_flags" in result, "semantic_mapper output must have data_gap_flags field"
    assert isinstance(result["data_gap_flags"], list)
    assert result["data_gap_flags"] == []


def test_semantic_mapper_gap_question_populates_data_gap_flags(metadata_service):
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    mapper = SemanticMapper(metadata_service=metadata_service)
    result = mapper.map(question="تعداد کارکنان اخراجی چند نفر است؟")
    assert "data_gap_flags" in result
    assert len(result["data_gap_flags"]) > 0
    assert all(isinstance(f, str) for f in result["data_gap_flags"])


# ---------------------------------------------------------------------------
# Trace fields: template_status, unused_filters, model_reason
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sql_planner_trace_has_template_status(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    traces = payload["context"]["traces"]
    planner = next((t for t in traces if t["step"] == "sql_planner"), None)
    assert planner is not None, "sql_planner trace step missing"
    assert "template_status" in planner["details"], "sql_planner trace must include template_status"


@pytest.mark.integration
def test_sql_planner_trace_has_model_reason(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    traces = payload["context"]["traces"]
    planner = next((t for t in traces if t["step"] == "sql_planner"), None)
    assert planner is not None
    assert "model_reason" in planner["details"], "sql_planner trace must include model_reason"


@pytest.mark.integration
def test_sql_planner_trace_has_unused_filters(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    traces = payload["context"]["traces"]
    planner = next((t for t in traces if t["step"] == "sql_planner"), None)
    assert planner is not None
    assert "unused_filters" in planner["details"], "sql_planner trace must include unused_filters"
    assert isinstance(planner["details"]["unused_filters"], list)


# ---------------------------------------------------------------------------
# Trace fields: sql_executed, row_count in query_executor
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_query_executor_trace_has_sql_executed(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    traces = payload["context"]["traces"]
    executor = next((t for t in traces if t["step"] == "query_executor"), None)
    assert executor is not None, "query_executor trace step missing"
    assert "sql_executed" in executor["details"], "query_executor trace must include sql_executed"
    assert executor["details"]["sql_executed"] is False


@pytest.mark.integration
def test_query_executor_trace_has_row_count(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    traces = payload["context"]["traces"]
    executor = next((t for t in traces if t["step"] == "query_executor"), None)
    assert executor is not None
    assert "row_count" in executor["details"], "query_executor trace must include row_count"


# ---------------------------------------------------------------------------
# Knowledge questions → KNOWLEDGE_GAP (not SQL)
# ---------------------------------------------------------------------------


def test_question_validator_definition_is_knowledge_gap():
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

    v = QuestionValidator()
    result = v.validate("تعریف چارت مصوب چیست؟")
    assert result["route"] == "GAP", f"Expected GAP, got: {result['route']}"
    assert result["status"] == "KNOWLEDGE_GAP", f"Expected KNOWLEDGE_GAP, got: {result['status']}"


def test_question_validator_difference_is_knowledge_gap():
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

    v = QuestionValidator()
    result = v.validate("تفاوت نوع استخدام و نوع قرارداد چیست؟")
    assert result["route"] == "GAP", f"Expected GAP, got: {result['route']}"
    assert result["status"] == "KNOWLEDGE_GAP", f"Expected KNOWLEDGE_GAP, got: {result['status']}"


def test_question_validator_meaning_is_knowledge_gap():
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

    v = QuestionValidator()
    result = v.validate("چارت مصوب یعنی چه؟")
    assert result["route"] == "GAP", f"Expected GAP, got: {result['route']}"
    assert result["status"] == "KNOWLEDGE_GAP", f"Expected KNOWLEDGE_GAP, got: {result['status']}"


def test_question_validator_normal_data_question_not_knowledge_gap():
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

    v = QuestionValidator()
    result = v.validate("تعداد کارکنان زن چند نفر است؟")
    assert result.get("status") != "KNOWLEDGE_GAP"


@pytest.mark.integration
def test_orchestrator_knowledge_question_routes_to_knowledge_gap(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orch, "تعریف چارت مصوب چیست؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == "KNOWLEDGE_GAP"


# ---------------------------------------------------------------------------
# Fix D: Q6 province filter vs group_by
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q6_province_filter_routes_to_sql(metadata_service):
    """'استان تهران' should be a WHERE filter, not cause group_by:province failure."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "تعداد کارکنان استان تهران به تفکیک حوزه سازمانی چقدر است؟")
    assert payload["route"] == "SQL", f"Expected SQL, got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q6_province_filter_sql_contains_province_and_domain(metadata_service):
    """Generated SQL must filter by province and group by service_domain."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "تعداد کارکنان استان تهران به تفکیک حوزه سازمانی چقدر است؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "PROVINCE" in sql, "SQL must reference province column"
    assert "SERVICE_DOMAIN" in sql, "SQL must group by service_domain"


# ---------------------------------------------------------------------------
# Fix B2: Q4 average age of contractors by gender
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q4_avg_age_contractor_by_gender_routes_to_sql(metadata_service):
    """'میانگین سن پیمانکاری به تفکیک جنسیت' must route to SQL, not REJECT."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "میانگین سن کارکنان شاغل در پیمانکاری به تفکیک جنسیت چقدر است؟")
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q4_avg_age_contractor_sql_has_avg_and_gender(metadata_service):
    """SQL must have AVG(age) grouped by gender with contractor filter."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "میانگین سن کارکنان شاغل در پیمانکاری به تفکیک جنسیت چقدر است؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "AVG" in sql, "SQL must use AVG aggregation for age"
    assert "GENDER" in sql, "SQL must reference gender column"


# ---------------------------------------------------------------------------
# Fix B3: Q1 gender composition by service domain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q1_gender_by_domain_routes_to_sql(metadata_service):
    """'ترکیب جنسیتی هر حوزه' must route to SQL."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "ترکیب جنسیتی هر حوزه سازمانی به درصد چگونه است؟")
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q1_gender_by_domain_sql_has_gender_and_service_domain(metadata_service):
    """SQL must group by both gender and service_domain."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "ترکیب جنسیتی هر حوزه سازمانی به درصد چگونه است؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "GENDER" in sql, "SQL must include gender column"
    assert "SERVICE_DOMAIN" in sql, "SQL must group by service_domain"


# ---------------------------------------------------------------------------
# Fix B1: Q7 education share intent routing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q7_education_share_routes_to_sql(metadata_service):
    """'سهم هر مدرک تحصیلی' must route to SQL via education intent."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "سهم هر مدرک تحصیلی از کل کارکنان چقدر است؟")
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q7_education_share_sql_has_education_title(metadata_service):
    """SQL must group by education_title."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "سهم هر مدرک تحصیلی از کل کارکنان چقدر است؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "EDUCATION_TITLE" in sql, "SQL must reference education_title"


# ---------------------------------------------------------------------------
# Fix C: Q5 female percentage by employment type
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q5_female_pct_by_employment_type_routes_to_sql(metadata_service):
    """'درصد زنان در هر نوع استخدام' must route to SQL."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "در هر نوع استخدام چند درصد کارکنان زن هستند؟")
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q5_female_pct_sql_has_gender_and_employment_type(metadata_service):
    """SQL must reference both gender and employment_type."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "در هر نوع استخدام چند درصد کارکنان زن هستند؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "EMPLOYMENT_TYPE" in sql, "SQL must group by employment_type"
    assert "GENDER" in sql or "ZAN" in sql or "زن".upper() in sql, "SQL must reference gender"


# ---------------------------------------------------------------------------
# Fix A: Q3 contract type by province
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q3_contract_by_province_routes_to_sql(metadata_service):
    """'سهم قرارداد در هر استان' must route to SQL."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "در هر استان سهم هر نوع قرارداد از کل کارکنان همان استان چند درصد است؟")
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q3_contract_by_province_sql_has_province_and_contract(metadata_service):
    """SQL must group by both province and contract_type."""
    orch = _full_orch(metadata_service)
    payload = _run(orch, "در هر استان سهم هر نوع قرارداد از کل کارکنان همان استان چند درصد است؟")
    sql = (payload.get("generated_sql") or "").upper()
    assert "PROVINCE" in sql, "SQL must reference province"
    assert "CONTRACT_TYPE" in sql, "SQL must group by contract_type"


# ---------------------------------------------------------------------------
# Fix A: Q8 near-retirement employees by service domain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_q8_near_retirement_by_domain_routes_to_sql(metadata_service):
    """'کارکنان نزدیک بازنشستگی بالای ۵۵ سال به تفکیک حوزه' must route to SQL."""
    orch = _full_orch(metadata_service)
    payload = _run(
        orch,
        "تعداد کارکنان نزدیک به بازنشستگی یعنی بالای ۵۵ سال به تفکیک حوزه سازمانی چقدر است؟",
    )
    assert payload["route"] == "SQL", f"Got {payload['route']} / {payload['status']}"


@pytest.mark.integration
def test_q8_near_retirement_sql_has_age_filter_and_domain(metadata_service):
    """SQL must filter by age > 55 and group by service_domain."""
    orch = _full_orch(metadata_service)
    payload = _run(
        orch,
        "تعداد کارکنان نزدیک به بازنشستگی یعنی بالای ۵۵ سال به تفکیک حوزه سازمانی چقدر است؟",
    )
    sql = (payload.get("generated_sql") or "").upper()
    assert "AGE" in sql, "SQL must reference age column"
    assert "SERVICE_DOMAIN" in sql, "SQL must group by service_domain"


# ---------------------------------------------------------------------------
# Roadmap item 1: LLM Fallback — PARAMETER_VALIDATION_FAILED and
# COVERAGE_INCOMPLETE must reach the sql_generator when LLM is absent.
# ---------------------------------------------------------------------------


def _orch_with_spy_generator(metadata_service) -> tuple[LLMOrchestrator, _SpySQLGenerator]:
    spy = _SpySQLGenerator()
    orch = LLMOrchestrator(
        metadata_service=metadata_service,
        question_validator=QuestionValidator(),
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        router=DecisionRouter(metadata_service=metadata_service),
        sql_template_engine=SQLTemplateEngine(metadata_service=metadata_service),
        sql_generator=spy,
        sql_validator=SQLValidator(metadata_service=metadata_service),
        gap_service=GapService(metadata_service=metadata_service),
        response_builder=ResponseBuilder(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    return orch, spy


@pytest.mark.integration
def test_parameter_validation_failed_reaches_sql_generator(metadata_service):
    """When template fails with PARAMETER_VALIDATION_FAILED, sql_generator must be called."""
    orch, spy = _orch_with_spy_generator(metadata_service)
    _run(orch, "تعداد زنان متأهل چند نفر است؟")
    assert spy.called, "sql_generator was not called for PARAMETER_VALIDATION_FAILED question"


@pytest.mark.integration
def test_coverage_incomplete_reaches_sql_generator_when_controlled_dynamic_fails(metadata_service):
    """When controlled_dynamic cannot patch COVERAGE_INCOMPLETE, sql_generator must be called."""
    orch, spy = _orch_with_spy_generator(metadata_service)
    _run(orch, "تعداد کارکنان زن قراردادی با تحصیلات لیسانس در هر استان چند نفر است؟")
    assert spy.called, "sql_generator was not called for COVERAGE_INCOMPLETE question"
