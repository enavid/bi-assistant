from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi_offline import FastAPIOffline
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.request_id import RequestIDMiddleware
from app.api.routes import chat, hr_bi, ollama, workspace
from app.core.config import settings
from app.core.logging import setup_logging
from app.infrastructure.db.models import Base  # noqa: F401
from app.infrastructure.db.session import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("Starting: env=%s log_level=%s", settings.app_env, settings.log_level)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    yield
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPIOffline(
    title="BI Assistant API",
    version="3.0.0",
    description="HR analytics assistant — controlled SQL pipeline with metadata, templates and validators.",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace.router)
app.include_router(chat.router)
app.include_router(hr_bi.router)
app.include_router(ollama.router)


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    return {"status": "ok", "version": "3.0.0", "env": settings.app_env}
