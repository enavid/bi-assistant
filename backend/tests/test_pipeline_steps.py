from __future__ import annotations

from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
from app.hr_analytics.use_cases.steps.gap_service import GapService
from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

# ---------------------------------------------------------------------------
# SemanticMapper
# ---------------------------------------------------------------------------


def test_semantic_mapper_maps_employee_count_question(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map("تعداد کل کارکنان چند نفر است؟")
    assert isinstance(result, dict)
    assert result.get("route") in {"SQL", "GAP", "REJECT", "NEEDS_CLARIFICATION"}


def test_semantic_mapper_handles_empty_question(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map("")
    assert isinstance(result, dict)
    assert result.get("route") in {"NEEDS_CLARIFICATION", "REJECT"}


def test_semantic_mapper_result_has_required_fields(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map("تعداد کارکنان زن چند نفر است؟")
    assert "route" in result
    assert "status" in result


def test_semantic_mapper_callable_returns_same_as_map(metadata_service):
    question = "تعداد کارکنان زن چند نفر است؟"
    mapper = SemanticMapper(metadata_service=metadata_service)
    map_result = mapper.map(question)
    call_result = mapper(question)
    assert map_result["route"] == call_result["route"]


# ---------------------------------------------------------------------------
# IntentParser
# ---------------------------------------------------------------------------


def test_intent_parser_parses_employee_count(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse("تعداد کل کارکنان چند نفر است؟")
    assert isinstance(result, dict)
    assert "intent" in result or "intent_id" in result


def test_intent_parser_parses_gender_question(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "درصد کارکنان زن و مرد چقدر است؟"
    )
    assert isinstance(result, dict)
    assert result.get("route") in {"SQL", "GAP"}


def test_intent_parser_handles_empty_question(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse("")
    assert isinstance(result, dict)
    assert "route" in result


def test_intent_parser_result_has_required_fields(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse("تعداد کارکنان چند نفر است؟")
    for field in ("route", "status"):
        assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# DecisionRouter
# ---------------------------------------------------------------------------


def test_decision_router_routes_sql_intent(metadata_service):
    router = DecisionRouter(metadata_service=metadata_service)
    context = {
        "normalized_question": "تعداد کل کارکنان چند نفر است؟",
        "validation_result": {"is_valid": True, "status": "VALID", "route": "SQL"},
        "intent_result": {"intent": "employee_count_total", "route": "SQL", "status": "OK"},
        "semantic_result": {"route": "SQL", "status": "OK"},
    }
    result = router.route(
        question="تعداد کل کارکنان چند نفر است؟",
        context=context,
        metadata=metadata_service,
    )
    assert isinstance(result, dict)
    assert "route" in result


def test_decision_router_routes_gap(metadata_service):
    router = DecisionRouter(metadata_service=metadata_service)
    context = {
        "normalized_question": "تعداد کارکنان شهر تهران چند نفر است؟",
        "validation_result": {"is_valid": False, "status": "DATA_GAP", "route": "GAP"},
        "intent_result": {"intent": "city_level_analysis", "route": "GAP", "status": "DATA_GAP"},
        "semantic_result": {"route": "GAP", "status": "DATA_GAP"},
    }
    result = router.route(
        question="تعداد کارکنان شهر تهران چند نفر است؟",
        context=context,
        metadata=metadata_service,
    )
    assert isinstance(result, dict)
    assert result.get("route") == "GAP"


# ---------------------------------------------------------------------------
# GapService
# ---------------------------------------------------------------------------


def test_gap_service_creates_gap_record(metadata_service):
    service = GapService(metadata_service=metadata_service)
    gap = {
        "question": "تعداد کارکنان شهر تهران چند نفر است؟",
        "normalized_question": "تعداد کارکنان شهر تهران چند نفر است؟",
        "intent": "city_level_analysis",
        "reason": "City-level data is not available.",
        "missing_data": ["city column"],
        "created_by": "test",
    }
    result = service.create_gap(gap=gap, metadata=metadata_service)
    assert isinstance(result, dict)
    assert result.get("route") == "GAP"
    assert result.get("status") in {"DATA_GAP", "KNOWLEDGE_GAP", "BUSINESS_RULE_GAP"}


def test_gap_service_result_has_required_fields(metadata_service):
    service = GapService(metadata_service=metadata_service)
    gap = {
        "question": "تعداد کارکنان شهر تهران چند نفر است؟",
        "normalized_question": "تعداد کارکنان شهر تهران",
        "intent": "city_level_analysis",
        "reason": "not available",
        "created_by": "test",
    }
    result = service.create_gap(gap=gap, metadata=metadata_service)
    for field in ("route", "status"):
        assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# BUG-005 — secondary dimension filters must not be dropped for average_age
# ---------------------------------------------------------------------------


def _filters_for(result: dict) -> list[dict]:
    return result.get("filters") or []


def _has_filter(result: dict, column: str, value: object = None) -> bool:
    for f in _filters_for(result):
        if f.get("column") == column and f.get("scope") != "numerator":
            if value is None or f.get("value") == value:
                return True
    return False


def test_average_age_contractor_includes_contractor_filter(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "میانگین سن کارمندان پیمانکار چقدر است؟"
    )
    assert result.get("intent_id") == "average_age" or result.get("intent") == "average_age", (
        f"Expected average_age intent, got {result.get('intent_id') or result.get('intent')}"
    )
    assert _has_filter(result, "is_contractor", True), (
        f"Expected is_contractor=True filter in WHERE, got filters: {_filters_for(result)}"
    )


def test_average_age_female_with_masters_includes_both_filters(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "میانگین سن کارمندان زن با مدرک کارشناسی ارشد چقدر است؟"
    )
    assert result.get("intent_id") == "average_age" or result.get("intent") == "average_age", (
        f"Expected average_age intent, got {result.get('intent_id') or result.get('intent')}"
    )
    assert _has_filter(result, "gender", "زن"), (
        f"Expected gender=زن filter, got filters: {_filters_for(result)}"
    )
    assert _has_filter(result, "education_title"), (
        f"Expected education_title filter, got filters: {_filters_for(result)}"
    )


# ---------------------------------------------------------------------------
# BUG-011 — terminated/fired employee questions must route to DATA_GAP
# ---------------------------------------------------------------------------


def test_fired_employees_question_routes_to_gap(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map(
        "کارمندانی که اخراج شدند چند نفرند؟"
    )
    assert result.get("route") == "GAP", f"Expected GAP, got {result.get('route')}"
    assert result.get("status") == "DATA_GAP", f"Expected DATA_GAP, got {result.get('status')}"


def test_inactive_employees_question_routes_to_gap(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map(
        "تعداد کارمندان غیرفعال چقدر است؟"
    )
    assert result.get("route") == "GAP", f"Expected GAP, got {result.get('route')}"


def test_left_service_question_routes_to_gap(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map(
        "چند نفر از کارمندان ترک خدمت کرده‌اند؟"
    )
    assert result.get("route") == "GAP", f"Expected GAP, got {result.get('route')}"


# ---------------------------------------------------------------------------
# BUG-008 — MAX/MIN/STDDEV age questions must not map to COUNT template
# ---------------------------------------------------------------------------


def test_max_age_intent_is_recognized(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "بیشترین سن کارمندان چقدر است؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "max_age", f"Expected max_age intent, got {intent!r}"


def test_min_age_intent_is_recognized(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "کمترین سن کارمندان چقدر است؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "min_age", f"Expected min_age intent, got {intent!r}"


def test_stddev_age_intent_is_recognized(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "انحراف معیار سن کارمندان چقدر است؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "stddev_age", f"Expected stddev_age intent, got {intent!r}"


# ---------------------------------------------------------------------------
# BUG-009 — service_years range filter must produce correct intent and SQL filter
# ---------------------------------------------------------------------------


def _sy_filter(result: dict) -> dict | None:
    for f in result.get("filters") or []:
        if f.get("column") == "service_years":
            return f
    return None


def test_service_years_above_10_routes_to_count_intent(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "تعداد کارمندانی که بیش از ۱۰ سال سابقه دارند چقدر است؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_service_years_filter", (
        f"Expected employee_count_by_service_years_filter, got {intent!r}"
    )
    f = _sy_filter(result)
    assert f is not None, "Expected service_years filter in result"
    assert f.get("operator") in {">", ">="}, f"Expected > or >= operator, got {f.get('operator')!r}"
    assert f.get("value") == 10, f"Expected value=10, got {f.get('value')!r}"


def test_service_years_below_1_routes_to_count_intent(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "چند نفر کمتر از ۱ سال سابقه دارند؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_service_years_filter", (
        f"Expected employee_count_by_service_years_filter, got {intent!r}"
    )
    f = _sy_filter(result)
    assert f is not None, "Expected service_years filter"
    assert f.get("operator") == "<", f"Expected < operator, got {f.get('operator')!r}"
    assert f.get("value") == 1, f"Expected value=1, got {f.get('value')!r}"


def test_service_years_between_5_and_15_routes_to_count_intent(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "تعداد کارمندانی با سابقه بین ۵ تا ۱۵ سال"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_service_years_filter", (
        f"Expected employee_count_by_service_years_filter, got {intent!r}"
    )
    f = _sy_filter(result)
    assert f is not None, "Expected service_years filter"
    assert f.get("operator") == "BETWEEN"
    assert f.get("value") == [5, 15], f"Expected [5,15], got {f.get('value')!r}"


# ---------------------------------------------------------------------------
# BUG-001 — education_title for doctorate must match the actual DB value
# ---------------------------------------------------------------------------

_DB_DOCTORATE_VALUE = "دکترای تخصصی PHD / دکترای حرفه ای"


def test_doctorate_question_produces_correct_education_title_filter(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service)
    result = orch._extract_template_params(
        "میانگین سن کارمندان دکترا چقدر است؟", intent={}
    )
    filters = result.get("filters") or []
    ed_filter = next((f for f in filters if f.get("column") == "education_title"), None)
    assert ed_filter is not None, "Expected education_title filter in result"
    assert ed_filter.get("value") == _DB_DOCTORATE_VALUE, (
        f"Expected {_DB_DOCTORATE_VALUE!r}, got {ed_filter.get('value')!r}"
    )


def test_doctorate_params_produce_correct_education_title(metadata_service):
    orch = LLMOrchestrator(metadata_service=metadata_service)
    result = orch._extract_template_params(
        "تعداد کارمندان دکترا چند نفرند؟", intent={}
    )
    params = result.get("params") or {}
    assert params.get("education_title") == _DB_DOCTORATE_VALUE, (
        f"Expected education_title param={_DB_DOCTORATE_VALUE!r}, got {params.get('education_title')!r}"
    )


# ---------------------------------------------------------------------------
# BUG-010 — hire_year filter must not be dropped
# ---------------------------------------------------------------------------


def _hy_filter(result: dict) -> dict | None:
    for f in result.get("filters") or []:
        if f.get("column") == "hire_year":
            return f
    return None


def test_hire_year_question_routes_to_correct_intent(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "کارمندانی که در سال ۱۴۰۰ استخدام شدند چند نفرند؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_hire_year", (
        f"Expected employee_count_by_hire_year, got {intent!r}"
    )
    f = _hy_filter(result)
    assert f is not None, "Expected hire_year filter in result"
    assert f.get("operator") == "=", f"Expected = operator, got {f.get('operator')!r}"
    assert f.get("value") == 1400, f"Expected value=1400, got {f.get('value')!r}"


def test_hire_year_1402_is_extracted(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "تعداد کارکنان جذب‌شده در سال ۱۴۰۲ چند نفر است؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_hire_year", (
        f"Expected employee_count_by_hire_year, got {intent!r}"
    )
    f = _hy_filter(result)
    assert f is not None, "Expected hire_year filter"
    assert f.get("value") == 1402, f"Expected value=1402, got {f.get('value')!r}"


# ---------------------------------------------------------------------------
# BUG-006 — superlative questions must set result_limit=1
# ---------------------------------------------------------------------------


def test_most_employees_in_department_sets_limit_1(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "کدام دپارتمان بیشترین کارمند را دارد؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_department", (
        f"Expected employee_count_by_department, got {intent!r}"
    )
    assert result.get("params", {}).get("result_limit") == 1, (
        f"Expected result_limit=1 in params, got {result.get('params')}"
    )


def test_least_employees_in_province_sets_limit_1(metadata_service):
    result = IntentParser(metadata_service=metadata_service).parse(
        "کدام استان کمترین کارمند را دارد؟"
    )
    intent = result.get("intent_id") or result.get("intent")
    assert intent == "employee_count_by_province", (
        f"Expected employee_count_by_province, got {intent!r}"
    )
    assert result.get("params", {}).get("result_limit") == 1, (
        f"Expected result_limit=1 in params, got {result.get('params')}"
    )
