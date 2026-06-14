from __future__ import annotations

import asyncio

import pytest

from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator

pytestmark = pytest.mark.integration


def _run(orchestrator, question: str) -> dict:
    result = orchestrator.run(question)
    return result.to_dict() if hasattr(result, "to_dict") else result


def test_orchestrator_generates_sql_for_total_employee_count(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    assert payload["route"] == "SQL"
    assert payload["status"] in {"OK", "VALID", "SQL_READY", "NOT_EXECUTED"}
    assert "hr_mvp.vw_hr_employee_analytics" in (payload.get("generated_sql") or "")


def test_orchestrator_returns_gap_for_city_level_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کارکنان شهر تهران چند نفر است؟")
    assert payload["route"] == "GAP"
    assert payload["status"] == "DATA_GAP"


def test_orchestrator_rejects_personal_information(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "نام و کد ملی کارکنان را بده")
    assert payload["route"] == "REJECT"
    assert payload["status"] == "ACCESS_DENIED"


def test_orchestrator_rejects_out_of_scope_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "قیمت دلار امروز چقدر است؟")
    assert payload["route"] == "REJECT"
    assert payload["status"] in {"OUT_OF_SCOPE", "REJECT"}


def test_orchestrator_handles_empty_question_gracefully(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "")
    assert payload["route"] in {"REJECT", "NEEDS_CLARIFICATION"}
    assert "request_id" in payload


def test_orchestrator_handles_whitespace_only_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "   ")
    assert payload["route"] in {"REJECT", "NEEDS_CLARIFICATION"}


def test_orchestrator_gender_breakdown_question(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "درصد کارکنان زن و مرد چقدر است؟")
    assert payload["route"] == "SQL"
    assert payload.get("generated_sql") is not None


def test_orchestrator_response_has_required_fields(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    for field in ("route", "status", "message_fa", "request_id", "warnings", "errors"):
        assert field in payload, f"Missing field: {field}"


def test_orchestrator_fallback_mode_without_steps(metadata_service):
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        domain_classifier=None,
        question_validator=None,
    )
    payload = _run(orchestrator, "تعداد کل کارکنان چند نفر است؟")
    assert payload["route"] in {"SQL", "GAP", "REJECT", "NEEDS_CLARIFICATION"}
    assert "request_id" in payload


def test_orchestrator_arun_is_consistent_with_run(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    question = "تعداد کل کارکنان چند نفر است؟"
    sync_result = orchestrator.run(question)
    async_result = asyncio.run(orchestrator.arun(question))
    sync_payload = sync_result.to_dict() if hasattr(sync_result, "to_dict") else sync_result
    async_payload = async_result.to_dict() if hasattr(async_result, "to_dict") else async_result
    assert sync_payload["route"] == async_payload["route"]
    assert sync_payload["status"] == async_payload["status"]


# ---------------------------------------------------------------------------
# BUG-002 — LLMOrchestrator must accept and store ollama_client
# ---------------------------------------------------------------------------


def test_orchestrator_accepts_ollama_client_param(metadata_service):
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_client,
    )
    assert orchestrator.ollama_client is mock_client


def test_orchestrator_ollama_client_defaults_to_none(metadata_service):
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    assert orchestrator.ollama_client is None


