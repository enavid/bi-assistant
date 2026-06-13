from __future__ import annotations

import time

import pandas as pd
import psycopg2

from app.hr_analytics.domain.entities import QueryResult


class HRQueryExecutor:
    """
    Executes raw SQL against the active query database using psycopg2.
    Accepts a full postgresql+asyncpg:// DSN and strips the driver prefix.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    def run(self, sql: str) -> QueryResult:
        start = time.perf_counter()
        try:
            conn = psycopg2.connect(self._dsn, connect_timeout=10)
            df: pd.DataFrame = pd.read_sql_query(sql, conn)
            conn.close()
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            return QueryResult(
                columns=list(df.columns),
                rows=[[None if pd.isna(v) else v for v in row] for row in df.values.tolist()],
                row_count=len(df),
                elapsed_ms=elapsed_ms,
                success=True,
            )
        except psycopg2.OperationalError as exc:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                elapsed_ms=0,
                success=False,
                error=f"Connection failed: {exc}",
            )
        except Exception as exc:
            return QueryResult(
                columns=[], rows=[], row_count=0, elapsed_ms=0, success=False, error=str(exc)
            )
