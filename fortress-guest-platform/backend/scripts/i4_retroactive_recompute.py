#!/usr/bin/env python3
"""
I.4 — One-time retroactive recompute of non-finalized OBPs.

OBPs that existed before I.4 was shipped had stale closing_balance
if charges were posted and voided during validation (I.1, I.1a, I.1b).
This script recomputes all non-finalized OBPs and logs any deltas.

Usage:
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    source .env
    python3 backend/scripts/i4_retroactive_recompute.py
"""
import asyncio
import sys
from datetime import timezone

sys.path.insert(0, ".")

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.services.obp_recompute import (
    OBPFinalizedError,
    recompute_obp_for_period,
)

_FINALIZED = frozenset([
    StatementPeriodStatus.APPROVED.value,
    StatementPeriodStatus.PAID.value,
    StatementPeriodStatus.EMAILED.value,
    StatementPeriodStatus.VOIDED.value,
])


async def main() -> None:
    changed = 0
    skipped = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OwnerBalancePeriod).order_by(OwnerBalancePeriod.id)
        )
        all_obps = result.scalars().all()

        print(f"\nFound {len(all_obps)} OBP(s) total. Processing non-finalized...\n")

        for obp in all_obps:
            if obp.status in _FINALIZED:
                print(f"  SKIP   OBP {obp.id:6} | {obp.status:<18} | (finalized — not touched)")
                skipped += 1
                continue

            old_closing = obp.closing_balance
            old_charges = obp.total_charges

            try:
                r = await recompute_obp_for_period(
                    db,
                    owner_payout_account_id=int(obp.owner_payout_account_id),  # type: ignore[arg-type]
                    period_start=obp.period_start,
                    period_end=obp.period_end,
                    charge_id=0,   # synthetic — retroactive
                    event_type="update",
                )
                if r is None:
                    print(f"  NOOP   OBP {obp.id:6} | {obp.status:<18} | no-op (should not happen here)")
                    skipped += 1
                    continue

                delta = r.delta
                if delta != 0:
                    print(
                        f"  CHANGED OBP {obp.id:6} | {obp.status:<18} | "
                        f"old_closing={float(old_closing):,.2f}  "
                        f"new_closing={float(r.new_closing):,.2f}  "
                        f"delta={float(delta):+,.2f}  "
                        f"charges: {float(old_charges):,.2f} → {float(r.new_total_charges):,.2f}"
                    )
                    changed += 1
                else:
                    print(
                        f"  OK     OBP {obp.id:6} | {obp.status:<18} | "
                        f"closing={float(r.new_closing):,.2f} (unchanged)"
                    )

            except OBPFinalizedError as exc:
                print(f"  FINALIZED OBP {obp.id}: {exc}")
                skipped += 1
            except Exception as exc:
                print(f"  ERROR  OBP {obp.id}: {exc}")
                errors += 1

        await db.commit()

    print(f"\n{'─' * 60}")
    print(f"  Total OBPs:    {len(all_obps)}")
    print(f"  Changed:       {changed}")
    print(f"  Unchanged:     {len(all_obps) - changed - skipped - errors}")
    print(f"  Skipped:       {skipped}")
    print(f"  Errors:        {errors}")
    if changed:
        print(f"\n  {changed} OBP(s) had stale closing_balance — now corrected.")
    else:
        print(f"\n  All OBPs were already current.")
    print()


asyncio.run(main())
