"""
Admin Owner Charges API — manual expense/credit entries.

Endpoints:
  POST   /api/admin/payouts/charges               — create a charge
  GET    /api/admin/payouts/charges               — list charges
  GET    /api/admin/payouts/charges/{id}          — get one charge
  PATCH  /api/admin/payouts/charges/{id}          — update a charge
  POST   /api/admin/payouts/charges/{id}/void     — void a charge

All endpoints require require_manager_or_admin.

Charges inside an approved/paid/emailed statement period are locked —
create, update, and void will all return HTTP 409 if the posting_date
falls in a finalized period.
"""
from __future__ import annotations

import uuid as _uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_manager_or_admin
from backend.models.owner_balance_period import OwnerBalancePeriod
from backend.models.owner_charge import OwnerCharge, OwnerChargeType
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.models.staff import StaffUser
from backend.models.vendor import Vendor
from backend.services.owner_emails import send_owner_charge_notification
from backend.services.obp_recompute import (
    OBPFinalizedError,
    RecomputeResult,
    recompute_obp_for_charge_event,
)

logger = structlog.get_logger(service="admin_charges_api")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
_UTC = timezone.utc

# Statement statuses that prevent charge modifications
_LOCKED_STATUSES = frozenset(["approved", "paid", "emailed", "voided"])


# ── C3: Approval lock helper ──────────────────────────────────────────────────

