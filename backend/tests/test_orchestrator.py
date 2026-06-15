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
    """When model is set and template returns NO_TEMPLATE, OllamaClient must be called."""
    from unittest.mock import AsyncMock, MagicMock, patch

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
    no_template_result = {
        "status": "NO_TEMPLATE",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
    }
    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=no_template_result
    ):
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
    """When LLM is invoked (NO_TEMPLATE), model name must appear in sql_plan metadata."""
    from unittest.mock import AsyncMock, MagicMock, patch

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
    no_template_result = {
        "status": "NO_TEMPLATE",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
    }
    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=no_template_result
    ):
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
    """When LLM is invoked (NO_TEMPLATE), sql_plan.metadata must include prompt_tokens."""
    from unittest.mock import AsyncMock, patch

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
    no_template_result = {
        "status": "NO_TEMPLATE",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": None,
        "can_execute_sql": False,
    }
    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=no_template_result
    ):
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
    """When the template SQL is missing a user-requested filter, Controlled Dynamic
    patches it. Plan status becomes OK with source=controlled_dynamic."""
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

    # Controlled Dynamic patches the missing gender filter → plan becomes OK
    assert context.sql_plan.get("status") == "OK"
    assert context.sql_plan.get("source") == "controlled_dynamic"
    assert "v.gender = 'زن'" in (context.sql_plan.get("sql") or "")
    assert context.sql_plan.get("can_execute_sql") is True


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

    # coverage_result must always be populated when coverage was checked
    assert context.coverage_result != {}
    # CD patched the missing gender filter — coverage_result still records the original gap
    missing = context.coverage_result.get("missing", [])
    assert any("gender" in m for m in missing), f"Expected gender in missing: {missing}"
    # status is either COVERAGE_INCOMPLETE (before CD) or PATCHED_BY_CONTROLLED_DYNAMIC (after)
    assert context.coverage_result.get("status") in {
        "COVERAGE_INCOMPLETE",
        "PATCHED_BY_CONTROLLED_DYNAMIC",
    }


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
    """When model is set and template is valid, neither sql_generator nor LLM is called.
    The gate must prevent LLM invocation when template already provides valid SQL."""
    from unittest.mock import AsyncMock

    mock_ollama = AsyncMock()
    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
        ollama_client=mock_ollama,
    )
    await orchestrator.arun("تعداد کارکنان؟", runtime_params={"model": "llama3.1:8b"})

    mock_generator.arun.assert_not_called()
    mock_ollama.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2.4 — No silent fallback on hard template errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_generator_not_called_when_coverage_incomplete(metadata_service):
    """When coverage is incomplete with group_by missing (CD cannot fix it),
    sql_generator must NOT be called — COVERAGE_INCOMPLETE is a hard stop."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_generator = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        sql_generator=mock_generator,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان در هر دپارتمان")
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
        ],
        "group_by": ["department_name"],
        "metrics": [],
        "params": {},
    }

    # Template SQL has no GROUP BY — CD cannot fix group_by gap → stays COVERAGE_INCOMPLETE
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) AS employee_count FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
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


# ---------------------------------------------------------------------------
# BUG-008 — max_age / min_age / stddev_age routing in fallback intent parser
# ---------------------------------------------------------------------------


def test_fallback_intent_parser_routes_max_age(metadata_service):
    """'بیشترین سن' must select max_age intent, not employee_count_by_age_filter."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("بیشترین سن کارمندان چقدر است؟")
    d = result.to_dict() if hasattr(result, "to_dict") else result
    assert d.get("detected_intent") == "max_age", (
        f"Expected detected_intent=max_age but got {d.get('detected_intent')!r}"
    )
    sql = d.get("generated_sql") or ""
    assert "MAX" in sql.upper(), f"Expected MAX in SQL but got: {sql[:120]}"
    assert "age" in sql.lower(), "Expected 'age' in SQL"


