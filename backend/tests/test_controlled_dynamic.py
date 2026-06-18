"""Unit tests for Controlled Dynamic SQL patcher (Phase 4.2)."""

from __future__ import annotations

from app.hr_analytics.use_cases.sql.controlled_dynamic import apply_controlled_dynamic

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_COUNT_SQL = """\
SELECT COUNT(v.employee_id) AS employee_count
FROM hr_mvp.vw_hr_employee_analytics v
WHERE v.is_active = TRUE
ORDER BY employee_count DESC"""

_BASE_AGE_FILTER_SQL = """\
SELECT COUNT(v.employee_id) AS employee_count
FROM hr_mvp.vw_hr_employee_analytics v
WHERE v.is_active = TRUE
  AND (NULL IS NULL OR v.age < NULL)
ORDER BY employee_count DESC"""

_BASE_GROUP_BY_SQL = """\
SELECT v.department_name, COUNT(v.employee_id) AS employee_count
FROM hr_mvp.vw_hr_employee_analytics v
WHERE v.is_active = TRUE
GROUP BY v.department_name
ORDER BY employee_count DESC"""

# ---------------------------------------------------------------------------
# Basic filter injection
# ---------------------------------------------------------------------------


def test_adds_missing_gender_filter():
    """Gender missing from SQL → AND v.gender = 'زن' injected before ORDER BY."""
    intent = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK", f"Expected OK, got: {result}"
    assert "v.gender = 'زن'" in result["sql"]
    assert "v.gender = 'زن'" in result["patches_applied"]
    assert result["can_execute_sql"] is True


