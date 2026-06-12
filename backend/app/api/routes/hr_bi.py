from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.dependencies import get_hr_bi_orchestrator
from app.api.schemas import HRBIRequest, HRBIResponse
from app.core.config import settings
from app.use_cases.hr_analytics.orchestrate import HRBIOrchestrationUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hr-bi", tags=["hr-bi"])


@router.get("/health", summary="Metadata and pipeline health")
async def hr_bi_health() -> dict[str, Any]:
    try:
        from app.infrastructure.metadata.loader import get_metadata

        metadata = get_metadata()
        health = (
            metadata.health_check().to_dict() if hasattr(metadata, "health_check") else {"ok": True}
        )
        return {
            "status": "ok" if health.get("ok", True) else "metadata_warning",
            "metadata": health,
            "view": "hr_mvp.vw_hr_employee_analytics",
            "default_execute_sql": settings.default_execute_sql,
            "current_shamsi_year": settings.current_shamsi_year,
        }
    except Exception as exc:
        logger.error("HR BI health check failed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Health check failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/chat", response_model=HRBIResponse, summary="HR analytics pipeline with execution")
async def hr_bi_chat(request: HRBIRequest) -> dict[str, Any]:
    try:
        orchestrator = get_hr_bi_orchestrator()
        response = await orchestrator.arun(
            request.question,
            user_id=request.user_id,
            user_role=request.user_role,
            execute_sql=request.execute_sql
            if request.execute_sql is not None
            else settings.default_execute_sql,
            runtime_params=request.runtime_params,
        )
        return response.to_dict()
    except Exception as exc:
        logger.error("HR BI chat failed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"HR BI chat failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/generate", summary="SQL generation only")
async def hr_bi_generate(request: HRBIRequest) -> dict[str, Any]:
    try:
        orchestrator = get_hr_bi_orchestrator()
        uc = HRBIOrchestrationUseCase(orchestrator)
        result = await uc.generate(
            request.question,
            user_id=request.user_id,
            user_role=request.user_role,
            execute_sql=False,
        )
        return {
            "sql": result.sql,
            "success": result.success,
            "error": result.error,
            "route": result.route,
            "status": result.status,
            "message_fa": result.message,
            "detected_intent": result.detected_intent,
            "warnings": result.warnings,
        }
    except Exception as exc:
        logger.error("HR BI generate failed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"HR BI generate failed: {type(exc).__name__}: {exc}"
        ) from exc
