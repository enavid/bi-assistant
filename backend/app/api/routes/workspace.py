from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import get_db
from app.db.models import Experiment, Project, Section, Workspace
from app.schemas.schemas import (
    ExperimentCreate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SectionCreate,
    SectionUpdate,
)

router = APIRouter(tags=["workspace"])

_PROJECT_LOAD = [selectinload(Project.sections),
                 selectinload(Project.experiments)]


async def _get_or_create_workspace(db: AsyncSession) -> Workspace:
    result = await db.execute(select(Workspace).limit(1))
    ws = result.scalar_one_or_none()
    if not ws:
        ws = Workspace()
        db.add(ws)
        await db.flush()
    return ws


async def _require_project(project_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).options(*_PROJECT_LOAD).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    ws = await _get_or_create_workspace(db)
    result = await db.execute(
        select(Project).options(
            *_PROJECT_LOAD).where(Project.workspace_id == ws.id)
        .order_by(Project.created_at.asc())
    )
    return list(result.scalars().all())


@router.post("/projects", response_model=ProjectOut)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    ws = await _get_or_create_workspace(db)
    project = Project(workspace_id=ws.id, name=body.name,
                      description=body.description)
    db.add(project)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> Project:
    return await _require_project(project_id, db)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate, db: AsyncSession = Depends(get_db)) -> Project:
    project = await _require_project(project_id, db)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.notes is not None:
        project.notes = body.notes
    if body.output_format is not None:
        project.output_format = body.output_format
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    project = await _require_project(project_id, db)
    await db.delete(project)
    return {"deleted": True}


# ── Sections ──────────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/sections", response_model=ProjectOut)
async def create_section(project_id: str, body: SectionCreate, db: AsyncSession = Depends(get_db)) -> Project:
    project = await _require_project(project_id, db)
    section = Section(project_id=project_id, name=body.name,
                      content=body.content, order=body.order)
    db.add(section)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.patch("/projects/{project_id}/sections/{section_id}", response_model=ProjectOut)
async def update_section(project_id: str, section_id: str, body: SectionUpdate, db: AsyncSession = Depends(get_db)) -> Project:
    project = await _require_project(project_id, db)
    section = next((s for s in project.sections if s.id == section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    if body.name is not None:
        section.name = body.name
    if body.content is not None:
        section.content = body.content
    if body.order is not None:
        section.order = body.order
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.delete("/projects/{project_id}/sections/{section_id}", response_model=ProjectOut)
async def delete_section(project_id: str, section_id: str, db: AsyncSession = Depends(get_db)) -> Project:
    project = await _require_project(project_id, db)
    section = next((s for s in project.sections if s.id == section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    await db.delete(section)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


# ── Experiments ───────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/experiments", response_model=ProjectOut)
async def add_experiment(project_id: str, body: ExperimentCreate, db: AsyncSession = Depends(get_db)) -> Project:
    project = await _require_project(project_id, db)
    exp = Experiment(
        project_id=project_id,
        question=body.question,
        sql_output=body.sql_output,
        correct=body.correct,
        elapsed_ms=body.elapsed_ms,
        comment=body.comment,
    )
    db.add(exp)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project
