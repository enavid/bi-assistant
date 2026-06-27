"""Unit tests for the per-intent payload builder registry (Phase 3.1, target B).

Exercises steps/payload_builders.py: the registry shape and individual builders
run in isolation against a fresh PayloadState.
"""

from __future__ import annotations

import pytest

from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.payload_builders import (
    PAYLOAD_BUILDERS,
    PayloadContext,
    PayloadState,
    build_payload,
)


@pytest.fixture(scope="module")
def parser() -> IntentParser:
    return IntentParser()


def _ctx(parser, *, question="", best_intent_id, query_features=None):
    return parser._make_payload_context(
        question=parser.normalize_text(question),
        intent=parser._get_intent(parser.metadata, best_intent_id) or {},
        best_intent_id=best_intent_id,
        semantic_result={},
        query_features=query_features or {},
        current_shamsi_year=1404,
        service=parser.metadata,
    )


def _run(parser, **kw):
    ctx = _ctx(parser, **kw)
    state = PayloadState()
    build_payload(ctx, state)
    return state


# --------------------------------------------------------------------------
# Registry structure
# --------------------------------------------------------------------------


def test_registry_is_dict_of_callables():
    assert isinstance(PAYLOAD_BUILDERS, dict)
    assert PAYLOAD_BUILDERS
    assert all(callable(v) for v in PAYLOAD_BUILDERS.values())


def test_registry_covers_core_intents():
    expected = {
        "gender_percentage",
        "employee_count_by_age_filter",
        "employee_count_by_age_group",
        "average_age",
        "most_common_education",
        "least_common_education",
        "contractor_share",
        "employee_count_by_service_domain",
        "employee_count_by_department",
        "headcount_gap_by_department",
        "employee_count_by_service_years_filter",
        "employee_count_by_marital_status",
        "hiring_trend_annual",
    }
    assert expected <= set(PAYLOAD_BUILDERS)


def test_unknown_intent_has_no_builder():
    assert PAYLOAD_BUILDERS.get("totally_unknown_intent") is None


def test_make_payload_context_type(parser):
    assert isinstance(_ctx(parser, best_intent_id="average_age"), PayloadContext)


# --------------------------------------------------------------------------
# Individual builder behavior (fresh state)
# --------------------------------------------------------------------------


def test_age_group_sets_group_by(parser):
    state = _run(parser, best_intent_id="employee_count_by_age_group")
    assert "age_group_title" in state.group_by
    assert "age_group_title" in state.required_columns


def test_most_common_education_orders_desc(parser):
    state = _run(parser, best_intent_id="most_common_education")
    assert state.order_by == ["employee_count DESC"]
    assert state.group_by == ["education_title"]


def test_least_common_education_orders_asc(parser):
    state = _run(parser, best_intent_id="least_common_education")
    assert state.order_by == ["employee_count ASC"]


def test_contractor_share_adds_numerator_filter(parser):
    state = _run(parser, best_intent_id="contractor_share")
    flt = [f for f in state.filters if f.get("column") == "is_contractor"]
    assert flt and flt[0]["value"] is True and flt[0].get("scope") == "numerator"


def test_service_years_filter_maps_operator_to_param(parser):
    qf = {"service_years_filter": {"column": "service_years", "operator": ">=", "value": 10}}
    state = _run(parser, best_intent_id="employee_count_by_service_years_filter", query_features=qf)
    assert state.params.get("service_years_min") == 10


def test_headcount_gap_groups_by_department(parser):
    state = _run(parser, best_intent_id="headcount_gap_by_department")
    assert state.group_by == ["department_id", "department_name"]
    assert "department_approved_headcount" in state.required_columns


def test_gender_percentage_extracts_value(parser):
    state = _run(parser, question="درصد زنان چقدر است؟", best_intent_id="gender_percentage")
    assert state.params.get("gender_value") == "زن"
    assert any(f.get("column") == "gender" for f in state.filters)


# --------------------------------------------------------------------------
# End-to-end through the public method (post-processing intact)
# --------------------------------------------------------------------------


def test_method_applies_superlative_limit(parser):
    payload = parser._extract_structured_payload(
        question=parser.normalize_text("پرجمعیت‌ترین دپارتمان کدام است؟"),
        intent=parser._get_intent(parser.metadata, "employee_count_by_department") or {},
        best_intent_id="employee_count_by_department",
        semantic_result={},
        query_features={"asks_most": True},
        current_shamsi_year=1404,
        service=parser.metadata,
    )
    assert payload["params"].get("result_limit") == 1
    # Default active filter is always injected first.
    assert payload["filters"][0]["column"] == "is_active"
