from __future__ import annotations

from typing import Any

from app.hr_analytics.domain.entities import GenerationResult


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
        rejected = status in {
            "ACCESS_DENIED",
            "OUT_OF_SCOPE",
            "DATA_GAP",
            "ANALYTICAL_GAP",
            "SQL_VALIDATION_FAILED",
            "METADATA_ERROR",
        }
        success = bool(sql) and not rejected

        error = None
        if not success:
            error = payload.get("message_fa") or (
                errors[0] if errors else status or "Phase 2 did not generate SQL."
            )

        ctx = payload.get("context") or {}
        traces = ctx.get("traces") or []
        sql_plan = ctx.get("sql_plan") or {}
        query_result = ctx.get("query_result") or {}
        source = sql_plan.get("source") or _derive_source(route, status)
        template_id = sql_plan.get("template_id") or sql_plan.get("report_id")
        llm_meta = sql_plan.get("metadata") or {}
        model_called = llm_meta.get("model") if isinstance(llm_meta, dict) else None
        execution_status = str(query_result.get("execution_status") or "")
        executed = execution_status == "SUCCESS"
        rows = query_result.get("rows") or []
        row_count = len(rows) if executed else None

        return GenerationResult(
            sql=sql,
            success=success,
            error=error,
            route=route,
            status=status,
            message=payload.get("message_fa"),
            detected_intent=payload.get("detected_intent"),
            warnings=payload.get("warnings") or [],
            traces=traces,
            source=source,
            template_id=str(template_id) if template_id else None,
            executed=executed,
            row_count=row_count,
            model_called=str(model_called) if model_called else None,
        )


def _derive_source(route: str, status: str) -> str:
    if status in {"ACCESS_DENIED", "OUT_OF_SCOPE"} or route == "REJECT":
        return "reject"
    if status in {"DATA_GAP", "ANALYTICAL_GAP"} or route == "GAP":
        return "gap"
    if status == "NEEDS_CLARIFICATION" or route == "NEEDS_CLARIFICATION":
        return "clarification"
    return "unknown"
