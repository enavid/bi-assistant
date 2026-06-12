from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_offline import FastAPIOffline

from app.api.middleware.request_id import RequestIDMiddleware
from app.api.routes import chat, eval, hr_bi, ollama, workspace
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
    await _seed_eval_defaults()
    yield
    await engine.dispose()
    logger.info("Shutdown complete")


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
app.include_router(eval.router)


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    return {"status": "ok", "version": "3.0.0", "env": settings.app_env}
