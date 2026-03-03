"""
Revenue Bridge — QuantRevenue Forecast → General Ledger
==========================================================
Bridges the gap between the QuantRevenue pricing engine (revenue_ledger)
and the double-entry general ledger (division_b.general_ledger).

Pattern: Accrual + Reversal
    1. After each QuantRevenue run, post FORECAST ACCRUAL entries:
           Dr  1150  Assets:Accounts Receivable:Forecast Revenue
           Cr  4050  Revenue:Rental Income:Forecast
    2. When a guest actually books (fin_reservations), REVERSE the accrual
       and post ACTUAL revenue:
           Reversal:  Dr 4050 / Cr 1150  (undo forecast)
           Actual:    Dr 1000 / Cr 4000  (real revenue)
    3. Stale accruals (dates passed without booking) are reversed nightly.

All forecast entries carry source_type='quantrevenue_forecast' so they
never contaminate the real P&L.

Integration:
    - Called from quant_revenue.run_engine() after a successful pricing run
    - Stale reversal runs from Watchtower or cron
    - Booking confirmation triggered when fin_reservations updated

Module: CF-02 QuantRevenue / Operation Strangler Fig
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

from accounting.models import AccountingError, JournalEntry, LedgerLine
from accounting.engine import post_journal_entry

logger = logging.getLogger("accounting.revenue_bridge")

# Forecast account codes (must exist in division_b.chart_of_accounts)
FORECAST_AR_CODE = "1150"          # Assets:Accounts Receivable:Forecast Revenue
FORECAST_AR_NAME = "Accounts Receivable:Forecast Revenue"
FORECAST_REV_CODE = "4050"         # Revenue:Rental Income:Forecast
FORECAST_REV_NAME = "Rental Income:Forecast"

# Actual revenue accounts (for confirmed bookings)
ACTUAL_BANK_CODE = "1000"          # Assets:Bank:Operating
ACTUAL_BANK_NAME = "Bank:Operating"
ACTUAL_REV_CODE = "4000"           # Revenue:Rental Income:Management Fees
ACTUAL_REV_NAME = "Rental Income:Management Fees"

SOURCE_TYPE = "quantrevenue_forecast"
REVERSAL_SOURCE = "quantrevenue_reversal"
SCHEMA = "division_b"


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def _connect():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _ensure_forecast_accounts(conn):
    """Ensure forecast CoA accounts exist. Idempotent."""
    cur = conn.cursor()
    for code, name, acct_type, normal in [
        (FORECAST_AR_CODE, FORECAST_AR_NAME, "asset", "debit"),
        (FORECAST_REV_CODE, FORECAST_REV_NAME, "revenue", "credit"),
    ]:
        cur.execute(f"""
            INSERT INTO {SCHEMA}.chart_of_accounts
                (code, name, account_type, description, is_active, normal_balance)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (code) DO NOTHING
        """, (code, name, acct_type,
              f"QuantRevenue forecast account (auto-created)", normal))
    conn.commit()


# =============================================================================
# 1. POST FORECAST ACCRUALS
# =============================================================================

def post_forecast_accruals(
    run_id: str,
    schema: str = SCHEMA,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Read the latest QuantRevenue run from revenue_ledger and post
    accrual journal entries to the general ledger.

    Each property-date gets one journal entry:
        Dr  1150  Forecast AR     (adjusted_rate)
        Cr  4050  Forecast Revenue (adjusted_rate)

    Before posting, reverses any stale accruals from prior runs for
    overlapping dates (prevents double-counting).

    Args:
        run_id: The QuantRevenue run_id to process
        schema: Target division schema
        dry_run: If True, compute but don't write

    Returns:
        {"entries_posted": N, "total_accrued": $X, "reversed": M}
    """
    conn = _connect()
    result = {"entries_posted": 0, "total_accrued": Decimal("0.00"), "reversed": 0}

    try:
        _ensure_forecast_accounts(conn)
        cur = conn.cursor()

        # Load rate entries for this run
        cur.execute("""
            SELECT cabin_name, target_date, adjusted_rate, trading_signal, tier
            FROM revenue_ledger
            WHERE run_id = %s AND target_date >= CURRENT_DATE
            ORDER BY cabin_name, target_date
        """, (run_id,))
        rows = cur.fetchall()

        if not rows:
            logger.info(f"[BRIDGE] No future-dated entries for run {run_id}")
            conn.close()
            return result

        # Reverse stale accruals from prior runs covering the same dates
        min_date = min(r["target_date"] for r in rows)
        max_date = max(r["target_date"] for r in rows)
        reversed_count = _reverse_accruals_for_range(
            conn, min_date, max_date, schema, dry_run,
        )
        result["reversed"] = reversed_count

        # Post new forecast accruals
        entries = []
        for row in rows:
            amount = Decimal(str(row["adjusted_rate"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            if amount <= 0:
                continue

            cabin = row["cabin_name"]
            target = row["target_date"]
            display = cabin.replace("_", " ").title()

            entry = JournalEntry(
                entry_id=f"QR-{run_id}-{cabin}-{target}",
                date=target,
                description=(
                    f"QuantRevenue forecast: {display} @ "
                    f"${amount}/night ({row['trading_signal']})"
                ),
                lines=[
                    LedgerLine(
                        account_code=FORECAST_AR_CODE,
                        account_name=FORECAST_AR_NAME,
                        debit=amount,
                        credit=Decimal("0.00"),
                        memo=f"run:{run_id} cabin:{cabin} signal:{row['trading_signal']}",
                    ),
                    LedgerLine(
                        account_code=FORECAST_REV_CODE,
                        account_name=FORECAST_REV_NAME,
                        debit=Decimal("0.00"),
                        credit=amount,
                        memo=f"run:{run_id} cabin:{cabin} signal:{row['trading_signal']}",
                    ),
                ],
                source_type=SOURCE_TYPE,
                source_ref=f"{run_id}:{cabin}:{target}",
                division=schema,
                created_by="revenue_bridge",
                memo=f"tier:{row['tier']} signal:{row['trading_signal']}",
            )
            entries.append(entry)

        if dry_run:
            total = sum(e.total_debits for e in entries)
            logger.info(
                f"[BRIDGE] DRY RUN: Would post {len(entries)} accruals "
                f"totaling ${total:,.2f}"
            )
            result["entries_posted"] = len(entries)
            result["total_accrued"] = total
            conn.close()
            return result

        posted = 0
        total_accrued = Decimal("0.00")
        for entry in entries:
            try:
                entry.validate()
                post_journal_entry(entry, schema)
                posted += 1
                total_accrued += entry.total_debits
            except AccountingError as e:
                logger.warning(f"[BRIDGE] Skipped {entry.entry_id}: {e}")
            except Exception as e:
                # Duplicate entry_id (already posted) is expected on re-runs
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    logger.debug(f"[BRIDGE] Already posted: {entry.entry_id}")
                else:
                    logger.warning(f"[BRIDGE] Error posting {entry.entry_id}: {e}")

        result["entries_posted"] = posted
        result["total_accrued"] = total_accrued
        logger.info(
            f"[BRIDGE] Posted {posted} forecast accruals for run {run_id}, "
            f"total ${total_accrued:,.2f} (reversed {reversed_count} stale)"
        )

    except Exception as e:
        logger.error(f"[BRIDGE] Fatal error in post_forecast_accruals: {e}")
    finally:
        conn.close()

    return result


# =============================================================================
# 2. REVERSE STALE ACCRUALS
# =============================================================================

def _reverse_accruals_for_range(
    conn, start_date: date, end_date: date,
    schema: str = SCHEMA, dry_run: bool = False,
) -> int:
    """
    Reverse all existing forecast accrual entries in the given date range.
    This prevents double-counting when a new QuantRevenue run replaces
    a previous one.

    Returns the number of entries reversed.
    """
    cur = conn.cursor()

    # Find existing forecast journal entries in this date range
    cur.execute(f"""
        SELECT DISTINCT je.entry_id, je.entry_date, je.description
        FROM {schema}.journal_entries je
        WHERE je.source_type = %s
          AND je.entry_date BETWEEN %s AND %s
          AND je.is_posted = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM {schema}.journal_entries rev
              WHERE rev.source_ref = 'REVERSAL:' || je.entry_id
          )
    """, (SOURCE_TYPE, start_date, end_date))
    existing = cur.fetchall()

    if not existing:
        return 0

    if dry_run:
        logger.info(f"[BRIDGE] DRY RUN: Would reverse {len(existing)} stale accruals")
        return len(existing)

    reversed_count = 0
    for je in existing:
        original_id = je["entry_id"]

        # Get the original ledger lines to reverse
        cur.execute(f"""
            SELECT account_code, account_name, debit, credit, memo
            FROM {schema}.general_ledger
            WHERE journal_entry_id = %s
        """, (original_id,))
        lines = cur.fetchall()

        if not lines:
            continue

        # Build reversal entry (swap debits and credits)
        reversal_lines = []
        for line in lines:
            reversal_lines.append(LedgerLine(
                account_code=line["account_code"],
                account_name=line["account_name"],
                debit=Decimal(str(line["credit"])),    # Swap
                credit=Decimal(str(line["debit"])),     # Swap
                memo=f"REVERSAL of {original_id}",
            ))

        reversal = JournalEntry(
            entry_id=f"REV-{original_id}",
            date=je["entry_date"],
            description=f"Reversal: {je['description']}",
            lines=reversal_lines,
            source_type=REVERSAL_SOURCE,
            source_ref=f"REVERSAL:{original_id}",
            division=schema,
            created_by="revenue_bridge",
            memo=f"Auto-reversal of stale forecast accrual",
        )

        try:
            reversal.validate()
            post_journal_entry(reversal, schema)
            reversed_count += 1
        except Exception as e:
            if "duplicate" not in str(e).lower():
                logger.warning(f"[BRIDGE] Failed to reverse {original_id}: {e}")

    return reversed_count


def reverse_stale_accruals(schema: str = SCHEMA, dry_run: bool = False) -> int:
    """
    Reverse forecast accruals for dates that have already passed
    without a confirmed booking. Called from Watchtower or nightly cron.

    Returns the number of entries reversed.
    """
    conn = _connect()
    try:
        _ensure_forecast_accounts(conn)
        yesterday = date.today() - timedelta(days=1)
        past_start = yesterday - timedelta(days=60)  # Look back 60 days
        return _reverse_accruals_for_range(
            conn, past_start, yesterday, schema, dry_run,
        )
    finally:
        conn.close()


# =============================================================================
# 3. CONFIRM BOOKING REVENUE
# =============================================================================

def confirm_booking_revenue(
    cabin_name: str,
    checkin_date: date,
    checkout_date: date,
    total_revenue: float,
    reservation_id: str = "",
    schema: str = SCHEMA,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Called when a guest booking is confirmed via fin_reservations.

    1. Reverse any forecast accruals for this property + date range
    2. Post actual revenue journal entry

    Args:
        cabin_name: Property ID (e.g., "rolling_river")
        checkin_date: Guest check-in date
        checkout_date: Guest check-out date
        total_revenue: Confirmed total revenue amount
        reservation_id: Reference ID from fin_reservations
        schema: Target division schema

    Returns:
        {"reversed": N, "actual_posted": bool, "amount": $X}
    """
    conn = _connect()
    result = {"reversed": 0, "actual_posted": False, "amount": Decimal("0.00")}

    try:
        _ensure_forecast_accounts(conn)
        cur = conn.cursor()

        # 1. Find and reverse forecast accruals for this property + dates
        normalized = cabin_name.lower().replace(" ", "_").replace("'", "")
        cur.execute(f"""
            SELECT DISTINCT je.entry_id, je.entry_date, je.description
            FROM {schema}.journal_entries je
            WHERE je.source_type = %s
              AND je.entry_date BETWEEN %s AND %s
              AND je.source_ref LIKE %s
              AND je.is_posted = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.journal_entries rev
                  WHERE rev.source_ref = 'REVERSAL:' || je.entry_id
              )
        """, (SOURCE_TYPE, checkin_date, checkout_date,
              f"%{normalized[:15]}%"))
        forecasts = cur.fetchall()

        reversed_count = 0
        for je in forecasts:
            original_id = je["entry_id"]
            cur.execute(f"""
                SELECT account_code, account_name, debit, credit
                FROM {schema}.general_ledger
                WHERE journal_entry_id = %s
            """, (original_id,))
            lines = cur.fetchall()
            if not lines:
                continue

            reversal_lines = [
                LedgerLine(
                    account_code=l["account_code"],
                    account_name=l["account_name"],
                    debit=Decimal(str(l["credit"])),
                    credit=Decimal(str(l["debit"])),
                    memo=f"Booking confirmed: {reservation_id}",
                ) for l in lines
            ]

            reversal = JournalEntry(
                entry_id=f"BKREV-{original_id}",
                date=je["entry_date"],
                description=f"Booking reversal: {je['description']}",
                lines=reversal_lines,
                source_type=REVERSAL_SOURCE,
                source_ref=f"REVERSAL:{original_id}",
                division=schema,
                created_by="revenue_bridge",
                memo=f"Reversed by booking {reservation_id}",
            )

            if not dry_run:
                try:
                    reversal.validate()
                    post_journal_entry(reversal, schema)
                    reversed_count += 1
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.warning(f"[BRIDGE] Reversal failed: {e}")

        result["reversed"] = reversed_count

        # 2. Post actual revenue
        amount = Decimal(str(total_revenue)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        if amount <= 0:
            conn.close()
            return result

        display = cabin_name.replace("_", " ").title()
        nights = (checkout_date - checkin_date).days

        actual_entry = JournalEntry(
            entry_id=f"BK-{reservation_id or uuid.uuid4().hex[:12]}",
            date=checkin_date,
            description=(
                f"Confirmed booking: {display}, "
                f"{nights} nights @ ${amount / max(nights, 1):,.0f}/night"
            ),
            lines=[
                LedgerLine(
                    account_code=ACTUAL_BANK_CODE,
                    account_name=ACTUAL_BANK_NAME,
                    debit=amount,
                    credit=Decimal("0.00"),
                    memo=f"reservation:{reservation_id}",
                ),
                LedgerLine(
                    account_code=ACTUAL_REV_CODE,
                    account_name=ACTUAL_REV_NAME,
                    debit=Decimal("0.00"),
                    credit=amount,
                    memo=f"reservation:{reservation_id}",
                ),
            ],
            source_type="booking_confirmed",
            source_ref=reservation_id,
            division=schema,
            created_by="revenue_bridge",
            memo=f"{display} {checkin_date} to {checkout_date}",
        )

        if not dry_run:
            try:
                actual_entry.validate()
                post_journal_entry(actual_entry, schema)
                result["actual_posted"] = True
                result["amount"] = amount
                logger.info(
                    f"[BRIDGE] Confirmed: {display} ${amount:,.2f} "
                    f"({nights} nights, reversed {reversed_count} forecasts)"
                )
            except Exception as e:
                logger.error(f"[BRIDGE] Failed to post actual revenue: {e}")
        else:
            result["actual_posted"] = True
            result["amount"] = amount

    except Exception as e:
        logger.error(f"[BRIDGE] Error in confirm_booking_revenue: {e}")
    finally:
        conn.close()

    return result


# =============================================================================
# 4. RECONCILIATION
# =============================================================================

def reconcile(schema: str = SCHEMA) -> Dict[str, Any]:
    """
    Compare revenue_ledger totals against division_b.general_ledger
    forecast entries to ensure parity.

    Returns:
        {
            "revenue_ledger_total": $X,
            "gl_forecast_total": $Y,
            "gl_reversal_total": $Z,
            "gl_net_forecast": $Y - $Z,
            "delta": $X - ($Y - $Z),
            "status": "RECONCILED" | "MISMATCH" | "NO_DATA"
        }
    """
    conn = _connect()
    try:
        cur = conn.cursor()

        # Revenue ledger: sum of adjusted_rate for future dates (latest run)
        cur.execute("""
            SELECT run_id FROM revenue_ledger
            WHERE engine_version >= '2.0.0'
            ORDER BY generated_at DESC LIMIT 1
        """)
        run_row = cur.fetchone()
        if not run_row:
            return {"status": "NO_DATA", "message": "No QuantRevenue runs found"}

        run_id = run_row["run_id"]
        cur.execute("""
            SELECT COALESCE(SUM(adjusted_rate), 0) as total
            FROM revenue_ledger
            WHERE run_id = %s AND target_date >= CURRENT_DATE
        """, (run_id,))
        rl_total = Decimal(str(cur.fetchone()["total"]))

        # General ledger: forecast accruals (debits to 1150)
        cur.execute(f"""
            SELECT COALESCE(SUM(gl.debit), 0) as total_accrued
            FROM {schema}.general_ledger gl
            JOIN {schema}.journal_entries je ON gl.journal_entry_id = je.entry_id
            WHERE je.source_type = %s
              AND gl.account_code = %s
              AND je.entry_date >= CURRENT_DATE
        """, (SOURCE_TYPE, FORECAST_AR_CODE))
        gl_accrued = Decimal(str(cur.fetchone()["total_accrued"]))

        # General ledger: reversals (credits to 1150 from reversal entries)
        cur.execute(f"""
            SELECT COALESCE(SUM(gl.credit), 0) as total_reversed
            FROM {schema}.general_ledger gl
            JOIN {schema}.journal_entries je ON gl.journal_entry_id = je.entry_id
            WHERE je.source_type = %s
              AND gl.account_code = %s
              AND je.entry_date >= CURRENT_DATE
        """, (REVERSAL_SOURCE, FORECAST_AR_CODE))
        gl_reversed = Decimal(str(cur.fetchone()["total_reversed"]))

        gl_net = gl_accrued - gl_reversed
        delta = rl_total - gl_net

        status = "RECONCILED" if abs(delta) < Decimal("1.00") else "MISMATCH"

        result = {
            "run_id": run_id,
            "revenue_ledger_total": float(rl_total),
            "gl_forecast_accrued": float(gl_accrued),
            "gl_forecast_reversed": float(gl_reversed),
            "gl_net_forecast": float(gl_net),
            "delta": float(delta),
            "status": status,
        }

        if status == "MISMATCH":
            logger.warning(
                f"[BRIDGE] RECONCILIATION MISMATCH: "
                f"revenue_ledger=${rl_total:,.2f} vs GL net=${gl_net:,.2f} "
                f"(delta=${delta:,.2f})"
            )
        else:
            logger.info(
                f"[BRIDGE] Reconciled: revenue_ledger=${rl_total:,.2f} "
                f"≈ GL net=${gl_net:,.2f} (delta=${delta:,.2f})"
            )

        return result

    except Exception as e:
        logger.error(f"[BRIDGE] Reconciliation error: {e}")
        return {"status": "ERROR", "message": str(e)}
    finally:
        conn.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Revenue Bridge — QuantRevenue → General Ledger",
    )
    parser.add_argument(
        "--run-id", type=str,
        help="QuantRevenue run_id to post accruals for",
    )
    parser.add_argument(
        "--reverse-stale", action="store_true",
        help="Reverse forecast accruals for past dates",
    )
    parser.add_argument(
        "--reconcile", action="store_true",
        help="Run reconciliation check",
    )
    parser.add_argument(
        "--schema", type=str, default=SCHEMA,
        help=f"Target division schema (default: {SCHEMA})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute but don't write to DB",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [BRIDGE] %(message)s",
    )

    if args.reconcile:
        print(f"\n{'='*60}")
        print("  REVENUE BRIDGE — Reconciliation")
        print(f"{'='*60}\n")
        result = reconcile(args.schema)
        for k, v in result.items():
            if isinstance(v, float):
                print(f"  {k:30s}  ${v:>12,.2f}")
            else:
                print(f"  {k:30s}  {v}")
        print()

    elif args.reverse_stale:
        print(f"\n{'='*60}")
        print("  REVENUE BRIDGE — Reverse Stale Accruals")
        print(f"{'='*60}\n")
        count = reverse_stale_accruals(args.schema, args.dry_run)
        print(f"  Reversed: {count} stale forecast accruals")
        if args.dry_run:
            print("  (DRY RUN — no changes written)")
        print()

    elif args.run_id:
        print(f"\n{'='*60}")
        print("  REVENUE BRIDGE — Post Forecast Accruals")
        print(f"  Run ID: {args.run_id}")
        print(f"{'='*60}\n")
        result = post_forecast_accruals(args.run_id, args.schema, args.dry_run)
        print(f"  Entries posted: {result['entries_posted']}")
        print(f"  Total accrued:  ${float(result['total_accrued']):,.2f}")
        print(f"  Stale reversed: {result['reversed']}")
        if args.dry_run:
            print("  (DRY RUN — no changes written)")
        print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
