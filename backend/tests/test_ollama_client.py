"""Unit tests for OllamaClient.

These tests mock httpx so no real Ollama server is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.llm.ollama_client import OllamaClient


def _make_client() -> OllamaClient:
    return OllamaClient(
        url="http://fake-ollama:11434/api/generate",
        default_model="test-model",
    )


def _mock_response(response_text: str, prompt_eval_count: int | None = None) -> MagicMock:
    data: dict = {"response": response_text}
    if prompt_eval_count is not None:
        data["prompt_eval_count"] = prompt_eval_count
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# Existing behaviour — must not regress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_sql_on_success():
    client = _make_client()
    mock_resp = _mock_response("SELECT COUNT(*) FROM employees;", prompt_eval_count=100)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.return_value = mock_resp

        result = await client.generate("give me SQL")

    assert result.success is True
    assert "SELECT" in result.sql


@pytest.mark.asyncio
async def test_generate_returns_error_on_timeout():
    import httpx

    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.side_effect = httpx.TimeoutException("timeout")

        result = await client.generate("give me SQL")

    assert result.success is False
    assert "timed out" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Phase 1.3 — prompt_tokens captured from Ollama response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_prompt_tokens_when_present():
    client = _make_client()
    mock_resp = _mock_response("SELECT 1;", prompt_eval_count=7536)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.return_value = mock_resp

        result = await client.generate("give me SQL")

    assert result.prompt_tokens == 7536


@pytest.mark.asyncio
async def test_generate_prompt_tokens_is_none_when_absent():
    client = _make_client()
    mock_resp = _mock_response("SELECT 1;", prompt_eval_count=None)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.return_value = mock_resp

        result = await client.generate("give me SQL")

    assert result.prompt_tokens is None


@pytest.mark.asyncio
async def test_generate_context_window_reflected_in_result():
    """When num_ctx is set in model_configs it should appear in result.context_window."""
    client = OllamaClient(
        url="http://fake-ollama:11434/api/generate",
        default_model="test-model",
        model_configs={"test-model": {"num_ctx": 16384}},
    )
    mock_resp = _mock_response("SELECT 1;", prompt_eval_count=500)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_http
        mock_http.post.return_value = mock_resp

        result = await client.generate("give me SQL")

    assert result.context_window == 16384
