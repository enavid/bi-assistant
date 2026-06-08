from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

"""
llm_client.py
-------------
Optional LLM adapter for HR BI Assistant Phase 2.

This file intentionally keeps the model behind a small, controlled interface.
The backend can run without a model (provider=none). When an LLM is configured,
it is used only by fallback components such as SQL generation or explanation.

Supported providers through environment variables:

1) LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=llama3.1:8b

2) LLM_PROVIDER=openai_compatible
   OPENAI_COMPATIBLE_BASE_URL=https://api.example.com/v1
   OPENAI_API_KEY=...
   OPENAI_MODEL=gpt-4o-mini

3) LLM_PROVIDER=none  (default)
   No external/model call is made.
"""


JsonDict = dict[str, Any]


class LLMClientError(RuntimeError):
    pass


@dataclass
class LLMClientConfig:
    provider: str = field(default_factory=lambda: os.getenv(
        "LLM_PROVIDER", "none").strip().lower())
    timeout_seconds: int = field(default_factory=lambda: int(
        os.getenv("LLM_TIMEOUT_SECONDS", "60")))
    max_tokens: int = field(default_factory=lambda: int(
        os.getenv("LLM_MAX_TOKENS", "1200")))
    temperature: float = field(default_factory=lambda: float(
        os.getenv("LLM_TEMPERATURE", "0")))

    ollama_base_url: str = field(default_factory=lambda: os.getenv(
        "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"))
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1:8b"))

    openai_base_url: str = field(default_factory=lambda: os.getenv(
        "OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/"))
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


@dataclass
class LLMResult:
    status: str
    provider: str
    model: str | None = None
    text: str | None = None
    sql: str | None = None
    prompt_used: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class LLMClient:
    """Small synchronous LLM client with no mandatory external dependency."""

    def __init__(self, config: LLMClientConfig | None = None) -> None:
        self.config = config or LLMClientConfig()

    @property
    def is_configured(self) -> bool:
        if self.config.provider == "ollama":
            return bool(self.config.ollama_base_url and self.config.ollama_model)
        if self.config.provider in {"openai", "openai_compatible"}:
            return bool(self.config.openai_base_url and self.config.openai_api_key and self.config.openai_model)
        return False

    def generate_sql(self, prompt: str, *, system_prompt: str | None = None) -> LLMResult:
        """Generate SQL text and extract the first safe-looking SELECT/WITH statement."""
        if not self.is_configured:
            return LLMResult(
                status="LLM_NOT_CONFIGURED",
                provider=self.config.provider,
                prompt_used=False,
                warnings=[
                    "LLM provider is not configured; fallback prompt was not sent to a model."],
            )

        try:
            if self.config.provider == "ollama":
                text = self._generate_ollama(
                    prompt=prompt, system_prompt=system_prompt)
                model = self.config.ollama_model
            elif self.config.provider in {"openai", "openai_compatible"}:
                text = self._generate_openai_compatible(
                    prompt=prompt, system_prompt=system_prompt)
                model = self.config.openai_model
            else:
                raise LLMClientError(
                    f"Unsupported LLM_PROVIDER: {self.config.provider}")
            sql = self.extract_sql(text)
            return LLMResult(status="OK" if sql else "NO_SQL_EXTRACTED", provider=self.config.provider, model=model, text=text, sql=sql, prompt_used=True)
        except Exception as exc:
            return LLMResult(status="LLM_CALL_FAILED", provider=self.config.provider, errors=[f"{type(exc).__name__}: {exc}"], prompt_used=True)

    def _generate_ollama(self, *, prompt: str, system_prompt: str | None) -> str:
        url = f"{self.config.ollama_base_url}/api/generate"
        payload = {
            "model": self.config.ollama_model,
            "prompt": prompt if not system_prompt else f"{system_prompt}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": self.config.temperature, "num_predict": self.config.max_tokens},
        }
        return self._post_json(url, payload).get("response", "")

    def _generate_openai_compatible(self, *, prompt: str, system_prompt: str | None) -> str:
        url = f"{self.config.openai_base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.config.openai_api_key}"}
        data = self._post_json(url, payload, headers=headers)
        choices = data.get("choices") or []
        if not choices:
            return ""
        return ((choices[0].get("message") or {}).get("content") or "").strip()

    def _post_json(self, url: str, payload: JsonDict, *, headers: JsonDict | None = None) -> JsonDict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
                                     "Content-Type": "application/json", **(headers or {})}, method="POST")
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:  # noqa: S310 - configured internal endpoint/API
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def extract_sql(text: str | None) -> str | None:
        if not text:
            return None
        raw = text.strip()
        fenced = re.search(r"```(?:sql)?\s*(.*?)```", raw,
                           flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            raw = fenced.group(1).strip()
        # Remove common prose before the SQL statement.
        match = re.search(r"\b(WITH|SELECT)\b", raw, flags=re.IGNORECASE)
        if not match:
            return None
        sql = raw[match.start():].strip()
        # Keep exactly the first statement.
        if ";" in sql:
            sql = sql[: sql.index(";") + 1]
        else:
            sql = sql + ";"
        return sql.strip()


__all__ = ["LLMClient", "LLMClientConfig", "LLMResult", "LLMClientError"]