def test_fallback_intent_parser_routes_min_age(metadata_service):
    """'کمترین سن' must select min_age intent."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("کمترین سن کارمندان چقدر است؟")
    d = result.to_dict() if hasattr(result, "to_dict") else result
    assert d.get("detected_intent") == "min_age", (
        f"Expected detected_intent=min_age but got {d.get('detected_intent')!r}"
    )
    sql = d.get("generated_sql") or ""
    assert "MIN" in sql.upper(), f"Expected MIN in SQL but got: {sql[:120]}"


def test_fallback_intent_parser_routes_stddev_age(metadata_service):
    """'انحراف معیار سن' must select stddev_age intent."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("انحراف معیار سن کارمندان چقدر است؟")
    d = result.to_dict() if hasattr(result, "to_dict") else result
    assert d.get("detected_intent") == "stddev_age", (
        f"Expected detected_intent=stddev_age but got {d.get('detected_intent')!r}"
    )
    sql = d.get("generated_sql") or ""
    assert "STDDEV" in sql.upper(), f"Expected STDDEV in SQL but got: {sql[:120]}"


def test_fallback_sql_template_engine_renders_default_params(metadata_service):
    """_fallback_sql_template_engine must fill template parameter defaults so
    no '{placeholder}' strings remain in the rendered SQL."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    result = orchestrator.run("میانگین سن کارکنان چقدر است؟")
    d = result.to_dict() if hasattr(result, "to_dict") else result
    sql = d.get("generated_sql") or ""
    assert "{" not in sql, f"Unrendered placeholder found in SQL: {sql[:200]}"
    assert "AVG" in sql.upper(), f"Expected AVG in SQL: {sql[:120]}"


# ---------------------------------------------------------------------------
# Phase 3.3 / BUG-006: superlative questions → result_limit=1 in fallback
# ---------------------------------------------------------------------------


def test_extract_template_params_sets_result_limit_for_most(metadata_service):
    """_extract_template_params must set result_limit=1 when the question
    asks for the group with the most members (بیشترین) and the intent is
    a sortable GROUP BY intent."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_department"}
    result = orchestrator._extract_template_params(
        "کدام دپارتمان بیشترین تعداد کارکنان را دارد؟", intent
    )
    assert result["params"].get("result_limit") == 1, (
        f"Expected result_limit=1 for superlative question, got: {result['params']}"
    )


def test_extract_template_params_sets_result_limit_for_least(metadata_service):
    """_extract_template_params must set result_limit=1 when the question
    asks for the group with the fewest members (کمترین)."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_province"}
    result = orchestrator._extract_template_params(
        "کدام استان کمترین تعداد کارمند را دارد؟", intent
    )
    assert result["params"].get("result_limit") == 1, (
        f"Expected result_limit=1 for 'least' superlative, got: {result['params']}"
    )


def test_extract_template_params_no_result_limit_for_non_superlative(metadata_service):
    """_extract_template_params must NOT set result_limit=1 for plain
    GROUP BY questions that don't ask for a ranking."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_department"}
    result = orchestrator._extract_template_params("تعداد کارکنان در هر دپارتمان چقدر است؟", intent)
    assert result["params"].get("result_limit") != 1, (
        f"result_limit should NOT be 1 for non-superlative, got: {result['params']}"
    )


def test_fallback_pipeline_superlative_dept_produces_limit_1_sql(metadata_service):
    """End-to-end: a superlative department question must produce SQL with LIMIT 1."""
    orchestrator = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orchestrator, "کدام دپارتمان بیشترین تعداد کارکنان را دارد؟")
    sql = (d.get("generated_sql") or "").upper()
    assert "LIMIT" in sql, f"Expected LIMIT in SQL: {sql[:200]}"
    assert "LIMIT 1" in sql or "LIMIT\n1" in sql, f"Expected LIMIT 1 in SQL: {sql[:200]}"


# ---------------------------------------------------------------------------
# Phase 3.6 / 3.4: service_years and hire_year param extraction in fallback
# ---------------------------------------------------------------------------


