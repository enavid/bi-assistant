"""Audit-integrity and fail-loud logging tests (Phase 1.5 + 1.6).

For a financial-grade system, a privacy parameter falling back to a default,
a failed write to the gap audit ledger, and a hardening statement that did not
take effect must all be observable in the logs — never silently swallowed.
The gap registry must also stay internally consistent: the persisted count
must equal the in-memory count, with exactly one line per gap.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
from app.hr_analytics.use_cases.steps.gap_service import GapService

# ---------------------------------------------------------------------------
# 1.5 — privacy parameter fallback must be logged (compliance)
# ---------------------------------------------------------------------------


class _RaisingMetadata:
    """A metadata service whose privacy lookup fails."""

    def get_min_group_size(self, default: int = 5) -> int:
        raise RuntimeError("metadata backend unavailable")


def test_min_group_size_fallback_is_logged(caplog):
    # Passing a truthy metadata_service skips the constructor's autoload path.
    router = DecisionRouter(metadata_service=object())
    with caplog.at_level(logging.WARNING):
        hints = router._build_policy_hints(
            user_role="demo_user", intent_result={}, service=_RaisingMetadata()
        )

    # The policy still fails safe to the strictest default.
    assert hints["minimum_group_size"] == 5
    # ...but the fallback must leave an audit trail, not vanish silently.
    assert any(
        "min_group_size" in r.getMessage().lower() or "group size" in r.getMessage().lower()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_min_group_size_uses_service_value_when_available():
    class _GoodMetadata:
        def get_min_group_size(self, default: int = 5) -> int:
            return 8

    router = DecisionRouter(metadata_service=object())
    hints = router._build_policy_hints(
        user_role="demo_user", intent_result={}, service=_GoodMetadata()
    )
    assert hints["minimum_group_size"] == 8


# ---------------------------------------------------------------------------
# 1.5 — failed write to the gap audit ledger must be logged
# ---------------------------------------------------------------------------


def test_gap_registry_write_failure_is_logged(tmp_path, caplog, monkeypatch):
    service = GapService(registry_path=tmp_path / "gap_registry.jsonl")

    def _boom(_record):
        raise OSError("disk full")

    monkeypatch.setattr(service, "_save_record", _boom)

    with caplog.at_level(logging.ERROR):
        result = service.create_gap(
            question="تعداد کارکنان شهر تهران چند نفر است؟",
            normalized_question="تعداد کارکنان شهر تهران",
            intent="city_level_analysis",
            reason="not available",
            created_by="test",
        )

    assert result.get("gap_logged") is False
    assert any("gap" in r.getMessage().lower() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


# ---------------------------------------------------------------------------
# 1.6 — gap registry must rewrite in place (persisted == in-memory)
# ---------------------------------------------------------------------------


def _gap_payload() -> dict:
    return {
        "question": "تعداد کارکنان شهر تهران چند نفر است؟",
        "normalized_question": "تعداد کارکنان شهر تهران",
        "intent": "city_level_analysis",
        "reason": "City-level data is not available.",
        "created_by": "test",
    }


def _read_lines(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_duplicate_gap_does_not_append_redundant_line(tmp_path):
    registry = tmp_path / "gap_registry.jsonl"
    service = GapService(registry_path=registry)

    service.create_gap(**_gap_payload())
    service.create_gap(**_gap_payload())  # same gap_id -> duplicate

    lines = _read_lines(registry)
    # Exactly one ledger line for the single distinct gap.
    assert len(lines) == 1, lines
    # ...and the persisted occurrence count reflects both sightings.
    assert lines[0]["occurrence_count"] == 2


def test_persisted_count_matches_in_memory_after_reload(tmp_path):
    registry = tmp_path / "gap_registry.jsonl"

    first = GapService(registry_path=registry)
    first.create_gap(**_gap_payload())
    first.create_gap(**_gap_payload())
    first.create_gap(**_gap_payload())

    lines = _read_lines(registry)
    assert len(lines) == 1
    assert lines[0]["occurrence_count"] == 3

    # A fresh service that reloads the ledger must see the same single record.
    second = GapService(registry_path=registry)
    second.create_gap(**_gap_payload())
    lines_after = _read_lines(registry)
    assert len(lines_after) == 1
    assert lines_after[0]["occurrence_count"] == 4


@pytest.mark.parametrize("persist", [True, False])
def test_create_gap_is_stable_regardless_of_persistence(tmp_path, persist):
    service = GapService(registry_path=tmp_path / "g.jsonl", persist_to_jsonl=persist)
    result = service.create_gap(**_gap_payload())
    assert result.get("route") == "GAP"
