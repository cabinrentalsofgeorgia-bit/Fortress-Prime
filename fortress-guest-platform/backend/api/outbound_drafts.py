from uuid import UUID
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.staff import StaffUser
from backend.schemas.message_review import (
    MessageReviewContext,
    ReviewActionResponse,
)
from backend.services.message_service import MessageService

router = APIRouter(prefix="/api/messages/outbound-drafts", tags=["HITL Outbound Review"])


@router.get("", response_model=list[MessageReviewContext])
async def get_outbound_drafts(
    db: AsyncSession = Depends(get_db),
    _current_user: StaffUser = Depends(get_current_user),
):
    """Returns all outbound drafts pending human approval."""
    service = MessageService(db)
    return await service.get_pending_outbound_drafts()


@router.get("/{message_id}", response_model=MessageReviewContext)
async def get_draft_detail(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: StaffUser = Depends(get_current_user),
):
    """Returns a single draft with full review context."""
    service = MessageService(db)
    message = await service.get_draft_context_by_id(message_id)
    if not message or message["approval_status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found or not pending review",
        )
    return message


@router.post("/{message_id}/approve", response_model=ReviewActionResponse)
async def approve_draft(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(get_current_user),
):
    """Marks draft as approved, records reviewer, and dispatches via Twilio."""
    service = MessageService(db)
    try:
        return await service.execute_approval_and_dispatch(message_id, cast(UUID, current_user.id))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/{message_id}/reject", response_model=ReviewActionResponse)
async def reject_draft(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(get_current_user),
):
    """Terminal rejection. Updates status and records reviewer metadata."""
    service = MessageService(db)
    try:
        return await service.execute_rejection(message_id, cast(UUID, current_user.id))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
