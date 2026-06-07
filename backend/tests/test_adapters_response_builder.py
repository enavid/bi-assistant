from __future__ import annotations

from app.adapters.presenters.response_builder import ResponseBuilder, ResponsePayload


def test_response_builder_builds_success_response(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "intent_result": {"intent": "total_employee_count", "route": "SQL"},
        "route_result": {"route": "SQL", "status": "SUCCESS"},
        "sql_plan": {"sql": "SELECT COUNT(v.employee_id) AS employee_count FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE;"},
        "query_result": {
            "status": "SUCCESS",
            "execution_status": "SUCCESS",
            "rows": [{"employee_count": 750}],
        },
    }
    result = builder.build(context=context, status_payload={"status": "SUCCESS", "route": "SQL"})
    assert result["route"] == "SQL"
    assert result["status"] == "SUCCESS"
    assert result["data"] == [{"employee_count": 750}]


def test_response_builder_returns_data_gap_status(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "route_result": {"route": "GAP", "status": "DATA_GAP"},
        "gap_result": {"reason_fa": "داده در دسترس نیست"},
        "query_result": {},
    }
    result = builder.build(context=context, status_payload={"status": "DATA_GAP", "route": "GAP"})
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"
    assert result["data"] == []


def test_response_builder_returns_access_denied(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "route_result": {"route": "REJECT", "status": "ACCESS_DENIED"},
        "query_result": {},
    }
    result = builder.build(context=context, status_payload={"status": "ACCESS_DENIED", "route": "REJECT"})
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"


def test_response_builder_suppresses_sensitive_columns(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "intent_result": {"intent": "total_employee_count", "route": "SQL"},
        "route_result": {"route": "SQL", "status": "SUCCESS"},
        "sql_plan": {},
        "query_result": {
            "status": "SUCCESS",
            "execution_status": "SUCCESS",
            "rows": [{"employee_count": 100, "national_id": "1234567890"}],
        },
    }
    result = builder.build(context=context, status_payload={"status": "SUCCESS", "route": "SQL"})
    assert result["status"] == "SUCCESS"
    for row in result.get("data", []):
        assert "national_id" not in row


def test_response_builder_extracts_embedded_status(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "intent_result": {"intent": "total_employee_count", "route": "SQL"},
        "route_result": {"route": "SQL", "status": "SUCCESS"},
        "sql_plan": {},
        "query_result": {
            "status": "SUCCESS",
            "rows": [{"status": "DATA_GAP"}],
        },
    }
    result = builder.build(context=context, status_payload={"status": "SUCCESS", "route": "SQL"})
    assert result["status"] == "DATA_GAP"
    assert result["route"] == "GAP"


def test_response_builder_no_data_response(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "intent_result": {"intent": "total_employee_count", "route": "SQL"},
        "route_result": {"route": "SQL", "status": "SUCCESS"},
        "sql_plan": {},
        "query_result": {"status": "SUCCESS", "rows": []},
    }
    result = builder.build(context=context, status_payload={"status": "SUCCESS", "route": "SQL"})
    assert result["status"] == "NO_DATA"
