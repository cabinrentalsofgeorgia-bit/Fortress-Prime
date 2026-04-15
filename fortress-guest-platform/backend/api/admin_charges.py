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

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_manager_or_admin
from backend.models.owner_balance_period import OwnerBalancePeriod
from backend.models.owner_charge import OwnerCharge, OwnerChargeType
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.models.staff import StaffUser

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
    amount: Decimal
    reference_id: Optional[str] = Field(None, max_length=100)

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: Decimal) -> Decimal:
        if v == Decimal("0"):
            raise ValueError("amount must not be zero; use void to cancel a charge")
        return v


class OwnerChargePatchRequest(BaseModel):
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    posting_date: Optional[date] = None
    amount: Optional[Decimal] = None
    reference_id: Optional[str] = Field(None, max_length=100)

    @field_validator("amount")
    @classmethod
    def _amount_not_zero(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v == Decimal("0"):
            raise ValueError("amount must not be zero")
        return v


class VoidRequest(BaseModel):
    void_reason: str = Field(..., min_length=1, max_length=500)


# ── Serializer ────────────────────────────────────────────────────────────────

def _charge_dict(
    charge: OwnerCharge,
    owner_name: Optional[str] = None,
    property_name: Optional[str] = None,
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
        "created_at": charge.created_at.isoformat() if charge.created_at else None,
        "created_by": charge.created_by,
        "voided_at": charge.voided_at.isoformat() if charge.voided_at else None,
        "voided_by": charge.voided_by,
        "void_reason": charge.void_reason,
    }


async def _enrich(
    db: AsyncSession, charge: OwnerCharge
) -> tuple[Optional[str], Optional[str]]:
    """Return (owner_name, property_name) for display purposes."""
    opa = await db.get(OwnerPayoutAccount, charge.owner_payout_account_id)
    owner_name = opa.owner_name if opa else None
    property_name: Optional[str] = None
    if opa:
        import uuid as _uuid
        try:
            prop_uuid = _uuid.UUID(opa.property_id)
            prop = await db.get(Property, prop_uuid)
            property_name = prop.name if prop else opa.property_id
        except ValueError:
            property_name = opa.property_id
    return owner_name, property_name


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

    # Verify property is active (not offboarded)
    import uuid as _uuid
    try:
        prop_uuid = _uuid.UUID(opa.property_id)
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

    charge = OwnerCharge(
        owner_payout_account_id=body.owner_payout_account_id,
        posting_date=body.posting_date,
        transaction_type=body.transaction_type.value,
        description=body.description,
        amount=body.amount,
        reference_id=body.reference_id,
        created_by=user.email,
    )
    db.add(charge)
    await db.commit()
    await db.refresh(charge)

    owner_name, property_name = await _enrich(db, charge)
    logger.info(
        "owner_charge_created",
        charge_id=charge.id,
        owner=owner_name,
        amount=float(charge.amount),
        type=charge.transaction_type,
    )
    return _charge_dict(charge, owner_name, property_name)


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
        owner_name, property_name = await _enrich(db, c)
        items.append(_charge_dict(c, owner_name, property_name))

    return {"charges": items, "total": len(items)}


@router.get("/charges/{charge_id}")
async def get_charge(charge_id: int, db: AsyncSession = Depends(get_db)):
    charge = await db.get(OwnerCharge, charge_id)
    if not charge:
        raise HTTPException(404, f"Charge {charge_id} not found")
    owner_name, property_name = await _enrich(db, charge)
    return _charge_dict(charge, owner_name, property_name)


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

    await db.commit()
    await db.refresh(charge)
    owner_name, property_name = await _enrich(db, charge)
    logger.info("owner_charge_updated", charge_id=charge_id, fields=list(updates.keys()))
    return _charge_dict(charge, owner_name, property_name)


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
    owner_name, property_name = await _enrich(db, charge)
    logger.info("owner_charge_voided", charge_id=charge_id, voided_by=user.email)
    return _charge_dict(charge, owner_name, property_name)