def test_extract_template_params_service_years_min(metadata_service):
    """_extract_template_params must set service_years_min for 'بیش از N سال سابقه'."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_service_years_filter"}
    result = orch._extract_template_params(
        "تعداد کارکنان با بیش از ۱۰ سال سابقه چند نفر است؟", intent
    )
    assert result["params"].get("service_years_min") == 10, (
        f"Expected service_years_min=10, got: {result['params']}"
    )


def test_extract_template_params_service_years_max_exclusive(metadata_service):
    """_extract_template_params must set service_years_max_exclusive for 'کمتر از N سال سابقه'."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_service_years_filter"}
    result = orch._extract_template_params("کارکنان با کمتر از ۵ سال سابقه چند نفرند؟", intent)
    assert result["params"].get("service_years_max_exclusive") == 5, (
        f"Expected service_years_max_exclusive=5, got: {result['params']}"
    )


def test_extract_template_params_service_years_between(metadata_service):
    """_extract_template_params must set min and max_inclusive for 'سابقه بین N تا M سال'."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_service_years_filter"}
    result = orch._extract_template_params("سابقه بین ۵ تا ۱۵ سال", intent)
    p = result["params"]
    assert p.get("service_years_min") == 5, f"Expected min=5, got: {p}"
    assert p.get("service_years_max_inclusive") == 15, f"Expected max_inclusive=15, got: {p}"


def test_extract_template_params_hire_year(metadata_service):
    """_extract_template_params must extract hire_year from questions like 'سال ۱۴۰۰ استخدام'."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_hire_year"}
    result = orch._extract_template_params("چند نفر از کارکنان در سال ۱۴۰۰ استخدام شده‌اند؟", intent)
    assert result["params"].get("hire_year") == 1400, (
        f"Expected hire_year=1400, got: {result['params']}"
    )


def test_fallback_pipeline_service_years_min_produces_correct_sql(metadata_service):
    """End-to-end: service_years >=10 question must produce SQL with 10 in the WHERE clause."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "تعداد کارکنان با بیش از ۱۰ سال سابقه چند نفر است؟")
    assert d.get("detected_intent") == "employee_count_by_service_years_filter", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "SERVICE_YEARS" in sql, f"Expected SERVICE_YEARS in SQL: {sql[:200]}"
    assert "10" in sql, f"Expected 10 in SQL: {sql[:200]}"


def test_fallback_pipeline_hire_year_produces_correct_sql(metadata_service):
    """End-to-end: hire_year question must produce SQL with the year in the WHERE clause."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "چند نفر از کارکنان در سال ۱۴۰۰ استخدام شده‌اند؟")
    assert d.get("detected_intent") == "employee_count_by_hire_year", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "HIRE_YEAR" in sql, f"Expected HIRE_YEAR in SQL: {sql[:200]}"
    assert "1400" in sql, f"Expected 1400 in SQL: {sql[:200]}"


# ---------------------------------------------------------------------------
# Phase 3.5 / BUG-007: 2D GROUP BY — new intents + templates
# ---------------------------------------------------------------------------


def test_avg_age_by_dept_intent_and_sql(metadata_service):
    """'میانگین سن در هر دپارتمان' must route to avg_age_by_department and
    produce SQL with AVG(age), department_name, and GROUP BY."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "میانگین سن کارکنان در هر دپارتمان چقدر است؟")
    assert d.get("detected_intent") == "avg_age_by_department", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "AVG" in sql, f"Expected AVG in SQL: {sql[:200]}"
    assert "DEPARTMENT_NAME" in sql, f"Expected DEPARTMENT_NAME in SQL: {sql[:200]}"
    assert "GROUP BY" in sql, f"Expected GROUP BY in SQL: {sql[:200]}"


def test_female_count_by_dept_intent_and_sql(metadata_service):
    """'تعداد زنان در هر واحد' must route to a department×gender intent and
    produce SQL with gender, department_name, and GROUP BY."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "تعداد کارکنان زن در هر واحد سازمانی چند نفر است؟")
    assert d.get("detected_intent") == "employee_count_by_department_gender", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "GENDER" in sql, f"Expected GENDER in SQL: {sql[:200]}"
    assert "DEPARTMENT_NAME" in sql, f"Expected DEPARTMENT_NAME in SQL: {sql[:200]}"
    assert "GROUP BY" in sql, f"Expected GROUP BY in SQL: {sql[:200]}"


