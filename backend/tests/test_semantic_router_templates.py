from __future__ import annotations

from app.hr_analytics.use_cases.sql.template_engine import SQLTemplateEngine
from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper


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
        "semantic_result": {
            "route": "SQL",
            "mapped_columns": ["employee_id"],
            "required_columns": ["employee_id"],
        },
        "intent_result": {
            "intent_id": "total_employee_count",
            "route": "SQL",
            "required_columns": ["employee_id"],
            "template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
        },
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
        "intent_result": {
            "intent_id": "total_employee_count",
            "template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="تعداد کل کارکنان چند نفر است؟", context=context, metadata=metadata_service
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL"
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "COUNT(v.employee_id)" in sql


# ---------------------------------------------------------------------------
# BUG-005 — TPL_AVERAGE_AGE must apply secondary filters (contractor, gender, education)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BUG-008 — TPL_MAX_AGE / TPL_MIN_AGE / TPL_STDDEV_AGE must render correct SQL
# ---------------------------------------------------------------------------


def test_max_age_template_renders_max_sql(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_MAX_AGE"},
        "intent_result": {"intent_id": "max_age", "template_id": "TPL_MAX_AGE"},
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="بیشترین سن کارمندان چقدر است؟", context=context, metadata=metadata_service
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL", f"Unexpected route: {result}"
    assert "MAX(v.age)" in sql, f"Expected MAX(v.age) in SQL, got:\n{sql}"


def test_min_age_template_renders_min_sql(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_MIN_AGE"},
        "intent_result": {"intent_id": "min_age", "template_id": "TPL_MIN_AGE"},
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="کمترین سن کارمندان چقدر است؟", context=context, metadata=metadata_service
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL"
    assert "MIN(v.age)" in sql, f"Expected MIN(v.age) in SQL, got:\n{sql}"


def test_stddev_age_template_renders_stddev_sql(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_STDDEV_AGE"},
        "intent_result": {"intent_id": "stddev_age", "template_id": "TPL_STDDEV_AGE"},
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="انحراف معیار سن کارمندان چقدر است؟", context=context, metadata=metadata_service
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL"
    assert "STDDEV" in sql, f"Expected STDDEV in SQL, got:\n{sql}"


def test_service_years_filter_template_applies_min_filter(metadata_service):
    context = {
        "route_result": {
            "route": "SQL",
            "template_id": "TPL_EMPLOYEE_COUNT_BY_SERVICE_YEARS_FILTER",
        },
        "intent_result": {
            "intent_id": "employee_count_by_service_years_filter",
            "template_id": "TPL_EMPLOYEE_COUNT_BY_SERVICE_YEARS_FILTER",
            "params": {"service_years_min": 10},
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="تعداد کارمندانی که بیش از ۱۰ سال سابقه دارند",
        context=context,
        metadata=metadata_service,
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL", f"Unexpected: {result}"
    assert "service_years" in sql, f"Expected service_years in SQL:\n{sql}"
    assert "10" in sql, f"Expected 10 in SQL:\n{sql}"


def test_average_age_template_applies_contractor_filter(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_AVERAGE_AGE"},
        "intent_result": {
            "intent_id": "average_age",
            "template_id": "TPL_AVERAGE_AGE",
            "filters": [
                {"column": "is_active", "operator": "=", "value": True},
                {"column": "is_contractor", "operator": "=", "value": True},
            ],
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="میانگین سن کارمندان پیمانکار چقدر است؟",
        context=context,
        metadata=metadata_service,
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL", f"Expected SQL route, got: {result}"
    assert "is_contractor = TRUE" in sql, (
        f"Expected is_contractor = TRUE in SQL, got:\n{sql}"
    )


def test_average_age_template_applies_gender_and_education_filters(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_AVERAGE_AGE"},
        "intent_result": {
            "intent_id": "average_age",
            "template_id": "TPL_AVERAGE_AGE",
            "filters": [
                {"column": "is_active", "operator": "=", "value": True},
                {"column": "gender", "operator": "=", "value": "زن"},
                {"column": "education_title", "operator": "=", "value": "کارشناسی ارشد"},
            ],
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="میانگین سن کارمندان زن با مدرک کارشناسی ارشد چقدر است؟",
        context=context,
        metadata=metadata_service,
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL", f"Expected SQL route, got: {result}"
    assert "gender = 'زن'" in sql, f"Expected gender filter in SQL, got:\n{sql}"
    assert "education_title = 'کارشناسی ارشد'" in sql, (
        f"Expected education_title filter in SQL, got:\n{sql}"
    )


def test_average_age_template_without_secondary_filters_has_null_conditions(metadata_service):
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_AVERAGE_AGE"},
        "intent_result": {
            "intent_id": "average_age",
            "template_id": "TPL_AVERAGE_AGE",
            "filters": [{"column": "is_active", "operator": "=", "value": True}],
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="میانگین سن کارکنان چقدر است؟",
        context=context,
        metadata=metadata_service,
    )
    sql = result.get("sql") or ""
    assert result["route"] == "SQL", f"Expected SQL route, got: {result}"
    assert "AVG(v.age)" in sql
    # Optional conditions render with NULL params (always true — no actual filtering)
    assert "NULL IS NULL" in sql
    assert "is_contractor = TRUE" not in sql
    assert "gender = 'زن'" not in sql
