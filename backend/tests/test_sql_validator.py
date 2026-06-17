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
