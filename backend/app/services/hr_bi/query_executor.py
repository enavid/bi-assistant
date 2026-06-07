from __future__ import annotations
import asyncio
import inspect
import os
import re
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


"""
query_executor.py
-----------------
Safe query execution service for HR BI Assistant, Controlled SQL-based MVP.

Place this file in:
    backend/app/services/query_executor.py

Responsibility:
    - Execute ONLY SQL that has already passed sql_validator.py.
    - Keep execution read-only and bounded.
    - Return a stable result payload for llm_orchestrator.py / response_builder.py.
    - Support multiple DB backends/adapters with zero hard dependency in the MVP:
        * SQLAlchemy Engine / Connection, if installed and injected
        * DB-API connection or connection factory, e.g. psycopg2/psycopg
        * asyncpg connection / pool, if injected
        * PostgreSQL DSN via env, when a supported optional driver is installed

Important:
    This module is still defensive. Even if the orchestrator has already called
    sql_validator.py, the executor refuses to run SQL that is not marked valid
    unless `trust_external_validation=False` and an internal validator is supplied.
"""


try:  # package import when used inside backend/app/services
    from .metadata_service import MetadataService, get_metadata_service
except Exception:  # pragma: no cover - local/script execution fallback
    try:
        from metadata_service import MetadataService, get_metadata_service  # type: ignore
    except Exception:  # pragma: no cover
        MetadataService = Any  # type: ignore
        get_metadata_service = None  # type: ignore

try:  # optional local validator
    from .sql_validator import SQLValidator
except Exception:  # pragma: no cover
    try:
        from sql_validator import SQLValidator  # type: ignore
    except Exception:  # pragma: no cover
        SQLValidator = None  # type: ignore


JsonDict = dict[str, Any]
_STATUS_SQL_RE = re.compile(
    r"^\s*SELECT\s+'(?P<status>DATA_GAP|ACCESS_DENIED|OUT_OF_SCOPE|NEEDS_CLARIFICATION|SQL_VALIDATION_FAILED)'\s+AS\s+status\s*;?\s*$",
    flags=re.IGNORECASE,
)


class QueryExecutorError(RuntimeError):
    """Base exception for query execution failures."""


class QueryExecutorNotConfiguredError(QueryExecutorError):
    """Raised when no executable database connection/engine is configured."""


class QueryExecutionSecurityError(QueryExecutorError):
    """Raised when SQL is not validated or violates execution policy."""


@dataclass
class QueryExecutorConfig:
    """Runtime configuration for QueryExecutor."""

    main_view: str = "hr_mvp.vw_hr_employee_analytics"
    schema_name: str = "hr_mvp"
    required_alias: str = "v"
    source_name: str = "query_executor"

    # Safety limits
    max_rows: int = 500
    statement_timeout_ms: int = 10_000
    read_only_transaction: bool = True
    require_validated_sql: bool = True
    execute_status_sql_locally: bool = True
    allow_unvalidated_status_sql: bool = True

    # Connection discovery. Prefer injection; env is a fallback only.
    database_url_env: str = "DATABASE_URL"
    postgres_url_env: str = "POSTGRES_DSN"
    app_name: str = "hr_bi_assistant_phase2"

    # Result shaping
    include_sql_in_result: bool = True
    include_column_metadata: bool = True
    include_execution_timing: bool = True
    convert_decimals_to_float: bool = False


