from __future__ import annotations

from app.infrastructure.metadata.service import get_metadata_service


def test_metadata_service_health_ok(metadata_service):
    health = metadata_service.health_check().to_dict()
    assert health["ok"] is True
    assert health["errors"] == []


def test_metadata_service_main_view(metadata_service):
    view = metadata_service.get_main_view()
    assert view.get("name") == "hr_mvp.vw_hr_employee_analytics"


def test_metadata_service_columns_non_empty(metadata_service):
    columns = metadata_service.get_columns()
    assert len(columns) > 0
    assert all("name" in col for col in columns)


def test_metadata_service_sql_template_total_count(metadata_service):
    tpl = metadata_service.get_sql_template("TPL_TOTAL_EMPLOYEE_COUNT")
    assert tpl is not None
    sql = tpl.get("sql", "")
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "COUNT" in sql


def test_metadata_service_status_sql_data_gap(metadata_service):
    sql = metadata_service.get_status_sql("DATA_GAP")
    assert sql == "SELECT 'DATA_GAP' AS status;"


def test_metadata_service_get_intent_exists(metadata_service):
    intents = metadata_service.list_intents()
    assert len(intents) > 0
    first_id = intents[0]["intent_id"]
    fetched = metadata_service.get_intent(first_id)
    assert fetched is not None
    assert fetched["intent_id"] == first_id


def test_metadata_service_sensitive_columns_non_empty(metadata_service):
    sensitive = metadata_service.get_sensitive_columns()
    assert "national_id" in sensitive or "personnel_number" in sensitive


def test_metadata_service_schema_context_for_prompt(metadata_service):
    context = metadata_service.build_schema_context_for_prompt()
    assert "hr_mvp.vw_hr_employee_analytics" in context
    assert "employee_id" in context


def test_metadata_service_reload_returns_bundle(metadata_service):
    bundle = metadata_service.reload()
    assert bundle is not None
    assert bundle.data_dictionary


def test_get_metadata_service_singleton():
    from pathlib import Path
    metadata_dir = Path(__file__).resolve().parents[1] / "metadata"
    s1 = get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=True)
    s2 = get_metadata_service(strict=True)
    assert s1 is s2
