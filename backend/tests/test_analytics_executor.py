from __future__ import annotations

from app.infrastructure.hr_db.analytics_executor import (
    QueryExecutor,
)

VALID_SQL = (
    "SELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE"
)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def test_asyncpg_url_is_normalized_to_sync_url():
    """asyncpg-format DSN must be stripped to plain postgresql:// before sync drivers try it."""
    executor = QueryExecutor(
        database_url="postgresql+asyncpg://user:pass@host:5432/db",
        require_validated_sql=False,
    )
    normalized = executor._normalize_sync_url()
    assert "+asyncpg" not in normalized
    assert normalized.startswith("postgresql://")


def test_plain_postgresql_url_unchanged():
    executor = QueryExecutor(
        database_url="postgresql://user:pass@host:5432/db",
        require_validated_sql=False,
    )
    assert executor._normalize_sync_url() == "postgresql://user:pass@host:5432/db"


def test_postgres_url_unchanged():
    executor = QueryExecutor(
        database_url="postgres://user:pass@host:5432/db",
        require_validated_sql=False,
    )
    assert executor._normalize_sync_url() == "postgres://user:pass@host:5432/db"


def test_no_url_returns_empty():
    executor = QueryExecutor(require_validated_sql=False)
    executor.database_url = None
    assert executor._normalize_sync_url() == ""


# ---------------------------------------------------------------------------
# connect_args: application_name must not appear for asyncpg dialect
# ---------------------------------------------------------------------------


def test_connect_args_empty_for_asyncpg_url():
    """asyncpg does not accept application_name via connect_args — must return {}."""
    executor = QueryExecutor(
        database_url="postgresql+asyncpg://user:pass@host:5432/db",
        require_validated_sql=False,
    )
    args = executor._sqlalchemy_connect_args()
    assert args == {}


def test_connect_args_has_app_name_for_plain_postgresql():
    executor = QueryExecutor(
        database_url="postgresql://user:pass@host:5432/db",
        require_validated_sql=False,
    )
    args = executor._sqlalchemy_connect_args()
    assert "application_name" in args


# ---------------------------------------------------------------------------
# Execution path: asyncpg URL must not raise UnexpectedKeyword on connect_args
# ---------------------------------------------------------------------------


def test_asyncpg_url_execution_raises_not_configured_not_keyword_error():
    """
    When no real DB is available, executing with an asyncpg URL must raise
    QueryExecutorNotConfiguredError (driver unavailable), NOT TypeError about
    unexpected keyword argument 'application_name'.
    """
    executor = QueryExecutor(
        database_url="postgresql+asyncpg://user:pass@unreachable-host:5432/db",
        require_validated_sql=False,
    )
    result = executor.execute(sql=VALID_SQL)
    assert result["status"] == "NOT_EXECUTED"
    assert "application_name" not in (result.get("errors") or [""])[0]
