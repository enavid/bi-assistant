from __future__ import annotations

from app.hr_analytics.domain.entities import QueryResult
from app.hr_analytics.domain.interfaces import IQueryExecutor
from app.workspace.domain.entities import ExperimentEntry


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
            correct=None,
            elapsed_ms=result.elapsed_ms,
        )
