from __future__ import annotations

from app.use_cases.hr_analytics.steps.semantic_mapper import SemanticMapper
from app.use_cases.hr_analytics.steps.decision_router import DecisionRouter
from app.use_cases.hr_analytics.sql.template_engine import SQLTemplateEngine


def test_semantic_mapper_maps_core_hr_terms(metadata_service):
    result = SemanticMapper(metadata_service=metadata_service).map_question(
        "سهم پیمانکاری در هر حوزه چند درصد است؟",
        metadata=metadata_service,
    )
    columns = set(result.get("mapped_columns", []))
    assert "is_contractor" in columns
    assert "service_domain" in columns
    assert result["route"] == "SQL"
    assert result.get("detected_intent") == "contractor_share_by_service_domain"


def test_router_routes_supported_intent_to_sql(metadata_service):
    context = {
        "domain_result": {"status": "OK", "domain": "HR", "is_hr": True},
        "validation_result": {"status": "OK", "is_valid": True},
        "semantic_result": {"route": "SQL", "mapped_columns": ["employee_id"], "required_columns": ["employee_id"]},
        "intent_result": {"intent_id": "total_employee_count", "route": "SQL", "required_columns": ["employee_id"], "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
    }
    result = DecisionRouter(metadata_service=metadata_service).route(
        "تعداد کل کارکنان چند نفر است؟", context=context, metadata=metadata_service
    )
    assert result["route"] == "SQL"
    assert result["status"] in {"OK", "VALID", "READY", "SQL_READY"}
    assert result.get("can_execute_sql") is True


def test_sql_template_engine_renders_total_count(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
        "intent_result": {"intent_id": "total_employee_count", "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="تعداد کل کارکنان چند نفر است؟", context=context, metadata=metadata_service
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL"
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "COUNT(v.employee_id)" in sql
