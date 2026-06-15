"""
Shared Persian text normalizer used by all pipeline steps.

Applies normalization in a single pass so every step (DomainClassifier,
IntentParser, etc.) operates on identical text without duplicating logic.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Character-level tables
# ---------------------------------------------------------------------------

_ARABIC_TO_PERSIAN: dict[str, str] = {
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    "ۀ": "ه",
    "ة": "ه",
    "ؤ": "و",
    "أ": "ا",
    "إ": "ا",
    "ٱ": "ا",
    "‌": " ",  # ZWNJ → ordinary space
    "–": "-",
    "—": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_TRANS: dict[int, str] = {ord(ch): str(i) for i, ch in enumerate(_PERSIAN_DIGITS)}
_DIGIT_TRANS.update({ord(ch): str(i) for i, ch in enumerate(_ARABIC_DIGITS)})

# ---------------------------------------------------------------------------
# Compound word table (split → joined canonical form)
# Order: longer splits first to avoid partial matches.
# ---------------------------------------------------------------------------

_COMPOUND_WORDS: list[tuple[str, str]] = [
    # Retirement
    ("باز نشستگی", "بازنشستگی"),
    ("باز نشستن", "بازنشستن"),
    ("باز نشسته", "بازنشسته"),
    # Employee / workforce
    ("کار کنان", "کارکنان"),
    ("کار مندان", "کارمندان"),
    ("کار مند", "کارمند"),
    # Contractor
    ("پیمان کاری", "پیمانکاری"),
    ("پیمان کار", "پیمانکار"),
]

# ---------------------------------------------------------------------------
# Colloquial → standard verb forms
# ---------------------------------------------------------------------------

_COLLOQUIAL_VERBS: list[tuple[str, str]] = [
    ("میشن", "میشوند"),
    ("میشه", "میشود"),
    ("هستن", "هستند"),
    ("میکنن", "میکنند"),
    ("دارن", "دارند"),
    ("بشن", "بشوند"),
    ("بشه", "بشود"),
]

# Pre-compiled patterns for word-boundary colloquial replacement.
_COLLOQUIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?<!\S){re.escape(col)}(?!\S)"), std) for col, std in _COLLOQUIAL_VERBS
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Return a normalized Persian string suitable for all pipeline steps."""
    text = str(text or "")

    text = unicodedata.normalize("NFKC", text)

    for src, dst in _ARABIC_TO_PERSIAN.items():
        text = text.replace(src, dst)

    text = text.translate(_DIGIT_TRANS)

    for split_form, joined in _COMPOUND_WORDS:
        text = text.replace(split_form, joined)

    # Join standalone "می <verb>" → "می<verb>" only when "می" is a word-initial prefix.
    # (?<!\S) ensures "می" is not the suffix of another word (e.g. "اسامی کارکنان").
    text = re.sub(r"(?<!\S)می ([ا-ی])", r"می\1", text)

    for pattern, canonical in _COLLOQUIAL_PATTERNS:
        text = pattern.sub(canonical, text)

    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r"[؟?؛;،,]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
