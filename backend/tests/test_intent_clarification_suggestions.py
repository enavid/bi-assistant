from __future__ import annotations

import time

from app.hr_analytics.adapters.response_builder import ResponseBuilder
from app.hr_analytics.use_cases.steps.intent_parser import IntentCandidate, IntentParser


def _candidate(intent_id: str, score: float) -> IntentCandidate:
    return IntentCandidate(intent_id=intent_id, score=score, reasons=[f"reason:{intent_id}"])


# ---------------------------------------------------------------------------
# IntentParser._build_interpretation_suggestions
# ---------------------------------------------------------------------------


def test_suggestions_enriches_sql_candidates_with_titles(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    candidates = [
        _candidate("total_employee_count", 30.0),
        _candidate("employee_count_by_gender", 22.0),
    ]

    result = parser._build_interpretation_suggestions(candidates, metadata_service)

    assert [s["intent_id"] for s in result] == [
        "total_employee_count",
        "employee_count_by_gender",
    ]
    first = result[0]
    # Enriched with a human-readable Farsi title (not just the raw intent id).
    assert first["title_fa"]
    assert first["title_fa"] != "total_employee_count"
    assert first["template_id"] == "TPL_TOTAL_EMPLOYEE_COUNT"
    assert first["score"] == 30.0


def test_suggestions_skip_non_sql_unknown_and_ambiguous(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    candidates = [
        _candidate("ambiguous_hr_question", 99.0),  # placeholder intent -> skip
        _candidate("city_level_analysis", 40.0),  # GAP route -> not actionable -> skip
        _candidate("__no_such_intent__", 35.0),  # unknown id -> skip
        _candidate("average_age", 20.0),  # SQL route -> keep
    ]

    result = parser._build_interpretation_suggestions(candidates, metadata_service)

    assert [s["intent_id"] for s in result] == ["average_age"]


def test_suggestions_respects_limit(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    candidates = [
        _candidate("total_employee_count", 30.0),
        _candidate("employee_count_by_gender", 28.0),
        _candidate("average_age", 26.0),
        _candidate("median_age", 24.0),
        _candidate("max_age", 22.0),
    ]

    result = parser._build_interpretation_suggestions(candidates, metadata_service, limit=3)

    assert len(result) == 3
    assert [s["intent_id"] for s in result] == [
        "total_employee_count",
        "employee_count_by_gender",
        "average_age",
    ]


def test_suggestions_dedupes_repeated_intent(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    candidates = [
        _candidate("average_age", 30.0),
        _candidate("average_age", 10.0),  # duplicate -> collapsed
        _candidate("median_age", 9.0),
    ]

    result = parser._build_interpretation_suggestions(candidates, metadata_service)

    assert [s["intent_id"] for s in result] == ["average_age", "median_age"]
    # The higher-scoring occurrence wins.
    assert result[0]["score"] == 30.0


def test_suggestions_empty_when_no_actionable_candidates(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    candidates = [
        _candidate("city_level_analysis", 40.0),  # GAP
        _candidate("__no_such__", 5.0),  # unknown
    ]

    assert parser._build_interpretation_suggestions(candidates, metadata_service) == []


def test_suggestions_handles_empty_candidate_list(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    assert parser._build_interpretation_suggestions([], metadata_service) == []


# ---------------------------------------------------------------------------
# IntentParser._terminal_result payload contract
# ---------------------------------------------------------------------------


def test_terminal_result_carries_suggested_interpretations(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)
    suggestions = [
        {
            "intent_id": "average_age",
            "title_fa": "میانگین سن کارکنان",
            "template_id": "TPL_AVERAGE_AGE",
            "score": 1.0,
        }
    ]

    payload = parser._terminal_result(
        intent_id="ambiguous_hr_question",
        route="NEEDS_CLARIFICATION",
        status="NEEDS_CLARIFICATION",
        question="q",
        normalized_question="q",
        started=time.perf_counter(),
        reason="ambiguous",
        suggested_interpretations=suggestions,
    )

    assert payload["suggested_interpretations"] == suggestions


def test_terminal_result_defaults_to_empty_suggestions(metadata_service):
    parser = IntentParser(metadata_service=metadata_service)

    payload = parser._terminal_result(
        intent_id="ambiguous_hr_question",
        route="NEEDS_CLARIFICATION",
        status="NEEDS_CLARIFICATION",
        question="",
        normalized_question="",
        started=time.perf_counter(),
        reason="empty",
    )

    assert payload["suggested_interpretations"] == []


# ---------------------------------------------------------------------------
# ResponseBuilder renders the suggestions into user-facing Farsi notes
# ---------------------------------------------------------------------------


def test_clarification_response_lists_interpretation_suggestions(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "route_result": {"route": "NEEDS_CLARIFICATION", "status": "NEEDS_CLARIFICATION"},
        "intent_result": {
            "route": "NEEDS_CLARIFICATION",
            "status": "NEEDS_CLARIFICATION",
            "suggested_interpretations": [
                {
                    "intent_id": "employee_count_by_department",
                    "title_fa": "تعداد کارکنان به تفکیک واحد",
                },
                {
                    "intent_id": "employee_count_by_service_domain",
                    "title_fa": "تعداد کارکنان به تفکیک حوزه",
                },
            ],
        },
        "query_result": {},
    }

    result = builder.build(
        context=context,
        status_payload={"status": "NEEDS_CLARIFICATION", "route": "NEEDS_CLARIFICATION"},
    )

    assert result["status"] == "NEEDS_CLARIFICATION"
    note_blob = " ".join(result["notes_fa"])
    assert "تعداد کارکنان به تفکیک واحد" in note_blob
    assert "تعداد کارکنان به تفکیک حوزه" in note_blob


def test_clarification_response_without_suggestions_has_no_interpretation_note(metadata_service):
    builder = ResponseBuilder(metadata_service=metadata_service)
    context = {
        "route_result": {"route": "NEEDS_CLARIFICATION", "status": "NEEDS_CLARIFICATION"},
        "intent_result": {"route": "NEEDS_CLARIFICATION", "status": "NEEDS_CLARIFICATION"},
        "query_result": {},
    }

    result = builder.build(
        context=context,
        status_payload={"status": "NEEDS_CLARIFICATION", "route": "NEEDS_CLARIFICATION"},
    )

    assert all("تفسیرهای محتمل" not in note for note in result["notes_fa"])