def test_age_filter_by_dept_intent_and_sql(metadata_service):
    """'زیر ۳۰ سال در هر واحد' must route to employee_count_by_age_filter_by_department
    and produce SQL with age filter and GROUP BY department_name."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "چند نفر از کارکنان زیر ۳۰ سال در هر واحد سازمانی هستند؟")
    assert d.get("detected_intent") == "employee_count_by_age_filter_by_department", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "AGE" in sql, f"Expected AGE in SQL: {sql[:200]}"
    assert "DEPARTMENT_NAME" in sql, f"Expected DEPARTMENT_NAME in SQL: {sql[:200]}"
    assert "GROUP BY" in sql, f"Expected GROUP BY in SQL: {sql[:200]}"
    assert "30" in sql, f"Expected 30 in SQL: {sql[:200]}"


def test_employment_type_by_dept_intent_and_sql(metadata_service):
    """'توزیع نوع استخدام در هر دپارتمان' must route to employment_type_by_department
    and produce SQL with employment_type, department_name, and GROUP BY."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "توزیع نوع استخدام در هر دپارتمان چگونه است؟")
    assert d.get("detected_intent") == "employment_type_by_department", (
        f"Wrong intent: {d.get('detected_intent')}"
    )
    sql = (d.get("generated_sql") or "").upper()
    assert "EMPLOYMENT_TYPE" in sql, f"Expected EMPLOYMENT_TYPE in SQL: {sql[:200]}"
    assert "DEPARTMENT_NAME" in sql, f"Expected DEPARTMENT_NAME in SQL: {sql[:200]}"
    assert "GROUP BY" in sql, f"Expected GROUP BY in SQL: {sql[:200]}"


def test_extract_template_params_age_filter_by_dept(metadata_service):
    """_extract_template_params for employee_count_by_age_filter_by_department
    must set age_max_exclusive for 'زیر N سال'."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    intent = {"intent_id": "employee_count_by_age_filter_by_department"}
    result = orch._extract_template_params(
        "چند نفر از کارکنان زیر ۳۰ سال در هر واحد سازمانی هستند؟", intent
    )
    assert result["params"].get("age_max_exclusive") == 30, (
        f"Expected age_max_exclusive=30, got: {result['params']}"
    )


# ---------------------------------------------------------------------------
# Phase 4.1 — LLM Invocation Gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_not_called_when_template_valid(metadata_service):
    """When template returns status OK with valid SQL, LLM must NOT be called
    even when model is provided in runtime_params."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان؟")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {"filters": [], "group_by": [], "metrics": [], "params": {}}

    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template_engine",
        "sql": "SELECT COUNT(v.employee_id) AS employee_count FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE",
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    mock_ollama.generate.assert_not_called()
    assert context.sql_plan.get("status") == "OK"
    assert "SELECT COUNT" in (context.sql_plan.get("sql") or "")


