#!/usr/bin/env python3
"""
H.2 — Generate March 2026 OBPs for Gary Knight's Cherokee Sunrise and Serendipity.

Run AFTER h2_opa_insert.sql. Generates or updates OBPs for all 3 Gary properties:
  - Fallen Timber Lodge                  (OPA 1824, stripe_account_id set)
  - Cherokee Sunrise on Noontootla Creek (OPA created in H.2, stripe_account_id=NULL)
  - Serendipity on Noontootla Creek      (OPA created in H.2, stripe_account_id=NULL)

Bypasses the stripe_account_id IS NOT NULL filter in generate_monthly_statements
by querying for OPAs by streamline_owner_id=146514 directly.

Fallen Timber (OBP 25680, pending_approval) will be regenerated in-place:
  - opening_balance=500702.41 is PRESERVED (get_or_create returns existing row unchanged)
  - closing_balance is RECOMPUTED from current reservations (same value expected)

Usage:
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    source .env
    python backend/scripts/h2_generate_obps.py

Expected output (after h2_opa_insert.sql committed):
    updated   | Gary Knight | Fallen Timber Lodge                  | closing=$504,738.26
    created   | Gary Knight | Cherokee Sunrise on Noontootla Creek | closing=$64,822.71
    created   | Gary Knight | Serendipity on Noontootla Creek      | closing=$X,XXX.XX
"""
import asyncio
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.services.balance_period import get_or_create_balance_period
from backend.services.statement_computation import (
    compute_owner_statement,
    StatementComputationError,
)

PERIOD_START = date(2026, 3, 1)
PERIOD_END   = date(2026, 3, 31)
SL_OWNER_ID  = 146514  # Gary Knight

_LOCKED_STATUSES = frozenset([
    StatementPeriodStatus.APPROVED.value,
    StatementPeriodStatus.PAID.value,
    StatementPeriodStatus.EMAILED.value,
    StatementPeriodStatus.VOIDED.value,
])


async def main() -> None:
    _UTC = timezone.utc
    errors = 0

    async with AsyncSessionLocal() as db:
        # Query ALL OPAs for Gary (including those without stripe_account_id)
        result = await db.execute(
            select(OwnerPayoutAccount).where(
                OwnerPayoutAccount.streamline_owner_id == SL_OWNER_ID
            )
        )
        opas = result.scalars().all()

        if not opas:
            print(f"ERROR: no OPAs found for streamline_owner_id={SL_OWNER_ID}")
            sys.exit(1)

        print(f"\nFound {len(opas)} OPA(s) for sl_owner {SL_OWNER_ID}")
        print(f"Generating March 2026 OBPs...\n")

        for opa in opas:
            try:
                period = await get_or_create_balance_period(
                    db, opa.id, PERIOD_START, PERIOD_END
                )

                if period.status in _LOCKED_STATUSES:
                    closing = f"${float(period.closing_balance):,.2f}"
                    print(f"  skipped_locked    | {opa.owner_name:<15} | OPA {opa.id} | closing={closing}")
                    continue

                # Compute statement from reservations in fortress_shadow.
                # require_stripe_enrollment=False: Cherokee/Serendipity OPAs have
                # stripe_account_id=NULL (Gary's single Stripe account is on OPA 1824).
                stmt = await compute_owner_statement(
                    db, opa.id, PERIOD_START, PERIOD_END,
                    require_stripe_enrollment=False,
                )

                was_new = period.total_revenue == Decimal("0") and period.status == "draft"

                new_closing = (
                    Decimal(str(period.opening_balance))
                    + stmt.total_gross
                    - stmt.total_commission
                    - stmt.total_charges
                )

                period.total_revenue    = stmt.total_gross       # type: ignore[assignment]
                period.total_commission = stmt.total_commission   # type: ignore[assignment]
                period.total_charges    = stmt.total_charges      # type: ignore[assignment]
                period.closing_balance  = new_closing             # type: ignore[assignment]
                period.status           = StatementPeriodStatus.PENDING_APPROVAL.value  # type: ignore[assignment]
                period.updated_at       = datetime.now(_UTC)      # type: ignore[assignment]

                await db.flush()

                action = "created  " if was_new else "updated  "
                closing = f"${float(new_closing):,.2f}"
                print(
                    f"  {action} | OPA {opa.id:<6} | "
                    f"{opa.owner_name:<15} | "
                    f"property={opa.property_id[:8]}... | "
                    f"revenue=${float(stmt.total_gross):,.2f} | "
                    f"commission=${float(stmt.total_commission):,.2f} | "
                    f"closing={closing}"
                )

            except StatementComputationError as exc:
                print(f"  ERROR             | OPA {opa.id} | {exc.code}: {exc.message[:100]}")
                errors += 1

        await db.commit()

    if errors:
        print(f"\n*** {errors} ERROR(S) — review output before running SQL scripts ***")
        sys.exit(1)
    else:
        print(
            "\nOK — OBPs committed. Now run:\n"
            "  psql $PSQL -f backend/scripts/h2_opening_balance_dryrun.sql\n"
            "  # verify output, then:\n"
            "  psql $PSQL -f backend/scripts/h2_opening_balance_commit.sql"
        )


asyncio.run(main())
