from __future__ import annotations

from app.infrastructure.llm.prompt_builder import PromptBuilder, SQLFallbackPrompt


def _make_context(**kwargs):
    class Ctx:
        pass

    ctx = Ctx()
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


def test_prompt_builder_returns_sql_fallback_prompt(metadata_service):
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "total_employee_count", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    result = builder.build_sql_fallback_prompt(question="total employees", context=ctx)
    assert isinstance(result, SQLFallbackPrompt)
    assert "hr_mvp.vw_hr_employee_analytics" in result.prompt
    assert result.schema_context


def test_prompt_builder_safe_modular_context_structure(metadata_service):
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "total_employee_count", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    modular = builder.build_safe_modular_context(ctx)
    assert "route" in modular
    assert "safety_constraints" in modular
    assert len(modular["safety_constraints"]) >= 3


def test_prompt_builder_without_metadata():
    builder = PromptBuilder(metadata_service=None)
    ctx = _make_context(
        intent_result={},
        semantic_result={},
        route_result={},
        validation_result={},
    )
    result = builder.build_sql_fallback_prompt(question="count", context=ctx)
    assert isinstance(result, SQLFallbackPrompt)


# ---------------------------------------------------------------------------
# BUG-002 — suggested_sql must appear in prompt when provided
# ---------------------------------------------------------------------------


def test_prompt_builder_includes_suggested_sql_in_prompt(metadata_service):
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "total_employee_count", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    suggested = "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
    result = builder.build_sql_fallback_prompt(
        question="تعداد کارکنان؟",
        context=ctx,
        suggested_sql=suggested,
    )
    assert "SELECT COUNT" in result.prompt


def test_prompt_builder_without_suggested_sql_still_works(metadata_service):
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "total_employee_count", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    result = builder.build_sql_fallback_prompt(question="تعداد کارکنان؟", context=ctx)
    assert isinstance(result, SQLFallbackPrompt)
    assert "hr_mvp.vw_hr_employee_analytics" in result.prompt


# ---------------------------------------------------------------------------
# Phase 4.3 — focused_columns reduces prompt length
# ---------------------------------------------------------------------------


def test_prompt_with_focused_columns_shorter_than_full_schema_prompt(metadata_service):
    """Prompt generated with focused_columns must be shorter than without."""
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={
            "intent": "total_employee_count",
            "route": "SQL",
            "required_columns": ["employee_id"],
            "filters": [],
            "group_by": [],
        },
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    full_result = builder.build_sql_fallback_prompt(question="تعداد کارکنان؟", context=ctx)
    focused_result = builder.build_sql_fallback_prompt(
        question="تعداد کارکنان؟",
        context=ctx,
        focused_columns=["employee_id", "is_active"],
    )
    assert len(focused_result.prompt) < len(full_result.prompt), (
        f"Focused prompt ({len(focused_result.prompt)}) should be shorter than full ({len(full_result.prompt)})"
    )


def test_prompt_focused_columns_still_has_view_name(metadata_service):
    """Focused prompt still contains the view name and base structure."""
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "count_by_gender", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    result = builder.build_sql_fallback_prompt(
        question="تعداد کارکنان بر اساس جنسیت؟",
        context=ctx,
        focused_columns=["employee_id", "is_active", "gender"],
    )
    assert "hr_mvp.vw_hr_employee_analytics" in result.prompt
    assert "gender" in result.prompt


def test_prompt_focused_columns_under_6000_chars(metadata_service):
    """A typical 5-column focused prompt must be under 6000 characters."""
    builder = PromptBuilder(metadata_service=metadata_service)
    ctx = _make_context(
        intent_result={"intent": "count_by_department", "route": "SQL"},
        semantic_result={},
        route_result={"route": "SQL"},
        validation_result={},
    )
    result = builder.build_sql_fallback_prompt(
        question="تعداد کارکنان به تفکیک دپارتمان؟",
        context=ctx,
        focused_columns=["employee_id", "is_active", "department_name", "gender", "age"],
    )
    assert len(result.prompt) < 6000, (
        f"Focused prompt should be under 6000 chars, got {len(result.prompt)}"
    )
