from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EvalQuestionSetCreate(BaseModel):
    name: str
    description: str = ""


class EvalQuestionSetOut(BaseModel):
    id: str
    name: str
    description: str
    is_default: bool = False
    created_at: datetime
    question_count: int = 0
    model_config = {"from_attributes": True}


class TriggerRunRequest(BaseModel):
    category: str | None = None
    model_name: str | None = None
    question_ids: list[str] | None = None


class EvalQuestionIn(BaseModel):
    question_id: str
    question: str
    category: str | None = None
    expected_route: str | None = None
    expected_status: str | None = None
    expected_intent: str | None = None


class EvalQuestionOut(BaseModel):
    id: str
    question_id: str
    question: str
    category: str | None = None
    expected_route: str | None = None
    expected_status: str | None = None
    expected_intent: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class BulkImportResult(BaseModel):
    imported: int


class EvalRunOut(BaseModel):
    id: str
    set_id: str
    status: str
    model_name: str | None = None
    total: int
    passed: int
    failed: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    current_question_idx: int | None = None
    question_ids_ordered: list[str] | None = None
    results: list[EvalRunResultOut] = []
    model_config = {"from_attributes": True}


class EvalRunResultOut(BaseModel):
    id: str
    run_id: str
    question_id: str
    question: str
    category: str | None = None
    actual_route: str | None = None
    actual_status: str | None = None
    actual_intent: str | None = None
    source: str | None = None
    model_called: str | None = None
    template_id: str | None = None
    sql_validator_status: str | None = None
    executed: bool
    row_count: int | None = None
    visualization: str | None = None
    total_duration_ms: float
    passed: bool
    trace_steps: list | None = None
    error: str | None = None
    warnings: list | None = None
    model_config = {"from_attributes": True}
