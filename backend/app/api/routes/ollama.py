from __future__ import annotations

from fastapi import APIRouter

from app.schemas.schemas import OllamaHealthResponse, OllamaModel
from app.services.llm_service import health_check

router = APIRouter(prefix="/ollama", tags=["ollama"])


@router.get("/health", response_model=OllamaHealthResponse)
async def ollama_health() -> OllamaHealthResponse:
    result = await health_check()
    return OllamaHealthResponse(
        online=result.online,
        models=[OllamaModel(name=m.name, size=m.size) for m in result.models],
        message=result.message,
    )
