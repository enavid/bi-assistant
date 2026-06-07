from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class SectionOut(BaseModel):
    id: str
    name: str
    content: str
    order: int
    created_at: datetime
    model_config = {"from_attributes": True}


class SectionCreate(BaseModel):
    name: str
    content: str = ""
    order: int = 0


class SectionUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    order: int | None = None


class ExperimentOut(BaseModel):
    id: str
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float
    comment: str
    created_at: datetime
    model_config = {"from_attributes": True}


class ExperimentCreate(BaseModel):
    question: str
    sql_output: str
    correct: bool
    elapsed_ms: float = 0.0
    comment: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    notes: str
    output_format: str
    sections: list[SectionOut] = []
    experiments: list[ExperimentOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    output_format: str | None = None