@dataclass
class QueryExecutionResult:
    """Standard output shape consumed by llm_orchestrator.py."""

    status: str
    execution_status: str
    source: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    column_metadata: list[JsonDict] = field(default_factory=list)
    rows: list[JsonDict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    max_rows: int | None = None
    duration_ms: float | None = None
    database: JsonDict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    @property
    def data(self) -> list[JsonDict]:
        return self.rows

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["data"] = self.data
        return payload


class QueryExecutor:
    """
    Execute a validated SQL statement safely.

    The orchestrator can call any of these methods:
        execute(sql=..., context=..., metadata=...)
        run(sql=..., context=..., metadata=...)
        arun(sql=..., context=..., metadata=...)
        __call__(sql=..., context=..., metadata=...)

    Connection options, in preferred order:
        1. Inject an existing SQLAlchemy Engine/Connection using `engine=`.
        2. Inject a DB-API connection using `connection=`.
        3. Inject a DB-API connection factory using `connection_factory=`.
        4. Inject an asyncpg connection/pool using `async_connection=` / `async_pool=`.
        5. Provide `database_url=` and have SQLAlchemy/psycopg/psycopg2 installed.
        6. Set DATABASE_URL or POSTGRES_DSN env var and install a supported driver.
    """

    def __init__(
        self,
        *,
        metadata_service: Any | None = None,
        metadata_dir: str | Path | None = None,
        sql_validator: Any | None = None,
        engine: Any | None = None,
        connection: Any | None = None,
        connection_factory: Callable[[], Any] | None = None,
        async_connection: Any | None = None,
        async_pool: Any | None = None,
        database_url: str | None = None,
        max_rows: int = 500,
        statement_timeout_ms: int = 10_000,
        require_validated_sql: bool = True,
        read_only_transaction: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        self.validator = sql_validator
        if self.validator is None and SQLValidator is not None:
            with suppress(Exception):
                self.validator = SQLValidator(metadata_service=self.metadata)

        self.engine = engine
        self.connection = connection
        self.connection_factory = connection_factory
        self.async_connection = async_connection
        self.async_pool = async_pool
        self.database_url = database_url or os.getenv(
            QueryExecutorConfig.database_url_env) or os.getenv(QueryExecutorConfig.postgres_url_env)

        self.config = QueryExecutorConfig(
            max_rows=int(max_rows),
            statement_timeout_ms=int(statement_timeout_ms),
            require_validated_sql=bool(require_validated_sql),
            read_only_transaction=bool(read_only_transaction),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        *,
        sql: str | None = None,
        context: Any | None = None,
        metadata: Any | None = None,
        validation_result: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
        **kwargs: Any,
    ) -> JsonDict:
        """Synchronous execution wrapper."""
        return self._execute_sync(
            sql=sql,
            context=context,
            metadata=metadata,
            validation_result=validation_result,
            params=params,
            max_rows=max_rows,
            **kwargs,
        ).to_dict()

    def run(self, **kwargs: Any) -> JsonDict:
        return self.execute(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return (await self._execute_async(**kwargs)).to_dict()

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.execute(**kwargs)

    # ------------------------------------------------------------------
    # Execution core
    # ------------------------------------------------------------------

    def _execute_sync(
        self,
        *,
        sql: str | None = None,
        context: Any | None = None,
        metadata: Any | None = None,
        validation_result: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
        **_: Any,
    ) -> QueryExecutionResult:
        started = time.perf_counter()
        sql_text = self._resolve_sql(sql, context)
        limit = int(max_rows or self.config.max_rows)
        warnings: list[str] = []

        status_sql = self._maybe_local_status_result(sql_text, started)
        if status_sql is not None:
            return status_sql

        guard = self._pre_execution_guard(
            sql_text, context=context, validation_result=validation_result, metadata=metadata)
        if not guard.get("ok", False):
            return self._failure(
                status="EXECUTION_BLOCKED",
                execution_status="FAILED",
                sql=sql_text,
                error=guard.get("reason", "SQL was not allowed to execute."),
                started=started,
                warnings=guard.get("warnings", []),
                metadata={"guard": guard},
            )
        warnings.extend(guard.get("warnings", []))

        try:
            executor = self._select_sync_executor()
            result = executor(sql_text, params=params or {}, max_rows=limit)
            return self._success_from_raw_result(
                result,
                sql=sql_text,
                started=started,
                max_rows=limit,
                warnings=warnings,
                database={"adapter": result.get("adapter") if isinstance(
                    result, dict) else "unknown"},
            )
        except QueryExecutorNotConfiguredError as exc:
            return self._failure(
                status="NOT_EXECUTED",
                execution_status="NOT_EXECUTED",
                sql=sql_text,
                error=str(exc),
                started=started,
                warnings=warnings,
            )
        except Exception as exc:
            return self._failure(
                status="EXECUTION_FAILED",
                execution_status="FAILED",
                sql=sql_text,
                error=str(exc),
                started=started,
                warnings=warnings,
            )

    async def _execute_async(
        self,
        *,
        sql: str | None = None,
        context: Any | None = None,
        metadata: Any | None = None,
        validation_result: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
        **_: Any,
    ) -> QueryExecutionResult:
        started = time.perf_counter()
        sql_text = self._resolve_sql(sql, context)
        limit = int(max_rows or self.config.max_rows)
        warnings: list[str] = []

        status_sql = self._maybe_local_status_result(sql_text, started)
        if status_sql is not None:
            return status_sql

        guard = self._pre_execution_guard(
            sql_text, context=context, validation_result=validation_result, metadata=metadata)
        if not guard.get("ok", False):
            return self._failure(
                status="EXECUTION_BLOCKED",
                execution_status="FAILED",
                sql=sql_text,
                error=guard.get("reason", "SQL was not allowed to execute."),
                started=started,
                warnings=guard.get("warnings", []),
                metadata={"guard": guard},
            )
        warnings.extend(guard.get("warnings", []))

        try:
            if self.async_pool is not None or self.async_connection is not None:
                raw = await self._execute_asyncpg_like(sql_text, params=params or {}, max_rows=limit)
            else:
                # Run sync adapter in a thread so FastAPI async routes are not blocked.
                raw = await asyncio.to_thread(
                    self._select_sync_executor(),
                    sql_text,
                    params or {},
                    limit,
                )
            return self._success_from_raw_result(
                raw,
                sql=sql_text,
                started=started,
                max_rows=limit,
                warnings=warnings,
                database={"adapter": raw.get("adapter") if isinstance(
                    raw, dict) else "unknown"},
            )
        except QueryExecutorNotConfiguredError as exc:
            return self._failure(
                status="NOT_EXECUTED",
                execution_status="NOT_EXECUTED",
                sql=sql_text,
                error=str(exc),
                started=started,
                warnings=warnings,
            )
        except Exception as exc:
            return self._failure(
                status="EXECUTION_FAILED",
                execution_status="FAILED",
                sql=sql_text,
                error=str(exc),
                started=started,
                warnings=warnings,
            )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _pre_execution_guard(
        self,
        sql: str,
        *,
        context: Any | None,
        validation_result: Mapping[str, Any] | None,
        metadata: Any | None,
    ) -> JsonDict:
        warnings: list[str] = []
        if not sql or not sql.strip():
            return {"ok": False, "reason": "SQL is empty.", "warnings": warnings}

        normalized_sql = sql.strip()
        extracted = validation_result or self._extract_validation_from_context(
            context)

        if self.config.require_validated_sql:
            if extracted:
                status = str(extracted.get("status") or extracted.get(
                    "validation_status") or "").upper()
                is_valid = bool(extracted.get("is_valid")) or status in {
                    "VALID", "SUCCESS"}
                can_execute = bool(extracted.get(
                    "can_execute_sql", extracted.get("is_executable", False)))
                if not (is_valid and can_execute):
                    return {
                        "ok": False,
                        "reason": "SQL validation result does not allow execution.",
                        "warnings": warnings,
                        "validation_status": status,
                    }
            elif self.validator is not None:
                validator_result = self._call_validator(
                    normalized_sql, context=context, metadata=metadata)
                status = str(validator_result.get("status") or validator_result.get(
                    "validation_status") or "").upper()
                if not (validator_result.get("is_valid") and validator_result.get("can_execute_sql")):
                    return {
                        "ok": False,
                        "reason": "Internal SQL validation failed before execution.",
                        "warnings": warnings,
                        "validation_status": status,
                        "violations": validator_result.get("violations", []),
                    }
                warnings.extend(validator_result.get("warnings", []) or [])
            else:
                return {"ok": False, "reason": "No SQL validation result or validator is available.", "warnings": warnings}

        # Final ultra-cheap guard. This should never replace sql_validator.py; it is an executor seatbelt.
        upper = normalized_sql.upper()
        if not (upper.startswith("SELECT") or upper.startswith("WITH")):
            return {"ok": False, "reason": "Executor only runs SELECT/WITH SQL.", "warnings": warnings}
        if self._has_multiple_statements(normalized_sql):
            return {"ok": False, "reason": "Executor refuses multiple SQL statements.", "warnings": warnings}
        forbidden = re.search(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE|COPY|CALL|DO)\b", upper)
        if forbidden:
            return {"ok": False, "reason": f"Forbidden SQL keyword detected: {forbidden.group(1)}", "warnings": warnings}
        if re.search(r"\bJOIN\b", upper):
            return {"ok": False, "reason": "JOIN is not allowed in Controlled SQL-based MVP.", "warnings": warnings}
        if self.config.main_view.lower() not in normalized_sql.lower():
            return {"ok": False, "reason": "SQL does not reference the approved analytics view.", "warnings": warnings}

        return {"ok": True, "warnings": warnings}

    def _call_validator(self, sql: str, *, context: Any | None, metadata: Any | None) -> JsonDict:
        if self.validator is None:
            return {}
        for method_name in ("validate", "run", "__call__"):
            candidate = self.validator if method_name == "__call__" else getattr(
                self.validator, method_name, None)
            if callable(candidate):
                result = candidate(sql=sql, context=context, metadata=metadata)
                if inspect.isawaitable(result):
                    # This sync path may run outside an event loop. If inside one, callers should use arun.
                    result = asyncio.run(result)
                return to_plain_dict(result)
        return {}

    @staticmethod
    def _has_multiple_statements(sql: str) -> bool:
        body = sql.strip()
        if not body:
            return False
        # Semicolons inside strings are ignored by this scanner.
        in_single = False
        escaped = False
        semicolons = 0
        for ch in body:
            if ch == "'" and not escaped:
                in_single = not in_single
            elif ch == ";" and not in_single:
                semicolons += 1
            escaped = (ch == "\\" and not escaped)
            if ch != "\\":
                escaped = False
        if semicolons == 0:
            return False
        if semicolons == 1 and body.endswith(";"):
            return False
        return True

    # ------------------------------------------------------------------
    # Adapter selection and execution
    # ------------------------------------------------------------------

    def _select_sync_executor(self) -> Callable[[str, Mapping[str, Any], int], JsonDict]:
        if self.engine is not None:
            return self._execute_sqlalchemy_engine
        if self.connection is not None:
            return self._execute_dbapi_connection
        if self.connection_factory is not None:
            return self._execute_dbapi_factory
        if self.database_url:
            return self._execute_from_database_url
        raise QueryExecutorNotConfiguredError(
            "No database connection is configured. Inject engine, connection, connection_factory, "
            "async_pool/async_connection, database_url, or set DATABASE_URL/POSTGRES_DSN."
        )

    def _execute_sqlalchemy_engine(self, sql: str, params: Mapping[str, Any], max_rows: int) -> JsonDict:
        try:
            from sqlalchemy import text  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise QueryExecutorNotConfiguredError(
                "SQLAlchemy is not installed but an engine was provided.") from exc

        connectable = self.engine
        owns_connection = hasattr(connectable, "connect")
        conn = connectable.connect() if owns_connection else connectable
        try:
            self._configure_sqlalchemy_connection(conn)
            result = conn.execute(text(sql), dict(params or {}))
            rows = result.fetchmany(max_rows + 1)
            columns = list(result.keys())
            column_metadata = [{"name": name} for name in columns]
            if hasattr(conn, "commit"):
                with suppress(Exception):
                    conn.commit()
            return self._raw_result(columns, rows, column_metadata, max_rows=max_rows, adapter="sqlalchemy")
        finally:
            if owns_connection:
                with suppress(Exception):
                    conn.close()

    def _execute_dbapi_connection(self, sql: str, params: Mapping[str, Any], max_rows: int) -> JsonDict:
        conn = self.connection
        return self._execute_dbapi_on_connection(conn, sql, params=params, max_rows=max_rows, close_after=False)

    def _execute_dbapi_factory(self, sql: str, params: Mapping[str, Any], max_rows: int) -> JsonDict:
        conn = self.connection_factory() if self.connection_factory is not None else None
        return self._execute_dbapi_on_connection(conn, sql, params=params, max_rows=max_rows, close_after=True)

    def _execute_from_database_url(self, sql: str, params: Mapping[str, Any], max_rows: int) -> JsonDict:
        if not self.database_url:
            raise QueryExecutorNotConfiguredError("database_url is empty.")

        # Prefer SQLAlchemy if available because it works with multiple DB URLs.
        try:
            from sqlalchemy import create_engine  # type: ignore

            engine = create_engine(
                self.database_url, pool_pre_ping=True, connect_args=self._sqlalchemy_connect_args())
            old_engine = self.engine
            self.engine = engine
            try:
                return self._execute_sqlalchemy_engine(sql, params=params, max_rows=max_rows)
            finally:
                self.engine = old_engine
                with suppress(Exception):
                    engine.dispose()
        except Exception as sqlalchemy_exc:
            # Fall back to psycopg / psycopg2 for PostgreSQL DSNs.
            conn = None
            try:
                import psycopg  # type: ignore

                conn = psycopg.connect(
                    self.database_url, application_name=self.config.app_name)
            except Exception:
                try:
                    import psycopg2  # type: ignore

                    conn = psycopg2.connect(
                        self.database_url, application_name=self.config.app_name)
                except Exception as exc:
                    raise QueryExecutorNotConfiguredError(
                        "Could not open database_url. Install SQLAlchemy, psycopg, or psycopg2 and verify the DSN. "
                        f"SQLAlchemy error: {sqlalchemy_exc}; driver error: {exc}"
                    ) from exc
            return self._execute_dbapi_on_connection(conn, sql, params=params, max_rows=max_rows, close_after=True)

    def _execute_dbapi_on_connection(
        self,
        conn: Any,
        sql: str,
        *,
        params: Mapping[str, Any],
        max_rows: int,
        close_after: bool,
    ) -> JsonDict:
        if conn is None:
            raise QueryExecutorNotConfiguredError("DB-API connection is None.")

        cursor = None
        try:
            if hasattr(conn, "autocommit"):
                with suppress(Exception):
                    conn.autocommit = False
            cursor = conn.cursor()
            self._configure_dbapi_cursor(cursor)
            cursor.execute(sql, dict(params or {}) if params else None)
            rows = cursor.fetchmany(max_rows + 1)
            description = cursor.description or []
            columns = [str(item[0]) for item in description]
            column_metadata = self._column_metadata_from_dbapi_description(
                description)
            with suppress(Exception):
                conn.commit()
            return self._raw_result(columns, rows, column_metadata, max_rows=max_rows, adapter="dbapi")
        except Exception:
            with suppress(Exception):
                conn.rollback()
            raise
        finally:
            if cursor is not None:
                with suppress(Exception):
                    cursor.close()
            if close_after:
                with suppress(Exception):
                    conn.close()

    async def _execute_asyncpg_like(self, sql: str, *, params: Mapping[str, Any], max_rows: int) -> JsonDict:
        # asyncpg uses positional placeholders ($1, $2). Our SQL templates already render literals,
        # so params are usually empty. This method still accepts no-param SQL safely.
        if params:
            raise QueryExecutorError(
                "Named params are not supported by asyncpg adapter in this MVP renderer.")

        async def run_on_conn(conn: Any) -> JsonDict:
            await self._configure_asyncpg_connection(conn)
            records = await conn.fetch(sql)
            rows = list(records[: max_rows + 1])
            columns = list(rows[0].keys()) if rows else []
            column_metadata = [{"name": name} for name in columns]
            return self._raw_result(columns, rows, column_metadata, max_rows=max_rows, adapter="asyncpg")

        if self.async_pool is not None:
            async with self.async_pool.acquire() as conn:
                return await run_on_conn(conn)
        if self.async_connection is not None:
            return await run_on_conn(self.async_connection)
        raise QueryExecutorNotConfiguredError(
            "No asyncpg connection or pool is configured.")

    # ------------------------------------------------------------------
    # Connection configuration
    # ------------------------------------------------------------------

    def _configure_dbapi_cursor(self, cursor: Any) -> None:
        # PostgreSQL-specific hardening. If the DB is not PostgreSQL, failures are ignored.
        if self.config.read_only_transaction:
            with suppress(Exception):
                cursor.execute("SET LOCAL TRANSACTION READ ONLY")
        with suppress(Exception):
            cursor.execute("SET LOCAL statement_timeout = %s",
                           (self.config.statement_timeout_ms,))
        with suppress(Exception):
            cursor.execute("SET LOCAL idle_in_transaction_session_timeout = %s",
                           (self.config.statement_timeout_ms + 2_000,))

    def _configure_sqlalchemy_connection(self, conn: Any) -> None:
        try:
            from sqlalchemy import text  # type: ignore
        except Exception:  # pragma: no cover
            return
        if self.config.read_only_transaction:
            with suppress(Exception):
                conn.execute(text("SET LOCAL TRANSACTION READ ONLY"))
        with suppress(Exception):
            conn.execute(
                text(f"SET LOCAL statement_timeout = {int(self.config.statement_timeout_ms)}"))
        with suppress(Exception):
            conn.execute(text(
                f"SET LOCAL idle_in_transaction_session_timeout = {int(self.config.statement_timeout_ms + 2000)}"))

    async def _configure_asyncpg_connection(self, conn: Any) -> None:
        if self.config.read_only_transaction:
            with suppress(Exception):
                await conn.execute("SET LOCAL TRANSACTION READ ONLY")
        with suppress(Exception):
            await conn.execute(f"SET LOCAL statement_timeout = {int(self.config.statement_timeout_ms)}")
        with suppress(Exception):
            await conn.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(self.config.statement_timeout_ms + 2000)}")

    def _sqlalchemy_connect_args(self) -> JsonDict:
        # Do not force connect_args for non-PostgreSQL URLs. SQLAlchemy will ignore or reject unknown args.
        if self.database_url and self.database_url.startswith(("postgresql", "postgres")):
            return {"application_name": self.config.app_name}
        return {}

    # ------------------------------------------------------------------
    # Result conversion
    # ------------------------------------------------------------------

    def _raw_result(
        self,
        columns: Sequence[str],
        rows: Sequence[Any],
        column_metadata: list[JsonDict],
        *,
        max_rows: int,
        adapter: str,
    ) -> JsonDict:
        truncated = len(rows) > max_rows
        visible_rows = list(rows[:max_rows])
        converted_rows = [self._row_to_dict(
            row, columns) for row in visible_rows]
        return {
            "adapter": adapter,
            "columns": list(columns),
            "column_metadata": column_metadata,
            "rows": converted_rows,
            "row_count": len(converted_rows),
            "truncated": truncated,
            "max_rows": max_rows,
        }

    def _success_from_raw_result(
        self,
        raw: Mapping[str, Any],
        *,
        sql: str,
        started: float,
        max_rows: int,
        warnings: list[str],
        database: JsonDict | None = None,
    ) -> QueryExecutionResult:
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        rows = list(raw.get("rows") or [])
        row_count = int(raw.get("row_count", len(rows)))
        result_warnings = list(warnings)
        if raw.get("truncated"):
            result_warnings.append(
                f"Result was truncated to max_rows={max_rows}.")
        return QueryExecutionResult(
            status="SUCCESS",
            execution_status="SUCCESS",
            source=self.config.source_name,
            sql=sql if self.config.include_sql_in_result else None,
            columns=list(raw.get("columns") or []),
            column_metadata=list(raw.get("column_metadata") or [
            ]) if self.config.include_column_metadata else [],
            rows=rows,
            row_count=row_count,
            truncated=bool(raw.get("truncated", False)),
            max_rows=max_rows,
            duration_ms=duration_ms if self.config.include_execution_timing else None,
            database=database or {},
            warnings=list(dict.fromkeys(result_warnings)),
            metadata={"executed_at": utc_now_iso()},
        )

    def _failure(
        self,
        *,
        status: str,
        execution_status: str,
        sql: str | None,
        error: str,
        started: float,
        warnings: list[str] | None = None,
        metadata: JsonDict | None = None,
    ) -> QueryExecutionResult:
        return QueryExecutionResult(
            status=status,
            execution_status=execution_status,
            source=self.config.source_name,
            sql=sql if self.config.include_sql_in_result else None,
            rows=[],
            row_count=0,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            warnings=warnings or [],
            errors=[error],
            metadata=metadata or {"failed_at": utc_now_iso()},
        )

    def _maybe_local_status_result(self, sql: str, started: float) -> QueryExecutionResult | None:
        match = _STATUS_SQL_RE.match(sql or "")
        if not match or not self.config.execute_status_sql_locally:
            return None
        status = match.group("status").upper()
        return QueryExecutionResult(
            status=status,
            execution_status="SUCCESS",
            source=self.config.source_name,
            sql=sql if self.config.include_sql_in_result else None,
            columns=["status"],
            column_metadata=[{"name": "status", "type": "text"}],
            rows=[{"status": status}],
            row_count=1,
            truncated=False,
            max_rows=1,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            metadata={"executed_locally": True, "executed_at": utc_now_iso()},
        )

    def _row_to_dict(self, row: Any, columns: Sequence[str]) -> JsonDict:
        if isinstance(row, Mapping):
            return {str(k): self._json_safe(v) for k, v in row.items()}
        if hasattr(row, "_mapping"):
            return {str(k): self._json_safe(v) for k, v in row._mapping.items()}
        if hasattr(row, "keys") and callable(row.keys):
            try:
                return {str(k): self._json_safe(row[k]) for k in row.keys()}
            except Exception:
                pass
        return {str(col): self._json_safe(value) for col, value in zip(columns, row)}

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value
        if isinstance(value, Decimal):
            return float(value) if self.config.convert_decimals_to_float else str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if is_dataclass(value):
            return to_plain_dict(value)
        if isinstance(value, Mapping):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        return str(value)

    @staticmethod
    def _column_metadata_from_dbapi_description(description: Sequence[Any]) -> list[JsonDict]:
        metadata: list[JsonDict] = []
        for item in description:
            # DB-API description tuple: name, type_code, display_size, internal_size, precision, scale, null_ok
            metadata.append(
                {
                    "name": str(item[0]) if len(item) > 0 else None,
                    "type_code": str(item[1]) if len(item) > 1 and item[1] is not None else None,
                    "display_size": item[2] if len(item) > 2 else None,
                    "internal_size": item[3] if len(item) > 3 else None,
                    "precision": item[4] if len(item) > 4 else None,
                    "scale": item[5] if len(item) > 5 else None,
                    "null_ok": item[6] if len(item) > 6 else None,
                }
            )
        return metadata

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_sql(sql: str | None, context: Any | None) -> str:
        if sql and str(sql).strip():
            return str(sql).strip()
        if context is not None:
            for attr in ("sql_plan", "sql_validation"):
                payload = getattr(context, attr, None)
                if isinstance(payload, Mapping) and payload.get("sql"):
                    return str(payload.get("sql")).strip()
            if isinstance(context, Mapping):
                for key in ("sql", "generated_sql"):
                    if context.get(key):
                        return str(context.get(key)).strip()
                payload = context.get(
                    "sql_plan") or context.get("sql_validation")
                if isinstance(payload, Mapping) and payload.get("sql"):
                    return str(payload.get("sql")).strip()
        return ""

    @staticmethod
    def _extract_validation_from_context(context: Any | None) -> JsonDict:
        if context is None:
            return {}
        payload = getattr(context, "sql_validation", None)
        if payload:
            return to_plain_dict(payload)
        if isinstance(context, Mapping):
            return to_plain_dict(context.get("sql_validation") or {})
        return {}


# ---------------------------------------------------------------------------
# Factory and generic helpers
# ---------------------------------------------------------------------------


def get_query_executor(
    *,
    metadata_service: Any | None = None,
    metadata_dir: str | Path | None = None,
    sql_validator: Any | None = None,
    engine: Any | None = None,
    connection: Any | None = None,
    connection_factory: Callable[[], Any] | None = None,
    async_connection: Any | None = None,
    async_pool: Any | None = None,
    database_url: str | None = None,
    max_rows: int = 500,
    statement_timeout_ms: int = 10_000,
    require_validated_sql: bool = True,
) -> QueryExecutor:
    return QueryExecutor(
        metadata_service=metadata_service,
        metadata_dir=metadata_dir,
        sql_validator=sql_validator,
        engine=engine,
        connection=connection,
        connection_factory=connection_factory,
        async_connection=async_connection,
        async_pool=async_pool,
        database_url=database_url,
        max_rows=max_rows,
        statement_timeout_ms=statement_timeout_ms,
        require_validated_sql=require_validated_sql,
    )


def to_plain_dict(value: Any) -> JsonDict:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): to_plain_value(v) for k, v in value.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_plain_dict(value.to_dict())
    if is_dataclass(value):
        return to_plain_dict(asdict(value))
    return {"value": to_plain_value(value)}


def to_plain_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): to_plain_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain_value(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_plain_value(value.to_dict())
    if is_dataclass(value):
        return to_plain_value(asdict(value))
    return str(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Lightweight local smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    # No real DB is required for this check. It proves the module imports and
    # handles status SQL locally.
    executor = QueryExecutor(require_validated_sql=False)
    print(
        executor.run(
            sql="SELECT 'DATA_GAP' AS status;",
            max_rows=5,
        )
    )
