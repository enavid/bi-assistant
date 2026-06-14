from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.hr_analytics.use_cases.sql.generator import SQLGenerator


def test_sql_generator_produces_select_for_total_count(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {
            "intent": "total_employee_count",
            "intent_id": "total_employee_count",
            "route": "SQL",
            "template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
            "required_columns": ["employee_id"],
        },
        "route_result": {"route": "SQL", "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="total employees",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "SQL"
    sql = result.get("sql") or ""
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "SELECT" in sql.upper()


def test_sql_generator_returns_data_gap_for_gap_route(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {"route": "GAP", "status": "DATA_GAP"},
        "route_result": {"route": "GAP", "status": "DATA_GAP"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="city level analysis",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "GAP"
    sql = result.get("sql") or ""
    assert "DATA_GAP" in sql


def test_sql_generator_rejects_access_denied_route(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    context = {
        "intent_result": {"route": "REJECT", "status": "ACCESS_DENIED"},
        "route_result": {"route": "REJECT", "status": "ACCESS_DENIED"},
        "semantic_result": {},
    }
    result = gen.generate(
        question="show me personal IDs",
        context=context,
        metadata=metadata_service,
    )
    assert result["route"] == "REJECT"
    sql = result.get("sql") or ""
    assert "ACCESS_DENIED" in sql


# ---------------------------------------------------------------------------
# BUG-002 — arun() must call OllamaClient when NEEDS_LLM_SQL_FALLBACK + model
# ---------------------------------------------------------------------------


def _make_context_with_model(model: str) -> MagicMock:
    ctx = MagicMock()
    ctx.runtime_params = {"model": model}
    ctx.normalized_question = "تعداد کارکنان"
    ctx.question = "تعداد کارکنان"
    ctx.intent_result = {}
    ctx.semantic_result = {}
    ctx.route_result = {}
    ctx.validation_result = {}
    return ctx


def _make_ollama_client(raw_response: str, success: bool = True) -> AsyncMock:
    client = AsyncMock()
    result = MagicMock()
    result.sql = raw_response
    result.success = success
    result.error = None if success else "connection error"
    client.generate.return_value = result
    return client


@pytest.mark.asyncio
async def test_arun_calls_ollama_when_needs_llm_and_model_provided(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    needs_llm = {"status": "NEEDS_LLM_SQL_FALLBACK", "route": "SQL", "can_execute_sql": False}

    ollama_client = _make_ollama_client(
        "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    ctx = _make_context_with_model("llama3.1:8b")

    with patch.object(gen, "generate", return_value=needs_llm):
        result = await gen.arun(context=ctx, ollama_client=ollama_client)

    ollama_client.generate.assert_called_once()
    call_kwargs = ollama_client.generate.call_args
    assert call_kwargs.kwargs.get("model") == "llama3.1:8b"
    assert result["status"] == "OK"
    assert result["metadata"]["model"] == "llama3.1:8b"
    assert "SELECT" in (result.get("sql") or "")


@pytest.mark.asyncio
async def test_arun_does_not_call_ollama_when_no_model(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    needs_llm = {"status": "NEEDS_LLM_SQL_FALLBACK", "route": "SQL", "can_execute_sql": False}

    ollama_client = _make_ollama_client("SELECT 1")
    ctx = MagicMock()
    ctx.runtime_params = {}  # no model
    ctx.normalized_question = "تعداد کارکنان"
    ctx.question = "تعداد کارکنان"
    ctx.intent_result = {}
    ctx.semantic_result = {}
    ctx.route_result = {}
    ctx.validation_result = {}

    with patch.object(gen, "generate", return_value=needs_llm):
        result = await gen.arun(context=ctx, ollama_client=ollama_client)

    ollama_client.generate.assert_not_called()
    assert result["status"] == "NEEDS_LLM_SQL_FALLBACK"


@pytest.mark.asyncio
async def test_arun_does_not_call_ollama_when_generate_succeeds(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    success_result = {
        "status": "OK",
        "route": "SQL",
        "sql": "SELECT COUNT(*) FROM hr_mvp.vw_hr_employee_analytics v",
        "can_execute_sql": True,
    }

    ollama_client = _make_ollama_client("SELECT 1")
    ctx = _make_context_with_model("llama3.1:8b")

    with patch.object(gen, "generate", return_value=success_result):
        result = await gen.arun(context=ctx, ollama_client=ollama_client)

    ollama_client.generate.assert_not_called()
    assert result["status"] == "OK"


@pytest.mark.asyncio
async def test_arun_returns_error_when_ollama_returns_no_sql(metadata_service):
    gen = SQLGenerator(metadata_service=metadata_service)
    needs_llm = {"status": "NEEDS_LLM_SQL_FALLBACK", "route": "SQL", "can_execute_sql": False}

    ollama_client = _make_ollama_client("I cannot generate SQL for this.")
    ctx = _make_context_with_model("llama3.1:8b")

    with patch.object(gen, "generate", return_value=needs_llm):
        result = await gen.arun(context=ctx, ollama_client=ollama_client)

    ollama_client.generate.assert_called_once()
    assert result["status"] == "NEEDS_LLM_SQL_FALLBACK"
    assert result.get("sql") is None
