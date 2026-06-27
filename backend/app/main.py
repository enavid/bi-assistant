from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_offline import FastAPIOffline

from app.connections.api import ollama_routes as connection_ollama_routes
from app.connections.api import routes as connection_routes
from app.core.config import APP_VERSION, settings
from app.core.logging import setup_logging
from app.evaluation.api import routes as eval_routes
from app.hr_analytics.api import chat_routes, ollama_routes
from app.hr_analytics.api import routes as hr_bi_routes
from app.infrastructure.db.models import Base  # noqa: F401
from app.infrastructure.db.session import engine
from app.middleware.request_id import RequestIDMiddleware
from app.workspace.api import routes as workspace_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("Starting: env=%s log_level=%s", settings.app_env, settings.log_level)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    await _restore_active_connections()
    await _reset_orphaned_eval_runs()
    await _seed_eval_defaults()
    yield
    await engine.dispose()
    logger.info("Shutdown complete")


async def _restore_active_connections() -> None:
    from urllib.parse import quote_plus

    from app.connections.active import set_active_dsn, set_active_ollama_base_url, set_model_config
    from app.connections.repositories.database_repository import QueryDatabaseRepository
    from app.connections.repositories.model_config_repository import ModelConfigRepository
    from app.connections.repositories.ollama_repository import OllamaConnectionRepository
    from app.infrastructure.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db_repo = QueryDatabaseRepository(db)
        active_db = await db_repo.get_active()
        if active_db:
            dsn = (
                f"postgresql+asyncpg://{quote_plus(active_db.username)}"
                f":{quote_plus(active_db.password)}"
                f"@{active_db.host}:{active_db.port}/{active_db.db_name}"
            )
            set_active_dsn(dsn)
            logger.info("Restored active query database: %s", active_db.name)

        ollama_repo = OllamaConnectionRepository(db)
        active_ollama = await ollama_repo.get_active()
        if active_ollama:
            set_active_ollama_base_url(active_ollama.base_url)
            logger.info("Restored active Ollama connection: %s", active_ollama.name)

        config_repo = ModelConfigRepository(db)
        configs = await config_repo.list_all()
        for cfg in configs:
            set_model_config(cfg.model_name, cfg.config_json)
        if configs:
            logger.info("Restored %d model config(s)", len(configs))


async def _seed_eval_defaults() -> None:
    from pathlib import Path

    from sqlalchemy import select

    from app.infrastructure.db.models import EvalQuestionORM, EvalQuestionSetORM
    from app.infrastructure.db.session import AsyncSessionLocal

    phase2_file = Path(__file__).parents[1] / "eval" / "phase2_trace_questions.json"
    if not phase2_file.exists():
        return

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(EvalQuestionSetORM).where(EvalQuestionSetORM.is_default == True)  # noqa: E712
            )
        ).scalar_one_or_none()
        if existing:
            return

        import json

        questions_data: list[dict] = json.loads(phase2_file.read_text(encoding="utf-8"))
        qs = EvalQuestionSetORM(
            name="Consultant Questions",
            description="240 consultant questions for evaluation",
            is_default=True,
        )
        db.add(qs)
        await db.flush()
        for q in questions_data:
            db.add(
                EvalQuestionORM(
                    set_id=qs.id,
                    question_id=q.get("question_id", ""),
                    question=q.get("question", ""),
                    category=q.get("category") or None,
                    expected_route=q.get("expected_route") or None,
                    expected_status=q.get("expected_status") or None,
                    expected_intent=q.get("expected_intent") or None,
                )
            )
        await db.commit()
        logger.info("Seeded %d default eval questions", len(questions_data))


async def _reset_orphaned_eval_runs(
    session_factory=None,
) -> None:
    from sqlalchemy import update

    from app.infrastructure.db.models import EvalRunORM
    from app.infrastructure.db.session import AsyncSessionLocal

    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        result = await db.execute(
            update(EvalRunORM)
            .where(EvalRunORM.status.in_(["pending", "running"]))
            .values(status="failed")
        )
        count = result.rowcount
        await db.commit()
    if count:
        logger.warning("Reset %d orphaned eval run(s) to 'failed' on startup", count)


app = FastAPIOffline(
    title="BI Assistant API",
    version=APP_VERSION,
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

app.include_router(connection_routes.router)
app.include_router(connection_ollama_routes.router)
app.include_router(workspace_routes.router)
app.include_router(chat_routes.router)
app.include_router(hr_bi_routes.router)
app.include_router(ollama_routes.router)
app.include_router(eval_routes.router)


@app.exception_handler(RuntimeError)
async def _runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION, "env": settings.app_env}