@pytest.mark.asyncio
async def test_orchestrator_calls_ollama_when_model_in_runtime_params(metadata_service):
    """When model is set in runtime_params, OllamaClient must be called for valid SQL questions."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) AS employee_count"
        " FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    )
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()

    mock_ollama.generate.assert_called_once()
    call_kwargs = mock_ollama.generate.call_args.kwargs
    assert call_kwargs.get("model") == "llama3.1:8b"
    assert payload["route"] == "SQL"
    assert "employee_count" in (payload.get("generated_sql") or "").lower()


@pytest.mark.asyncio
async def test_orchestrator_does_not_call_ollama_when_no_model(metadata_service):
    """Without model in runtime_params, OllamaClient must not be called."""
    from unittest.mock import AsyncMock

    mock_ollama = AsyncMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun("تعداد کارکنان چند نفر است؟")

    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_ollama_not_called_for_rejected_question(metadata_service):
    """Rejected questions (ACCESS_DENIED, OUT_OF_SCOPE) must never reach OllamaClient."""
    from unittest.mock import AsyncMock

    mock_ollama = AsyncMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun(
        "نام و کد ملی کارکنان را بده",
        runtime_params={"model": "llama3.1:8b"},
    )

    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_model_called_appears_in_response(metadata_service):
    """model_called field in sql_plan metadata must reflect the selected model."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()
    sql_plan = (payload.get("context") or {}).get("sql_plan") or {}
    model_in_meta = (sql_plan.get("metadata") or {}).get("model")
    assert model_in_meta == "llama3.1:8b"


# ---------------------------------------------------------------------------
# Phase 1.3 — prompt_tokens and context_window in orchestrator trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_trace_includes_prompt_tokens(metadata_service):
    """When LLM is called, sql_plan.metadata must include prompt_tokens from OllamaClient."""
    from unittest.mock import AsyncMock

    from app.hr_analytics.domain.entities import GenerationResult

    mock_ollama = AsyncMock()
    gen_result = GenerationResult(
        sql="SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        success=True,
        prompt_tokens=7536,
        context_window=8192,
    )
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()
    sql_plan = (payload.get("context") or {}).get("sql_plan") or {}
    meta = sql_plan.get("metadata") or {}
    assert meta.get("prompt_tokens") == 7536, f"prompt_tokens not in trace metadata: {meta}"
    assert meta.get("context_window") == 8192, f"context_window not in trace metadata: {meta}"


@pytest.mark.asyncio
async def test_orchestrator_trace_prompt_tokens_none_when_not_returned(metadata_service):
    """prompt_tokens is absent from metadata when OllamaClient does not return it."""
    from unittest.mock import AsyncMock

    from app.hr_analytics.domain.entities import GenerationResult

    mock_ollama = AsyncMock()
    gen_result = GenerationResult(
        sql="SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        success=True,
        # prompt_tokens=None is the default
    )
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )
    response = await orchestrator.arun(
        "تعداد کارکنان چند نفر است؟",
        runtime_params={"model": "llama3.1:8b"},
    )
    payload = response.to_dict()
    sql_plan = (payload.get("context") or {}).get("sql_plan") or {}
    meta = sql_plan.get("metadata") or {}
    # Key should not exist (or be None) — not a hard assertion, just must not raise
    assert "prompt_tokens" not in meta or meta.get("prompt_tokens") is None


# ---------------------------------------------------------------------------
# BUG-003 — TEMPLATE_INCOMPLETE must be surfaced in response warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_incomplete_warning_surfaced_in_response(metadata_service):
    """BUG-003: when template has no GROUP BY but group_by was requested, context.warnings
    must include a template bypass message — it must not be silently swallowed."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="میانگین سن در دپارتمان")
    # Simulate intent parser having extracted group_by
    context.intent_result = {"intent": "average_age", "group_by": ["department_name"]}

    # Template result without GROUP BY — simulates average_age template ignoring dept dimension
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": (
            "SELECT ROUND(AVG(v.age), 2) AS average_age"
            " FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
        ),
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert any("template" in w.lower() for w in context.warnings), (
        f"Expected template bypass warning in context.warnings, got: {context.warnings}"
    )


@pytest.mark.asyncio
async def test_template_incomplete_warning_not_present_for_simple_query(metadata_service):
    """Simple queries with no group_by mismatch must not produce spurious template warnings."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    response = await orchestrator.arun("تعداد کل کارکنان چند نفر است؟")
    payload = response.to_dict()
    warnings = payload.get("warnings") or []
    assert not any("bypassed" in w.lower() for w in warnings), (
        f"Unexpected bypass warning for simple query: {warnings}"
    )


