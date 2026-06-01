from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import psycopg2

from app.core.config import settings


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    elapsed_ms: float
    success: bool
    error: str | None = None


def run_query(sql: str) -> QueryResult:
    """Execute a SELECT query against the HR PostgreSQL database."""
    start = time.perf_counter()
    try:
        conn = psycopg2.connect(
            host=settings.hr_db_host,
            port=settings.hr_db_port,
            dbname=settings.hr_db_name,
            user=settings.hr_db_user,
            password=settings.hr_db_password,
            connect_timeout=10,
        )
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
        return QueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0, success=False, error=f"Connection failed: {exc}")
    except Exception as exc:
        return QueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0, success=False, error=str(exc))
