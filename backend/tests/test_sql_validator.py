from __future__ import annotations

from app.hr_analytics.use_cases.sql.validator import SQLValidator


def validate(sql: str, metadata_service, question: str | None = None):
    return SQLValidator(metadata_service=metadata_service).validate(sql=sql, question=question)


# ---------------------------------------------------------------------------
# Allowed SQL
# ---------------------------------------------------------------------------


def test_validator_accepts_safe_select_on_view(metadata_service):
    sql = """
    SELECT COUNT(v.employee_id) AS employee_count
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.is_active = TRUE;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is True
    assert result["can_execute_sql"] is True
    assert result["status"] in {"OK", "VALID"}


def test_validator_allows_group_by_on_view(metadata_service):
    sql = """
    SELECT v.gender, COUNT(v.employee_id) AS cnt
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.is_active = TRUE
    GROUP BY v.gender;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is True


def test_validator_allows_status_only_data_gap(metadata_service):
    result = validate("SELECT 'DATA_GAP' AS status;", metadata_service)
    assert result["is_valid"] is True
    assert result["can_execute_sql"] is False
    assert result["status"] == "DATA_GAP"


def test_validator_allows_status_access_denied(metadata_service):
    result = validate("SELECT 'ACCESS_DENIED' AS status;", metadata_service)
    assert result["is_valid"] is True
    assert result["can_execute_sql"] is False


# ---------------------------------------------------------------------------
# Blocked SQL — structure violations
# ---------------------------------------------------------------------------


def test_validator_rejects_select_star(metadata_service):
    sql = "SELECT * FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False
    assert result["status"] == "SQL_VALIDATION_FAILED"


def test_validator_rejects_raw_table(metadata_service):
    sql = "SELECT COUNT(*) FROM hr_mvp.hr_employees e;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False
    assert result["status"] == "SQL_VALIDATION_FAILED"


def test_validator_rejects_join(metadata_service):
    sql = """
    SELECT COUNT(v.employee_id)
    FROM hr_mvp.vw_hr_employee_analytics v
    JOIN hr_mvp.hr_departments d ON d.department_id = v.department_id
    WHERE v.is_active = TRUE;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False
    assert result["status"] == "SQL_VALIDATION_FAILED"


def test_validator_blocks_sensitive_column(metadata_service):
    sql = "SELECT v.national_id FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False
    assert result["status"] in {"ACCESS_DENIED", "SQL_VALIDATION_FAILED"}


# ---------------------------------------------------------------------------
# Blocked SQL — write operations
# ---------------------------------------------------------------------------


def test_validator_rejects_insert(metadata_service):
    sql = "INSERT INTO hr_mvp.vw_hr_employee_analytics VALUES (1, 'test');"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False


def test_validator_rejects_update(metadata_service):
    sql = "UPDATE hr_mvp.vw_hr_employee_analytics SET gender='M' WHERE employee_id=1;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False


def test_validator_rejects_delete(metadata_service):
    sql = "DELETE FROM hr_mvp.vw_hr_employee_analytics WHERE employee_id=1;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False


def test_validator_rejects_drop(metadata_service):
    sql = "DROP TABLE hr_mvp.vw_hr_employee_analytics;"
    result = validate(sql, metadata_service)
    assert result["is_valid"] is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_validator_rejects_empty_sql(metadata_service):
    result = validate("", metadata_service)
    assert result["is_valid"] is False


def test_validator_result_has_required_fields(metadata_service):
    sql = "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v;"
    result = validate(sql, metadata_service)
    for field in ("is_valid", "status", "can_execute_sql"):
        assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Active filter auto-repair
# ---------------------------------------------------------------------------


def test_validator_repairs_missing_is_active_with_existing_where(metadata_service):
    """SQL with WHERE but missing v.is_active = TRUE must be repaired, not rejected."""
    sql = """
    SELECT v.gender, COUNT(v.employee_id) AS cnt
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.marital_status = 'متأهل'
    GROUP BY v.gender;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is True, f"Expected repair, got: {result.get('status')}"
    assert "IS_ACTIVE" in result.get("sql", "").upper()


