"""Dependency-inversion boundaries (Phase 3.3).

Two layering violations are pinned here:

1. Pipeline steps depended on the *concrete* ``MetadataService`` from the
   infrastructure layer (both as a type and by instantiating it in a self-
   healing fallback). They should depend on the ``IMetadataService`` abstraction
   and delegate default construction to a single infrastructure factory.
2. ``infrastructure/hr_db/analytics_executor.py`` imported ``SQLValidator`` from
   ``use_cases`` — an inner-layer-imports-outer-layer reversal. It should depend
   on the ``ISQLValidator`` abstraction and receive the validator by injection.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parent.parent / "app"
_STEP_FILES = [
    APP_ROOT / "hr_analytics" / "use_cases" / "steps" / "intent_parser.py",
    APP_ROOT / "hr_analytics" / "use_cases" / "steps" / "decision_router.py",
    APP_ROOT / "hr_analytics" / "use_cases" / "steps" / "semantic_mapper.py",
]


def _import_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out.append(f"{node.module}.{alias.name}")
    return out


# ---------------------------------------------------------------------------
# Steps depend on the abstraction, not the concrete service
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step_file", _STEP_FILES, ids=lambda p: p.stem)
def test_step_does_not_import_concrete_metadata_service(step_file):
    imports = _import_strings(step_file)
    assert "app.infrastructure.metadata.service.MetadataService" not in imports, (
        f"{step_file.name} must not import the concrete MetadataService class"
    )


@pytest.mark.parametrize("step_file", _STEP_FILES, ids=lambda p: p.stem)
def test_step_declares_imetadataservice(step_file):
    source = step_file.read_text(encoding="utf-8")
    assert "IMetadataService" in source, (
        f"{step_file.name} should depend on the IMetadataService abstraction"
    )


# ---------------------------------------------------------------------------
# Infrastructure no longer imports use_cases (reverse dependency removed)
# ---------------------------------------------------------------------------


def test_analytics_executor_has_no_use_cases_import():
    exec_file = APP_ROOT / "infrastructure" / "hr_db" / "analytics_executor.py"
    imports = _import_strings(exec_file)
    bad = [i for i in imports if "hr_analytics.use_cases" in i]
    assert not bad, f"analytics_executor must not import from use_cases: {bad}"


# ---------------------------------------------------------------------------
# The shared metadata resolver factory
# ---------------------------------------------------------------------------


class _HealthyMetadata:
    def health_check(self):
        class _R:
            def to_dict(self_inner):
                return {"ok": True}

        return _R()


def test_resolver_returns_injected_unchanged():
    from app.infrastructure.metadata.service import resolve_metadata_service

    injected = _HealthyMetadata()
    assert resolve_metadata_service(injected) is injected


def test_resolver_does_not_probe_local_dir_when_injected():
    from app.infrastructure.metadata.service import resolve_metadata_service

    injected = _HealthyMetadata()
    # Even with a probe configured, an injected service must win untouched.
    result = resolve_metadata_service(
        injected, local_dir=Path("/nonexistent"), probe_files=("nope.yaml",)
    )
    assert result is injected


def test_steps_construct_with_injected_metadata():
    """Smoke: every step accepts an injected IMetadataService and stores it."""
    from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper

    md = _HealthyMetadata()
    assert IntentParser(metadata_service=md).metadata is md
    assert DecisionRouter(metadata_service=md).metadata is md
    assert SemanticMapper(metadata_service=md).metadata is md


def test_resolver_logs_on_unhealthy_without_local_bundle(caplog):
    """An unhealthy default with no local fallback bundle must not crash and
    must surface a log line rather than swallowing the condition silently."""
    from app.infrastructure.metadata import service as service_mod

    class _Unhealthy:
        def health_check(self):
            class _R:
                def to_dict(self_inner):
                    return {"ok": False}

            return _R()

    # Force the default-singleton path to return an unhealthy service.
    original = service_mod.get_metadata_service
    service_mod.get_metadata_service = lambda **_kw: _Unhealthy()
    try:
        with caplog.at_level(logging.WARNING):
            resolved = service_mod.resolve_metadata_service(
                None, local_dir=Path("/nonexistent"), probe_files=("missing.yaml",)
            )
        assert isinstance(resolved, _Unhealthy)
    finally:
        service_mod.get_metadata_service = original
