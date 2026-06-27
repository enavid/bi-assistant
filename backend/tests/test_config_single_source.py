"""Single-source configuration tests (Phase 2.1).

Privacy/routing constants must come from one named source, not scattered
literals that can silently drift:

* ``MIN_GROUP_SIZE_FLOOR`` is the k-anonymity privacy floor. It is a code
  constant (not env-overridable). Metadata may only *raise* the effective
  threshold above the floor, never lower it.
* ``current_shamsi_year`` fallbacks must follow ``settings``, not a second
  hardcoded ``1404``.
* The intent confidence bands must be a named, documented table whose numeric
  behaviour is identical to the previous if/elif ladder (refactor guard).
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.constants import MIN_GROUP_SIZE_FLOOR
from app.hr_analytics.adapters.response_builder import ResponseBuilderConfig
from app.hr_analytics.use_cases.sql.generator import SQLGeneratorConfig
from app.hr_analytics.use_cases.sql.template_engine import SQLTemplateEngineConfig
from app.hr_analytics.use_cases.sql.validator import SQLValidatorConfig
from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

# ---------------------------------------------------------------------------
# Privacy floor: single constant, referenced everywhere
# ---------------------------------------------------------------------------


def test_privacy_floor_constant_value():
    # The strictest safe default for a financial/privacy system.
    assert MIN_GROUP_SIZE_FLOOR == 5


def test_all_config_defaults_reference_the_floor():
    """No component may carry its own private copy of the default threshold."""
    assert SQLValidatorConfig().minimum_group_size == MIN_GROUP_SIZE_FLOOR
    assert ResponseBuilderConfig().min_group_size_default == MIN_GROUP_SIZE_FLOOR
    assert QuestionValidator().min_group_size == MIN_GROUP_SIZE_FLOOR


class _LowballMetadata:
    """A metadata service that tries to weaken the privacy threshold."""

    def __init__(self, value: int) -> None:
        self._value = value

    def get_min_group_size(self, default: int = MIN_GROUP_SIZE_FLOOR) -> int:
        return self._value


def test_metadata_may_raise_threshold_above_floor():
    router = DecisionRouter(metadata_service=object())
    hints = router._build_policy_hints(
        user_role="demo_user", intent_result={}, service=_LowballMetadata(9)
    )
    assert hints["minimum_group_size"] == 9


def test_metadata_cannot_lower_threshold_below_floor():
    """A service returning a below-floor value must be clamped up, never trusted down."""
    router = DecisionRouter(metadata_service=object())
    hints = router._build_policy_hints(
        user_role="demo_user", intent_result={}, service=_LowballMetadata(2)
    )
    assert hints["minimum_group_size"] == MIN_GROUP_SIZE_FLOOR


# ---------------------------------------------------------------------------
# Shamsi year: fallback follows settings, not a second hardcoded literal
# ---------------------------------------------------------------------------


def test_template_engine_config_year_follows_settings(monkeypatch):
    monkeypatch.setattr(settings, "current_shamsi_year", 1405)
    assert SQLTemplateEngineConfig().current_shamsi_year == 1405


def test_generator_config_year_follows_settings(monkeypatch):
    monkeypatch.setattr(settings, "current_shamsi_year", 1405)
    assert SQLGeneratorConfig().current_shamsi_year == 1405


# ---------------------------------------------------------------------------
# Confidence bands: named table, numerically identical to the old ladder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (120, 0.99),
        (80, 0.99),
        (79.9, 0.96),
        (60, 0.96),
        (35, 0.9),
        (34, 0.78),
        (20, 0.78),
        (10, 0.62),
        (9, max(0.35, min(0.6, 9 / 18))),
        (5, max(0.35, min(0.6, 5 / 18))),
        (0, 0.35),
    ],
)
def test_score_to_confidence_bands_unchanged(score, expected):
    assert IntentParser._score_to_confidence(score, [object()]) == expected


def test_score_to_confidence_zero_when_no_candidates_below_lowest_band():
    assert IntentParser._score_to_confidence(3, []) == 0.0