@pytest.mark.asyncio
async def test_llm_called_when_no_template_and_model_set(metadata_service):
    """When template returns NO_TEMPLATE and model is set, LLM must be invoked."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

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

    context = RequestContext(request_id=str(uuid.uuid4()), question="سوال بدون template")
    context.runtime_params = {"model": "llama3.1:8b"}
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

    mock_ollama.generate.assert_called_once()


@pytest.mark.asyncio
async def test_llm_called_when_template_incomplete_and_model_set(metadata_service):
    """When template is marked TEMPLATE_INCOMPLETE and model is set, LLM must be invoked."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

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

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد زنان در هر دپارتمان")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": ["department_name"],
        "metrics": [],
        "params": {},
    }

    template_result = {
        "status": "TEMPLATE_INCOMPLETE",
        "route": "SQL",
        "source": "template_coverage_checker",
        "sql": None,
        "can_execute_sql": False,
        "reason": "Template does not cover all filters.",
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    mock_ollama.generate.assert_called_once()


@pytest.mark.asyncio
async def test_llm_trigger_reason_recorded_in_trace(metadata_service):
    """When LLM is invoked due to NO_TEMPLATE, the trace must record llm_trigger_reason."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

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

    context = RequestContext(request_id=str(uuid.uuid4()), question="سوال بدون template")
    context.runtime_params = {"model": "llama3.1:8b"}
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

    trace_entry = next((t for t in context.traces if t.step == "sql_planner"), None)
    assert trace_entry is not None, "sql_planner trace entry missing"
    assert trace_entry.details.get("llm_trigger_reason") == "NO_TEMPLATE", (
        f"Expected llm_trigger_reason='NO_TEMPLATE', got: {trace_entry.details}"
    )


# ---------------------------------------------------------------------------
# Phase 4.2 — Controlled Dynamic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_controlled_dynamic_patches_coverage_incomplete(metadata_service):
    """When template SQL covers only some filters, CD must patch the missing ones
    and plan status must become OK — no LLM needed."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن زیر ۳۰ سال")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [
            {"column": "is_active", "operator": "=", "value": True, "source": "default_rule"},
            {"column": "gender", "operator": "=", "value": "زن"},
            {"column": "age", "operator": "<", "value": 30},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    # Template produced SQL with age but missing gender — coverage fails
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template",
        "sql": (
            "SELECT COUNT(v.employee_id) AS employee_count\n"
            "FROM hr_mvp.vw_hr_employee_analytics v\n"
            "WHERE v.is_active = TRUE\n"
            "  AND v.age < 30\n"
            "ORDER BY employee_count DESC"
        ),
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("status") == "OK", (
        f"Expected OK after CD patch, got: {context.sql_plan.get('status')}"
    )
    assert context.sql_plan.get("source") == "controlled_dynamic"
    assert "v.gender = 'زن'" in (context.sql_plan.get("sql") or "")
    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_controlled_dynamic_llm_not_called_after_successful_patch(metadata_service):
    """After CD patches the SQL, LLM must NOT be invoked even when model is set."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان پیمانکار")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [
            {"column": "is_contractor", "operator": "=", "value": True},
        ],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    # Template has no is_contractor filter — coverage will fail
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template",
        "sql": (
            "SELECT COUNT(v.employee_id) AS employee_count\n"
            "FROM hr_mvp.vw_hr_employee_analytics v\n"
            "WHERE v.is_active = TRUE\n"
            "ORDER BY employee_count DESC"
        ),
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("source") == "controlled_dynamic"
    assert "v.is_contractor = TRUE" in (context.sql_plan.get("sql") or "")
    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_controlled_dynamic_falls_through_to_llm_on_group_by_missing(metadata_service):
    """When missing items include group_by:*, CD must fail and LLM must be called."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = "SELECT v.department_name, COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE GROUP BY v.department_name"
    gen_result.success = True
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(
        request_id=str(uuid.uuid4()), question="تعداد کارکنان زن در هر دپارتمان"
    )
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [
            {"column": "gender", "operator": "=", "value": "زن"},
        ],
        "group_by": ["department_name"],
        "metrics": [],
        "params": {},
    }

    # Template only counts total — no gender and no GROUP BY
    template_result = {
        "status": "OK",
        "route": "SQL",
        "source": "sql_template",
        "sql": (
            "SELECT COUNT(v.employee_id) AS employee_count\n"
            "FROM hr_mvp.vw_hr_employee_analytics v\n"
            "WHERE v.is_active = TRUE\n"
            "ORDER BY employee_count DESC"
        ),
        "can_execute_sql": True,
    }

    with patch.object(orchestrator, "_fallback_sql_template_engine", return_value=template_result):
        await orchestrator._plan_sql(context)

    # CD cannot fix GROUP BY → LLM must be called
    mock_ollama.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 4.4 — LLM output through Coverage Validator
# ---------------------------------------------------------------------------


_NO_TEMPLATE_PLAN = {
    "status": "NO_TEMPLATE",
    "route": "SQL",
    "source": "sql_template_engine",
    "sql": None,
    "can_execute_sql": False,
}


