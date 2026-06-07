from __future__ import annotations

from app.domain.entities import ExperimentEntry, QueryResult
from app.domain.interfaces import IQueryExecutor


class RunQueryUseCase:
    """
    Executes a validated SQL query against the HR database.
    Optionally logs a successful run as an experiment entry.
    """

    def __init__(self, executor: IQueryExecutor) -> None:
        self._executor = executor

    def execute(self, sql: str) -> QueryResult:
        return self._executor.run(sql)

    def build_experiment(
        self,
        question: str,
        sql: str,
        result: QueryResult,
    ) -> ExperimentEntry | None:
        if not result.success:
            return None
        return ExperimentEntry(
            question=question,
            sql_output=sql,
            correct=True,
            elapsed_ms=result.elapsed_ms,
        )
