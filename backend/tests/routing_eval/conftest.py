"""
Routing eval conftest: collects per-case results and prints a full report
at the end of the session, regardless of pass/fail.
"""
from __future__ import annotations

from typing import Any

import pytest

_RESULTS: list[dict[str, Any]] = []

_CATEGORY_ORDER = [
    "access_denied",
    "out_of_scope",
    "data_gap",
    "analytical_gap",
    "sql",
]

_CATEGORY_LABEL = {
    "access_denied":  "ACCESS DENIED",
    "out_of_scope":   "OUT OF SCOPE",
    "data_gap":       "DATA GAP",
    "analytical_gap": "ANALYTICAL GAP",
    "sql":            "SQL",
}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Any:  # type: ignore[type-arg]
    outcome = yield
    if call.when != "call":
        return

    report = outcome.get_result()
    case: dict[str, Any] | None = None
    for arg in (item.callspec.params.values() if hasattr(item, "callspec") else []):
        if isinstance(arg, dict) and "question" in arg:
            case = arg
            break

    if case is None:
        return

    payload: dict[str, Any] = getattr(item, "_eval_payload", {})
    _RESULTS.append(
        {
            "id": case.get("id", "?"),
            "question": case.get("question", ""),
            "category": case.get("category", "unknown"),
            "expect": case.get("expect", {}),
            "got_route": payload.get("route", "—"),
            "got_status": payload.get("status", "—"),
            "got_intent": payload.get("detected_intent") or payload.get("intent") or "—",
            "passed": report.passed,
        }
    )


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    if not _RESULTS:
        return

    tr = terminalreporter

    col_q = 50
    col_r = 18
    col_s = 18
    col_i = 30

    def sep(char: str = "─", width: int = col_q + col_r + col_s + col_i + 10) -> str:
        return "  " + char * width

    tr.write_sep("=", "Routing Evaluation Results", bold=True)
    tr.write_line("")

    by_cat: dict[str, list[dict]] = {}
    for r in _RESULTS:
        by_cat.setdefault(r["category"], []).append(r)

    header = (
        f"  {'Question':<{col_q}}  {'Route':<{col_r}}  {'Status':<{col_s}}  {'Intent'}"
    )

    for cat in _CATEGORY_ORDER + [c for c in by_cat if c not in _CATEGORY_ORDER]:
        rows = by_cat.get(cat, [])
        if not rows:
            continue

        label = _CATEGORY_LABEL.get(cat, cat.upper())
        passed = sum(1 for r in rows if r["passed"])
        total = len(rows)

        tr.write_line("")
        if passed == total:
            tr.write_line(f"  ▌ {label}  [{passed}/{total} ✓]", green=True, bold=True)
        else:
            tr.write_line(f"  ▌ {label}  [{passed}/{total} — {total-passed} FAILED]", red=True, bold=True)

        tr.write_line(sep())
        tr.write_line(header)
        tr.write_line(sep())

        for r in rows:
            q = r["question"]
            if len(q) > col_q:
                q = q[: col_q - 1] + "…"

            got_r = str(r["got_route"])
            got_s = str(r["got_status"])
            got_i = str(r["got_intent"])
            exp = r["expect"]

            mark = "✓" if r["passed"] else "✗"
            line = f"  {mark} {q:<{col_q}}  {got_r:<{col_r}}  {got_s:<{col_s}}  {got_i}"

            if r["passed"]:
                tr.write_line(line, green=True)
            else:
                tr.write_line(line, red=True)
                exp_parts = []
                if "route" in exp and got_r != exp["route"]:
                    exp_parts.append(f"route → {exp['route']}")
                if "status" in exp and got_s != exp["status"]:
                    exp_parts.append(f"status → {exp['status']}")
                if "intent" in exp and got_i != exp.get("intent"):
                    exp_parts.append(f"intent → {exp.get('intent')}")
                if exp_parts:
                    tr.write_line(f"      expected: {',  '.join(exp_parts)}", yellow=True)

        tr.write_line(sep())

    tr.write_line("")
    total_all = len(_RESULTS)
    passed_all = sum(1 for r in _RESULTS if r["passed"])
    failed_all = total_all - passed_all

    if failed_all == 0:
        tr.write_line(f"  All {total_all} routing cases passed.\n", bold=True, green=True)
    else:
        tr.write_line(f"  {passed_all}/{total_all} passed,  {failed_all} failed.\n", bold=True, red=True)
