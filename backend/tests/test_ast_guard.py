"""Tests for the AST-based structural SQL guard (Phase 3.5, defense in depth)."""

from __future__ import annotations

import pytest

from app.hr_analytics.use_cases.sql.ast_guard import analyze_sql

VIEW = "hr_mvp.vw_hr_employee_analytics"
SCHEMA = "hr_mvp"


def _rules(sql: str) -> set[str]:
    return {
        v.rule_id for v in analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA).violations
    }


# ---------------------------------------------------------------------------
# Legitimate generated SQL must pass cleanly
# ---------------------------------------------------------------------------


def test_simple_count_passes():
    sql = (
        "SELECT COUNT(v.employee_id) AS employee_count "
        "FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    result = analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA)
    assert result.ok, result.violations
    assert result.statement_type == "SELECT"


def test_count_star_is_allowed():
    sql = "SELECT COUNT(*) AS c FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    assert analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA).ok


def test_group_by_passes():
    sql = (
        "SELECT v.gender, COUNT(v.employee_id) AS employee_count "
        "FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE "
        "GROUP BY v.gender ORDER BY employee_count DESC LIMIT 50"
    )
    assert analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA).ok


def test_cte_referencing_allowed_view_passes():
    sql = (
        "WITH base AS ("
        "  SELECT v.gender, COUNT(v.employee_id) AS c "
        "  FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE GROUP BY v.gender"
        ") SELECT gender, c FROM base ORDER BY c DESC"
    )
    assert analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA).ok


def test_subquery_on_allowed_view_passes():
    sql = (
        "SELECT COUNT(*) AS c FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.age > (SELECT AVG(v2.age) FROM hr_mvp.vw_hr_employee_analytics v2 "
        "WHERE v2.is_active = TRUE) AND v.is_active = TRUE"
    )
    assert analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA).ok


# ---------------------------------------------------------------------------
# Structural attacks must be rejected
# ---------------------------------------------------------------------------


def test_select_star_rejected():
    sql = "SELECT * FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    assert "SQL_AST_SELECT_STAR" in _rules(sql)


def test_qualified_star_rejected():
    sql = "SELECT v.* FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    assert "SQL_AST_SELECT_STAR" in _rules(sql)


def test_stacked_statement_rejected():
    sql = (
        "SELECT COUNT(*) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE; "
        "DROP TABLE hr_employees"
    )
    rules = _rules(sql)
    assert "SQL_AST_MULTIPLE_STATEMENTS" in rules


def test_union_rejected():
    sql = (
        "SELECT v.employee_id FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE "
        "UNION SELECT 1"
    )
    rules = _rules(sql)
    assert "SQL_AST_SET_OPERATION" in rules or "SQL_AST_NOT_SELECT" in rules


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM hr_mvp.vw_hr_employee_analytics",
        "UPDATE hr_mvp.vw_hr_employee_analytics SET salary = 0",
        "DROP TABLE hr_employees",
        "INSERT INTO hr_employees (id) VALUES (1)",
    ],
)
def test_non_select_rejected(sql):
    result = analyze_sql(sql, allowed_view=VIEW, allowed_schema=SCHEMA)
    assert not result.ok


def test_information_schema_rejected():
    sql = "SELECT table_name FROM information_schema.tables"
    assert "SQL_AST_FORBIDDEN_RELATION" in _rules(sql)


def test_pg_catalog_subquery_rejected():
    sql = (
        "SELECT COUNT(v.employee_id) AS c FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.department_name IN (SELECT tablename FROM pg_catalog.pg_tables) "
        "AND v.is_active = TRUE"
    )
    assert "SQL_AST_FORBIDDEN_RELATION" in _rules(sql)


def test_raw_table_rejected():
    sql = "SELECT COUNT(*) FROM hr_employees"
    assert "SQL_AST_FORBIDDEN_RELATION" in _rules(sql)


def test_unparseable_sql_fails_safe():
    result = analyze_sql("SELECT FROM WHERE GROUP", allowed_view=VIEW, allowed_schema=SCHEMA)
    assert not result.ok
