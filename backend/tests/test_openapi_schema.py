"""OpenAPI/Swagger completeness guards (Phase 2.2).

Endpoints should expose typed request bodies (not free-form ``dict``) and a
human-readable ``summary`` so ``/docs`` is self-describing and request payloads
are validated.
"""

from __future__ import annotations

import pytest

from app.main import app


@pytest.fixture(scope="module")
def openapi_schema() -> dict:
    return app.openapi()


def _resolve(schema: dict, node: dict) -> dict:
    """Resolve a possible local $ref against the document's components."""
    ref = node.get("$ref")
    if not ref:
        return node
    name = ref.split("/")[-1]
    return schema.get("components", {}).get("schemas", {}).get(name, {})


def test_add_message_has_typed_request_body(openapi_schema):
    """POST /chat/sessions/{id}/messages must declare a typed body, not raw dict."""
    paths = openapi_schema["paths"]
    op = paths["/chat/sessions/{session_id}/messages"]["post"]
    body_schema = op["requestBody"]["content"]["application/json"]["schema"]
    resolved = _resolve(openapi_schema, body_schema)
    properties = resolved.get("properties", {})
    assert "role" in properties, resolved
    assert "content" in properties, resolved


# FastAPI auto-derives a summary from the function name, so "has a summary" is
# always true. The real gap the review flagged is dynamic `-> dict` endpoints
# whose purpose is opaque in /docs; these get explicit, curated summaries.
_CURATED_SUMMARIES = {
    ("get", "/connections/system-databases"): "List server-side system databases",
    ("get", "/connections/ollama/{id}/models"): "List models available on an Ollama connection",
    (
        "get",
        "/connections/ollama/{id}/model-info/{model_name}",
    ): "Inspect a model's metadata on an Ollama connection",
}


@pytest.mark.parametrize(
    ("method", "path", "summary"), [(*k, v) for k, v in _CURATED_SUMMARIES.items()]
)
def test_dynamic_dict_endpoints_have_curated_summaries(openapi_schema, method, path, summary):
    op = openapi_schema["paths"][path][method]
    assert op.get("summary") == summary
