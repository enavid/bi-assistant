from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.infrastructure.metadata.service import get_metadata_service
from app.use_cases.hr_analytics.orchestrator import LLMOrchestrator

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def metadata_service():
    metadata_dir = BACKEND_DIR / "metadata"
    return get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=True)


@pytest.fixture(scope="session")
def orchestrator(metadata_service):
    return LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        strict_metadata=True,
    )
