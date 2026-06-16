from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.active import (
    remove_model_config,
    set_active_ollama_base_url,
    set_model_config,
)
from app.connections.api.schemas import (
    DeactivateResult,
    ModelConfigOut,
    ModelConfigUpsert,
    OllamaConnectionCreate,
    OllamaConnectionOut,
    OllamaConnectionUpdate,
    OllamaTestRequest,
    OllamaTestResult,
)
from app.connections.repositories.model_config_repository import ModelConfigRepository
from app.connections.repositories.ollama_repository import OllamaConnectionRepository
from app.infrastructure.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


def _ollama_repo(db: AsyncSession = Depends(get_db)) -> OllamaConnectionRepository:
    return OllamaConnectionRepository(db)


def _config_repo(db: AsyncSession = Depends(get_db)) -> ModelConfigRepository:
    return ModelConfigRepository(db)


# ---------------------------------------------------------------------------
# Ollama connections
# ---------------------------------------------------------------------------


@router.get("/ollama", response_model=list[OllamaConnectionOut])
async def list_ollama(repo: OllamaConnectionRepository = Depends(_ollama_repo)):
    rows = await repo.list()
    return [OllamaConnectionOut.from_orm_safe(r) for r in rows]


@router.post("/ollama", response_model=OllamaConnectionOut, status_code=201)
async def create_ollama(
    body: OllamaConnectionCreate, repo: OllamaConnectionRepository = Depends(_ollama_repo)
):
    row = await repo.create(name=body.name, base_url=body.base_url)
    return OllamaConnectionOut.from_orm_safe(row)


@router.get("/ollama/{id}", response_model=OllamaConnectionOut)
async def get_ollama(id: str, repo: OllamaConnectionRepository = Depends(_ollama_repo)):
    row = await repo.get(id)
    if not row:
        raise HTTPException(status_code=404, detail="Ollama connection not found")
    return OllamaConnectionOut.from_orm_safe(row)


@router.patch("/ollama/{id}", response_model=OllamaConnectionOut)
async def update_ollama(
    id: str,
    body: OllamaConnectionUpdate,
    repo: OllamaConnectionRepository = Depends(_ollama_repo),
):
    row = await repo.update(id, **{k: v for k, v in body.model_dump().items() if v is not None})
    if not row:
        raise HTTPException(status_code=404, detail="Ollama connection not found")
    return OllamaConnectionOut.from_orm_safe(row)


@router.delete("/ollama/{id}", status_code=204)
async def delete_ollama(id: str, repo: OllamaConnectionRepository = Depends(_ollama_repo)):
    if not await repo.delete(id):
        raise HTTPException(status_code=404, detail="Ollama connection not found")


@router.post("/ollama/deactivate", response_model=DeactivateResult)
async def deactivate_ollama(repo: OllamaConnectionRepository = Depends(_ollama_repo)):
    await repo.deactivate_all()
    set_active_ollama_base_url(None)
    _clear_llm_cache()
    return DeactivateResult(success=True)


@router.post("/ollama/test", response_model=OllamaTestResult)
async def test_ollama_connection(body: OllamaTestRequest):
    tags_url = body.base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(tags_url)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return OllamaTestResult(success=True, models=models)
    except Exception as exc:
        return OllamaTestResult(success=False, error=str(exc))


@router.get("/ollama/{id}/model-info/{model_name:path}")
async def get_ollama_model_info_by_connection(
    id: str, model_name: str, repo: OllamaConnectionRepository = Depends(_ollama_repo)
) -> dict:
    row = await repo.get(id)
    if not row:
        raise HTTPException(status_code=404, detail="Ollama connection not found")
    show_url = row.base_url.rstrip("/") + "/api/show"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(show_url, json={"name": model_name})
            resp.raise_for_status()
            data = resp.json()
            return {
                "parameters": _parse_parameters(data.get("parameters", "")),
                "details": data.get("details", {}),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama: {exc}") from exc


@router.get("/ollama/{id}/models")
async def get_ollama_models(
    id: str, repo: OllamaConnectionRepository = Depends(_ollama_repo)
) -> dict:
    row = await repo.get(id)
    if not row:
        raise HTTPException(status_code=404, detail="Ollama connection not found")
    tags_url = row.base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(tags_url)
            resp.raise_for_status()
            models = [
                {"name": m.get("name", ""), "size": _fmt_size(m.get("size", 0))}
                for m in resp.json().get("models", [])
            ]
            return {"models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama: {exc}") from exc


@router.post("/ollama/{id}/activate", response_model=OllamaConnectionOut)
async def activate_ollama(id: str, repo: OllamaConnectionRepository = Depends(_ollama_repo)):
    row = await repo.activate(id)
    if not row:
        raise HTTPException(status_code=404, detail="Ollama connection not found")
    set_active_ollama_base_url(row.base_url)
    _clear_llm_cache()
    logger.info("Activated Ollama connection: %s (%s)", row.name, row.base_url)
    return OllamaConnectionOut.from_orm_safe(row)


# ---------------------------------------------------------------------------
# Model configs
# ---------------------------------------------------------------------------


@router.get("/model-configs", response_model=list[ModelConfigOut])
async def list_model_configs(repo: ModelConfigRepository = Depends(_config_repo)):
    rows = await repo.list_all()
    return [ModelConfigOut.from_orm_safe(r) for r in rows]


@router.get("/model-configs/{model_name}", response_model=ModelConfigOut)
async def get_model_config(model_name: str, repo: ModelConfigRepository = Depends(_config_repo)):
    row = await repo.get(model_name)
    if not row:
        raise HTTPException(status_code=404, detail="No saved config for this model")
    return ModelConfigOut.from_orm_safe(row)


@router.put("/model-configs/{model_name}", response_model=ModelConfigOut)
async def save_model_config(
    model_name: str,
    body: ModelConfigUpsert,
    repo: ModelConfigRepository = Depends(_config_repo),
):
    row = await repo.upsert(model_name, body.config_json)
    set_model_config(model_name, body.config_json)
    _clear_llm_cache()
    return ModelConfigOut.from_orm_safe(row)


@router.delete("/model-configs/{model_name}", status_code=204)
async def delete_model_config(model_name: str, repo: ModelConfigRepository = Depends(_config_repo)):
    deleted = await repo.delete(model_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="No saved config for this model")
    remove_model_config(model_name)
    _clear_llm_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_parameters(raw: str) -> dict:
    """Parse Ollama /api/show parameters string into a dict."""
    result: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0], parts[1].strip()
        parsed = _coerce(value)
        if key in result:
            existing = result[key]
            if isinstance(existing, list):
                existing.append(parsed)
            else:
                result[key] = [existing, parsed]
        else:
            result[key] = parsed
    return result


def _coerce(value: str):
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip('"').strip("'")


def _fmt_size(size_bytes: int) -> str:
    if not size_bytes:
        return ""
    return f"{size_bytes / 1_073_741_824:.1f} GB"


def _clear_llm_cache() -> None:
    try:
        from app.dependencies import get_hr_bi_orchestrator, get_llm_client

        get_llm_client.cache_clear()
        get_hr_bi_orchestrator.cache_clear()
    except Exception:
        pass