def test_adds_missing_is_contractor_filter():
    """is_contractor missing → AND v.is_contractor = TRUE injected."""
    intent = {
        "filters": [
            {"column": "is_contractor", "operator": "=", "value": True},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert "v.is_contractor = TRUE" in result["sql"]
    assert "v.is_contractor = TRUE" in result["patches_applied"]


def test_adds_missing_service_years_filter_gte():
    """service_years >= 10 missing → injected correctly."""
    intent = {
        "filters": [
            {"column": "service_years", "operator": ">=", "value": 10},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert "v.service_years >= 10" in result["sql"]


def test_adds_missing_province_name_filter():
    """province_name missing → AND v.province_name = 'تهران' injected."""
    intent = {
        "filters": [
            {"column": "province_name", "operator": "=", "value": "تهران"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert "v.province_name = 'تهران'" in result["sql"]


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def test_skips_column_already_in_sql():
    """If gender is already in SQL, it should NOT appear in patches_applied."""
    intent = {
        "filters": [
            {"column": "gender", "operator": "=", "value": "زن"},
        ]
    }
    sql_with_gender = _BASE_COUNT_SQL + "\nAND v.gender = 'زن'"
    result = apply_controlled_dynamic(sql_with_gender, intent)

    assert result["status"] == "OK"
    assert result["patches_applied"] == []


def test_skips_default_rule_filters():
    """Filters with source=default_rule (is_active) must not be injected."""
    intent = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert result["patches_applied"] == []


def test_skips_unknown_column_when_it_is_default_rule():
    """Unknown column with default_rule source is ignored, not a failure."""
    intent = {
        "filters": [
            {"column": "some_unknown_col", "operator": "=", "value": "x", "source": "default_rule"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert result["patches_applied"] == []


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_fails_when_no_base_sql():
    """Empty SQL → CONTROLLED_DYNAMIC_FAILED."""
    result = apply_controlled_dynamic("", {"filters": [{"column": "gender", "value": "زن"}]})

    assert result["status"] == "CONTROLLED_DYNAMIC_FAILED"
    assert result["source"] == "controlled_dynamic"


def test_injects_before_trailing_semicolon_not_after():
    """When base_sql has no GROUP BY/ORDER BY/LIMIT and ends with a trailing
    semicolon (a single-statement template), the patched clause must go
    before that semicolon — not appended as a dangling clause after it,
    which would produce two malformed statements."""
    base_sql = (
        "SELECT COUNT(v.employee_id) AS employee_count\n"
        "FROM hr_mvp.vw_hr_employee_analytics v\n"
        "WHERE v.is_active = TRUE\n"
        "  AND (NULL IS NULL OR v.age < NULL);\n"
    )
    intent = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "employment_type", "operator": "=", "value": "قراردادی"},
        ]
    }
    result = apply_controlled_dynamic(base_sql, intent)

    assert result["status"] == "OK", f"Expected OK, got: {result}"
    sql = result["sql"]
    assert sql.count(";") == 1, f"Expected exactly one statement terminator, got: {sql!r}"
    assert sql.rstrip().endswith(";"), f"Expected SQL to end with ';', got: {sql!r}"
    assert "v.employment_type = 'قراردادی'" in sql


def test_fails_when_sql_has_no_where_clause():
    """SQL without WHERE → cannot inject safely → FAILED."""
    no_where_sql = "SELECT COUNT(*) FROM hr_mvp.vw_hr_employee_analytics v"
    intent = {"filters": [{"column": "gender", "operator": "=", "value": "زن"}]}
    result = apply_controlled_dynamic(no_where_sql, intent)

    assert result["status"] == "CONTROLLED_DYNAMIC_FAILED"


def test_fails_when_missing_list_contains_non_filter_items():
    """If missing list has group_by:* or metric:* items, CD must defer to LLM."""
    intent = {"filters": [{"column": "gender", "operator": "=", "value": "زن"}]}
    missing = ["filter:gender", "group_by:department_name"]

    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent, missing=missing)

    assert result["status"] == "CONTROLLED_DYNAMIC_FAILED"
    assert "group_by" in result["reason"]


def test_fails_when_missing_list_has_metric():
    """Metric missing → CD cannot add aggregate functions → FAILED."""
    intent = {"filters": []}
    missing = ["metric:AVG"]

    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent, missing=missing)

    assert result["status"] == "CONTROLLED_DYNAMIC_FAILED"


def test_fails_when_unknown_non_default_column_is_missing():
    """Unknown column that is not a default_rule filter → FAILED (can't build safe clause)."""
    intent = {
        "filters": [
            {"column": "completely_unknown_col", "operator": "=", "value": "x"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "CONTROLLED_DYNAMIC_FAILED"


# ---------------------------------------------------------------------------
# Injection position
# ---------------------------------------------------------------------------


def test_injects_before_group_by():
    """Injected clause must appear BEFORE GROUP BY in the output SQL."""
    intent = {"filters": [{"column": "gender", "operator": "=", "value": "زن"}]}
    result = apply_controlled_dynamic(_BASE_GROUP_BY_SQL, intent)

    assert result["status"] == "OK"
    sql = result["sql"]
    gender_pos = sql.upper().find("GENDER")
    group_by_pos = sql.upper().find("GROUP BY")
    assert gender_pos < group_by_pos, "Filter clause must appear before GROUP BY"


def test_injects_before_order_by():
    """Injected clause must appear BEFORE ORDER BY."""
    intent = {"filters": [{"column": "gender", "operator": "=", "value": "مرد"}]}
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    sql = result["sql"]
    gender_pos = sql.upper().find("GENDER")
    order_pos = sql.upper().find("ORDER BY")
    assert gender_pos < order_pos, "Filter clause must appear before ORDER BY"


def test_injects_multiple_missing_filters():
    """Multiple missing filters → all injected in single pass."""
    intent = {
        "filters": [
            {"column": "gender", "operator": "=", "value": "زن"},
            {"column": "province_name", "operator": "=", "value": "تهران"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert "v.gender = 'زن'" in result["sql"]
    assert "v.province_name = 'تهران'" in result["sql"]
    assert len(result["patches_applied"]) == 2


def test_patches_applied_is_empty_when_all_present():
    """When all filters already in SQL, OK with empty patches_applied."""
    intent = {"filters": []}
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert result["patches_applied"] == []


# ---------------------------------------------------------------------------
# Value escaping
# ---------------------------------------------------------------------------


def test_escapes_single_quote_in_string_value():
    """Single quotes in string values must be escaped to prevent SQL injection."""
    intent = {
        "filters": [
            {"column": "province_name", "operator": "=", "value": "O'Brien"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent)

    assert result["status"] == "OK"
    assert "O''Brien" in result["sql"]


# ---------------------------------------------------------------------------
# missing= parameter (coverage-guided mode)
# ---------------------------------------------------------------------------


def test_missing_param_filter_only_succeeds():
    """When missing list has only filter:* items, CD should succeed."""
    intent = {"filters": [{"column": "gender", "operator": "=", "value": "زن"}]}
    missing = ["filter:gender"]

    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent, missing=missing)

    assert result["status"] == "OK"
    assert "v.gender = 'زن'" in result["sql"]


def test_patches_province_filter():
    """province column should be patchable as a WHERE filter."""
    intent = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "province", "operator": "=", "value": "تهران"},
        ]
    }
    result = apply_controlled_dynamic(_BASE_GROUP_BY_SQL, intent)

    assert result["status"] == "OK", f"Expected OK, got: {result}"
    assert "v.province" in result["sql"]
    assert "تهران" in result["sql"]
    assert result["can_execute_sql"] is True


def test_patches_province_filter_coverage_guided():
    """province patch works in coverage-guided mode (missing=['filter:province'])."""
    intent = {
        "filters": [
            {"column": "province", "operator": "=", "value": "اصفهان"},
        ]
    }
    missing = ["filter:province"]

    result = apply_controlled_dynamic(_BASE_COUNT_SQL, intent, missing=missing)

    assert result["status"] == "OK"
    assert "اصفهان" in result["sql"]