async def is_charge_period_locked(
    db: AsyncSession,
    owner_payout_account_id: int,
    posting_date: date,
) -> Optional["OwnerBalancePeriod"]:
    """
    Returns the OwnerBalancePeriod row if the posting_date falls inside a
    finalized (approved/paid/emailed/voided) period for this owner.
    Returns None if no locked period covers this date.
    """
    result = await db.execute(
        select(OwnerBalancePeriod)
        .where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id,
            OwnerBalancePeriod.period_start <= posting_date,
            OwnerBalancePeriod.period_end >= posting_date,
            OwnerBalancePeriod.status.in_(list(_LOCKED_STATUSES)),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _locked_error(period: "OwnerBalancePeriod") -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            f"Cannot modify charge: the statement period "
            f"{period.period_start} to {period.period_end} "
            f"is already '{period.status}'. "
            "Use a credit_from_management entry in a later period to correct this charge."
        ),
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class OwnerChargeCreateRequest(BaseModel):
    owner_payout_account_id: int
    posting_date: date
    transaction_type: OwnerChargeType
    description: str = Field(..., min_length=1, max_length=500)
    # amount is required only when no vendor is given; when vendor_id is set
    # the server computes amount = vendor_amount * (1 + markup_percentage/100).
    amount: Optional[Decimal] = None
    reference_id: Optional[str] = Field(None, max_length=100)

    # Vendor + markup fields (I.1a)
    vendor_id: Optional[_uuid_mod.UUID] = None
    markup_percentage: Decimal = Field(Decimal("0.00"), ge=0, le=100)
    vendor_amount: Optional[Decimal] = None

    # Email notification flag (I.1b)
    send_notification: bool = False

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v == Decimal("0"):
            raise ValueError("amount must not be zero; use void to cancel a charge")
        return v

    @field_validator("vendor_amount")
    @classmethod
    def _vendor_amount_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= Decimal("0"):
            raise ValueError("vendor_amount must be positive")
        return v

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "OwnerChargeCreateRequest":
        if self.vendor_id is not None and self.vendor_amount is None:
            raise ValueError("vendor_amount is required when vendor_id is provided")
        if self.vendor_id is None and self.amount is None:
            raise ValueError("amount is required when no vendor is provided")
        return self

    def computed_amount(self) -> Decimal:
        """Return the owner-facing charge amount."""
        if self.vendor_id and self.vendor_amount is not None:
            factor = Decimal("1") + self.markup_percentage / Decimal("100")
            return (self.vendor_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return self.amount  # type: ignore[return-value]


class OwnerChargePatchRequest(BaseModel):
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    posting_date: Optional[date] = None
    amount: Optional[Decimal] = None
    reference_id: Optional[str] = Field(None, max_length=100)
    markup_percentage: Optional[Decimal] = Field(None, ge=0, le=100)
    vendor_amount: Optional[Decimal] = None

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v == Decimal("0"):
            raise ValueError("amount must not be zero")
        return v

    @field_validator("vendor_amount")
    @classmethod
    def _vendor_amount_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= Decimal("0"):
            raise ValueError("vendor_amount must be positive")
        return v


class VoidRequest(BaseModel):
    void_reason: str = Field(..., min_length=1, max_length=500)


# ── Serializer ────────────────────────────────────────────────────────────────

def _charge_dict(
    charge: OwnerCharge,
    owner_name: Optional[str] = None,
    property_name: Optional[str] = None,
    vendor_name: Optional[str] = None,
    notification_sent: Optional[bool] = None,
    notification_error: Optional[str] = None,
    obp_recomputed: Optional[dict] = None,
    recompute_error: Optional[dict] = None,
) -> dict:
    return {
        "id": charge.id,
        "owner_payout_account_id": charge.owner_payout_account_id,
        "owner_name": owner_name,
        "property_name": property_name,
        "posting_date": charge.posting_date.isoformat() if charge.posting_date else None,
        "transaction_type": charge.transaction_type,
        "transaction_type_display": charge.transaction_type_display,
        "description": charge.description,
        "amount": str(charge.amount),
        "reference_id": charge.reference_id,
        # Vendor + markup fields (I.1a)
        "vendor_id": str(charge.vendor_id) if charge.vendor_id else None,
        "vendor_name": vendor_name,
        "markup_percentage": str(charge.markup_percentage) if charge.markup_percentage is not None else "0.00",
        "vendor_amount": str(charge.vendor_amount) if charge.vendor_amount is not None else None,
        "created_at": charge.created_at.isoformat() if charge.created_at else None,
        "created_by": charge.created_by,
        "voided_at": charge.voided_at.isoformat() if charge.voided_at else None,
        "voided_by": charge.voided_by,
        "void_reason": charge.void_reason,
        # Notification fields — only present on create response when send_notification=True
        **({"notification_sent": notification_sent, "notification_error": notification_error}
           if notification_sent is not None else {}),
        # OBP recompute result (I.4) — present on all mutation responses
        "obp_recomputed": obp_recomputed,
        "recompute_error": recompute_error,
    }


async def _enrich(
    db: AsyncSession, charge: OwnerCharge
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (owner_name, property_name, vendor_name) for display purposes."""
    opa = await db.get(OwnerPayoutAccount, charge.owner_payout_account_id)
    owner_name = opa.owner_name if opa else None
    property_name: Optional[str] = None
    if opa:
        try:
            prop_uuid = _uuid_mod.UUID(str(opa.property_id))
            prop = await db.get(Property, prop_uuid)
            property_name = prop.name if prop else str(opa.property_id)
        except ValueError:
            property_name = str(opa.property_id)
    vendor_name: Optional[str] = None
    if charge.vendor_id:
        vendor = await db.get(Vendor, charge.vendor_id)
        vendor_name = vendor.name if vendor else None
    return owner_name, property_name, vendor_name


# ── Recompute helper (I.4) ────────────────────────────────────────────────────

async def _run_recompute(
    db: AsyncSession,
    charge_id: int,
    event_type: Literal["create", "update", "void"],
) -> tuple[Optional[dict], Optional[dict]]:
    """
    Run OBP recompute after a charge mutation, then commit the recompute.
    Returns (obp_recomputed_dict, recompute_error_dict).

    Charge is already committed before this function is called.
    The recompute is a separate transaction — charge save is always safe.
    """
    try:
        result: Optional[RecomputeResult] = await recompute_obp_for_charge_event(
            db, charge_id=charge_id, event_type=event_type
        )
        await db.commit()  # commit the OBP update (separate from charge commit)
        if result is None:
            return None, None
        return {
            "obp_id": result.obp_id,
            "old_closing": str(result.old_closing),
            "new_closing": str(result.new_closing),
            "delta": str(result.delta),
            "old_total_charges": str(result.old_total_charges),
            "new_total_charges": str(result.new_total_charges),
        }, None
    except OBPFinalizedError as exc:
        logger.warning(
            "charge_recompute_skipped_finalized",
            charge_id=charge_id,
            obp_id=exc.obp_id,
            obp_status=exc.obp_status,
            event_type=event_type,
        )
        return None, {
            "code": "OBP_FINALIZED",
            "obp_id": exc.obp_id,
            "status": exc.obp_status,
            "message": (
                "Charge saved but statement is finalized. "
                "Un-finalize the statement to reflect this charge."
            ),
        }
    except Exception as exc:
        logger.error(
            "charge_recompute_failed",
            charge_id=charge_id,
            event_type=event_type,
            error=str(exc)[:200],
        )
        return None, {
            "code": "RECOMPUTE_FAILED",
            "message": str(exc)[:200],
        }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/charges", status_code=201)
async def create_charge(
    body: OwnerChargeCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Create an owner charge or credit."""
    # Verify owner is enrolled
    opa = await db.get(OwnerPayoutAccount, body.owner_payout_account_id)
    if not opa:
        raise HTTPException(404, f"No payout account found for id={body.owner_payout_account_id}")
    if not opa.stripe_account_id:
        raise HTTPException(
            422,
            f"Owner '{opa.owner_name}' has not completed Stripe onboarding. "
            "Charges can only be posted to enrolled owners.",
        )

    # Verify vendor exists (if provided)
    vendor_name: Optional[str] = None
    if body.vendor_id is not None:
        vendor = await db.get(Vendor, body.vendor_id)
        if not vendor:
            raise HTTPException(404, f"Vendor {body.vendor_id} not found")
        if not vendor.active:
            raise HTTPException(422, f"Vendor '{vendor.name}' is inactive")
        vendor_name = vendor.name

    # Verify property is active (not offboarded)
    try:
        prop_uuid = _uuid_mod.UUID(str(opa.property_id))
        prop = await db.get(Property, prop_uuid)
        if prop and getattr(prop, "renting_state", "active") not in ("active", "pre_launch"):
            raise HTTPException(
                422,
                f"Property '{prop.name}' has renting_state='{prop.renting_state}'. "
                "Charges cannot be posted to offboarded or paused properties.",
            )
    except ValueError:
        pass  # fake/test property_id — allow through

    # Check period lock
    locked_period = await is_charge_period_locked(
        db, body.owner_payout_account_id, body.posting_date
    )
    if locked_period:
        raise _locked_error(locked_period)

    # Compute final owner-facing amount
    owner_amount = body.computed_amount()

    charge = OwnerCharge(
        owner_payout_account_id=body.owner_payout_account_id,
        posting_date=body.posting_date,
        transaction_type=body.transaction_type.value,
        description=body.description,
        amount=owner_amount,
        reference_id=body.reference_id,
        vendor_id=body.vendor_id,
        markup_percentage=body.markup_percentage,
        vendor_amount=body.vendor_amount,
        created_by=user.email,
    )
    db.add(charge)
    await db.commit()
    await db.refresh(charge)

    owner_name, property_name, _ = await _enrich(db, charge)
    logger.info(
        "owner_charge_created",
        charge_id=charge.id,
        owner=owner_name,
        amount=float(charge.amount),
        type=charge.transaction_type,
        vendor=vendor_name,
        markup=float(body.markup_percentage),
        send_notification=body.send_notification,
    )

    # Fire email notification if requested (I.1b)
    notification_sent: Optional[bool] = None
    notification_error: Optional[str] = None
    if body.send_notification:
        try:
            notification_sent = await send_owner_charge_notification(db, charge_id=charge.id)
            if not notification_sent:
                notification_error = "Email not sent — SMTP not configured or owner has no email"
        except Exception as exc:
            notification_sent = False
            notification_error = str(exc)[:200]
            logger.error("owner_charge_notification_error", charge_id=charge.id, error=notification_error)

    # OBP recompute (I.4) — runs after charge commit, in separate transaction
    obp_recomputed, recompute_error = await _run_recompute(db, int(charge.id), "create")  # type: ignore[arg-type]

    return _charge_dict(charge, owner_name, property_name, vendor_name,
                        notification_sent=notification_sent,
                        notification_error=notification_error,
                        obp_recomputed=obp_recomputed,
                        recompute_error=recompute_error)


@router.get("/charges")
async def list_charges(
    owner_payout_account_id: Optional[int] = Query(None),
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    transaction_type: Optional[OwnerChargeType] = Query(None),
    include_voided: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List owner charges with optional filters."""
    q = select(OwnerCharge)

    if owner_payout_account_id is not None:
        q = q.where(OwnerCharge.owner_payout_account_id == owner_payout_account_id)
    if period_start is not None:
        q = q.where(OwnerCharge.posting_date >= period_start)
    if period_end is not None:
        q = q.where(OwnerCharge.posting_date <= period_end)
    if transaction_type is not None:
        q = q.where(OwnerCharge.transaction_type == transaction_type.value)
    if not include_voided:
        q = q.where(OwnerCharge.voided_at.is_(None))

    q = q.order_by(OwnerCharge.posting_date.desc(), OwnerCharge.created_at.desc())
    q = q.offset(offset).limit(limit)

    result = await db.execute(q)
    charges = result.scalars().all()

    items = []
    for c in charges:
        owner_name, property_name, vendor_name = await _enrich(db, c)
        items.append(_charge_dict(c, owner_name, property_name, vendor_name))

    return {"charges": items, "total": len(items)}


@router.get("/charges/{charge_id}")
async def get_charge(charge_id: int, db: AsyncSession = Depends(get_db)):
    charge = await db.get(OwnerCharge, charge_id)
    if not charge:
        raise HTTPException(404, f"Charge {charge_id} not found")
    owner_name, property_name, vendor_name = await _enrich(db, charge)
    return _charge_dict(charge, owner_name, property_name, vendor_name)


@router.patch("/charges/{charge_id}")
async def update_charge(
    charge_id: int,
    body: OwnerChargePatchRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Update description, posting_date, amount, or reference_id on a charge."""
    charge = await db.get(OwnerCharge, charge_id)
    if not charge:
        raise HTTPException(404, f"Charge {charge_id} not found")
    if charge.is_voided:
        raise HTTPException(422, f"Charge {charge_id} has already been voided and cannot be updated")

    # Lock check on current posting_date
    locked = await is_charge_period_locked(
        db, charge.owner_payout_account_id, charge.posting_date
    )
    if locked:
        raise _locked_error(locked)

    # If moving to a new posting_date, check that date too
    new_date = body.posting_date
    if new_date is not None and new_date != charge.posting_date:
        locked_new = await is_charge_period_locked(
            db, charge.owner_payout_account_id, new_date
        )
        if locked_new:
            raise _locked_error(locked_new)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(charge, field, value)  # type: ignore[arg-type]

    # If vendor_amount or markup_percentage updated, recompute amount
    if "vendor_amount" in updates or "markup_percentage" in updates:
        va = charge.vendor_amount
        mp = charge.markup_percentage
        if va is not None:
            factor = Decimal("1") + Decimal(str(mp)) / Decimal("100")
            charge.amount = (Decimal(str(va)) * factor).quantize(  # type: ignore[assignment]
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

    await db.commit()
    await db.refresh(charge)
    owner_name, property_name, vendor_name = await _enrich(db, charge)
    logger.info("owner_charge_updated", charge_id=charge_id, fields=list(updates.keys()))
    obp_recomputed, recompute_error = await _run_recompute(db, charge_id, "update")
    return _charge_dict(charge, owner_name, property_name, vendor_name,
                        obp_recomputed=obp_recomputed, recompute_error=recompute_error)


@router.post("/charges/{charge_id}/void")
async def void_charge(
    charge_id: int,
    body: VoidRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Void a charge. Voided charges are excluded from statement totals."""
    charge = await db.get(OwnerCharge, charge_id)
    if not charge:
        raise HTTPException(404, f"Charge {charge_id} not found")
    if charge.is_voided:
        raise HTTPException(422, f"Charge {charge_id} is already voided")

    locked = await is_charge_period_locked(
        db, charge.owner_payout_account_id, charge.posting_date
    )
    if locked:
        raise _locked_error(locked)

    charge.voided_at = datetime.now(_UTC)  # type: ignore[assignment]
    charge.voided_by = user.email  # type: ignore[assignment]
    charge.void_reason = body.void_reason  # type: ignore[assignment]
    await db.commit()
    await db.refresh(charge)
    owner_name, property_name, vendor_name = await _enrich(db, charge)
    logger.info("owner_charge_voided", charge_id=charge_id, voided_by=user.email)
    obp_recomputed, recompute_error = await _run_recompute(db, charge_id, "void")
    return _charge_dict(charge, owner_name, property_name, vendor_name,
                        obp_recomputed=obp_recomputed, recompute_error=recompute_error)
