"""
Admin Payouts API — Owner Disbursement Management

Endpoints for configuring payout schedules, viewing pending balances,
and manually triggering transfers for individual property owners.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_admin, require_manager_or_admin
from backend.services.owner_onboarding import create_invite, accept_invite
from decimal import Decimal
from backend.services.payout_scheduler import (
    _next_payout_date,
    calculate_pending_owner_amount,
    execute_staged_payout,
    run_payout_sweep,
    stage_payout,
)

logger = structlog.get_logger(service="admin_payouts_api")

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])

_UTC = timezone.utc


# ── Schemas ───────────────────────────────────────────────────────────────────


class PayoutScheduleUpdate(BaseModel):
    payout_schedule: str = Field(..., pattern="^(manual|weekly|biweekly|monthly)$")
    payout_day_of_week: Optional[int] = Field(None, ge=0, le=6)
    payout_day_of_month: Optional[int] = Field(None, ge=1, le=28)
    minimum_payout_threshold: Optional[float] = Field(None, gt=0)


class PayoutSummaryRow(BaseModel):
    property_id: str
    owner_name: str
    owner_email: Optional[str]
    account_status: str
    stripe_account_id: Optional[str]
    payout_schedule: str
    last_payout_at: Optional[datetime]
    next_scheduled_payout: Optional[datetime]
    minimum_payout_threshold: float
    outstanding_amount: Optional[float] = None
    last_transfer_id: Optional[str] = None
    last_transfer_status: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/pending")
async def list_pending_payouts(db: AsyncSession = Depends(get_db)):
    """
    List all active Stripe Connect accounts with their pending balance and
    schedule configuration. Calculates outstanding amount for each property.
    """
    rows_result = await db.execute(
        text("""
            SELECT
                opa.property_id,
                opa.owner_name,
                opa.owner_email,
                opa.account_status,
                opa.stripe_account_id,
                opa.payout_schedule,
                opa.last_payout_at,
                opa.next_scheduled_payout,
                opa.minimum_payout_threshold,
                pl.stripe_transfer_id,
                pl.status AS last_transfer_status
            FROM owner_payout_accounts opa
            LEFT JOIN LATERAL (
                SELECT stripe_transfer_id, status
                FROM payout_ledger
                WHERE property_id = opa.property_id
                ORDER BY created_at DESC
                LIMIT 1
            ) pl ON true
            WHERE opa.account_status IN ('active', 'restricted', 'onboarding')
            ORDER BY opa.owner_name
        """),
    )
    rows = rows_result.fetchall()

    results = []
    for row in rows:
        property_id = row[0]
        last_payout_at = row[6]
        outstanding = None
        try:
            outstanding = float(
                await calculate_pending_owner_amount(property_id, last_payout_at, db)
            )
        except Exception as exc:
            logger.warning("outstanding_calc_failed", property_id=property_id, error=str(exc)[:120])

        results.append(
            PayoutSummaryRow(
                property_id=property_id,
                owner_name=row[1] or "",
                owner_email=row[2],
                account_status=row[3] or "",
                stripe_account_id=row[4],
                payout_schedule=row[5] or "manual",
                last_payout_at=row[6],
                next_scheduled_payout=row[7],
                minimum_payout_threshold=float(row[8] or 100.0),
                outstanding_amount=outstanding,
                last_transfer_id=row[9],
                last_transfer_status=row[10],
            )
        )

    return {"owners": results, "total": len(results)}


@router.post("/{property_id}/send")
async def manual_send_payout(
    property_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger an immediate payout for a specific property owner.
    Calculates pending amount, stages the ledger row, and fires the Stripe transfer.
    Returns immediately; the transfer completes asynchronously via Stripe webhook.
    """
    # Verify the account exists and is active
    acct_result = await db.execute(
        text("""
            SELECT stripe_account_id, account_status, last_payout_at
            FROM owner_payout_accounts WHERE property_id = :pid
        """),
        {"pid": property_id},
    )
    acct = acct_result.first()
    if not acct:
        raise HTTPException(404, f"No payout account found for property {property_id}")
    if acct[1] != "active":
        raise HTTPException(400, f"Account is not active (status: {acct[1]}). Owner must complete Stripe onboarding.")

    last_payout_at = acct[2]
    pending = await calculate_pending_owner_amount(property_id, last_payout_at, db)

    if pending <= 0:
        return {"triggered": False, "reason": "no_pending_amount", "pending": 0.0}

    ledger_id = await stage_payout(property_id, pending, db)
    result = await execute_staged_payout(ledger_id, db)

    logger.info(
        "manual_payout_triggered",
        property_id=property_id,
        payout_ledger_id=ledger_id,
        amount=float(pending),
        result_status=result.get("status"),
    )
    return {
        "triggered": True,
        "payout_ledger_id": ledger_id,
        "amount": float(pending),
        "transfer_id": result.get("transfer_id"),
        "status": result.get("status"),
    }