@pytest.mark.asyncio
async def test_llm_plan_has_coverage_status_complete_when_sql_covers_all(metadata_service):
    """When LLM SQL includes all required filters/group_by, plan must have coverage_status=COMPLETE."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT v.gender, COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND v.department_name = 'IT' "
        "GROUP BY v.gender"
    )
    gen_result.prompt_tokens = None
    gen_result.context_window = None
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد زن و مرد در IT")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "department_name", "operator": "=", "value": "IT"}],
        "group_by": ["gender"],
        "metrics": [],
        "params": {},
    }

    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=_NO_TEMPLATE_PLAN
    ):
        await orchestrator._plan_sql(context)

    plan = context.sql_plan
    assert plan.get("coverage_status") == "COMPLETE", f"Expected COMPLETE, got: {plan}"
    assert plan.get("coverage_missing") == []


@pytest.mark.asyncio
async def test_llm_plan_has_coverage_status_incomplete_when_filter_missing(metadata_service):
    """When LLM SQL misses a required filter, plan must report LLM_COVERAGE_INCOMPLETE."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    # LLM forgot to include the gender filter
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE"
    )
    gen_result.prompt_tokens = None
    gen_result.context_window = None
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=_NO_TEMPLATE_PLAN
    ):
        await orchestrator._plan_sql(context)

    plan = context.sql_plan
    assert plan.get("coverage_status") == "LLM_COVERAGE_INCOMPLETE", (
        f"Expected LLM_COVERAGE_INCOMPLETE, got: {plan}"
    )
    assert "filter:gender" in (plan.get("coverage_missing") or [])


@pytest.mark.asyncio
async def test_llm_coverage_incomplete_still_can_execute(metadata_service):
    """Even when LLM SQL has incomplete coverage, can_execute_sql must remain True."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE"
    )
    gen_result.prompt_tokens = None
    gen_result.context_window = None
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=_NO_TEMPLATE_PLAN
    ):
        await orchestrator._plan_sql(context)

    assert context.sql_plan.get("can_execute_sql") is True


@pytest.mark.asyncio
async def test_llm_coverage_incomplete_adds_warning_to_context(metadata_service):
    """Incomplete LLM coverage must add a warning to context.warnings."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE"
    )
    gen_result.prompt_tokens = None
    gen_result.context_window = None
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=_NO_TEMPLATE_PLAN
    ):
        await orchestrator._plan_sql(context)

    assert any("coverage" in w.lower() or "missing" in w.lower() for w in context.warnings), (
        f"Expected a coverage warning, got: {context.warnings}"
    )


