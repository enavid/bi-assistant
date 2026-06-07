from __future__ import annotations


def test_metadata_health_is_ok(metadata_service):
    health = metadata_service.health_check().to_dict()
    assert health["ok"] is True
    assert not health["errors"]


def test_main_view_and_core_templates_exist(metadata_service):
    main_view = metadata_service.get_main_view()
    assert main_view.get("name") == "hr_mvp.vw_hr_employee_analytics"

    assert metadata_service.get_sql_template("TPL_TOTAL_EMPLOYEE_COUNT") is not None
    assert metadata_service.get_sql_template("TPL_DATA_GAP") is not None
    assert metadata_service.get_sql_template("TPL_ACCESS_DENIED") is not None
    assert metadata_service.get_status_sql("DATA_GAP") == "SELECT 'DATA_GAP' AS status;"
