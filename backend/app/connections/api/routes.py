from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.active import set_active_dsn
from app.connections.api.schemas import (
    DeactivateResult,
    QueryDatabaseCreate,
    QueryDatabaseOut,
    QueryDatabaseUpdate,
    TestConnectionRequest,
    TestConnectionResult,
)
from app.connections.repositories.database_repository import QueryDatabaseRepository
from app.infrastructure.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


def _repo(db: AsyncSession = Depends(get_db)) -> QueryDatabaseRepository:
    return QueryDatabaseRepository(db)


@router.get("/databases", response_model=list[QueryDatabaseOut])
async def list_databases(repo: QueryDatabaseRepository = Depends(_repo)):
    rows = await repo.list()
    return [QueryDatabaseOut.from_orm_safe(r) for r in rows]


@router.post("/databases", response_model=QueryDatabaseOut, status_code=201)
async def create_database(
    body: QueryDatabaseCreate, repo: QueryDatabaseRepository = Depends(_repo)
):
    row = await repo.create(
        name=body.name,
        host=body.host,
        port=body.port,
        db_name=body.db_name,
        username=body.username,
        password=body.password,
    )
    return QueryDatabaseOut.from_orm_safe(row)


@router.get("/databases/{id}", response_model=QueryDatabaseOut)
async def get_database(id: str, repo: QueryDatabaseRepository = Depends(_repo)):
    row = await repo.get(id)
    if not row:
        raise HTTPException(status_code=404, detail="Database connection not found")
    return QueryDatabaseOut.from_orm_safe(row)


@router.patch("/databases/{id}", response_model=QueryDatabaseOut)
async def update_database(
    id: str, body: QueryDatabaseUpdate, repo: QueryDatabaseRepository = Depends(_repo)
):
    row = await repo.update(
        id,
        **{k: v for k, v in body.model_dump().items() if v is not None},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Database connection not found")
    return QueryDatabaseOut.from_orm_safe(row)


@router.delete("/databases/{id}", status_code=204)
async def delete_database(id: str, repo: QueryDatabaseRepository = Depends(_repo)):
    deleted = await repo.delete(id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Database connection not found")


@router.post("/databases/deactivate", response_model=DeactivateResult)
async def deactivate_databases(repo: QueryDatabaseRepository = Depends(_repo)):
    await repo.deactivate_all()
    set_active_dsn(None)
    _clear_orchestrator_cache()
    return DeactivateResult(success=True)


@router.post("/databases/test", response_model=TestConnectionResult)
async def test_connection(body: TestConnectionRequest):
    from urllib.parse import quote_plus

    dsn = f"postgresql+asyncpg://{quote_plus(body.username)}:{quote_plus(body.password)}@{body.host}:{body.port}/{body.db_name}"
    start = time.monotonic()
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(dsn, connect_args={"timeout": 5})
        async with engine.connect():
            pass
        await engine.dispose()
        latency_ms = (time.monotonic() - start) * 1000
        return TestConnectionResult(success=True, latency_ms=round(latency_ms, 1))
    except Exception as exc:
        return TestConnectionResult(success=False, error=str(exc))


@router.post("/databases/{id}/activate", response_model=QueryDatabaseOut)
async def activate_database(id: str, repo: QueryDatabaseRepository = Depends(_repo)):
    row = await repo.activate(id)
    if not row:
        raise HTTPException(status_code=404, detail="Database connection not found")
    from urllib.parse import quote_plus

    dsn = f"postgresql+asyncpg://{quote_plus(row.username)}:{quote_plus(row.password)}@{row.host}:{row.port}/{row.db_name}"
    set_active_dsn(dsn)
    _clear_orchestrator_cache()
    logger.info(
        "Activated query database: %s (%s:%s/%s)", row.name, row.host, row.port, row.db_name
    )
    return QueryDatabaseOut.from_orm_safe(row)


def _clear_orchestrator_cache() -> None:
    try:
        from app.dependencies import get_hr_bi_orchestrator

        get_hr_bi_orchestrator.cache_clear()
    except Exception:
        pass
