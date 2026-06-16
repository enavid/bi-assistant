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

    sql = payload.get("generated_sql") or ""

    if "must_include_sql" in expect:
        for term in expect["must_include_sql"]:
            if not sql:
                errors.append(f"must_include_sql  term={term!r}  but generated_sql is empty/absent")
            elif term.lower() not in sql.lower():
                errors.append(f"must_include_sql  term={term!r}  not found in generated SQL")

    if "must_not_include_sql" in expect:
        for term in expect["must_not_include_sql"]:
            if sql and term.lower() in sql.lower():
                errors.append(f"must_not_include_sql  term={term!r}  found in generated SQL")

    if "expected_filters" in expect:
        for col in expect["expected_filters"] or []:
            if not sql:
                errors.append(f"expected_filters  col={col!r}  but generated_sql is empty/absent")
            elif col.lower() not in sql.lower():
                errors.append(f"expected_filters  col={col!r}  not found in generated SQL")

    if "expected_metric" in expect:
        metric = expect["expected_metric"]
        if metric:
            if not sql:
                errors.append(
                    f"expected_metric  metric={metric!r}  but generated_sql is empty/absent"
                )
            elif metric.lower() not in sql.lower():
                errors.append(f"expected_metric  metric={metric!r}  not found in generated SQL")

    if "expected_group_by" in expect:
        cols = expect["expected_group_by"] or []
        if cols:
            if not sql:
                errors.append(
                    f"expected_group_by  cols={cols!r}  but generated_sql is empty/absent"
                )
            else:
                if "group by" not in sql.lower():
                    errors.append(
                        f"expected_group_by  'GROUP BY' not found in generated SQL (cols={cols!r})"
                    )
                for col in cols:
                    if col.lower() not in sql.lower():
                        errors.append(f"expected_group_by  col={col!r}  not found in generated SQL")

    return errors


def _needs_review(case: dict, expect: dict) -> bool:
    """True when an SQL case has no structured semantic expectations yet."""
    if case.get("category") != "sql":
        return False
    return not any(
        k in expect for k in ("expected_filters", "expected_metric", "expected_group_by")
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_routing(request: pytest.FixtureRequest, orchestrator: Any, case: dict[str, Any]) -> None:
    question = case["question"]
    expect = case["expect"]
    category = case.get("category", "unknown")
    description = case.get("description", "")

    if case.get("xfail"):
        pytest.xfail(f"known gap: {case.get('xfail_reason', 'system routes incorrectly')}")

    payload = _run(orchestrator, question)
    payload = {**payload, "needs_review": _needs_review(case, expect)}

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
