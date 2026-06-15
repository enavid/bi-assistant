"""Tests for the SQL Coverage Validator.

The validator checks that every filter column, group_by column, metric
function, and superlative constraint extracted from the question actually
appears in the generated SQL.

All tests must pass without any external services.
"""

from __future__ import annotations

from app.hr_analytics.use_cases.steps.sql_coverage_validator import (
    CoverageResult,
    validate_coverage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_SQL = (
    "SELECT COUNT(v.employee_id) AS employee_count "
    "FROM hr_mvp.vw_hr_employee_analytics v "
    "WHERE v.is_active = TRUE"
)


def _intent(
    filters: list | None = None,
    group_by: list | None = None,
    metrics: list | None = None,
    params: dict | None = None,
) -> dict:
    return {
        "filters": filters or [],
        "group_by": group_by or [],
        "metrics": metrics or [],
        "params": params or {},
    }


def _active_filter() -> dict:
    return {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"}


# ---------------------------------------------------------------------------
# CoverageResult dataclass
# ---------------------------------------------------------------------------


def test_coverage_result_complete():
    r = CoverageResult(is_complete=True, missing=[], status="COMPLETE")
    assert r.is_complete is True
    assert r.missing == []
    assert r.status == "COMPLETE"


def test_coverage_result_incomplete():
    r = CoverageResult(is_complete=False, missing=["gender"], status="COVERAGE_INCOMPLETE")
    assert r.is_complete is False
    assert "gender" in r.missing


# ---------------------------------------------------------------------------
# Empty intent — trivially complete
# ---------------------------------------------------------------------------


def test_empty_intent_is_complete():
    result = validate_coverage(_intent(), _BASE_SQL)
    assert result.is_complete is True
    assert result.missing == []


def test_only_is_active_filter_is_complete():
    intent = _intent(filters=[_active_filter()])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is True


# ---------------------------------------------------------------------------
# Filter column checks
# ---------------------------------------------------------------------------


def test_filter_column_present_in_sql_is_complete():
    sql = _BASE_SQL + " AND v.gender = 'زن'"
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}]
    )
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_filter_column_missing_from_sql_is_incomplete():
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("gender" in m for m in result.missing)


