from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HRBIRequest(BaseModel):
    question: str = Field(..., min_length=2)
    user_id: str | None = None
    user_role: str = "demo_user"
    execute_sql: bool | None = None
    runtime_params: dict[str, Any] = Field(default_factory=dict)


class HRBIResponse(BaseModel):
    request_id: str
    route: str
    status: str
    message_fa: str
    detected_intent: str | None = None
    generated_sql: str | None = None
    data: Any = None
    visualization: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
