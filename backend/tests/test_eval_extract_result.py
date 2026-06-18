from __future__ import annotations

from types import SimpleNamespace

from app.evaluation.api.routes import _extract_result


def _make_question() -> SimpleNamespace:
    return SimpleNamespace(
        question_id="q001",
        question="سوال",
        category=None,
        expected_route=None,
        expected_status=None,
        expected_intent=None,
    )


def test_extract_result_model_called_from_trace_when_template_source() -> None:
    """model_called must be readable from the sql_planner trace step even when
    sql_plan.source is "sql_template" (the LLM was consulted earlier in the
    pipeline but the final plan came from a template, so sql_plan.metadata is
    empty)."""
    payload = {
        "route": "SQL",
        "status": "NOT_EXECUTED",
        "detected_intent": "",
        "errors": [],
        "warnings": [],
        "context": {
            "traces": [
                {
                    "step": "sql_planner",
                    "status": "ok",
                    "details": {"model_called": "qwen2.5:14b"},
                },
            ],
            "sql_plan": {"source": "sql_template"},
            "query_result": {},
            "sql_validation": {},
            "visualization_plan": {},
        },
    }

    result = _extract_result(payload, _make_question(), elapsed_ms=100)

    assert result["model_called"] == "qwen2.5:14b"


def test_extract_result_model_called_none_when_llm_not_called() -> None:
    payload = {
        "route": "SQL",
        "status": "NOT_EXECUTED",
        "detected_intent": "",
        "errors": [],
        "warnings": [],
        "context": {
            "traces": [
                {"step": "sql_planner", "status": "ok", "details": {"model_called": None}},
            ],
            "sql_plan": {"source": "sql_template"},
            "query_result": {},
            "sql_validation": {},
            "visualization_plan": {},
        },
    }

    result = _extract_result(payload, _make_question(), elapsed_ms=100)

    assert result["model_called"] is None
