from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.models.domain import ChatSession, Project, Section, Workspace


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def _load_workspace() -> Workspace:
    raw = _read_json(settings.workspace_file)
    if not raw:
        ws = Workspace()
        _save_workspace(ws)
        return ws
    return Workspace.model_validate(raw)


def _save_workspace(workspace: Workspace) -> None:
    _write_json(settings.workspace_file, workspace.model_dump())


def get_workspace() -> Workspace:
    return _load_workspace()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def list_projects() -> list[Project]:
    return _load_workspace().projects


def get_project(project_id: str) -> Project | None:
    return next((p for p in _load_workspace().projects if p.id == project_id), None)


def create_project(project: Project) -> Project:
    ws = _load_workspace()
    ws.projects.append(project)
    _save_workspace(ws)
    return project


def update_project(project: Project) -> Project:
    ws = _load_workspace()
    ws.projects = [project if p.id == project.id else p for p in ws.projects]
    _save_workspace(ws)
    return project


def delete_project(project_id: str) -> bool:
    ws = _load_workspace()
    before = len(ws.projects)
    ws.projects = [p for p in ws.projects if p.id != project_id]
    if len(ws.projects) == before:
        return False
    _save_workspace(ws)
    return True


# ---------------------------------------------------------------------------
# Sections (convenience — mutate project then save workspace)
# ---------------------------------------------------------------------------

def upsert_section(project_id: str, section: Section) -> Project | None:
    project = get_project(project_id)
    if not project:
        return None
    existing_ids = [s.id for s in project.sections]
    if section.id in existing_ids:
        project.sections = [section if s.id == section.id else s for s in project.sections]
    else:
        project.sections.append(section)
    return update_project(project)


def delete_section(project_id: str, section_id: str) -> Project | None:
    project = get_project(project_id)
    if not project:
        return None
    project.sections = [s for s in project.sections if s.id != section_id]
    return update_project(project)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _load_sessions() -> list[ChatSession]:
    raw = _read_json(settings.sessions_file)
    items = raw if isinstance(raw, list) else []
    return [ChatSession.model_validate(i) for i in items]


def _save_sessions(sessions: list[ChatSession]) -> None:
    _write_json(settings.sessions_file, [s.model_dump() for s in sessions])


def list_sessions() -> list[ChatSession]:
    return _load_sessions()


def get_session(session_id: str) -> ChatSession | None:
    return next((s for s in _load_sessions() if s.id == session_id), None)


def save_session(session: ChatSession) -> ChatSession:
    sessions = _load_sessions()
    ids = [s.id for s in sessions]
    if session.id in ids:
        sessions = [session if s.id == session.id else s for s in sessions]
    else:
        sessions.append(session)
    _save_sessions(sessions)
    return session


def delete_session(session_id: str) -> bool:
    sessions = _load_sessions()
    before = len(sessions)
    sessions = [s for s in sessions if s.id != session_id]
    if len(sessions) == before:
        return False
    _save_sessions(sessions)
    return True
