"""
Email HITL outbound-draft review API.

Mirrors backend/api/outbound_drafts.py for the email channel.
Prefix: /api/email/outbound-drafts
"""
from uuid import UUID
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.staff import StaffUser
from backend.schemas.email_review import (
    EmailMessageReviewContext,
    ReviewActionResponse,
)
from backend.services.email_message_service import EmailMessageService

router = APIRouter(
    prefix="/api/email/outbound-drafts",
    tags=["HITL Email Review"],
)


@router.get("", response_model=list[EmailMessageReviewContext])
async def get_email_outbound_drafts(
    db: AsyncSession = Depends(get_db),
    _current_user: StaffUser = Depends(get_current_user),
):
    """Returns all email drafts pending human approval."""
    service = EmailMessageService(db)
    return await service.get_pending_drafts()


@router.get("/{message_id}", response_model=EmailMessageReviewContext)
async def get_email_draft_detail(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: StaffUser = Depends(get_current_user),
):
    """Returns a single email draft with full review context."""
    service = EmailMessageService(db)
    ctx = await service.get_draft_context_by_id(message_id)
    if not ctx or ctx.get("approval_status") != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found or not pending review",
        )
    return ctx


@router.post("/{message_id}/approve", response_model=ReviewActionResponse)
async def approve_email_draft(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(get_current_user),
):
    """Marks draft approved and dispatches via SMTP."""
    service = EmailMessageService(db)
    try:
        return await service.execute_approval_and_dispatch(
            message_id, cast(UUID, current_user.id)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/{message_id}/reject", response_model=ReviewActionResponse)
async def reject_email_draft(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(get_current_user),
):
    """Terminal rejection. Records reviewer metadata."""
    service = EmailMessageService(db)
    try:
        return await service.execute_rejection(
            message_id, cast(UUID, current_user.id)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
