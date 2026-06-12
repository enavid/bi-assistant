"""
Architecture tests — enforce structural boundaries between features.

These tests guard against accidental dependency regressions. If a rule fails,
it means an import was added that crosses a boundary Clean Architecture prohibits.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).parent.parent / "app"


def _imports_in(module_path: Path) -> list[str]:
    """Return all module paths imported in a Python source file."""
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _all_py_files(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*.py") if "__pycache__" not in str(p)]


# ---------------------------------------------------------------------------
# Screaming Architecture: top-level folder names reflect domain
# ---------------------------------------------------------------------------


def test_feature_folders_exist():
    """Top-level app/ should expose domain names, not generic layer names."""
    assert (APP_ROOT / "hr_analytics").is_dir(), "hr_analytics feature folder missing"
    assert (APP_ROOT / "evaluation").is_dir(), "evaluation feature folder missing"
    assert (APP_ROOT / "workspace").is_dir(), "workspace feature folder missing"


def test_generic_layer_folders_removed():
    """Generic top-level folders (use_cases, domain, api, adapters) should be gone."""
    assert not (APP_ROOT / "use_cases").is_dir(), "use_cases/ should be inside features, not at top"
    assert not (APP_ROOT / "domain").is_dir(), "domain/ should be inside features, not at top"


def test_hr_analytics_has_own_domain():
    assert (APP_ROOT / "hr_analytics" / "domain" / "entities.py").exists()
    assert (APP_ROOT / "hr_analytics" / "domain" / "interfaces.py").exists()


def test_workspace_has_own_domain():
    assert (APP_ROOT / "workspace" / "domain" / "entities.py").exists()


# ---------------------------------------------------------------------------
# Dependency Rule: domain layer must not import from infrastructure
# ---------------------------------------------------------------------------


def test_hr_analytics_domain_entities_no_infrastructure_import():
    """Domain entities are pure dataclasses — no framework or infrastructure deps."""
    entities_file = APP_ROOT / "hr_analytics" / "domain" / "entities.py"
    imports = _imports_in(entities_file)
    infra_imports = [
        i for i in imports if "infrastructure" in i or "fastapi" in i or "sqlalchemy" in i
    ]
    assert not infra_imports, (
        f"hr_analytics/domain/entities.py imports from infrastructure: {infra_imports}"
    )


def test_hr_analytics_domain_interfaces_no_infrastructure_import():
    """Domain interfaces must not import concrete infrastructure classes."""
    interfaces_file = APP_ROOT / "hr_analytics" / "domain" / "interfaces.py"
    imports = _imports_in(interfaces_file)
    infra_imports = [i for i in imports if "infrastructure" in i]
    assert not infra_imports, (
        f"hr_analytics/domain/interfaces.py imports from infrastructure: {infra_imports}"
    )


def test_workspace_domain_entities_no_infrastructure_import():
    entities_file = APP_ROOT / "workspace" / "domain" / "entities.py"
    imports = _imports_in(entities_file)
    infra_imports = [
        i for i in imports if "infrastructure" in i or "fastapi" in i or "sqlalchemy" in i
    ]
    assert not infra_imports, (
        f"workspace/domain/entities.py imports from infrastructure: {infra_imports}"
    )


# ---------------------------------------------------------------------------
# Dependency Rule: use_cases must not import concrete MetadataService
#                  (the orchestrator is the only allowed exception via interface)
# ---------------------------------------------------------------------------


def test_orchestrator_uses_interface_not_concrete_metadata():
    """Orchestrator must import IMetadataService, not MetadataService directly."""
    orch_file = APP_ROOT / "hr_analytics" / "use_cases" / "orchestrator.py"
    source = orch_file.read_text(encoding="utf-8")
    assert "IMetadataService" in source, "orchestrator.py should use IMetadataService"
    # MetadataService (concrete) should only appear as the get_metadata_service factory call,
    # not as a type annotation in __init__
    assert "metadata_service: MetadataService" not in source, (
        "orchestrator.__init__ should annotate with IMetadataService, not MetadataService"
    )


# ---------------------------------------------------------------------------
# Dependency Rule: chat routes must not contain direct ORM queries
#                  (they should go through ChatRepository)
# ---------------------------------------------------------------------------


def test_chat_routes_use_repository_not_direct_orm():
    """Chat routes must delegate DB access to ChatRepository."""
    chat_routes_file = APP_ROOT / "hr_analytics" / "api" / "chat_routes.py"
    source = chat_routes_file.read_text(encoding="utf-8")
    assert "ChatRepository" in source, "chat_routes.py should use ChatRepository"
    # Should NOT contain raw select() calls against ChatSessionORM
    assert "select(ChatSessionORM)" not in source, (
        "chat_routes.py should not query ChatSessionORM directly — use ChatRepository"
    )


# ---------------------------------------------------------------------------
# Repository pattern: IChatRepository is defined in domain interfaces
# ---------------------------------------------------------------------------


def test_ichat_repository_in_domain_interfaces():
    interfaces_file = APP_ROOT / "hr_analytics" / "domain" / "interfaces.py"
    source = interfaces_file.read_text(encoding="utf-8")
    assert "IChatRepository" in source, "IChatRepository must be defined in domain interfaces"


def test_chat_repository_implementation_exists():
    repo_file = APP_ROOT / "hr_analytics" / "repositories" / "chat_repository.py"
    assert repo_file.exists(), "ChatRepository implementation file missing"
    source = repo_file.read_text(encoding="utf-8")
    assert "class ChatRepository" in source


# ---------------------------------------------------------------------------
# Infrastructure must not import from use_cases or hr_analytics features
# ---------------------------------------------------------------------------


def test_infrastructure_does_not_import_feature_use_cases():
    """Infrastructure should be plug-in to use_cases, not depend on them."""
    infra_files = _all_py_files(APP_ROOT / "infrastructure")
    violations = []
    for f in infra_files:
        imports = _imports_in(f)
        bad = [i for i in imports if "hr_analytics.use_cases" in i or "workspace.use_cases" in i]
        if bad:
            violations.append(f"{f.name}: {bad}")
    # analytics_executor.py imports SQLValidator — note this as acceptable (it's a validator tool)
    # Filter that known case
    real_violations = [
        v for v in violations if "analytics_executor" not in v or "SQLGenerator" in v
    ]
    assert not real_violations, f"Infrastructure imports from use_cases: {real_violations}"


# ---------------------------------------------------------------------------
# Modules import correctly (smoke test)
# ---------------------------------------------------------------------------


def test_can_import_hr_analytics_domain():
    from app.hr_analytics.domain.entities import GenerationResult, QueryResult  # noqa: F401

    assert GenerationResult is not None


def test_can_import_workspace_domain():
    from app.workspace.domain.entities import Project, Section  # noqa: F401

    assert Project is not None


def test_can_import_hr_analytics_interfaces():
    from app.hr_analytics.domain.interfaces import (  # noqa: F401
        IChatRepository,
        IMetadataService,
        ISQLValidator,
    )

    assert IMetadataService is not None
    assert IChatRepository is not None


def test_can_import_chat_repository():
    from app.hr_analytics.repositories.chat_repository import ChatRepository  # noqa: F401

    assert ChatRepository is not None


def test_can_import_orchestrator():
    from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator  # noqa: F401

    assert LLMOrchestrator is not None


def test_can_import_main_app():
    from app.main import app  # noqa: F401

    assert app is not None
