from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    sql: str
    success: bool
    error: str | None = None
    route: str | None = None
    status: str | None = None
    message: str | None = None
    detected_intent: str | None = None
    warnings: list[str] = field(default_factory=list)
    traces: list[dict] = field(default_factory=list)
    source: str | None = None
    template_id: str | None = None
    executed: bool = False
    row_count: int | None = None
    model_called: str | None = None


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    elapsed_ms: float
    success: bool
    error: str | None = None
