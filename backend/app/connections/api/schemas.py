from __future__ import annotations

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
