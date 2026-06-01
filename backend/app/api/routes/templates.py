from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.domain import ExperimentEntry, PromptTemplate
from app.schemas.requests import (
    ExperimentCreateRequest,
    TemplateCreateRequest,
    TemplateUpdateRequest,
)
from app.services import storage_service
from app.services.prompt_service import make_default_template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[PromptTemplate])
async def list_templates() -> list[PromptTemplate]:
    return storage_service.list_templates()


@router.post("", response_model=PromptTemplate)
async def create_template(body: TemplateCreateRequest) -> PromptTemplate:
    template = make_default_template(body.name)
    template.description = body.description
    template.notes = body.notes
    if body.blocks:
        template.blocks = body.blocks
    template.active = False
    return storage_service.save_template(template)


@router.get("/{template_id}", response_model=PromptTemplate)
async def get_template(template_id: str) -> PromptTemplate:
    template = storage_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/{template_id}", response_model=PromptTemplate)
async def update_template(template_id: str, body: TemplateUpdateRequest) -> PromptTemplate:
    template = storage_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description
    if body.blocks is not None:
        template.blocks = body.blocks
    if body.notes is not None:
        template.notes = body.notes
    return storage_service.save_template(template)


@router.post("/{template_id}/activate")
async def activate_template(template_id: str) -> dict:
    if not storage_service.set_active_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"activated": True}


@router.delete("/{template_id}")
async def delete_template(template_id: str) -> dict:
    if not storage_service.delete_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True}


@router.post("/{template_id}/experiments", response_model=PromptTemplate)
async def add_experiment(template_id: str, body: ExperimentCreateRequest) -> PromptTemplate:
    template = storage_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    entry = ExperimentEntry(
        question=body.question,
        sql_output=body.sql_output,
        correct=body.correct,
        comment=body.comment,
    )
    template.experiments.append(entry)
    return storage_service.save_template(template)
