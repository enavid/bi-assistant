"""Dead-code guard tests (Phase 2.4).

These assert that confirmed-unused symbols stay removed (regression guard against
reintroduction) and that the one behavioural simplification preserves behaviour.
Each symbol was verified to have no callers before removal.
"""

from __future__ import annotations

from app.connections import active
from app.core.config import Settings
from app.hr_analytics.adapters.response_builder import ResponseBuilder
from app.hr_analytics.use_cases.sql.validator import SQLValidator
from app.hr_analytics.use_cases.steps import domain_classifier, gap_service


def test_unused_digit_translator_removed():
    # question_validator has its own private _translate_digits_to_ascii; the public
    # domain_classifier copy had no callers.
    assert not hasattr(domain_classifier, "translate_digits_to_ascii")


def test_unread_llm_fallback_flag_removed():
    # The flag was defined on Settings but never read anywhere — misleading.
    assert "enable_llm_sql_fallback" not in Settings.model_fields


def test_unused_out_of_scope_terms_removed():
    assert not hasattr(gap_service, "OUT_OF_SCOPE_TERMS")


def test_unused_restricted_visible_columns_removed():
    assert not hasattr(SQLValidator, "RESTRICTED_VISIBLE_COLUMNS")


def test_unused_set_active_model_removed():
    # _active_model is maintained via set_model_config/remove_model_config; the
    # standalone setter had no callers.
    assert not hasattr(active, "set_active_model")


def test_sanitize_rows_drops_identifiers_keeps_hire_year():
    """The redundant `!= 'hire_year'` clause was removed; behaviour is unchanged.

    employee_id is an identifier and must be dropped; hire_year is a legitimate
    dimension (not in IDENTIFIER_COLUMNS) and must survive.
    """
    builder = ResponseBuilder()
    sanitized, _warnings = builder._sanitize_rows(
        [{"employee_id": 7, "hire_year": 1400, "employee_count": 12}], metadata=None
    )
    assert sanitized, "expected at least one sanitized row"
    row = sanitized[0]
    assert "employee_id" not in row
    assert row.get("hire_year") == 1400
    assert row.get("employee_count") == 12
