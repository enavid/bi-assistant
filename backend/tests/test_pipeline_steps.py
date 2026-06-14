from __future__ import annotations

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
