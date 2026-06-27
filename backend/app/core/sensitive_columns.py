"""Single source of truth for the sensitive-column blocklist.

The PII/financial columns that must never be exposed at row level (or used as a
GROUP BY / output column) were previously redefined as independent literal sets
in the SQL validator, the SQL generator and the response builder. Those sets had
silently drifted apart, so a column the validator blocked (``email``, ``iban``,
``medical_record`` ...) could slip past the generator's GROUP BY guard or the
response builder's row sanitizer.

``SENSITIVE_COLUMNS_FLOOR`` is the canonical, non-weakenable floor — the same
fail-safe pattern as :data:`app.core.constants.MIN_GROUP_SIZE_FLOOR`. It is a
deliberate code constant, NOT environment-overridable. Metadata
``access_policies`` / ``sql_validator_rules`` may only *add* columns on top of
the floor via :func:`resolve_sensitive_columns`; they can never remove a floor
column. If the metadata lookup fails, the resolver logs and falls back to the
floor, so the guarantee can never be silently weakened.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Canonical PII / financial columns. Lowercase, because every consumer compares
# against a lowercased column name. This is the floor every guard must enforce.
SENSITIVE_COLUMNS_FLOOR: frozenset[str] = frozenset(
    {
        # direct identifiers
        "national_id",
        "personnel_number",
        "personal_identifier",
        "birth_certificate_number",
        # names
        "first_name",
        "last_name",
        "full_name",
        # contact
        "phone_number",
        "mobile",
        "address",
        "email",
        # financial
        "bank_account",
        "iban",
        "salary",
        "base_salary",
        "wage",
        "insurance_number",
        # protected records
        "medical_record",
        "disciplinary_record",
    }
)


def resolve_sensitive_columns(metadata_service: Any | None = None) -> set[str]:
    """Return the effective sensitive-column set: the floor plus any metadata additions.

    Metadata may only widen the blocklist. A failure to read the metadata is
    logged (financial-grade auditability) and falls back to the bare floor, so
    the result is never weaker than :data:`SENSITIVE_COLUMNS_FLOOR`.
    """
    columns = set(SENSITIVE_COLUMNS_FLOOR)
    if metadata_service is None:
        return columns
    try:
        extra = metadata_service.get_sensitive_columns()
    except Exception:
        logger.warning(
            "Failed to load sensitive columns from metadata; "
            "falling back to the code-defined floor (%d columns)",
            len(columns),
            exc_info=True,
        )
        return columns
    for col in extra or []:
        text = str(col).strip().lower()
        if text:
            columns.add(text)
    return columns
