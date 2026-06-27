"""Single source of truth for the sensitive-column blocklist (Phase 3.2).

The PII/financial blocklist used to be redefined independently in
``sql/validator.py``, ``sql/generator.py`` and ``adapters/response_builder.py``.
The three sets had drifted: the SQL validator blocked ``email``/``iban``/
``medical_record`` while the GROUP BY guard in the generator and the row
sanitizer in the response builder did not. These tests pin the canonical floor
and guard against re-drift: every consumer's effective set must be a superset of
the code-defined floor, mirroring the non-weakenable ``MIN_GROUP_SIZE_FLOOR``
pattern (metadata may only *add* columns, never remove a floor column).
"""

from __future__ import annotations

import logging

import pytest

from app.core.sensitive_columns import (
    SENSITIVE_COLUMNS_FLOOR,
    resolve_sensitive_columns,
)

# Columns that the validator already blocked but the other two guards silently
# dropped. They MUST be part of the floor so no consumer can omit them.
_PREVIOUSLY_DRIFTED = {
    "email",
    "iban",
    "medical_record",
    "disciplinary_record",
    "base_salary",
    "birth_certificate_number",
}


class _FakeMetadata:
    def __init__(self, cols):
        self._cols = cols

    def get_sensitive_columns(self):
        return self._cols


class _ExplodingMetadata:
    def get_sensitive_columns(self):
        raise RuntimeError("metadata backend unavailable")


# ---------------------------------------------------------------------------
# The floor itself
# ---------------------------------------------------------------------------


def test_floor_is_frozen_and_lowercase():
    assert isinstance(SENSITIVE_COLUMNS_FLOOR, frozenset)
    assert all(c == c.lower() for c in SENSITIVE_COLUMNS_FLOOR)


@pytest.mark.parametrize(
    "col",
    sorted(
        {
            "national_id",
            "salary",
            "phone_number",
            "full_name",
            "bank_account",
            *_PREVIOUSLY_DRIFTED,
        }
    ),
)
def test_floor_contains_core_pii(col):
    assert col in SENSITIVE_COLUMNS_FLOOR


# ---------------------------------------------------------------------------
# The shared resolver
# ---------------------------------------------------------------------------


def test_resolver_without_metadata_returns_exactly_the_floor():
    assert resolve_sensitive_columns(None) == set(SENSITIVE_COLUMNS_FLOOR)


def test_resolver_unions_metadata_and_lowercases():
    resolved = resolve_sensitive_columns(_FakeMetadata(["Custom_Secret", "national_id"]))
    assert resolved >= set(SENSITIVE_COLUMNS_FLOOR)
    assert "custom_secret" in resolved  # lowercased


def test_resolver_metadata_can_only_add_never_remove():
    # A metadata source that returns an empty list cannot strip the floor.
    assert resolve_sensitive_columns(_FakeMetadata([])) == set(SENSITIVE_COLUMNS_FLOOR)


def test_resolver_failsafe_logs_and_keeps_floor(caplog):
    with caplog.at_level(logging.WARNING):
        resolved = resolve_sensitive_columns(_ExplodingMetadata())
    assert resolved == set(SENSITIVE_COLUMNS_FLOOR)  # fail-safe: never weaker
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "metadata failure must be logged for a financial system, not swallowed"
    )


# ---------------------------------------------------------------------------
# Every consumer must honor the floor (drift guards)
# ---------------------------------------------------------------------------


def test_validator_effective_set_supersets_floor():
    from app.hr_analytics.use_cases.sql.validator import SQLValidator

    validator = SQLValidator(metadata_service=None, strict=False)
    assert set(validator.sensitive_columns) >= set(SENSITIVE_COLUMNS_FLOOR)


def test_generator_effective_set_supersets_floor():
    from app.hr_analytics.use_cases.sql.generator import SQLGenerator

    gen = SQLGenerator(metadata_service=None)
    assert set(gen.sensitive_columns) >= set(SENSITIVE_COLUMNS_FLOOR)


def test_response_builder_default_supersets_floor():
    from app.hr_analytics.adapters.response_builder import DEFAULT_SENSITIVE_COLUMNS

    assert set(DEFAULT_SENSITIVE_COLUMNS) >= set(SENSITIVE_COLUMNS_FLOOR)


# ---------------------------------------------------------------------------
# Behavioral proof the drift gap is closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("col", sorted(_PREVIOUSLY_DRIFTED))
def test_generator_blocks_previously_drifted_columns(col):
    """The GROUP BY / output guard must now reject the columns it used to miss."""
    from app.hr_analytics.use_cases.sql.generator import SQLGenerator, SQLGeneratorError

    gen = SQLGenerator(metadata_service=None)
    # allowed_columns is irrelevant: sensitivity is checked before availability.
    with pytest.raises(SQLGeneratorError):
        gen._assert_safe_column(col, {col: {"name": col}})


@pytest.mark.parametrize("col", sorted(_PREVIOUSLY_DRIFTED))
def test_response_builder_drops_previously_drifted_columns(col):
    from app.hr_analytics.adapters.response_builder import ResponseBuilder

    builder = ResponseBuilder()
    rows = [{col: "secret-value", "employee_count": 7}]
    sanitized, _ = builder._sanitize_rows(rows, metadata=None)
    assert sanitized == [{"employee_count": 7}], f"{col} leaked into row output"
