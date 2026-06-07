from __future__ import annotations

from app.use_cases.hr_analytics.sql.validator import SQLValidator


def validate(sql: str, metadata_service, question: str | None = None):
    return SQLValidator(metadata_service=metadata_service).validate(sql=sql, question=question)


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


def test_validator_allows_status_only_data_gap(metadata_service):
    result = validate("SELECT 'DATA_GAP' AS status;", metadata_service)
    assert result["is_valid"] is True
    assert result["can_execute_sql"] is False
    assert result["status"] == "DATA_GAP"
