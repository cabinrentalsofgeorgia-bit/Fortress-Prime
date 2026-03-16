"""
Email Templates API — CRUD for the Sovereign Templating Engine.

Endpoints:
  GET    /api/templates             — List all templates
  POST   /api/templates             — Create a new template
  PUT    /api/templates/{id}        — Update an existing template
  POST   /api/templates/{id}/preview — Preview rendered output with sample data
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.template import EmailTemplate
from backend.services.template_engine import preview_template

router = APIRouter()

TRIGGER_EVENTS = [
    "7_days_before_checkin",
    "3_days_before_checkin",
    "1_day_before_checkin",
    "day_of_checkin",
    "mid_stay",
    "day_of_checkout",
    "1_day_after_checkout",
    "3_days_after_checkout",
    "quote_sent",
    "payment_confirmed",
    "inquiry_received",
    "cart_abandoned_2h",
    "2_days_into_stay",
    "11_months_after_checkout",
    "manual",
]


# ── Schemas ──────────────────────────────────────────────────────────────────


class TemplateResponse(BaseModel):
    id: UUID
    name: str
    trigger_event: str
    subject_template: str
    body_template: str
    is_active: bool
    requires_human_approval: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    trigger_event: str = Field(..., min_length=1, max_length=100)
    subject_template: str = Field(default="", max_length=1000)
    body_template: str = Field(default="")
    is_active: bool = True
    requires_human_approval: bool = True


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    trigger_event: Optional[str] = Field(None, min_length=1, max_length=100)
    subject_template: Optional[str] = Field(None, max_length=1000)
    body_template: Optional[str] = None
    is_active: Optional[bool] = None
    requires_human_approval: Optional[bool] = None


class PreviewResponse(BaseModel):
    subject: str
    body: str
    context_used: dict


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_response(t: EmailTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        name=t.name,
        trigger_event=t.trigger_event,
        subject_template=t.subject_template,
        body_template=t.body_template,
        is_active=t.is_active,
        requires_human_approval=t.requires_human_approval,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/", response_model=List[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all email templates ordered by name."""
    result = await db.execute(
        select(EmailTemplate).order_by(EmailTemplate.name)
    )
    return [_to_response(t) for t in result.scalars().all()]


@router.post("/", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new email template."""
    template = EmailTemplate(
        name=body.name,
        trigger_event=body.trigger_event,
        subject_template=body.subject_template,
        body_template=body.body_template,
        is_active=body.is_active,
        requires_human_approval=body.requires_human_approval,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: UUID,
    body: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing email template."""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, f"Template {template_id} not found")

    if body.name is not None:
        template.name = body.name
    if body.trigger_event is not None:
        template.trigger_event = body.trigger_event
    if body.subject_template is not None:
        template.subject_template = body.subject_template
    if body.body_template is not None:
        template.body_template = body.body_template
    if body.is_active is not None:
        template.is_active = body.is_active
    if body.requires_human_approval is not None:
        template.requires_human_approval = body.requires_human_approval

    template.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


@router.post("/{template_id}/preview", response_model=PreviewResponse)
async def preview_email_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Render a template with sample data for preview."""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, f"Template {template_id} not found")

    return preview_template(template.subject_template, template.body_template)


@router.get("/triggers")
async def list_trigger_events():
    """Return the list of valid trigger event identifiers."""
    return {"triggers": TRIGGER_EVENTS}
