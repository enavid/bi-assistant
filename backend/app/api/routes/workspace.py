from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ExperimentCreate,
    ExperimentFeedback,
    ExperimentOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SectionCreate,
    SectionUpdate,
)
from app.infrastructure.db.models import (
    ExperimentORM,
    ProjectORM,
    SectionORM,
    WorkspaceORM,
)
from app.infrastructure.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace"])

_PROJECT_OPTS = [
    selectinload(ProjectORM.sections),
    selectinload(ProjectORM.experiments),
]


async def _get_or_create_workspace(db: AsyncSession) -> WorkspaceORM:
    result = await db.execute(select(WorkspaceORM).limit(1))
    ws = result.scalar_one_or_none()
    if not ws:
        ws = WorkspaceORM()
        db.add(ws)
        await db.flush()
    return ws


async def _require_project(project_id: str, db: AsyncSession) -> ProjectORM:
    result = await db.execute(
        select(ProjectORM).options(*_PROJECT_OPTS).where(ProjectORM.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects", response_model=list[ProjectOut], summary="List all projects")
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectORM]:
    ws = await _get_or_create_workspace(db)
    result = await db.execute(
        select(ProjectORM)
        .options(*_PROJECT_OPTS)
        .where(ProjectORM.workspace_id == ws.id)
        .order_by(ProjectORM.created_at.asc())
    )
    return list(result.scalars().all())


@router.post("/projects", response_model=ProjectOut, status_code=201, summary="Create project")
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectORM:
    ws = await _get_or_create_workspace(db)
    project = ProjectORM(workspace_id=ws.id, name=body.name, description=body.description)
    db.add(project)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut, summary="Get project")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> ProjectORM:
    return await _require_project(project_id, db)


@router.patch("/projects/{project_id}", response_model=ProjectOut, summary="Update project")
async def update_project(
    project_id: str, body: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectORM:
    project = await _require_project(project_id, db)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.notes is not None:
        project.notes = body.notes
    if body.output_format is not None:
        project.output_format = body.output_format
    project.updated_at = datetime.now(UTC)
    await db.flush()
    return project


@router.delete("/projects/{project_id}", status_code=204, summary="Delete project")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)) -> None:
    project = await _require_project(project_id, db)
    await db.delete(project)


@router.post("/projects/{project_id}/sections", response_model=ProjectOut, status_code=201)
async def create_section(
    project_id: str, body: SectionCreate, db: AsyncSession = Depends(get_db)
) -> ProjectORM:
    project = await _require_project(project_id, db)
    section = SectionORM(
        project_id=project_id, name=body.name, content=body.content, order=body.order
    )
    db.add(section)
    project.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.patch("/projects/{project_id}/sections/{section_id}", response_model=ProjectOut)
async def update_section(
    project_id: str, section_id: str, body: SectionUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectORM:
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
    project.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.delete("/projects/{project_id}/sections/{section_id}", response_model=ProjectOut)
async def delete_section(
    project_id: str, section_id: str, db: AsyncSession = Depends(get_db)
) -> ProjectORM:
    project = await _require_project(project_id, db)
    section = next((s for s in project.sections if s.id == section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    await db.delete(section)
    project.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.post("/projects/{project_id}/experiments", response_model=ProjectOut, status_code=201)
async def add_experiment(
    project_id: str, body: ExperimentCreate, db: AsyncSession = Depends(get_db)
) -> ProjectORM:
    project = await _require_project(project_id, db)
    exp = ExperimentORM(
        project_id=project_id,
        question=body.question,
        sql_output=body.sql_output,
        correct=body.correct,
        elapsed_ms=body.elapsed_ms,
        comment=body.comment,
    )
    db.add(exp)
    project.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(project, ["sections", "experiments"])
    return project


@router.patch(
    "/experiments/{experiment_id}/feedback",
    response_model=ExperimentOut,
    summary="Set experiment correctness feedback",
)
async def set_experiment_feedback(
    experiment_id: str, body: ExperimentFeedback, db: AsyncSession = Depends(get_db)
) -> ExperimentORM:
    result = await db.execute(select(ExperimentORM).where(ExperimentORM.id == experiment_id))
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    exp.correct = body.correct
    await db.flush()
    return exp
