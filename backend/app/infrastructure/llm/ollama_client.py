from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.hr_analytics.domain.entities import GenerationResult


class OllamaClient:
    """
    Implements ILLMClient using Ollama HTTP API.
    All configuration comes from settings — no hardcoded values.
    """

    def __init__(
        self,
        url: str | None = None,
        tags_url: str | None = None,
        default_model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        timeout: int | None = None,
    ) -> None:
        self._url = url or settings.ollama_url
        self._tags_url = tags_url or settings.ollama_tags_url
        self._model = default_model or settings.model_name
        self._temperature = temperature if temperature is not None else settings.model_temperature
        self._top_p = top_p if top_p is not None else settings.model_top_p
        self._timeout = timeout or settings.model_timeout

    async def generate(self, prompt: str, model: str | None = None) -> GenerationResult:
        payload = {
            "model": model or self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "top_p": self._top_p,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload)
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

    async def list_models(self) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(self._tags_url)
                response.raise_for_status()
                data = response.json()
                return [
                    {
                        "name": m.get("name", ""),
                        "size": _fmt_size(m.get("size", 0)),
                    }
                    for m in data.get("models", [])
                ]
        except Exception:
            return []

    async def health(self) -> dict[str, Any]:
        models = await self.list_models()
        online = bool(models)
        return {
            "online": online,
            "models": models,
            "message": "online" if online else "unreachable",
        }


def _fmt_size(size_bytes: int) -> str:
    if not size_bytes:
        return ""
    return f"{size_bytes / 1_073_741_824:.1f} GB"
