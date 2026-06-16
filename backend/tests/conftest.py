from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator
from app.infrastructure.metadata.service import get_metadata_service

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def _noop_lifespan(monkeypatch):
    """Replace the app lifespan with a no-op so TestClient tests never touch PostgreSQL."""
    import app.main as app_module

    @asynccontextmanager
    async def _noop(_app):
        yield

    monkeypatch.setattr(app_module.app.router, "lifespan_context", _noop)


@pytest.fixture(scope="session")
def metadata_service():
    metadata_dir = BACKEND_DIR / "metadata"
    return get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=True)


@pytest.fixture(scope="session")
def orchestrator(metadata_service):
    return LLMOrchestrator(
        metadata_service=metadata_service,
        intent_parser=IntentParser(metadata_service=metadata_service),
        question_validator=QuestionValidator(),
        default_execute_sql=False,
        strict_metadata=True,
    )
