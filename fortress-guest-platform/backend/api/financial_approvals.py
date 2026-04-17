"""
Financial Approvals API — NeMo Triage endpoints for the Commander Dashboard.

GET  /pending   → List pending approvals with joined reservation context
POST /{id}/execute → Execute a pending approval with absorb | invoice strategy
"""
from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.core.database import get_db
from backend.models.financial_approval import FinancialApproval
from backend.models.reservation import Reservation
from backend.services.financial_approval_service import execute_financial_approval

logger = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ReservationContext(BaseModel):
    confirmation_code: str | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    total_amount_cents: int | None = None
    booking_source: str | None = None

    model_config = {"from_attributes": True}


class PendingApprovalResponse(BaseModel):
    id: str
    reservation_id: str
    status: str
    discrepancy_type: str
    local_total_cents: int
    streamline_total_cents: int
    delta_cents: int
    context_payload: dict
    resolution_strategy: str | None = None
    stripe_invoice_id: str | None = None
    created_at: str
    resolved_at: str | None = None
    reservation: ReservationContext | None = None

    model_config = {"from_attributes": True}


class ExecuteRequest(BaseModel):
    strategy: Literal["absorb", "invoice"]


class ExecuteResponse(BaseModel):
    id: str
    status: str
    resolution_strategy: str | None
    resolved_by: str | None
    resolved_at: str | None
    delta_cents: int
    stripe_invoice_id: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=list[PendingApprovalResponse])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
):
    """Return all pending FinancialApproval records with reservation context."""
    result = await db.execute(
        select(FinancialApproval)
        .where(FinancialApproval.status == "pending")
        .order_by(FinancialApproval.created_at.desc())
    )
    approvals = result.scalars().all()

    reservation_ids = {a.reservation_id for a in approvals}
    reservations_by_key: dict[str, Reservation] = {}

    if reservation_ids:
        res_result = await db.execute(
            select(Reservation).where(
                Reservation.confirmation_code.in_(reservation_ids)
                | Reservation.streamline_reservation_id.in_(reservation_ids)
            )
        )
        for r in res_result.scalars().all():
            if r.confirmation_code:
                reservations_by_key[r.confirmation_code] = r
            if r.streamline_reservation_id:
                reservations_by_key[r.streamline_reservation_id] = r

    items: list[PendingApprovalResponse] = []
    for a in approvals:
        reservation = reservations_by_key.get(a.reservation_id)
        res_ctx = None
        if reservation is not None:
            total_cents = None
            if reservation.total_amount is not None:
                total_cents = int(reservation.total_amount * 100)
            res_ctx = ReservationContext(
                confirmation_code=reservation.confirmation_code,
                guest_name=reservation.guest_name or "",
                guest_email=reservation.guest_email or "",
                check_in=str(reservation.check_in_date) if reservation.check_in_date else None,
                check_out=str(reservation.check_out_date) if reservation.check_out_date else None,
                total_amount_cents=total_cents,
                booking_source=reservation.booking_source,
            )

        items.append(
            PendingApprovalResponse(
                id=str(a.id),
                reservation_id=a.reservation_id,
                status=a.status,
                discrepancy_type=a.discrepancy_type,
                local_total_cents=a.local_total_cents,
                streamline_total_cents=a.streamline_total_cents,
                delta_cents=a.delta_cents,
                context_payload=a.context_payload or {},
                resolution_strategy=a.resolution_strategy,
                stripe_invoice_id=a.stripe_invoice_id,
                created_at=a.created_at.isoformat() if a.created_at else "",
                resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
                reservation=res_ctx,
            )
        )

    return items


@router.post("/{approval_id}/execute", response_model=ExecuteResponse)
async def execute_approval(
    approval_id: str,
    body: ExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute a pending financial approval with the chosen strategy."""
    try:
        approval = await execute_financial_approval(
            db,
            approval_id=approval_id,
            commander_username="commander",
            strategy=body.strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()

    return ExecuteResponse(
        id=str(approval.id),
        status=approval.status,
        resolution_strategy=approval.resolution_strategy,
        resolved_by=approval.resolved_by,
        resolved_at=approval.resolved_at.isoformat() if approval.resolved_at else None,
        delta_cents=approval.delta_cents,
        stripe_invoice_id=approval.stripe_invoice_id,
    )