# ---------------------------------------------------------------------------
# Coverage Validator integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_check_marks_plan_incomplete_when_filter_missing(metadata_service):
    """When the template SQL is missing a user-requested filter column, the plan
    must be marked COVERAGE_INCOMPLETE and can_execute_sql must be False."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    # Template returns SQL without the gender filter
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "COVERAGE_INCOMPLETE"
    assert context.sql_plan.get("can_execute_sql") is False


@pytest.mark.asyncio
async def test_coverage_check_does_not_mark_complete_plan_incomplete(metadata_service):
    """When the template SQL contains all required filter columns, status must stay OK."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE AND v.gender = 'زن'",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "OK"
    assert context.sql_plan.get("can_execute_sql") is True


@pytest.mark.asyncio
async def test_coverage_result_stored_in_context(metadata_service):
    """coverage_result must be populated on context after _plan_sql runs."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.coverage_result != {}
    assert context.coverage_result.get("status") == "COVERAGE_INCOMPLETE"
    missing = context.coverage_result.get("missing", [])
    assert any("gender" in m for m in missing)


@pytest.mark.asyncio
async def test_coverage_check_missing_group_by_marks_incomplete(metadata_service):
    """Missing group_by column must also trigger COVERAGE_INCOMPLETE."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان در هر دپارتمان")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
        ],
        "group_by": ["department_name"],
        "metrics": [],
        "params": {},
    }

    # Template returns SQL without GROUP BY department_name
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "COVERAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_coverage_check_skipped_when_no_sql_in_plan(metadata_service):
    """Coverage check must not run when the template produced no SQL at all."""
    import uuid
    from unittest.mock import patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان")
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    # Template returns no SQL
    template_result = {
        "status": "NO_TEMPLATE",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    # Status must remain NO_TEMPLATE — coverage check must not overwrite it
    assert context.sql_plan.get("status") != "COVERAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_orchestrator_skips_sql_generator_when_model_set(metadata_service):
    """When model is set, sql_generator must NOT be called — LLM primary path handles it."""
    from unittest.mock import AsyncMock, MagicMock

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun("تعداد کارکنان؟", runtime_params={"model": "llama3.1:8b"})

    mock_generator.arun.assert_not_called()
    mock_ollama.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 2.4 — No silent fallback on hard template errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_generator_not_called_when_coverage_incomplete(metadata_service):
    """When template coverage is incomplete, the sql_generator must NOT be called.
    COVERAGE_INCOMPLETE is a hard stop — it must not silently fall through."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "COVERAGE_INCOMPLETE"
    mock_generator.arun.assert_not_called()


@pytest.mark.asyncio
async def test_sql_generator_not_called_when_parameter_validation_failed(metadata_service):
    """When template parameter validation fails (critical filter unused), the
    sql_generator must NOT be called. PARAMETER_VALIDATION_FAILED is a hard stop."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.intent_result = {
        "filters": [
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    template_result = {
        "status": "PARAMETER_VALIDATION_FAILED",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
        "errors": ["Template cannot apply critical filter(s): ['gender_value']"],
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "PARAMETER_VALIDATION_FAILED"
    mock_generator.arun.assert_not_called()


@pytest.mark.asyncio
async def test_sql_generator_called_when_no_template(metadata_service):
    """When no template exists (NO_TEMPLATE), sql_generator SHOULD be called
    — the question might still be answerable via Controlled Dynamic."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_generator = AsyncMock()
    mock_generator.arun.return_value = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_generator",
        "sql": "SELECT 1",
        "can_execute_sql": True,
    }

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان؟")
    context.intent_result = {"filters": [], "group_by": [], "metrics": [], "params": {}}

    template_result = {
        "status": "NO_TEMPLATE",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    mock_generator.arun.assert_called_once()
