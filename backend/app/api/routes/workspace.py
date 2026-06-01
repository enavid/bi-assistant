from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models.domain import ExperimentEntry, Project, Section
from app.schemas.requests import (
    ExperimentCreateRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SectionCreateRequest,
    SectionUpdateRequest,
)
from app.services import storage_service

router = APIRouter(tags=["workspace"])


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

@router.get("/workspace")
async def get_workspace():
    return storage_service.get_workspace()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects")
async def list_projects():
    return storage_service.list_projects()


@router.post("/projects", response_model=Project)
async def create_project(body: ProjectCreateRequest) -> Project:
    project = Project(name=body.name, description=body.description)
    return storage_service.create_project(project)


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str) -> Project:
    project = storage_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, body: ProjectUpdateRequest) -> Project:
    project = storage_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.notes is not None:
        project.notes = body.notes
    if body.sections is not None:
        project.sections = body.sections
    if body.output_format is not None:
        project.output_format = body.output_format
    project.updated_at = datetime.now().isoformat()
    return storage_service.update_project(project)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> dict:
    if not storage_service.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/sections", response_model=Project)
async def create_section(project_id: str, body: SectionCreateRequest) -> Project:
    project = storage_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    section = Section(name=body.name, content=body.content, order=body.order)
    result = storage_service.upsert_section(project_id, section)
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.patch("/projects/{project_id}/sections/{section_id}", response_model=Project)
async def update_section(project_id: str, section_id: str, body: SectionUpdateRequest) -> Project:
    project = storage_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    section = next((s for s in project.sections if s.id == section_id), None)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    if body.name is not None:
        section.name = body.name
    if body.content is not None:
        section.content = body.content
    if body.order is not None:
        section.order = body.order
    result = storage_service.upsert_section(project_id, section)
    return result  # type: ignore[return-value]


@router.delete("/projects/{project_id}/sections/{section_id}", response_model=Project)
async def delete_section(project_id: str, section_id: str) -> Project:
    result = storage_service.delete_section(project_id, section_id)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    return result


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/experiments", response_model=Project)
async def add_experiment(project_id: str, body: ExperimentCreateRequest) -> Project:
    project = storage_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    entry = ExperimentEntry(
        question=body.question,
        sql_output=body.sql_output,
        correct=body.correct,
        elapsed_ms=body.elapsed_ms,
        comment=body.comment,
    )
    project.experiments.append(entry)
    return storage_service.update_project(project)
