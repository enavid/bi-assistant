from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryDatabaseCreate(BaseModel):
    name: str
    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    db_name: str
    username: str
    password: str


class QueryDatabaseUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    db_name: str | None = None
    username: str | None = None
    password: str | None = None


class QueryDatabaseOut(BaseModel):
    id: str
    name: str
    host: str
    port: int
    db_name: str
    username: str
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_safe(cls, row) -> QueryDatabaseOut:
        return cls(
            id=row.id,
            name=row.name,
            host=row.host,
            port=row.port,
            db_name=row.db_name,
            username=row.username,
            is_active=row.is_active,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# Ollama connections
# ---------------------------------------------------------------------------


class OllamaConnectionCreate(BaseModel):
    name: str
    base_url: str


class OllamaConnectionUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None


class OllamaConnectionOut(BaseModel):
    id: str
    name: str
    base_url: str
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm_safe(cls, row) -> OllamaConnectionOut:
        return cls(
            id=row.id,
            name=row.name,
            base_url=row.base_url,
            is_active=row.is_active,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )


class OllamaTestRequest(BaseModel):
    base_url: str


class OllamaTestResult(BaseModel):
    success: bool
    error: str | None = None
    models: list[str] = []


# ---------------------------------------------------------------------------
# Model configs
# ---------------------------------------------------------------------------


class ModelConfigUpsert(BaseModel):
    config_json: dict[str, Any]


class ModelConfigOut(BaseModel):
    model_name: str
    config_json: dict[str, Any]
    updated_at: str

    @classmethod
    def from_orm_safe(cls, row) -> ModelConfigOut:
        return cls(
            model_name=row.model_name,
            config_json=row.config_json,
            updated_at=row.updated_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# Query database connections (existing)
# ---------------------------------------------------------------------------


class TestConnectionRequest(BaseModel):
    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    db_name: str
    username: str
    password: str


class TestConnectionResult(BaseModel):
    success: bool
    error: str | None = None
    latency_ms: float | None = None


class DeactivateResult(BaseModel):
    success: bool
