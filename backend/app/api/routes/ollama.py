from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_llm_client
from app.api.schemas import OllamaHealthResponse, OllamaModelOut
from app.infrastructure.llm.ollama_client import OllamaClient

router = APIRouter(prefix="/ollama", tags=["ollama"])


@router.get("/health", response_model=OllamaHealthResponse, summary="Ollama health and available models")
async def ollama_health(client: OllamaClient = Depends(get_llm_client)) -> OllamaHealthResponse:
    data = await client.health()
    return OllamaHealthResponse(
        online=data["online"],
        models=[OllamaModelOut(name=m["name"], size=m.get("size", "")) for m in data["models"]],
        message=data["message"],
    )