def test_validator_repairs_missing_is_active_no_where_clause(metadata_service):
    """SQL with no WHERE clause at all must have is_active injected."""
    sql = """
    SELECT v.employment_type, COUNT(v.employee_id) AS cnt
    FROM hr_mvp.vw_hr_employee_analytics v
    GROUP BY v.employment_type;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is True, f"Expected repair, got: {result.get('status')}"
    assert "IS_ACTIVE" in result.get("sql", "").upper()


def test_validator_does_not_duplicate_is_active_when_already_present(metadata_service):
    """SQL that already has v.is_active = TRUE must not get a second copy."""
    sql = """
    SELECT COUNT(v.employee_id) AS cnt
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.is_active = TRUE AND v.gender = 'F'
    GROUP BY v.gender;
    """
    result = validate(sql, metadata_service)
    assert result["is_valid"] is True
    assert result.get("sql", "").upper().count("IS_ACTIVE") == 1


def _where_region(sql: str) -> str:
    """Return the WHERE clause body, up to the next top-level clause keyword."""
    upper = sql.upper()
    where = upper.find("WHERE")
    if where < 0:
        return ""
    end = len(sql)
    for kw in ("GROUP BY", "ORDER BY", "HAVING", "LIMIT"):
        pos = upper.find(kw, where)
        if pos != -1:
            end = min(end, pos)
    return sql[where:end]


def test_is_active_in_select_projection_does_not_satisfy_guard(metadata_service):
    """The mandatory v.is_active = TRUE filter must live in the WHERE clause.

    A projected boolean expression in the SELECT list (e.g.
    `(v.is_active = TRUE) AS flag`) must NOT satisfy the guard — otherwise an
    analytic query could run with no active-employee filter at all. The
    validator must detect the missing WHERE filter and inject it."""
    sql = (
        "SELECT (v.is_active = TRUE) AS active_flag, COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.gender = 'زن'"
    )
    result = validate(sql, metadata_service)
    where_region = _where_region(result.get("sql", ""))
    assert "is_active" in where_region.lower(), (
        f"is_active must be enforced in the WHERE clause, got WHERE region: {where_region!r}"
    )
    assert result["is_valid"] is True


def test_validator_does_not_flag_shahrivar_as_city_level_gap(metadata_service):
    """ "شهریور" (the Shamsi month) contains "شهر" (city) as a plain substring.
    A question naming Shahrivar must not be misclassified as a city-level
    data gap when the SQL itself never references a city column."""
    sql = """
    SELECT COUNT(v.employee_id) AS employee_count
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.is_active = TRUE
      AND hr_mvp.shamsi_month(v.hire_date) BETWEEN 4 AND 6;
    """
    result = validate(sql, metadata_service, question="تعداد جذب از تیر تا شهریور چقدره")
    assert result["is_valid"] is True
    assert result["status"] in {"OK", "VALID"}


def test_validator_still_flags_real_city_level_question(metadata_service):
    """Regression guard for the fix above: an actual city-level question
    must still be flagged as a data gap."""
    sql = """
    SELECT COUNT(v.employee_id) AS employee_count
    FROM hr_mvp.vw_hr_employee_analytics v
    WHERE v.is_active = TRUE;
    """
    result = validate(sql, metadata_service, question="تعداد کارکنان شهر تهران چند نفر است؟")
    assert result["is_valid"] is False
    assert result["status"] == "DATA_GAP"


# ---------------------------------------------------------------------------
# Negative / break-case coverage of the safety rules (1.4)
#
# Each test feeds hostile or malformed SQL and asserts both that the validator
# rejects it AND that the specific guard rule fired — so a silent regression in
# any single rule's regex is caught, not masked by another rule happening to
# also reject the statement.
# ---------------------------------------------------------------------------


def _rule_ids(result) -> set[str]:
    return {v.get("rule_id") for v in result.get("violations", [])}


def _assert_blocked(result, rule_id: str) -> None:
    # A blocked statement is never executable and never reports a pass status.
    # The exact failure status depends on the rule category (a structural
    # violation finalizes as SQL_VALIDATION_FAILED; a privacy violation such as
    # a visible raw date or employee_id finalizes as ACCESS_DENIED) — both are
    # genuine rejections, so we assert the rule fired and the SQL cannot run.
    assert result["is_valid"] is False, f"Expected rejection, got valid. result={result}"
    assert result["can_execute_sql"] is False, result
    assert result["status"] not in {"OK", "VALID"}, result["status"]
    assert rule_id in _rule_ids(result), f"Expected {rule_id}, got {_rule_ids(result)}"


def test_blocks_union_select(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE UNION SELECT password FROM hr_mvp.vw_hr_employee_analytics v"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_INJECTION_PATTERN_BLOCKED")


def test_blocks_or_1_equals_1(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE OR 1=1"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_INJECTION_PATTERN_BLOCKED")


def test_blocks_or_true_tautology(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE OR TRUE"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_INJECTION_PATTERN_BLOCKED")


def test_blocks_information_schema(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND v.department_id IN "
        "(SELECT table_name FROM information_schema.tables)"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_INTERNAL_SCHEMA_BLOCKED")


def test_blocks_pg_internal_object(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND pg_sleep(5) IS NOT NULL"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_PG_INTERNAL_OBJECT_BLOCKED")


def test_blocks_stacked_statements(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE; "
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_SINGLE_STATEMENT_ONLY")


def test_blocks_line_comment(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE -- drop the active filter"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_COMMENTS_NOT_ALLOWED")


def test_blocks_block_comment(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE /* sneaky */"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_COMMENTS_NOT_ALLOWED")


def test_blocks_unresolved_placeholder(metadata_service):
    sql = (
        "SELECT COUNT(v.employee_id) AS cnt FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND v.gender = {gender}"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_UNRESOLVED_PLACEHOLDER")


def test_blocks_employee_id_outside_count(metadata_service):
    """The CLAUDE.md invariant: employee_id may appear only inside COUNT."""
    sql = "SELECT v.employee_id FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    _assert_blocked(validate(sql, metadata_service), "SQL_EMPLOYEE_ID_COUNT_ONLY")


def test_blocks_raw_date_visible_output(metadata_service):
    sql = (
        "SELECT v.hire_date, COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE GROUP BY v.hire_date"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_RAW_DATE_VISIBLE_OUTPUT_BLOCKED")


def test_blocks_percentage_without_nullif(metadata_service):
    sql = (
        "SELECT ROUND(100.0 * COUNT(v.employee_id) / COUNT(v.employee_id), 2) AS pct "
        "FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_PERCENTAGE_REQUIRES_NULLIF")


def test_allows_percentage_with_nullif(metadata_service):
    """Positive guard: the same percentage query WITH NULLIF must pass."""
    sql = (
        "SELECT ROUND(100.0 * COUNT(v.employee_id) / NULLIF(COUNT(v.employee_id), 0), 2) AS pct "
        "FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    result = validate(sql, metadata_service)
    assert "SQL_PERCENTAGE_REQUIRES_NULLIF" not in _rule_ids(result)


def test_blocks_limit_above_ceiling(metadata_service):
    sql = (
        "SELECT v.gender, COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE GROUP BY v.gender LIMIT 9999"
    )
    _assert_blocked(validate(sql, metadata_service), "SQL_LIMIT_TOO_HIGH")
