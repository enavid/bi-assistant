"""Unit tests for the routing eval helper functions.

These tests verify _mismatches() itself — not the full orchestrator pipeline.
They must pass without any external services.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the eval module importable without running the parametrize-time fixtures.
_EVAL_DIR = Path(__file__).parent
sys.path.insert(0, str(_EVAL_DIR))

from test_routing_eval import _mismatches  # noqa: E402

# ---------------------------------------------------------------------------
# Existing checks — must not regress
# ---------------------------------------------------------------------------


def test_mismatches_no_errors_when_all_match():
    payload = {"route": "SQL", "status": "OK", "detected_intent": "count_employees"}
    expect = {"route": "SQL", "status": "OK", "intent": "count_employees"}
    assert _mismatches(payload, expect) == []


def test_mismatches_detects_wrong_route():
    payload = {"route": "GAP", "status": "DATA_GAP"}
    expect = {"route": "SQL", "status": "OK"}
    errs = _mismatches(payload, expect)
    assert any("route" in e for e in errs)


def test_mismatches_detects_wrong_status():
    payload = {"route": "SQL", "status": "SQL_VALIDATION_FAILED"}
    expect = {"route": "SQL", "status": "OK"}
    errs = _mismatches(payload, expect)
    assert any("status" in e for e in errs)


# ---------------------------------------------------------------------------
# 1.2 — must_include_sql / must_not_include_sql checks
# ---------------------------------------------------------------------------


def test_must_include_sql_passes_when_term_present():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT department_name, COUNT(*) FROM employees GROUP BY department_name",
    }
    expect = {"route": "SQL", "must_include_sql": ["department_name", "GROUP BY"]}
    assert _mismatches(payload, expect) == []


def test_must_include_sql_fails_when_term_missing():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT COUNT(*) FROM employees",
    }
    expect = {"route": "SQL", "must_include_sql": ["department_name"]}
    errs = _mismatches(payload, expect)
    assert len(errs) == 1
    assert "department_name" in errs[0]
    assert "must_include_sql" in errs[0]


def test_must_include_sql_fails_when_multiple_terms_missing():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT COUNT(*) FROM employees",
    }
    expect = {"route": "SQL", "must_include_sql": ["department_name", "gender"]}
    errs = _mismatches(payload, expect)
    assert len(errs) == 2


def test_must_include_sql_skipped_when_no_sql_in_payload():
    payload = {"route": "GAP", "status": "DATA_GAP", "generated_sql": None}
    expect = {"route": "GAP", "must_include_sql": ["department_name"]}
    errs = _mismatches(payload, expect)
    # should report an error because SQL was expected but absent
    assert any("must_include_sql" in e for e in errs)


def test_must_not_include_sql_passes_when_term_absent():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT COUNT(*) FROM employees WHERE is_active = TRUE",
    }
    expect = {"route": "SQL", "must_not_include_sql": ["personal_id", "national_id"]}
    assert _mismatches(payload, expect) == []


def test_must_not_include_sql_fails_when_forbidden_term_present():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT national_id, name FROM employees",
    }
    expect = {"route": "SQL", "must_not_include_sql": ["national_id"]}
    errs = _mismatches(payload, expect)
    assert len(errs) == 1
    assert "national_id" in errs[0]
    assert "must_not_include_sql" in errs[0]


def test_must_not_include_sql_skipped_when_no_sql_in_payload():
    payload = {"route": "REJECT", "status": "ACCESS_DENIED", "generated_sql": None}
    expect = {"route": "REJECT", "must_not_include_sql": ["national_id"]}
    # REJECT has no SQL — must_not constraint trivially satisfied (nothing to check)
    assert _mismatches(payload, expect) == []


def test_both_constraints_checked_independently():
    payload = {
        "route": "SQL",
        "status": "OK",
        "generated_sql": "SELECT gender, COUNT(*) FROM employees GROUP BY gender",
    }
    expect = {
        "route": "SQL",
        "must_include_sql": ["gender", "GROUP BY"],
        "must_not_include_sql": ["national_id"],
    }
    assert _mismatches(payload, expect) == []
