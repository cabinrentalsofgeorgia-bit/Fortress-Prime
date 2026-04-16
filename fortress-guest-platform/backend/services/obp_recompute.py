"""
OBP Recompute Service — event-driven closing_balance update (I.4).

When an owner_charge is created, updated, or voided, the affected
OwnerBalancePeriod's aggregates (total_charges, total_revenue,
total_commission, closing_balance) need to be rebuilt from source
records to stay accurate.

Entry points
────────────
  recompute_obp_for_charge_event(db, charge_id, event_type)
    → used by admin_charges.py on every create / update / void

  recompute_obp_for_period(db, owner_payout_account_id, period_start,
                            period_end, charge_id, event_type)
    → lower-level; callable from future I.2 / I.3 / I.5 paths

Design invariants
─────────────────
  • Full rebuild from source records on every call — no drift
  • Row-level lock (SELECT FOR UPDATE) — concurrent-safe
  • Charge save and recompute are separate transactions:
    charge commit happens in the caller first, then recompute
    runs in the same session (new implicit transaction).
    Charge save is always the source of truth.
  • Finalized OBPs (approved / emailed / paid) raise OBPFinalizedError.
    Charge still saves; API surface exposes the error reason.
  • DRAFT OBPs and PENDING_APPROVAL OBPs are both recomputable.
  • If no OBP covers the charge's posting_date, recompute is a no-op
    (charge exists without a generated statement; user must generate).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.models.owner_charge import OwnerCharge
from backend.services.statement_computation import (
    compute_owner_statement,
    StatementComputationError,
)

logger = structlog.get_logger(service="obp_recompute")
_UTC = timezone.utc

# Statuses that block recompute — audit integrity of finalized statements
_FINALIZED_STATUSES = frozenset([
    StatementPeriodStatus.APPROVED.value,
    StatementPeriodStatus.PAID.value,
    StatementPeriodStatus.EMAILED.value,
])
# NOTE: VOIDED statements are excluded — a voided OBP is already dead,
# not worth recomputing, but not an error either (treat as no-op below).
_VOIDED_STATUS = StatementPeriodStatus.VOIDED.value


# ── Exception ─────────────────────────────────────────────────────────────────

class OBPFinalizedError(Exception):
    """Raised when a charge event tries to recompute a finalized OBP."""

    def __init__(self, obp_id: int, obp_status: str, charge_id: int) -> None:
        super().__init__(
            f"OBP {obp_id} is '{obp_status}' — charge {charge_id} was saved "
            "but the closing_balance was NOT updated. Un-finalize the statement "
            "to reflect this charge."
        )
        self.obp_id = obp_id
        self.obp_status = obp_status
        self.charge_id = charge_id


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RecomputeResult:
    obp_id: int
    old_closing: Decimal
    new_closing: Decimal
    delta: Decimal
    old_total_charges: Decimal
    new_total_charges: Decimal


# ── Core recompute ────────────────────────────────────────────────────────────

async def recompute_obp_for_period(
    db: AsyncSession,
    *,
    owner_payout_account_id: int,
    period_start: date,
    period_end: date,
    charge_id: int,
    event_type: Literal["create", "update", "void"],
) -> Optional[RecomputeResult]:
    """
    Rebuild aggregates for the OBP matching (opa_id, period_start, period_end).

    Returns None if no OBP exists for this scope (no-op — charge is
    recorded but has no generated statement to update yet).

    Raises OBPFinalizedError if the OBP is in an approved/paid/emailed state.
    """
    # 1. Find and lock the OBP (SELECT FOR UPDATE)
    result = await db.execute(
        select(OwnerBalancePeriod)
        .where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id,
            OwnerBalancePeriod.period_start == period_start,
            OwnerBalancePeriod.period_end == period_end,
        )
        .with_for_update()
    )
    period = result.scalar_one_or_none()

    if period is None:
        logger.info(
            "obp_recompute_no_period",
            charge_id=charge_id,
            opa_id=owner_payout_account_id,
            period_start=str(period_start),
            period_end=str(period_end),
            event_type=event_type,
        )
        return None

    # 2. Voided OBPs: no-op (not an error, but no point recomputing)
    if period.status == _VOIDED_STATUS:
        logger.info(
            "obp_recompute_skipped_voided",
            obp_id=period.id,
            charge_id=charge_id,
            event_type=event_type,
        )
        return None

    # 3. Finalized OBPs: raise (charge saved, but OBP locked)
    if period.status in _FINALIZED_STATUSES:
        raise OBPFinalizedError(
            obp_id=period.id,
            obp_status=str(period.status),
            charge_id=charge_id,
        )

    old_closing = Decimal(str(period.closing_balance))
    old_charges = Decimal(str(period.total_charges))

    # 4. Recompute from source records via compute_owner_statement.
    #    require_stripe_enrollment=False: secondary OPAs (Cherokee, Serendipity)
    #    have stripe_account_id=NULL; their charges must still be recomputed.
    stmt = await compute_owner_statement(
        db,
        owner_payout_account_id,
        period_start,
        period_end,
        require_stripe_enrollment=False,
    )

    new_total_revenue = stmt.total_gross
    new_total_commission = stmt.total_commission
    new_total_charges = stmt.total_charges
    new_closing = (
        Decimal(str(period.opening_balance))
        + new_total_revenue
        - new_total_commission
        - new_total_charges
        # total_payments and total_owner_income are future phases
    )

    period.total_revenue    = new_total_revenue     # type: ignore[assignment]
    period.total_commission = new_total_commission  # type: ignore[assignment]
    period.total_charges    = new_total_charges     # type: ignore[assignment]
    period.closing_balance  = new_closing           # type: ignore[assignment]
    period.updated_at       = datetime.now(_UTC)    # type: ignore[assignment]
    # Keep existing status — never escalate/demote on recompute

    await db.flush()

    result_obj = RecomputeResult(
        obp_id=period.id,
        old_closing=old_closing,
        new_closing=new_closing,
        delta=new_closing - old_closing,
        old_total_charges=old_charges,
        new_total_charges=new_total_charges,
    )

    logger.info(
        "obp_recomputed",
        obp_id=period.id,
        charge_id=charge_id,
        event_type=event_type,
        old_closing=float(old_closing),
        new_closing=float(new_closing),
        delta=float(new_closing - old_closing),
        old_total_charges=float(old_charges),
        new_total_charges=float(new_total_charges),
        opa_id=owner_payout_account_id,
        period=f"{period_start}..{period_end}",
    )

    return result_obj


async def recompute_obp_for_charge_event(
    db: AsyncSession,
    *,
    charge_id: int,
    event_type: Literal["create", "update", "void"],
) -> Optional[RecomputeResult]:
    """
    Load the charge, derive the affected period, and delegate to
    recompute_obp_for_period.

    Returns None if the charge doesn't exist or has no covering OBP.
    Propagates OBPFinalizedError to the caller.
    """
    charge = await db.get(OwnerCharge, charge_id)
    if charge is None:
        logger.warning("obp_recompute_charge_not_found", charge_id=charge_id)
        return None

    posting_date: date = charge.posting_date  # type: ignore[assignment]

    # Period = the calendar month containing posting_date.
    # OBPs are created per-calendar-month by generate_monthly_statements.
    period_start = posting_date.replace(day=1)
    # End of month: first day of next month - 1 day
    if posting_date.month == 12:
        period_end = posting_date.replace(year=posting_date.year + 1, month=1, day=1)
    else:
        period_end = posting_date.replace(month=posting_date.month + 1, day=1)
    # Subtract one day to get last day of the month
    import datetime as _dt
    period_end = (
        _dt.date(period_end.year, period_end.month, 1)
        - _dt.timedelta(days=1)
    )

    return await recompute_obp_for_period(
        db,
        owner_payout_account_id=int(charge.owner_payout_account_id),  # type: ignore[arg-type]
        period_start=period_start,
        period_end=period_end,
        charge_id=charge_id,
        event_type=event_type,
    )
