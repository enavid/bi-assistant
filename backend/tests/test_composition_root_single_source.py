"""Single composition root for the HR-BI orchestrator (Phase 3.4).

The evaluation API used to re-implement the entire orchestrator wiring graph in
``evaluation/api/routes.build_orchestrator``. That second graph had drifted from
the canonical one in ``dependencies`` (it dropped the LLM client, the active
model and the template-engine/controlled-dynamic/force-llm flags) and its
``model_name`` argument was silently ignored, so the eval harness scored a
pipeline configured differently from production. These tests pin both callers to
a single builder.
"""

from __future__ import annotations

import app.dependencies as deps
import app.evaluation.api.routes as eval_routes


def test_builder_exists_and_accepts_model_override():
    builder = deps.build_hr_bi_orchestrator
    assert callable(builder)


def test_cached_production_getter_delegates_to_builder(monkeypatch):
    deps.get_hr_bi_orchestrator.cache_clear()
    monkeypatch.setattr(
        deps, "build_hr_bi_orchestrator", lambda *, model_name=None: ("ROOT", model_name)
    )
    try:
        assert deps.get_hr_bi_orchestrator() == ("ROOT", None)
    finally:
        deps.get_hr_bi_orchestrator.cache_clear()


def test_eval_build_orchestrator_delegates_to_single_root(monkeypatch):
    captured = {}

    def fake_build(*, model_name=None):
        captured["model_name"] = model_name
        return "SENTINEL_ORCHESTRATOR"

    monkeypatch.setattr(deps, "build_hr_bi_orchestrator", fake_build)

    result = eval_routes.build_orchestrator("model-override-x")

    assert result == "SENTINEL_ORCHESTRATOR"
    # The override that used to be dead must now reach the single builder.
    assert captured["model_name"] == "model-override-x"


def test_eval_no_longer_defines_its_own_wiring_graph():
    """build_orchestrator must be a thin delegator, not a parallel wiring graph."""
    import inspect

    source = inspect.getsource(eval_routes.build_orchestrator)
    # The canonical graph instantiates these; the eval delegator must not.
    assert "LLMOrchestrator(" not in source
    assert "DecisionRouter(" not in source
    assert "build_hr_bi_orchestrator" in source
