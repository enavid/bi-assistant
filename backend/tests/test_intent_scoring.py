"""Tests for the extracted intent confidence scoring (Phase 3.1).

The confidence band logic used to live as inline magic numbers inside the
3000-line IntentParser God class. It now lives in a small, pure, independently
testable module. These tests pin the numeric contract and the band precedence so
the extraction is provably behavior-preserving.
"""

from __future__ import annotations

import pytest

from app.hr_analytics.use_cases.steps.intent_scoring import (
    CONFIDENCE_BANDS,
    score_to_confidence,
)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, 0.99),
        (80, 0.99),  # exact band boundary is inclusive
        (79.9, 0.96),
        (60, 0.96),
        (35, 0.9),
        (34, 0.78),
        (20, 0.78),
        (10, 0.62),
        (9, 0.5),  # sub-band: 9/18 = 0.5
    ],
)
def test_band_values(score, expected):
    assert score_to_confidence(score, has_candidates=True) == expected


def test_sub_band_is_clamped_to_floor_and_ceiling():
    # very small score clamps up to the floor
    assert score_to_confidence(1, has_candidates=True) == 0.35
    # a score just under the lowest band but high in the sub-band clamps to ceiling
    assert score_to_confidence(9.99, has_candidates=True) == pytest.approx(0.555, abs=1e-9)


def test_zero_when_no_candidates_below_lowest_band():
    assert score_to_confidence(3, has_candidates=False) == 0.0


def test_bands_are_descending():
    thresholds = [t for t, _ in CONFIDENCE_BANDS]
    assert thresholds == sorted(thresholds, reverse=True)


def test_parser_delegator_matches_module():
    """The thin IntentParser._score_to_confidence wrapper must equal the module fn."""
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser

    for score in (100, 80, 50, 25, 12, 4):
        assert IntentParser._score_to_confidence(score, [object()]) == score_to_confidence(
            score, has_candidates=True
        )
    assert IntentParser._score_to_confidence(3, []) == 0.0