@pytest.mark.asyncio
async def test_llm_coverage_result_stored_on_context(metadata_service):
    """After LLM call, context.coverage_result must contain llm_coverage_status."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.hr_analytics.use_cases.orchestrator import RequestContext

    mock_ollama = AsyncMock()
    gen_result = MagicMock()
    gen_result.sql = (
        "SELECT COUNT(v.employee_id) AS cnt "
        "FROM hr_mvp.vw_hr_employee_analytics v "
        "WHERE v.is_active = TRUE AND v.gender = 'زن'"
    )
    gen_result.prompt_tokens = None
    gen_result.context_window = None
    gen_result.error = None
    mock_ollama.generate.return_value = gen_result

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        ollama_client=mock_ollama,
    )

    context = RequestContext(request_id=str(uuid.uuid4()), question="تعداد کارکنان زن")
    context.runtime_params = {"model": "llama3.1:8b"}
    context.intent_result = {
        "filters": [{"column": "gender", "operator": "=", "value": "زن"}],
        "group_by": [],
        "metrics": [],
        "params": {},
    }

    with patch.object(
        orchestrator, "_fallback_sql_template_engine", return_value=_NO_TEMPLATE_PLAN
    ):
        await orchestrator._plan_sql(context)

    assert "llm_coverage_status" in context.coverage_result, (
        f"coverage_result missing llm_coverage_status: {context.coverage_result}"
    )
    assert context.coverage_result["llm_coverage_status"] == "COMPLETE"


# ---------------------------------------------------------------------------
# Bug fix: near_retirement_analysis must NOT be a hardcoded GAP rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retirement_question_routes_to_sql_not_gap(metadata_service):
    """Retirement question must route to SQL, not GAP, via fallback parser."""
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
    )
    result = await orchestrator.arun(
        "چند نفر از کارمندان تا ۵ سال آینده بازنشسته می‌شوند؟"
    )
    ctx = result.context
    intent_res = ctx.get("intent_result") or {}
    assert isinstance(intent_res, dict), "intent_result must be a dict"
    assert intent_res.get("route") != "GAP", (
        f"Retirement question must not route to GAP. Got: {intent_res.get('route')}"
    )
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"Wrong intent: {intent_res.get('intent_id')}"
    )


@pytest.mark.asyncio
async def test_retirement_question_has_sql_template(metadata_service):
    """Retirement question result must carry the SQL template reference."""
    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
    )
    result = await orchestrator.arun(
        "تعداد کارکنان در آستانه بازنشستگی چند نفر است؟"
    )
    ctx = result.context
    intent_res = ctx.get("intent_result") or {}
    sql_plan = ctx.get("sql_plan") or {}
    assert isinstance(intent_res, dict)
    assert intent_res.get("sql_template_id") == "TPL_NEAR_RETIREMENT_5_YEARS", (
        f"Expected template TPL_NEAR_RETIREMENT_5_YEARS, got: {intent_res.get('sql_template_id')}"
    )


# ---------------------------------------------------------------------------
# Bug fix: explicit_gender must not fire on "بازنشسته" via substring "زن"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retirement_question_not_detected_as_gender(metadata_service):
    """'بازنشسته' must not trigger gender detection via substring 'زن'."""
    from app.hr_analytics.use_cases.steps.domain_classifier import DomainClassifier
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        domain_classifier=DomainClassifier(),
        question_validator=QuestionValidator(),
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    result = await orchestrator.arun(
        "چند نفر از کارمندان تا ۵ سال آینده بازنشسته می‌شوند؟"
    )
    ctx = result.context
    intent_res = ctx.get("intent_result") or {}
    assert isinstance(intent_res, dict)
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"Retirement question got wrong intent: {intent_res.get('intent_id')} "
        f"(likely gender false-positive via 'زن' inside 'بازنشسته')"
    )


# ---------------------------------------------------------------------------
# Bug fix: "باز نشسته" (split spelling) must route to near_retirement_analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retirement_split_spelling_routes_to_sql(metadata_service):
    """'باز نشسته' (two words) must detect near_retirement_analysis, not age filter."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    result = await orchestrator.arun(
        "چند نفر از کارمندان تا 5 سال آینده باز نشسته میشوند؟"
    )
    ctx = result.context
    intent_res = ctx.get("intent_result") or {}
    assert intent_res.get("route") != "GAP", "retirement question must not be GAP"
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"split 'باز نشسته' got wrong intent: {intent_res.get('intent_id')}"
    )


@pytest.mark.asyncio
async def test_retirement_no_half_space_routes_to_sql(metadata_service):
    """'بازنشسته میشوند' (no half-space before میشوند) must still detect near_retirement_analysis."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    result = await orchestrator.arun(
        "چند نفر از کارمندان تا 5 سال آینده بازنشسته میشوند؟"
    )
    ctx = result.context
    intent_res = ctx.get("intent_result") or {}
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"'بازنشسته میشوند' (no half-space) got wrong intent: {intent_res.get('intent_id')}"
    )


def test_normalize_text_splits_baz_neshaste():
    """normalize_text must collapse 'باز نشسته' → 'بازنشسته'."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser

    ip = IntentParser.__new__(IntentParser)
    result = ip.normalize_text("باز نشسته میشوند")
    assert "بازنشسته" in result, f"expected 'بازنشسته' in '{result}'"


# ---------------------------------------------------------------------------
# Phase 1.2 — Persian colloquial verb normalization
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    ip = IntentParser.__new__(IntentParser)
    return ip.normalize_text(text)


def test_normalize_joins_mi_with_next_verb():
    """'می شوند' (half-space already converted to space) → 'میشوند'."""
    assert "میشوند" in _norm("می شوند")


def test_normalize_joins_mi_from_halfspace():
    """'می‌شوند' (half-space U+200C) → 'میشوند' after join."""
    assert "میشوند" in _norm("می‌شوند")


def test_normalize_colloquial_mishon():
    assert "میشوند" in _norm("میشن")


def test_normalize_colloquial_mishe():
    assert "میشود" in _norm("میشه")


def test_normalize_colloquial_hastan():
    assert "هستند" in _norm("هستن")


def test_normalize_colloquial_mikonan():
    assert "میکنند" in _norm("میکنن")


