"""
Balance Period Service
======================
Manages the running ledger for owner balance periods.

Entry point:
    get_or_create_balance_period(db, owner_payout_account_id, period_start, period_end)
        → OwnerBalancePeriod

The function is idempotent: calling it twice for the same owner+period returns
the same row without creating a duplicate.  It uses SELECT FOR UPDATE to prevent
races when multiple workers call it simultaneously.

Opening balance logic:
  - If a prior closed period exists for this owner, the opening balance is that
    period's closing balance (carries forward indefinitely, including negatives).
  - If no prior period exists (first statement ever, or post-backfill), the
    opening balance is 0.00.  The backfill process (Phase H) will update this
    to the Streamline closing balance before any real statements are generated.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus

logger = structlog.get_logger(service="balance_period")


async def get_or_create_balance_period(
    db: AsyncSession,
    owner_payout_account_id: int,
    period_start: date,
    period_end: date,
) -> OwnerBalancePeriod:
    """
    Return the OwnerBalancePeriod for this owner+period, creating it if needed.

    If a row already exists, it is returned unchanged (regardless of status).
    Callers must not assume the row is in 'draft' — check `.status` if the
    caller cares about the current lifecycle state.

    Uses SELECT FOR UPDATE on the lookup so concurrent calls don't race to
    create duplicate rows.
    """
    if period_end <= period_start:
        raise ValueError(
            f"period_end ({period_end}) must be strictly after period_start ({period_start})"
        )

    # Try to fetch an existing row under a row-level lock.
    existing_result = await db.execute(
        select(OwnerBalancePeriod)
        .where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id,
            OwnerBalancePeriod.period_start == period_start,
            OwnerBalancePeriod.period_end == period_end,
        )
        .with_for_update()
    )
    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        logger.debug(
            "balance_period_found",
            owner_payout_account_id=owner_payout_account_id,
            period_start=str(period_start),
            period_end=str(period_end),
            status=existing.status,
        )
        return existing

    # No row yet — find the most recent prior period's closing balance.
    prior_result = await db.execute(
        select(OwnerBalancePeriod.closing_balance)
        .where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id,
            OwnerBalancePeriod.period_end < period_start,
        )
        .order_by(OwnerBalancePeriod.period_end.desc())
        .limit(1)
    )
    prior_row = prior_result.first()
    opening_balance: Decimal = (
        Decimal(str(prior_row[0])) if prior_row else Decimal("0.00")
    )

    # Create with zero activity; closing_balance satisfies the ledger equation:
    #   closing = opening + 0 - 0 - 0 - 0 + 0 = opening
    new_period = OwnerBalancePeriod(
        owner_payout_account_id=owner_payout_account_id,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=opening_balance,  # no activity yet
        total_revenue=Decimal("0.00"),
        total_commission=Decimal("0.00"),
        total_charges=Decimal("0.00"),
        total_payments=Decimal("0.00"),
        total_owner_income=Decimal("0.00"),
        status=StatementPeriodStatus.DRAFT.value,
    )
    db.add(new_period)
    await db.flush()  # get the auto-generated id without committing
    await db.refresh(new_period)

    logger.info(
        "balance_period_created",
        owner_payout_account_id=owner_payout_account_id,
        period_start=str(period_start),
        period_end=str(period_end),
        opening_balance=float(opening_balance),
    )
    return new_period
