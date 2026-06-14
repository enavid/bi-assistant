from __future__ import annotations

from typing import Any

import httpx

from app.hr_analytics.domain.entities import GenerationResult

_DEFAULT_TEMPERATURE = 0.4
_DEFAULT_TOP_P = 0.5
_DEFAULT_TIMEOUT = 120


class OllamaClient:
    def __init__(
        self,
        url: str | None = None,
        tags_url: str | None = None,
        default_model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        timeout: int | None = None,
        model_configs: dict[str, dict] | None = None,
    ) -> None:
        self._url = url or ""
        self._tags_url = tags_url or ""
        self._model = default_model or ""
        self._temperature = temperature if temperature is not None else _DEFAULT_TEMPERATURE
        self._top_p = top_p if top_p is not None else _DEFAULT_TOP_P
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._model_configs: dict[str, dict] = model_configs or {}

    async def generate(self, prompt: str, model: str | None = None) -> GenerationResult:
        target_model = model or self._model
        model_cfg = self._model_configs.get(target_model, {})

        options: dict = {
            "temperature": model_cfg.get("temperature", self._temperature),
            "top_p": model_cfg.get("top_p", self._top_p),
        }
        if "num_ctx" in model_cfg:
            options["num_ctx"] = model_cfg["num_ctx"]
        if "think" in model_cfg:
            options["think"] = model_cfg["think"]
        for key, val in model_cfg.items():
            if key not in ("temperature", "top_p", "num_ctx", "think"):
                options[key] = val

        payload = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        context_window: int | None = model_cfg.get("num_ctx")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload)
                response.raise_for_status()
                data = response.json()
                sql = data.get("response", "").strip()
                prompt_tokens: int | None = data.get("prompt_eval_count")
                return GenerationResult(
                    sql=sql,
                    success=True,
                    prompt_tokens=prompt_tokens,
                    context_window=context_window,
                )
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