def test_normalize_colloquial_daran():
    assert "دارند" in _norm("دارن")


def test_normalize_colloquial_bashn():
    assert "بشوند" in _norm("بشن")


@pytest.mark.asyncio
async def test_retirement_colloquial_mishon_routes_correctly(metadata_service):
    """'بازنشسته میشن' must route to near_retirement_analysis."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    result = await orchestrator.arun("چند نفر از کارمندان تا 5 سال آینده بازنشسته میشن؟")
    intent_res = result.context.get("intent_result") or {}
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"colloquial 'میشن' got wrong intent: {intent_res.get('intent_id')}"
    )


@pytest.mark.asyncio
async def test_retirement_colloquial_baz_neshaste_mishon(metadata_service):
    """'باز نشسته میشن' (split word + colloquial) must route to near_retirement_analysis."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    orchestrator = LLMOrchestrator(
        metadata_service=metadata_service,
        semantic_mapper=SemanticMapper(metadata_service=metadata_service),
        intent_parser=IntentParser(metadata_service=metadata_service),
        default_execute_sql=False,
    )
    result = await orchestrator.arun("چند نفر از کارمندان تا 5 سال آینده باز نشسته میشن؟")
    intent_res = result.context.get("intent_result") or {}
    assert intent_res.get("intent_id") == "near_retirement_analysis", (
        f"'باز نشسته میشن' got wrong intent: {intent_res.get('intent_id')}"
    )


# ---------------------------------------------------------------------------
# 1.4 — Trace completeness: sql_planner must expose coverage_status,
#        missing_filters, and model_called in its details dict.
# ---------------------------------------------------------------------------


def _sql_planner_trace(d: dict) -> dict:
    """Extract the sql_planner trace step from a full orchestrator result dict."""
    ctx = d.get("context") or {}
    traces = ctx.get("traces") or []
    for step in traces:
        if step.get("step") == "sql_planner":
            return step.get("details") or {}
    return {}


def test_trace_sql_planner_has_coverage_status(metadata_service):
    """sql_planner trace must include coverage_status from coverage_result."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "میانگین سن کارکنان چقدر است؟")
    details = _sql_planner_trace(d)
    assert "coverage_status" in details, (
        f"sql_planner trace must contain coverage_status. Got keys: {list(details.keys())}"
    )
    assert details["coverage_status"] in {"COMPLETE", "COVERAGE_INCOMPLETE", "PATCHED_BY_CONTROLLED_DYNAMIC"}, (
        f"Unexpected coverage_status value: {details['coverage_status']!r}"
    )


def test_trace_sql_planner_has_missing_filters(metadata_service):
    """sql_planner trace must include missing_filters (empty list when coverage is complete)."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "میانگین سن کارکنان چقدر است؟")
    details = _sql_planner_trace(d)
    assert "missing_filters" in details, (
        f"sql_planner trace must contain missing_filters. Got keys: {list(details.keys())}"
    )
    assert isinstance(details["missing_filters"], list), (
        f"missing_filters must be a list, got {type(details['missing_filters'])}"
    )


def test_trace_sql_planner_has_model_called(metadata_service):
    """sql_planner trace must include model_called (None when no LLM was invoked)."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "میانگین سن کارکنان چقدر است؟")
    details = _sql_planner_trace(d)
    assert "model_called" in details, (
        f"sql_planner trace must contain model_called. Got keys: {list(details.keys())}"
    )
    assert details["model_called"] is None, (
        f"model_called must be None when no LLM is configured, got {details['model_called']!r}"
    )


def test_trace_sql_planner_complete_coverage_has_empty_missing_filters(metadata_service):
    """When template covers all fields, missing_filters must be an empty list."""
    orch = LLMOrchestrator(metadata_service=metadata_service, default_execute_sql=False)
    d = _run(orch, "تعداد کل کارکنان چند نفر است؟")
    details = _sql_planner_trace(d)
    assert details.get("coverage_status") == "COMPLETE", (
        f"Expected COMPLETE coverage for simple headcount, got: {details.get('coverage_status')!r}"
    )
    assert details.get("missing_filters") == [], (
        f"Expected empty missing_filters, got: {details.get('missing_filters')!r}"
    )
