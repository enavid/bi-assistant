"""Tests for HRQueryExecutor hardening — TDD.

The chat /query path must run client SQL with a statement timeout, a read-only
session, and a bounded result set. These tests drive the executor against a fake
psycopg2 connection so no real database is required.
"""

from __future__ import annotations

import psycopg2
import pytest

from app.infrastructure.hr_db.executor import HRQueryExecutor


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self.description = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql, params=None) -> None:
        self._conn.executed.append((sql, params))
        if sql.strip().upper().startswith(("SET ", "RESET ")):
            return
        # A data query: expose the canned result set.
        self.description = [(name,) for name in self._conn.result_columns]
        self._rows = list(self._conn.result_rows)

    def fetchmany(self, size):
        rows, self._rows = self._rows[:size], self._rows[size:]
        return rows

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, columns, rows) -> None:
        self.result_columns = columns
        self.result_rows = rows
        self.executed: list = []
        self.autocommit = False
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def patch_connect(monkeypatch):
    def _install(columns, rows):
        conn = _FakeConnection(columns, rows)
        monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: conn)
        return conn

    return _install


def _executed_sql(conn: _FakeConnection) -> list[str]:
    return [sql.strip().upper() for sql, _ in conn.executed]


# ---------------------------------------------------------------------------
# Happy path + hardening
# ---------------------------------------------------------------------------


def test_run_returns_rows_on_success(patch_connect):
    conn = patch_connect(["employee_count"], [(750,)])
    executor = HRQueryExecutor(dsn="postgresql://u:p@h:5432/db")

    result = executor.run("SELECT COUNT(v.employee_id) FROM v")

    assert result.success is True
    assert result.columns == ["employee_count"]
    assert result.rows == [[750]]
    assert result.row_count == 1
    assert conn.closed is True


def test_run_sets_statement_timeout(patch_connect):
    conn = patch_connect(["x"], [(1,)])
    HRQueryExecutor(dsn="postgresql://u:p@h/db", statement_timeout_ms=4321).run("SELECT 1")

    joined = " | ".join(_executed_sql(conn))
    assert "STATEMENT_TIMEOUT" in joined


def test_run_sets_read_only_session(patch_connect):
    conn = patch_connect(["x"], [(1,)])
    HRQueryExecutor(dsn="postgresql://u:p@h/db", read_only=True).run("SELECT 1")

    joined = " | ".join(_executed_sql(conn))
    assert "READ_ONLY" in joined or "READ ONLY" in joined


def test_run_caps_rows_to_max(patch_connect):
    rows = [(i,) for i in range(50)]
    patch_connect(["n"], rows)
    executor = HRQueryExecutor(dsn="postgresql://u:p@h/db", max_rows=10)

    result = executor.run("SELECT n FROM big")

    assert result.row_count == 10
    assert len(result.rows) == 10


def test_run_strips_asyncpg_driver_prefix():
    executor = HRQueryExecutor(dsn="postgresql+asyncpg://u:p@h:5432/db")
    assert "+asyncpg" not in executor._dsn
    assert executor._dsn.startswith("postgresql://")


# ---------------------------------------------------------------------------
# Failure paths — must fail safe and not raise
# ---------------------------------------------------------------------------


def test_run_handles_operational_error(monkeypatch):
    def _boom(*a, **k):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", _boom)
    result = HRQueryExecutor(dsn="postgresql://u:p@h/db").run("SELECT 1")

    assert result.success is False
    assert result.error
    assert result.row_count == 0


def test_run_handles_generic_error_and_closes_connection(monkeypatch):
    class _ExplodingConn(_FakeConnection):
        def cursor(self):
            raise RuntimeError("query blew up")

    conn = _ExplodingConn(["x"], [(1,)])
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: conn)

    result = HRQueryExecutor(dsn="postgresql://u:p@h/db").run("SELECT 1")

    assert result.success is False
    assert result.error
    assert conn.closed is True


def test_failed_session_hardening_does_not_abort_query(monkeypatch):
    # If SET statement_timeout fails (e.g. restricted role), the query must still run,
    # but the failure must be observable (logged) rather than silently swallowed.
    class _PickyCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if sql.strip().upper().startswith("SET "):
                raise psycopg2.errors.InsufficientPrivilege("nope")
            return super().execute(sql, params)

    class _PickyConn(_FakeConnection):
        def cursor(self):
            return _PickyCursor(self)

    conn = _PickyConn(["x"], [(7,)])
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: conn)

    result = HRQueryExecutor(dsn="postgresql://u:p@h/db").run("SELECT 7")
    assert result.success is True
    assert result.rows == [[7]]
