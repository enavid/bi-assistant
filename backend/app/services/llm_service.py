from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import settings


@dataclass
class GenerationResult:
    sql: str
    success: bool
    error: str | None = None


@dataclass
class OllamaModel:
    name: str
    size: str = ""


@dataclass
class HealthResult:
    online: bool
    models: list[OllamaModel] = field(default_factory=list)
    message: str = ""


async def generate_sql(prompt: str, model_name: str | None = None) -> GenerationResult:
    model = model_name or settings.model_name
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": settings.model_temperature,
            "top_p": settings.model_top_p,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=settings.model_timeout) as client:
            response = await client.post(settings.ollama_url, json=payload)
            response.raise_for_status()
            sql = response.json().get("response", "").strip()
            return GenerationResult(sql=sql, success=True)
    except httpx.TimeoutException:
        return GenerationResult(sql="", success=False, error="Request timed out.")
    except httpx.ConnectError:
        return GenerationResult(sql="", success=False, error="Cannot connect to Ollama.")
    except httpx.HTTPStatusError as exc:
        return GenerationResult(sql="", success=False, error=f"HTTP {exc.response.status_code}")
    except Exception as exc:
        return GenerationResult(sql="", success=False, error=str(exc))


async def health_check() -> HealthResult:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(settings.ollama_tags_url)
            response.raise_for_status()
            data = response.json()
            models = [
                OllamaModel(
                    name=m.get("name", ""),
                    size=_format_size(m.get("size", 0)),
                )
                for m in data.get("models", [])
            ]
            return HealthResult(online=True, models=models, message="online")
    except Exception:
        return HealthResult(online=False, models=[], message="unreachable")


def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return ""
    gb = size_bytes / 1_073_741_824
    return f"{gb:.1f} GB"
