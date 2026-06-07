from __future__ import annotations


class DomainError(Exception):
    """Base domain exception."""


class NotFoundError(DomainError):
    """Resource not found."""


class ValidationError(DomainError):
    """Input validation failed."""


class AccessDeniedError(DomainError):
    """Access to resource is denied."""


class DataGapError(DomainError):
    """Requested data is not available."""


class SQLValidationError(DomainError):
    """Generated SQL failed safety validation."""


class LLMError(DomainError):
    """LLM request failed."""


class MetadataError(DomainError):
    """Metadata loading or lookup failed."""
