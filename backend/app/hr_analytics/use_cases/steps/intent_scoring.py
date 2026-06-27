"""Intent confidence scoring.

Extracted from the ``IntentParser`` God class so the routing-confidence model is
a small, pure, independently testable unit instead of inline magic numbers.

Given a raw additive match score for the best intent candidate, map it to a
normalized ``[0, 1]`` confidence:

- If the score reaches a band threshold, return that band's confidence
  (first match wins; bands are ordered high → low).
- Below the lowest band, return ``clamp(score / divisor, floor, ceiling)`` — but
  ``0.0`` when there were no candidates at all.

The numbers are deliberately conservative: everything at or above 80 saturates to
0.99, so larger raw scores act only as tie-breakers, not as unbounded confidence.
"""

from __future__ import annotations

# Ordered high → low. A score >= threshold yields the paired confidence.
CONFIDENCE_BANDS: tuple[tuple[float, float], ...] = (
    (80, 0.99),
    (60, 0.96),
    (35, 0.9),
    (20, 0.78),
    (10, 0.62),
)

# Below the lowest band: confidence = clamp(score / divisor, floor, ceiling).
SUB_BAND_FLOOR = 0.35
SUB_BAND_CEILING = 0.6
SUB_BAND_DIVISOR = 18


def score_to_confidence(best_score: float, *, has_candidates: bool) -> float:
    """Map a raw best-candidate score to a normalized confidence in ``[0, 1]``."""
    for threshold, confidence in CONFIDENCE_BANDS:
        if best_score >= threshold:
            return confidence
    if not has_candidates:
        return 0.0
    return max(SUB_BAND_FLOOR, min(SUB_BAND_CEILING, best_score / SUB_BAND_DIVISOR))
