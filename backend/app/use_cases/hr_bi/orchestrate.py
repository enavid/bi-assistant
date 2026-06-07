from __future__ import annotations

from typing import Any
from app.domain.entities import GenerationResult


class HRBIOrchestrationUseCase:
    """
    Facade for controlled SQL pipeline.
    Delegates to the hr_bi orchestrator from infrastructure.
    This use case exists to keep the API layer decoupled from hr_bi internals.
    """

    def __init__(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    async def generate(
        self,
        question: str,
        user_id: str | None = None,
        user_role: str = "demo_user",
        execute_sql: bool = False,
        model: str | None = None,
    ) -> GenerationResult:
        response = await self._orchestrator.arun(
            question,
            user_id=user_id,
            user_role=user_role,
            execute_sql=execute_sql,
        )
        payload = response.to_dict() if hasattr(response, "to_dict") else dict(response)

        sql = payload.get("generated_sql") or ""
        status = str(payload.get("status") or "")
        route = str(payload.get("route") or "")
        errors = payload.get("errors") or []
        rejected = status in {"ACCESS_DENIED", "OUT_OF_SCOPE",
                              "DATA_GAP", "SQL_VALIDATION_FAILED", "METADATA_ERROR"}
        success = bool(sql) and not rejected

        error = None
        if not success:
            error = payload.get("message_fa") or (
                errors[0] if errors else status or "Phase 2 did not generate SQL.")

        return GenerationResult(
            sql=sql,
            success=success,
            error=error,
            route=route,
            status=status,
            message=payload.get("message_fa"),
            detected_intent=payload.get("detected_intent"),
            warnings=payload.get("warnings") or [],
        )
