"""
Routing Evaluation — Golden Test Suite
=======================================
Loads cases from cases.yaml and verifies that each question is routed to
the correct route/status/intent by the orchestrator.

Run via:  make eval
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

CASES_FILE = Path(__file__).parent / "cases.yaml"


# ---------------------------------------------------------------------------
# Load and parametrize
# ---------------------------------------------------------------------------


def _load_cases() -> list[dict[str, Any]]:
    with open(CASES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["cases"]


_CASES = _load_cases()
_IDS = [c["id"] for c in _CASES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(orchestrator: Any, question: str) -> dict[str, Any]:
    result = orchestrator.run(question)
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def _mismatches(payload: dict, expect: dict) -> list[str]:
    errors: list[str] = []

    if "route" in expect:
        got = payload.get("route")
        if got != expect["route"]:
            errors.append(f"route      expected={expect['route']!r:20s}  got={got!r}")

    if "status" in expect:
        got = payload.get("status")
        if got != expect["status"]:
            errors.append(f"status     expected={expect['status']!r:20s}  got={got!r}")

    if "intent" in expect:
        got = payload.get("detected_intent") or payload.get("intent")
        if got != expect["intent"]:
            errors.append(f"intent     expected={expect['intent']!r:20s}  got={got!r}")

    return errors


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_routing(request: pytest.FixtureRequest, orchestrator: Any, case: dict[str, Any]) -> None:
    question = case["question"]
    expect = case["expect"]
    category = case.get("category", "unknown")
    description = case.get("description", "")

    payload = _run(orchestrator, question)

    # Expose payload to conftest hook for the results table.
    request.node._eval_payload = payload  # type: ignore[attr-defined]

    errors = _mismatches(payload, expect)

    if errors:
        lines = [
            "",
            f"  Question  : {question}",
            f"  Category  : {category}",
            f"  Desc      : {description}",
            "  ─────────────────────────────────────────────────",
        ]
        lines += [f"  MISMATCH  : {e}" for e in errors]
        lines += [
            "  ─────────────────────────────────────────────────",
            f"  Full route : {payload.get('route')}  status={payload.get('status')}  intent={payload.get('detected_intent')}",
        ]
        pytest.fail("\n".join(lines))
