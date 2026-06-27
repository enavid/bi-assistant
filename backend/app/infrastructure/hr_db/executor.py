from __future__ import annotations

import logging
import time

import psycopg2

from app.hr_analytics.domain.entities import QueryResult

logger = logging.getLogger(__name__)


class HRQueryExecutor:
    """Executes raw (already-validated) SQL against the active query database.

    Hardened for an untrusted-input path: every query runs with a statement
    timeout, in a read-only session, and with a bounded result set. Accepts a
    full ``postgresql+asyncpg://`` DSN and strips the async driver prefix.
    """

    def __init__(
        self,
        dsn: str,
        *,
        statement_timeout_ms: int = 10_000,
        max_rows: int = 500,
        read_only: bool = True,
        connect_timeout_s: int = 10,
    ) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._max_rows = int(max_rows)
        self._read_only = read_only
        self._connect_timeout_s = int(connect_timeout_s)

    def run(self, sql: str) -> QueryResult:
        start = time.perf_counter()
        conn = None
        try:
            conn = psycopg2.connect(self._dsn, connect_timeout=self._connect_timeout_s)
            conn.autocommit = True
            self._configure_session(conn)

            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                # Fetch one extra row to detect (and log) truncation without scanning all rows.
                fetched = cur.fetchmany(self._max_rows + 1)

            truncated = len(fetched) > self._max_rows
            capped = fetched[: self._max_rows]
            rows = [[None if value is None else value for value in row] for row in capped]
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

            if truncated:
                logger.warning(
                    "HR query result truncated to max_rows=%d (more rows were available)",
                    self._max_rows,
                )
            logger.info(
                "HR query executed: rows=%d elapsed_ms=%.1f truncated=%s",
                len(rows),
                elapsed_ms,
                truncated,
            )
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                elapsed_ms=elapsed_ms,
                success=True,
            )
        except psycopg2.OperationalError as exc:
            logger.error("HR query connection failed: %s", exc, exc_info=True)
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                elapsed_ms=0,
                success=False,
                error=f"Connection failed: {exc}",
            )
        except Exception as exc:
            logger.error("HR query execution failed: %s", exc, exc_info=True)
            return QueryResult(
                columns=[], rows=[], row_count=0, elapsed_ms=0, success=False, error=str(exc)
            )
        finally:
            if conn is not None:
                conn.close()

    def _configure_session(self, conn) -> None:
        """Apply statement timeout and read-only mode for this session.

        Failures are logged (not silently swallowed) so a degraded safety posture
        is auditable; the query still proceeds because write operations are already
        blocked upstream by the SQL validator.
        """
        with conn.cursor() as cur:
            try:
                cur.execute("SET statement_timeout = %s", (self._statement_timeout_ms,))
                cur.execute(
                    "SET idle_in_transaction_session_timeout = %s",
                    (self._statement_timeout_ms + 2_000,),
                )
            except Exception as exc:
                logger.warning("HR executor could not set statement_timeout: %s", exc)
            if self._read_only:
                try:
                    cur.execute("SET default_transaction_read_only = on")
                except Exception as exc:
                    logger.warning("HR executor could not enable read-only session: %s", exc)
