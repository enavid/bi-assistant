"""Unit tests for the manual-intent rule registry (Phase 3.1, target A).

These exercise the extracted steps/intent_rules.py registry directly: structural
invariants, and the precedence/guard logic of individual rules driven by
synthetic feature dicts (independent of the feature detector).
"""

from __future__ import annotations

import numbers

import pytest

from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.intent_rules import (
    MANUAL_INTENT_RULES,
    RuleContext,
    evaluate,
)


@pytest.fixture(scope="module")
def parser() -> IntentParser:
    return IntentParser()


def _eval(parser: IntentParser, question: str, features: dict) -> list[tuple]:
    ctx = parser._make_rule_context(parser.normalize_text(question), features, parser.metadata)
    return evaluate(ctx)


# --------------------------------------------------------------------------
# Structural invariants
# --------------------------------------------------------------------------


def test_registry_is_nonempty_tuple_of_callables():
    assert isinstance(MANUAL_INTENT_RULES, tuple)
    assert len(MANUAL_INTENT_RULES) >= 15
    assert all(callable(rule) for rule in MANUAL_INTENT_RULES)


def test_every_rule_returns_wellformed_tuples(parser):
    ctx = parser._make_rule_context("میانگین سن کارکنان", {"explicit_age": True}, parser.metadata)
    for rule in MANUAL_INTENT_RULES:
        out = rule(ctx)
        assert isinstance(out, list)
        for item in out:
            assert isinstance(item, tuple) and len(item) == 3
            intent_id, score, reason = item
            assert isinstance(intent_id, str) and intent_id
            assert isinstance(score, numbers.Number) and score > 0
            assert isinstance(reason, str) and reason


def test_make_rule_context_type(parser):
    ctx = parser._make_rule_context("x", {}, parser.metadata)
    assert isinstance(ctx, RuleContext)


def test_empty_question_does_not_crash(parser):
    assert isinstance(_eval(parser, "", {}), list)


# --------------------------------------------------------------------------
# Feature-driven precedence / guard logic (synthetic features)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "features,expected",
    [
        (
            {"asks_individual": True},
            ("individual_employee_info", 100, "sensitive_or_individual_request"),
        ),
        ({"explicit_city": True}, ("city_level_analysis", 90, "city_level_data_gap")),
        (
            {"explicit_gender": True, "explicit_department": True},
            ("employee_count_by_department_gender", 88, "department_gender_2d"),
        ),
        (
            {"explicit_gender": True, "asks_percentage": True},
            ("gender_percentage", 65, "gender_percentage_phrase"),
        ),
        ({"explicit_gender": True}, ("employee_count_by_gender", 45, "gender_distribution")),
        ({"asks_median": True, "explicit_age": True}, ("median_age", 92, "median_age")),
        (
            {"asks_average": True, "explicit_age": True, "explicit_department": True},
            ("avg_age_by_department", 85, "avg_age_by_department"),
        ),
        ({"asks_average": True, "explicit_age": True}, ("average_age", 92, "average_age")),
        ({"asks_most": True, "explicit_age": True}, ("max_age", 75, "max_age")),
        ({"asks_least": True, "explicit_age": True}, ("min_age", 75, "min_age")),
        ({"asks_stddev": True, "explicit_age": True}, ("stddev_age", 80, "stddev_age")),
        (
            {"explicit_education": True, "explicit_department": True},
            ("employee_count_by_department_education", 88, "department_education_2d"),
        ),
        (
            {"explicit_employment_type": True, "asks_least": True},
            ("least_populated_employment_type", 90, "least_employment_type"),
        ),
        (
            {"explicit_contract_type": True, "asks_least": True},
            ("least_populated_contract_type", 90, "least_contract_type"),
        ),
        (
            {"explicit_service_domain": True, "asks_least": True},
            ("least_populated_service_domain", 90, "least_service_domain"),
        ),
        (
            {"explicit_criticality_level": True},
            ("employee_count_by_criticality_level", 90, "criticality_level_distribution"),
        ),
        ({"explicit_marital": True}, ("employee_count_by_marital_status", 60, "marital_status")),
        ({"hire_year_filter": 1399}, ("employee_count_by_hire_year", 85, "hire_year_exact_filter")),
    ],
)
def test_feature_driven_rules(parser, features, expected):
    assert expected in _eval(parser, "", features)


# --------------------------------------------------------------------------
# Term-driven precedence (real questions, minimal features)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "چند نفر اخراج شده‌اند؟",
            ("terminated_employee_analysis", 200, "terminated_employee_data_gap"),
        ),
        (
            "چند نفر در آستانه بازنشستگی هستند؟",
            ("near_retirement_analysis", 300, "near_future_retirement_keywords"),
        ),
        ("جوان‌ترین و مسن‌ترین کارمند چند ساله است؟", ("age_min_max", 96, "age_min_max_combined")),
    ],
)
def test_term_driven_rules(parser, question, expected):
    assert expected in _eval(parser, question, {})


def test_gender_department_beats_plain_gender(parser):
    """The 2-D department×gender rule (88) and plain gender (45) can coexist;
    the score ordering is what disambiguates downstream."""
    out = dict(
        (i, s)
        for i, s, _ in _eval(parser, "", {"explicit_gender": True, "explicit_department": True})
    )
    assert out["employee_count_by_department_gender"] == 88
