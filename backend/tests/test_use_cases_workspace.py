from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.entities import QueryResult
from app.use_cases.workspace.run_query import RunQueryUseCase


def _make_executor(success: bool = True, columns=None, rows=None, error=None):
    executor = MagicMock()
    executor.run.return_value = QueryResult(
        columns=columns or ["count"],
        rows=rows or [[42]],
        row_count=1,
        elapsed_ms=10.0,
        success=success,
        error=error,
    )
    return executor


def test_run_query_use_case_execute_returns_result():
    executor = _make_executor(success=True, columns=["count"], rows=[[42]])
    uc = RunQueryUseCase(executor=executor)
    result = uc.execute("SELECT COUNT(*) FROM x;")
    assert result.success is True
    assert result.columns == ["count"]
    assert result.rows == [[42]]


def test_run_query_use_case_delegates_to_executor():
    executor = _make_executor()
    uc = RunQueryUseCase(executor=executor)
    uc.execute("SELECT 1;")
    executor.run.assert_called_once_with("SELECT 1;")


def test_build_experiment_returns_entry_on_success():
    executor = _make_executor(success=True)
    uc = RunQueryUseCase(executor=executor)
    result = QueryResult(columns=["c"], rows=[[1]], row_count=1, elapsed_ms=5.0, success=True)
    entry = uc.build_experiment(question="how many?", sql="SELECT 1;", result=result)
    assert entry is not None
    assert entry.question == "how many?"
    assert entry.sql_output == "SELECT 1;"
    assert entry.correct is True


def test_build_experiment_returns_none_on_failure():
    executor = _make_executor(success=False)
    uc = RunQueryUseCase(executor=executor)
    result = QueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0.0, success=False, error="db error")
    entry = uc.build_experiment(question="how many?", sql="SELECT 1;", result=result)
    assert entry is None
