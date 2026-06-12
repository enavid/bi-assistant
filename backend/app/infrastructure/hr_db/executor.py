from __future__ import annotations

import time

import pandas as pd
import psycopg2

from app.core.config import settings
from app.hr_analytics.domain.entities import QueryResult


class HRQueryExecutor:
    """
    Implements IQueryExecutor for the HR PostgreSQL database.
    Uses psycopg2 sync driver — intentionally separate from the app DB.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        dbname: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host or settings.hr_db_host
        self._port = port or settings.hr_db_port
        self._dbname = dbname or settings.hr_db_name
        self._user = user or settings.hr_db_user
        self._password = password or settings.hr_db_password

    def run(self, sql: str) -> QueryResult:
        start = time.perf_counter()
        try:
            conn = psycopg2.connect(
                host=self._host,
                port=self._port,
                dbname=self._dbname,
                user=self._user,
                password=self._password,
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