def test_filter_is_contractor_missing_is_incomplete():
    intent = _intent(
        filters=[_active_filter(), {"column": "is_contractor", "operator": "=", "value": True}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("is_contractor" in m for m in result.missing)


def test_filter_service_years_present_is_complete():
    sql = _BASE_SQL + " AND v.service_years >= 10"
    intent = _intent(
        filters=[_active_filter(), {"column": "service_years", "operator": ">=", "value": 10}]
    )
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_filter_service_years_missing_is_incomplete():
    intent = _intent(
        filters=[_active_filter(), {"column": "service_years", "operator": ">=", "value": 10}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("service_years" in m for m in result.missing)


def test_filter_hire_year_missing_is_incomplete():
    intent = _intent(
        filters=[_active_filter(), {"column": "hire_year", "operator": "=", "value": 1400}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("hire_year" in m for m in result.missing)


def test_is_active_filter_always_skipped():
    """is_active is always in the template — validator must not flag it as missing."""
    intent = _intent(filters=[{"column": "is_active", "operator": "=", "value": True}])
    sql = "SELECT COUNT(*) FROM hr_mvp.vw_hr_employee_analytics v"
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_default_rule_source_filter_skipped():
    """Filters with source='default_rule' are injected by the pipeline, not the user — skip them."""
    intent = _intent(
        filters=[{"column": "gender", "operator": "=", "value": "زن", "source": "default_rule"}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is True


def test_multiple_filters_all_missing_reports_all():
    intent = _intent(
        filters=[
            _active_filter(),
            {"column": "gender", "operator": "=", "value": "زن"},
            {"column": "is_contractor", "operator": "=", "value": True},
        ]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    missing_str = " ".join(result.missing)
    assert "gender" in missing_str
    assert "is_contractor" in missing_str


def test_filter_column_check_is_case_insensitive():
    sql = _BASE_SQL + " AND v.GENDER = 'زن'"
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}]
    )
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


# ---------------------------------------------------------------------------
# group_by checks
# ---------------------------------------------------------------------------


def test_group_by_column_present_is_complete():
    sql = _BASE_SQL + " GROUP BY v.department_name"
    intent = _intent(group_by=["department_name"])
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_group_by_column_missing_is_incomplete():
    intent = _intent(group_by=["department_name"])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("department_name" in m for m in result.missing)


def test_group_by_two_columns_one_missing_is_incomplete():
    sql = _BASE_SQL + " GROUP BY v.department_name"
    intent = _intent(group_by=["department_name", "gender"])
    result = validate_coverage(intent, sql)
    assert result.is_complete is False
    assert any("gender" in m for m in result.missing)
    assert not any("department_name" in m for m in result.missing)


def test_group_by_province_missing_is_incomplete():
    intent = _intent(group_by=["province"])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False


# ---------------------------------------------------------------------------
# Metric function checks
# ---------------------------------------------------------------------------


def test_metric_avg_present_is_complete():
    sql = "SELECT ROUND(AVG(v.age), 2) AS average_age FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    intent = _intent(metrics=[{"name": "average_age", "expression": "ROUND(AVG(v.age), 2)"}])
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_metric_avg_missing_is_incomplete():
    intent = _intent(metrics=[{"name": "average_age", "expression": "ROUND(AVG(v.age), 2)"}])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("AVG" in m for m in result.missing)


def test_metric_max_present_is_complete():
    sql = "SELECT MAX(v.age) AS max_age FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    intent = _intent(metrics=[{"name": "max_age", "expression": "MAX(v.age)"}])
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_metric_max_missing_is_incomplete():
    intent = _intent(metrics=[{"name": "max_age", "expression": "MAX(v.age)"}])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("MAX" in m for m in result.missing)


def test_metric_min_missing_is_incomplete():
    intent = _intent(metrics=[{"name": "min_age", "expression": "MIN(v.age)"}])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("MIN" in m for m in result.missing)


def test_metric_stddev_missing_is_incomplete():
    intent = _intent(
        metrics=[{"name": "stddev_age", "expression": "ROUND(STDDEV(v.age)::numeric, 2)"}]
    )
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is False
    assert any("STDDEV" in m for m in result.missing)


def test_metric_count_not_checked():
    """COUNT is always present in aggregate queries — validator must not flag it."""
    intent = _intent(metrics=[{"name": "employee_count", "expression": "COUNT(v.employee_id)"}])
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is True


# ---------------------------------------------------------------------------
# Superlative / LIMIT checks
# ---------------------------------------------------------------------------


def test_result_limit_1_with_limit_in_sql_is_complete():
    sql = _BASE_SQL + " GROUP BY v.department_name ORDER BY employee_count DESC LIMIT 1"
    intent = _intent(params={"result_limit": 1})
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_result_limit_1_without_limit_in_sql_is_incomplete():
    sql = _BASE_SQL + " GROUP BY v.department_name ORDER BY employee_count DESC"
    intent = _intent(params={"result_limit": 1})
    result = validate_coverage(intent, sql)
    assert result.is_complete is False
    assert any("LIMIT" in m for m in result.missing)


def test_no_result_limit_param_does_not_require_limit():
    intent = _intent(params={})
    result = validate_coverage(intent, _BASE_SQL)
    assert result.is_complete is True


# ---------------------------------------------------------------------------
# Combined checks
# ---------------------------------------------------------------------------


def test_all_constraints_satisfied_is_complete():
    sql = (
        "SELECT v.department_name, v.gender, COUNT(v.employee_id) AS employee_count "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND v.is_contractor = TRUE "
        "GROUP BY v.department_name, v.gender "
        "ORDER BY employee_count DESC"
    )
    intent = _intent(
        filters=[
            _active_filter(),
            {"column": "is_contractor", "operator": "=", "value": True},
        ],
        group_by=["department_name", "gender"],
        metrics=[{"name": "employee_count", "expression": "COUNT(v.employee_id)"}],
    )
    result = validate_coverage(intent, sql)
    assert result.is_complete is True


def test_partial_satisfaction_reports_only_missing():
    sql = (
        "SELECT v.department_name, COUNT(v.employee_id) AS employee_count "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE "
        "GROUP BY v.department_name"
    )
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}],
        group_by=["department_name"],
    )
    result = validate_coverage(intent, sql)
    assert result.is_complete is False
    assert any("gender" in m for m in result.missing)
    assert not any("department_name" in m for m in result.missing)


def test_empty_sql_with_filters_is_incomplete():
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}]
    )
    result = validate_coverage(intent, "")
    assert result.is_complete is False


def test_status_field_matches_is_complete():
    intent = _intent(
        filters=[_active_filter(), {"column": "gender", "operator": "=", "value": "زن"}]
    )
    result_fail = validate_coverage(intent, _BASE_SQL)
    assert result_fail.status == "COVERAGE_INCOMPLETE"

    sql = _BASE_SQL + " AND v.gender = 'زن'"
    result_ok = validate_coverage(intent, sql)
    assert result_ok.status == "COMPLETE"
