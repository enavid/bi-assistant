from __future__ import annotations

"""
conftest.py
-----------
Shared pytest fixtures for HR BI Assistant Phase 2 tests.

TDD contract:
- All tests must be runnable with: pytest tests -q
- No real DB connection required for unit tests
- metadata_service fixture loads from backend/metadata/
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.services.hr_bi.metadata_service import get_metadata_service
from app.services.hr_bi.llm_orchestrator import LLMOrchestrator


@pytest.fixture(scope="session")
def metadata_service():
    """Load real metadata from backend/metadata/ directory."""
    metadata_dir = BACKEND_DIR / "metadata"
    return get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=True)


@pytest.fixture(scope="session")
def orchestrator(metadata_service):
    """
    Orchestrator with no DB execution.
    Used for unit tests — does not require PostgreSQL.
    """
    return LLMOrchestrator(
        metadata_service=metadata_service,
        default_execute_sql=False,
        strict_metadata=True,
    )
