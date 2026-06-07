from __future__ import annotations

from pydantic import BaseModel


class OllamaModelOut(BaseModel):
    name: str
    size: str = ""


class OllamaHealthResponse(BaseModel):
    online: bool
    models: list[OllamaModelOut]
    message: str
