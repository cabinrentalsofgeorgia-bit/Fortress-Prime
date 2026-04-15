"""
Owner Statement API — thin wrapper around statement_computation service.

The computation logic (DB lookups, commission_rate resolution, payout math)
lives in backend/services/statement_computation.py.  This module is now only
responsible for:
  - HTTP routing
  - Translating owner_id → owner_payout_account_id
  - Converting StatementResult into the HTTP response shape
  - The commission_rate_override what-if query parameter (staff only)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.property import Property
from backend.services.statement_computation import (
    StatementComputationError,
    StatementResult,
    compute_owner_statement,
)

logger = structlog.get_logger(service="owner_statements")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


# ── Response schemas ──────────────────────────────────────────────────────────

class ReservationPayoutDetail(BaseModel):
    reservation_id: str
    confirmation_code: str
    description: str
    check_in: str
    check_out: str
    nights: int
    gross_revenue: float
    pass_through_total: float
    commission_rate_pct: float
    commission_amount: float
    cc_processing_fee: float
    net_owner_payout: float


class OwnerStatementResponse(BaseModel):
    owner_id: str
    owner_name: Optional[str]
    property_id: str
    property_name: str
    period_start: str
    period_end: str
    commission_rate_pct: float
    reservation_count: int
    total_gross_revenue: float
    total_commission: float
    total_cc_processing: float
    total_pass_through: float
    total_net_payout: float
    reservations: list[ReservationPayoutDetail]
    source: str = "crog"


def _to_response(result: StatementResult, owner_id: str) -> OwnerStatementResponse:
    """Convert a StatementResult into the HTTP response model."""
    return OwnerStatementResponse(
        owner_id=owner_id,
        owner_name=result.owner_name,
        property_id=result.property_id,
        property_name=result.property_name,
        period_start=result.period_start.isoformat(),
        period_end=result.period_end.isoformat(),
        commission_rate_pct=float(result.commission_rate_percent),
        reservation_count=result.reservation_count,
        total_gross_revenue=float(result.total_gross),
        total_commission=float(result.total_commission),
        total_cc_processing=float(result.total_cc_processing),
        total_pass_through=float(result.total_pass_through),
        total_net_payout=float(result.total_net_to_owner),
        source=result.source,
        reservations=[
            ReservationPayoutDetail(
                reservation_id=li.reservation_id,
                confirmation_code=li.confirmation_code,
                description=li.description,
                check_in=li.check_in.isoformat(),
                check_out=li.check_out.isoformat(),
                nights=li.nights,
                gross_revenue=float(li.gross_amount),
                pass_through_total=float(li.pass_through_total),
                commission_rate_pct=float(result.commission_rate_percent),
                commission_amount=float(li.commission_amount),
                cc_processing_fee=float(li.cc_processing_fee),
                net_owner_payout=float(li.net_to_owner),
            )
            for li in result.line_items
        ],
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/statements/{owner_id}", response_model=OwnerStatementResponse)
async def get_owner_statement(
    owner_id: str,
    start_date: date = Query(default=None, description="Period start (default: first of current month)"),
    end_date: date = Query(default=None, description="Period end (default: today)"),
    commission_rate_override: Optional[float] = Query(
        default=None,
        description=(
            "Staff what-if tool: override commission % for modelling (e.g. 30.0). "
            "NOT a real rate source — if omitted, the rate stored in "
            "owner_payout_accounts is used. 0 to 50 only."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a detailed owner statement with per-reservation payout breakdown.

    Thin wrapper around compute_owner_statement().  The commission rate is always
    read from owner_payout_accounts, unless commission_rate_override is supplied
    by a staff member for what-if modelling (not a real rate source).
    """
    today = date.today()
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today

    # Translate owner_id → owner_payout_account_id.
    # owner_id is stored on properties.owner_id (VARCHAR); find the matching
    # owner_payout_accounts row via the property.
    props_result = await db.execute(
        select(Property)
        .where(Property.owner_id == owner_id)
        .where(Property.is_active.is_(True))
    )
    properties = props_result.scalars().all()

    if not properties:
        raise HTTPException(status_code=404, detail=f"No active properties found for owner_id={owner_id}")

    # Find the payout account for the first property (each property has at most one).
    opa_result = await db.execute(
        text("""
            SELECT id
            FROM owner_payout_accounts
            WHERE property_id = ANY(:pids)
            ORDER BY created_at
            LIMIT 1
        """),
        {"pids": [str(p.id) for p in properties]},
    )
    opa_row = opa_result.fetchone()
    if not opa_row:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No owner_payout_accounts row found for owner_id={owner_id}. "
                "The owner must accept their invite before a statement can be generated."
            ),
        )

    owner_payout_account_id: int = opa_row[0]

    # If staff want a what-if at a different rate, temporarily patch the result.
    # This does NOT modify the database.
    if commission_rate_override is not None and not (0 <= commission_rate_override <= 50):
        raise HTTPException(status_code=422, detail="commission_rate_override must be 0–50")

    try:
        result = await compute_owner_statement(
            db,
            owner_payout_account_id=owner_payout_account_id,
            period_start=start_date,
            period_end=end_date,
        )
    except StatementComputationError as exc:
        status = 404 if exc.code == "not_found" else 422
        raise HTTPException(status_code=status, detail=exc.message) from exc

    # What-if override: recompute totals using the override rate.
    # commission_rate_override is a staff modelling tool — it does NOT modify
    # owner_payout_accounts and is NOT the authoritative rate.
    if commission_rate_override is not None:
        from backend.services.statement_computation import _apply_rate_override
        result = _apply_rate_override(result, Decimal(str(commission_rate_override)))

    return _to_response(result, owner_id)
