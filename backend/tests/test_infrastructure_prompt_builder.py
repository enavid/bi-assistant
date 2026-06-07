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
