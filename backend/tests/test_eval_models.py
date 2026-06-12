"""Tests for eval DB models — written before implementation (TDD)."""

from __future__ import annotations

from app.infrastructure.db.models import (
    EvalQuestionORM,
    EvalQuestionSetORM,
    EvalRunORM,
    EvalRunResultORM,
)


def test_eval_question_set_tablename() -> None:
    assert EvalQuestionSetORM.__tablename__ == "eval_question_sets"


def test_eval_question_tablename() -> None:
    assert EvalQuestionORM.__tablename__ == "eval_questions"


def test_eval_run_tablename() -> None:
    assert EvalRunORM.__tablename__ == "eval_runs"


def test_eval_run_result_tablename() -> None:
    assert EvalRunResultORM.__tablename__ == "eval_run_results"


def test_eval_question_set_has_required_columns() -> None:
    cols = {c.key for c in EvalQuestionSetORM.__table__.columns}
    assert {"id", "name", "description", "created_at"}.issubset(cols)


def test_eval_question_has_required_columns() -> None:
    cols = {c.key for c in EvalQuestionORM.__table__.columns}
    assert {
        "id",
        "set_id",
        "question_id",
        "question",
        "category",
        "expected_route",
        "expected_status",
        "expected_intent",
    }.issubset(cols)


def test_eval_run_has_required_columns() -> None:
    cols = {c.key for c in EvalRunORM.__table__.columns}
    assert {
        "id",
        "set_id",
        "status",
        "total",
        "passed",
        "failed",
        "started_at",
        "finished_at",
    }.issubset(cols)


def test_eval_run_result_has_required_columns() -> None:
    cols = {c.key for c in EvalRunResultORM.__table__.columns}
    assert {
        "id",
        "run_id",
        "question_id",
        "question",
        "category",
        "actual_route",
        "actual_status",
        "actual_intent",
        "source",
        "model_called",
        "template_id",
        "sql_validator_status",
        "executed",
        "row_count",
        "visualization",
        "total_duration_ms",
        "passed",
        "trace_steps",
        "error",
        "warnings",
    }.issubset(cols)


def test_eval_question_set_to_question_relationship() -> None:
    assert hasattr(EvalQuestionSetORM, "questions")


def test_eval_question_set_to_run_relationship() -> None:
    assert hasattr(EvalQuestionSetORM, "runs")


def test_eval_run_to_result_relationship() -> None:
    assert hasattr(EvalRunORM, "results")
