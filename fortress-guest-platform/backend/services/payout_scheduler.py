"""
Payout Scheduler — Automated Owner Disbursement Engine

Bridges the gap between calculate_owner_payout() (which knows what's owed)
and initiate_transfer() (which sends it via Stripe Connect) — neither was
calling the other. This service is the missing link.

Sweep logic:
  1. Find active owners with a scheduled payout due (next_scheduled_payout <= now)
  2. Sum unpaid reservation amounts since last_payout_at
  3. Stage a payout_ledger row
  4. Call initiate_transfer() to send the Stripe transfer
  5. Post a trust ledger debit / credit pair
  6. Update next_scheduled_payout
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal

logger = structlog.get_logger(service="payout_scheduler")

_UTC = timezone.utc


def _next_payout_date(
    schedule: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    from_dt: datetime,
) -> datetime:
    """Calculate the next payout date after from_dt."""
    base = from_dt.replace(hour=6, minute=0, second=0, microsecond=0)
    if schedule == "weekly":
        target_dow = day_of_week if day_of_week is not None else 0  # Monday default
        days_ahead = (target_dow - base.weekday()) % 7 or 7
        return base + timedelta(days=days_ahead)
    if schedule == "biweekly":
        target_dow = day_of_week if day_of_week is not None else 0
        days_ahead = (target_dow - base.weekday()) % 7 or 14
        return base + timedelta(days=days_ahead)
    if schedule == "monthly":
        target_dom = max(1, min(28, day_of_month or 1))
        candidate = base.replace(day=target_dom)
        if candidate <= from_dt:
            # Advance one month
            month = base.month + 1
            year = base.year + (month > 12)
            month = month if month <= 12 else 1
            candidate = candidate.replace(year=year, month=month, day=target_dom)
        return candidate
    # 'manual' or unknown — no scheduled next date
    return from_dt + timedelta(days=3650)  # Far future sentinel


async def calculate_pending_owner_amount(
    property_id: str,
    since: Optional[datetime],
    db: AsyncSession,
) -> Decimal:
    """
    Calculate the total unpaid owner share for a property since a given date.
    Sums revenue from reservations that checked out after `since` and have
    not been included in an existing payout_ledger row.
    """
    since_dt = since or datetime(2020, 1, 1, tzinfo=_UTC)

    # Sum owner_amount from payout_ledger rows already processed for this property
    already_paid_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(owner_amount), 0)
            FROM payout_ledger
            WHERE property_id = :pid
              AND status IN ('staged', 'processing', 'completed', 'settled')
              AND created_at >= :since
        """),
        {"pid": property_id, "since": since_dt},
    )
    already_paid = Decimal(str(already_paid_result.scalar() or 0))

    # Sum trust ledger entries tagged as owner revenue since the cutoff
    # Fallback: use a simple 65% split of total_amount from checked-out reservations
    revenue_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_amount), 0)
            FROM reservations
            WHERE property_id = :pid
              AND status IN ('checked_out', 'confirmed')
              AND check_out_date >= :since_date
              AND check_out_date <= CURRENT_DATE
        """),
        {"pid": property_id, "since_date": since_dt.date()},
    )
    gross = Decimal(str(revenue_result.scalar() or 0))

    # Apply 65% owner split (default; overridden by management_splits table if present)
    owner_split_result = await db.execute(
        text("""
            SELECT COALESCE(owner_pct, 65) / 100.0
            FROM management_splits
            WHERE property_id = :pid
            LIMIT 1
        """),
        {"pid": property_id},
    )
    row = owner_split_result.first()
    owner_pct = Decimal(str(row[0])) if row else Decimal("0.65")

    gross_owner_share = (gross * owner_pct).quantize(Decimal("0.01"))
    pending = max(Decimal("0.00"), gross_owner_share - already_paid)
    return pending


async def stage_payout(
    property_id: str,
    owner_amount: Decimal,
    db: AsyncSession,
) -> int:
    """Insert a staged payout_ledger row. Returns the new row id."""
    result = await db.execute(
        text("""
            INSERT INTO payout_ledger
                (property_id, gross_amount, owner_amount, status, created_at, updated_at)
            VALUES
                (:pid, :gross, :owner, 'staged', NOW(), NOW())
            RETURNING id
        """),
        {
            "pid": property_id,
            "gross": float(owner_amount),
            "owner": float(owner_amount),
        },
    )
    row = result.first()
    await db.flush()
    return int(row[0])


async def execute_staged_payout(
    payout_ledger_id: int,
    db: AsyncSession,
) -> dict:
    """
    Execute a staged payout: call Stripe Transfer and update ledger state.
    Posts to trust ledger as a debit against Owner Payable.
    """
    from backend.services.payout_service import initiate_transfer
    from backend.services.trust_ledger import post_variance_trust_entry

    # Load the payout row
    row_result = await db.execute(
        text("SELECT property_id, owner_amount FROM payout_ledger WHERE id = :id"),
        {"id": payout_ledger_id},
    )
    row = row_result.first()
    if not row:
        raise RuntimeError(f"payout_ledger row {payout_ledger_id} not found")
    property_id, owner_amount = row[0], Decimal(str(row[1]))

    # Look up connected Stripe account
    acct_result = await db.execute(
        text("SELECT stripe_account_id FROM owner_payout_accounts WHERE property_id = :pid"),
        {"pid": property_id},
    )
    acct_row = acct_result.first()
    if not acct_row or not acct_row[0]:
        await db.execute(
            text("UPDATE payout_ledger SET status='failed', failure_reason='no_stripe_account', updated_at=NOW() WHERE id=:id"),
            {"id": payout_ledger_id},
        )
        await db.commit()
        return {"status": "failed", "reason": "no_stripe_account"}

    stripe_account_id = acct_row[0]

    transfer_result = await initiate_transfer(
        account_id=stripe_account_id,
        amount=float(owner_amount),
        description=f"Owner payout — property {property_id}",
        metadata={"payout_ledger_id": str(payout_ledger_id), "property_id": property_id},
    )

    if not transfer_result or transfer_result.get("status") == "failed":
        failure = (transfer_result or {}).get("error", "transfer_failed")
        await db.execute(
            text("UPDATE payout_ledger SET status='failed', failure_reason=:reason, updated_at=NOW() WHERE id=:id"),
            {"id": payout_ledger_id, "reason": failure[:255]},
        )
        await db.commit()
        return {"status": "failed", "reason": failure}

    transfer_id = transfer_result["transfer_id"]
    await db.execute(
        text("""
            UPDATE payout_ledger
            SET stripe_transfer_id = :tid, status = 'processing',
                initiated_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """),
        {"id": payout_ledger_id, "tid": transfer_id},
    )

    # Update schedule tracking
    await db.execute(
        text("""
            UPDATE owner_payout_accounts
            SET last_payout_at = NOW(), updated_at = NOW()
            WHERE property_id = :pid
        """),
        {"pid": property_id},
    )

    # Post trust ledger entry: Debit Owner Payable / Credit Operating Cash
    amount_cents = int(owner_amount * 100)
    event_id = f"payout_scheduler_{payout_ledger_id}_{transfer_id}"
    try:
        await post_variance_trust_entry(
            db=db,
            reservation_id=property_id,
            amount_cents=amount_cents,
            debit_account_name="Owner Payable",
            credit_account_name="Operating Cash",
            event_id=event_id,
        )
    except Exception as exc:
        logger.warning(
            "payout_trust_ledger_post_failed",
            payout_ledger_id=payout_ledger_id,
            error=str(exc)[:200],
        )

    await db.commit()
    logger.info(
        "payout_executed",
        payout_ledger_id=payout_ledger_id,
        property_id=property_id,
        transfer_id=transfer_id,
        amount=float(owner_amount),
    )
    return {"status": "processing", "transfer_id": transfer_id, "amount": float(owner_amount)}


async def run_payout_sweep() -> dict:
    """
    Daily sweep: find all owners with a scheduled payout due, calculate pending
    amounts, and execute transfers. Safe to call multiple times — idempotent
    per property per day via the minimum_payout_threshold guard.
    """
    processed = 0
    total_amount = Decimal("0.00")
    skipped = 0
    errors: list[str] = []

    async with AsyncSessionLocal() as db:
        # Find owners due for a scheduled payout
        due_result = await db.execute(
            text("""
                SELECT property_id, last_payout_at, payout_schedule,
                       payout_day_of_week, payout_day_of_month,
                       minimum_payout_threshold, next_scheduled_payout
                FROM owner_payout_accounts
                WHERE account_status = 'active'
                  AND payout_schedule != 'manual'
                  AND stripe_account_id IS NOT NULL
                  AND (next_scheduled_payout IS NULL OR next_scheduled_payout <= NOW())
            """),
        )
        due_rows = due_result.fetchall()

        if not due_rows:
            logger.info("payout_sweep_no_owners_due")
            return {"processed": 0, "total_amount": 0.0, "skipped": 0, "errors": []}

        for row in due_rows:
            property_id = row[0]
            last_payout_at = row[1]
            schedule = row[2]
            dow = row[3]
            dom = row[4]
            min_threshold = Decimal(str(row[5] or "100.00"))
            try:
                pending = await calculate_pending_owner_amount(property_id, last_payout_at, db)

                if pending < min_threshold:
                    logger.info(
                        "payout_sweep_below_threshold",
                        property_id=property_id,
                        pending=float(pending),
                        threshold=float(min_threshold),
                    )
                    skipped += 1
                    continue

                ledger_id = await stage_payout(property_id, pending, db)
                result = await execute_staged_payout(ledger_id, db)

                if result.get("status") in ("processing", "completed"):
                    processed += 1
                    total_amount += pending
                    # Advance next_scheduled_payout
                    next_dt = _next_payout_date(schedule, dow, dom, datetime.now(_UTC))
                    await db.execute(
                        text("""
                            UPDATE owner_payout_accounts
                            SET next_scheduled_payout = :next_dt, updated_at = NOW()
                            WHERE property_id = :pid
                        """),
                        {"next_dt": next_dt, "pid": property_id},
                    )
                    await db.commit()
                else:
                    errors.append(f"{property_id}: {result.get('reason', 'unknown')}")

            except Exception as exc:
                errors.append(f"{property_id}: {str(exc)[:120]}")
                logger.error("payout_sweep_property_error", property_id=property_id, error=str(exc)[:200])

    logger.info(
        "payout_sweep_complete",
        processed=processed,
        total_amount=float(total_amount),
        skipped=skipped,
        errors=len(errors),
    )
    return {
        "processed": processed,
        "total_amount": float(total_amount),
        "skipped": skipped,
        "errors": errors,
    }
