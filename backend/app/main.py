from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, ollama, workspace
from app.core.config import settings

app = FastAPI(
    title="BI Assistant API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace.router)
app.include_router(chat.router)
app.include_router(ollama.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