@router.patch("/{property_id}/schedule")
async def update_payout_schedule(
    property_id: str,
    body: PayoutScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update the payout schedule configuration for a property owner.
    Automatically recalculates next_scheduled_payout based on the new schedule.
    """
    acct_result = await db.execute(
        text("SELECT id FROM owner_payout_accounts WHERE property_id = :pid"),
        {"pid": property_id},
    )
    if not acct_result.first():
        raise HTTPException(404, f"No payout account found for property {property_id}")

    now = datetime.now(_UTC)
    next_dt = _next_payout_date(
        body.payout_schedule,
        body.payout_day_of_week,
        body.payout_day_of_month,
        now,
    ) if body.payout_schedule != "manual" else None

    update_fields: dict = {
        "payout_schedule": body.payout_schedule,
        "payout_day_of_week": body.payout_day_of_week,
        "payout_day_of_month": body.payout_day_of_month,
        "next_scheduled_payout": next_dt,
        "pid": property_id,
    }
    if body.minimum_payout_threshold is not None:
        update_fields["minimum_payout_threshold"] = body.minimum_payout_threshold
        await db.execute(
            text("""
                UPDATE owner_payout_accounts
                SET payout_schedule = :payout_schedule,
                    payout_day_of_week = :payout_day_of_week,
                    payout_day_of_month = :payout_day_of_month,
                    next_scheduled_payout = :next_scheduled_payout,
                    minimum_payout_threshold = :minimum_payout_threshold,
                    updated_at = NOW()
                WHERE property_id = :pid
            """),
            update_fields,
        )
    else:
        await db.execute(
            text("""
                UPDATE owner_payout_accounts
                SET payout_schedule = :payout_schedule,
                    payout_day_of_week = :payout_day_of_week,
                    payout_day_of_month = :payout_day_of_month,
                    next_scheduled_payout = :next_scheduled_payout,
                    updated_at = NOW()
                WHERE property_id = :pid
            """),
            update_fields,
        )

    await db.commit()
    logger.info(
        "payout_schedule_updated",
        property_id=property_id,
        schedule=body.payout_schedule,
        next_payout=str(next_dt),
    )
    return {
        "property_id": property_id,
        "payout_schedule": body.payout_schedule,
        "next_scheduled_payout": next_dt.isoformat() if next_dt else None,
    }


@router.post("/sweep")
async def trigger_sweep(background_tasks: BackgroundTasks):
    """
    Manually trigger the payout sweep (same logic as the daily 6am cron).
    Useful for catching up after a system outage or testing the sweep pipeline.
    """
    background_tasks.add_task(run_payout_sweep)
    return {"triggered": True, "message": "Payout sweep started in background"}


# ── Owner Invite Flow ─────────────────────────────────────────────────────────

class OwnerInviteRequest(BaseModel):
    property_id: str
    owner_email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    owner_name: str
    sl_owner_id: str = ""
    # Management commission percentage (e.g. 30.0 means management keeps 30%).
    # Required — no default. Must be between 0 and 50 inclusive.
    commission_rate_percent: float = Field(
        ...,
        description="Management commission as a percent (0–50, e.g. 30 or 35.5).",
        gt=-0.001,   # >=0 with float tolerance
        le=50.0,
    )
    # Optional Streamline integer owner ID — used for monthly statement comparison.
    streamline_owner_id: Optional[int] = Field(
        None,
        description="Streamline's integer owner ID, for statement reconciliation.",
    )
    # Owner mailing address — required. Stored on the invite token and copied to
    # owner_payout_accounts when the owner accepts. Used in PDF statements.
    mailing_address_line1: str = Field(..., min_length=1, max_length=255)
    mailing_address_line2: Optional[str] = Field(None, max_length=255)
    mailing_address_city: str = Field(..., min_length=1, max_length=100)
    mailing_address_state: str = Field(..., min_length=1, max_length=50)
    mailing_address_postal_code: str = Field(..., min_length=1, max_length=20)
    mailing_address_country: str = Field(default="USA", max_length=50)

    @field_validator("commission_rate_percent")
    @classmethod
    def _validate_rate(cls, v: float) -> float:
        if v < 0:
            raise ValueError("commission_rate_percent must be >= 0")
        if v > 50:
            raise ValueError("commission_rate_percent must be <= 50")
        return v


@router.post("/invites", dependencies=[Depends(require_admin)])
async def create_owner_invite(
    body: OwnerInviteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create an owner invite token and send an email invitation.

    The invite link leads to /owner/accept-invite (storefront) which calls
    POST /api/owner/invite/accept (public endpoint).

    commission_rate_percent is stored on the token and written to
    owner_payout_accounts.commission_rate (as a fraction) when the owner accepts.
    Requires admin role.
    """
    commission_rate = Decimal(str(body.commission_rate_percent)) / Decimal("100")
    result = await create_invite(
        db,
        property_id=body.property_id,
        owner_email=body.owner_email,
        owner_name=body.owner_name,
        commission_rate=commission_rate,
        sl_owner_id=str(body.streamline_owner_id) if body.streamline_owner_id else "",
        invited_by="admin",
        mailing_address_line1=body.mailing_address_line1,
        mailing_address_line2=body.mailing_address_line2,
        mailing_address_city=body.mailing_address_city,
        mailing_address_state=body.mailing_address_state,
        mailing_address_postal_code=body.mailing_address_postal_code,
        mailing_address_country=body.mailing_address_country,
    )
    return result


class InviteAcceptRequest(BaseModel):
    raw_token: str
    property_id: str
    owner_name: str
    return_url: str = ""


@router.post("/invites/accept")
async def accept_owner_invite(
    body: InviteAcceptRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an owner invite. Called from the owner portal frontend after the
    owner clicks the email link.

    Creates the Stripe Connect Express account (or returns a stub message if
    STRIPE_CONNECT_CLIENT_ID is not yet configured), writes to
    owner_payout_accounts, and marks the token used.
    """
    result = await accept_invite(
        db,
        raw_token=body.raw_token,
        property_id=body.property_id,
        owner_name=body.owner_name,
        return_url=body.return_url,
    )
    if not result["success"]:
        raise HTTPException(422, result["message"])
    return result


# ── Monthly Statement Trigger ──────────────────────────────────────────────────

class StatementTriggerRequest(BaseModel):
    year: int
    month: int = Field(..., ge=1, le=12)


@router.post("/statements/send-all", dependencies=[Depends(require_admin)])
async def trigger_monthly_statements(
    body: StatementTriggerRequest,
):
    """
    NOT YET IMPLEMENTED.

    The old statement pipeline (send_all_monthly_statements) was deleted in
    Phase 1.5 because it used a hardcoded 65% commission split.  The
    replacement (send_owner_statement from backend/services/owner_statement_service.py)
    will be wired here in Phase 4 of the Area 2 gap remediation.

    Use POST /api/admin/payouts/statements/send-test (Phase 5) for manual
    single-owner test sends once Phase 4 is complete.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Monthly statement send is not yet implemented. "
            "The old pipeline used a hardcoded commission rate and was removed. "
            "The replacement will be available after Phase 4 is complete."
        ),
    )
