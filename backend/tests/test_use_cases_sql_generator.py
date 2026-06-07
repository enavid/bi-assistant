from __future__ import annotations

from app.use_cases.hr_analytics.sql.generator import SQLGenerator


def test_sql_generator_produces_select_for_total_count(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {
            "intent": "total_employee_count",
            "intent_id": "total_employee_count",
            "route": "SQL",
            "template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
            "required_columns": ["employee_id"],
        },
        "route_result": {"route": "SQL", "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="total employees",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "SQL"
    sql = result.get("sql") or ""
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "SELECT" in sql.upper()


def test_sql_generator_returns_data_gap_for_gap_route(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {"route": "GAP", "status": "DATA_GAP"},
        "route_result": {"route": "GAP", "status": "DATA_GAP"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="city level analysis",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "GAP"
    sql = result.get("sql") or ""
    assert "DATA_GAP" in sql


def test_sql_generator_rejects_access_denied_route(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {"route": "REJECT", "status": "ACCESS_DENIED"},
        "route_result": {"route": "REJECT", "status": "ACCESS_DENIED"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="show me personal IDs",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "REJECT"
    sql = result.get("sql") or ""
    assert "ACCESS_DENIED" in sql
