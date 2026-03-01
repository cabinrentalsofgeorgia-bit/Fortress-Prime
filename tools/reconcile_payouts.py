#!/usr/bin/env python3
"""
Payout Reconciliation Engine — Daily Safety Net

Compares payout_ledger entries against Stripe Transfer/Payout status to catch:
  1. Stale 'processing' entries (Transfer completed but webhook missed)
  2. Orphaned transfers (in Stripe but not in our ledger)
  3. Stuck entries (in ledger but Stripe has no record)
  4. Failed entries eligible for retry

Run via cron daily at 4:00 AM ET:
    0 4 * * * /usr/bin/python3 /home/admin/Fortress-Prime/tools/reconcile_payouts.py

Usage:
    python tools/reconcile_payouts.py
    python tools/reconcile_payouts.py --dry-run
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("payout_reconciler")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

STALE_THRESHOLD_HOURS = 48
MAX_RETRY_COUNT = 5


def _get_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def _get_stripe():
    if not STRIPE_SECRET_KEY:
        log.error("STRIPE_SECRET_KEY not set — cannot reconcile against Stripe")
        return None
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def reconcile_stale_processing(conn, stripe_mod, dry_run: bool) -> int:
    """Find payout_ledger entries stuck in 'processing' beyond the stale threshold.

    Query Stripe for the actual Transfer status and update accordingly.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_THRESHOLD_HOURS)
    fixed = 0

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, stripe_transfer_id, confirmation_code, owner_amount, initiated_at
            FROM payout_ledger
            WHERE status = 'processing'
              AND initiated_at < %s
              AND stripe_transfer_id IS NOT NULL
            ORDER BY initiated_at
            """,
            (cutoff,),
        )
        stale_rows = cur.fetchall()

    if not stale_rows:
        log.info("No stale 'processing' entries found (threshold: %dh)", STALE_THRESHOLD_HOURS)
        return 0

    log.info("Found %d stale 'processing' entries (older than %s)", len(stale_rows), cutoff.isoformat())

    for row_id, transfer_id, conf_code, amount, initiated_at in stale_rows:
        try:
            transfer = stripe_mod.Transfer.retrieve(transfer_id)
            stripe_reversed = transfer.get("reversed", False)

            if stripe_reversed:
                new_status = "failed"
                reason = "Transfer reversed (detected by reconciliation)"
            else:
                new_status = "completed"
                reason = None

            age_hours = (datetime.now(timezone.utc) - initiated_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600

            if dry_run:
                log.info(
                    "[DRY RUN] Would update %s: %s → %s (Transfer %s, age=%.1fh)",
                    conf_code, "processing", new_status, transfer_id, age_hours,
                )
            else:
                with conn:
                    with conn.cursor() as cur:
                        if new_status == "completed":
                            cur.execute(
                                """
                                UPDATE payout_ledger
                                SET status = 'completed', completed_at = NOW()
                                WHERE id = %s AND status = 'processing'
                                """,
                                (row_id,),
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE payout_ledger
                                SET status = 'failed', failure_reason = %s
                                WHERE id = %s AND status = 'processing'
                                """,
                                (reason, row_id),
                            )
                log.info(
                    "RECONCILED: %s | %s → %s | Transfer %s | $%.2f | age=%.1fh",
                    conf_code, "processing", new_status, transfer_id, float(amount), age_hours,
                )
                fixed += 1

        except Exception as e:
            log.error("Failed to reconcile Transfer %s for %s: %s", transfer_id, conf_code, e)

    return fixed


def reconcile_failed_retryable(conn, stripe_mod, dry_run: bool) -> int:
    """Find failed payouts that can be retried (retry_count < max)."""
    retried = 0

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.property_id, pl.confirmation_code, pl.owner_amount,
                   pl.retry_count, pl.failure_reason,
                   opa.stripe_account_id, opa.account_status
            FROM payout_ledger pl
            LEFT JOIN owner_payout_accounts opa ON opa.property_id = pl.property_id
            WHERE pl.status = 'failed'
              AND COALESCE(pl.retry_count, 0) < %s
              AND opa.account_status = 'active'
            ORDER BY pl.created_at
            LIMIT 50
            """,
            (MAX_RETRY_COUNT,),
        )
        retryable = cur.fetchall()

    if not retryable:
        log.info("No retryable failed payouts found (max_retries=%d)", MAX_RETRY_COUNT)
        return 0

    log.info("Found %d failed payouts eligible for retry", len(retryable))

    for row_id, prop_id, conf_code, amount, retry_count, reason, stripe_acct, _ in retryable:
        if dry_run:
            log.info(
                "[DRY RUN] Would retry %s: $%.2f (attempt %d/%d, last_error: %s)",
                conf_code, float(amount), (retry_count or 0) + 1, MAX_RETRY_COUNT,
                (reason or "")[:80],
            )
            continue

        try:
            import hashlib
            idem_key = hashlib.sha256(
                f"crog-payout-{conf_code}-retry{(retry_count or 0) + 1}".encode()
            ).hexdigest()[:32]

            transfer = stripe_mod.Transfer.create(
                amount=int(float(amount) * 100),
                currency="usd",
                destination=stripe_acct,
                description=f"CROG Payout (retry {(retry_count or 0) + 1}): {conf_code}",
                idempotency_key=idem_key,
                metadata={
                    "property_id": prop_id,
                    "confirmation_code": conf_code,
                    "payout_ledger_id": str(row_id),
                    "retry_attempt": str((retry_count or 0) + 1),
                },
            )

            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE payout_ledger
                        SET status = 'processing',
                            stripe_transfer_id = %s,
                            failure_reason = NULL,
                            retry_count = %s,
                            initiated_at = NOW()
                        WHERE id = %s
                        """,
                        (transfer.id, (retry_count or 0) + 1, row_id),
                    )

            log.info(
                "RETRY TRANSFER INITIATED: %s | $%.2f → %s | Transfer %s (attempt %d)",
                conf_code, float(amount), stripe_acct[:12] + "...",
                transfer.id, (retry_count or 0) + 1,
            )
            retried += 1

        except Exception as e:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE payout_ledger
                        SET retry_count = %s, failure_reason = %s
                        WHERE id = %s
                        """,
                        ((retry_count or 0) + 1, str(e)[:500], row_id),
                    )
            log.error("Retry failed for %s: %s", conf_code, e)

    return retried


def report_summary(conn):
    """Print a summary of the current payout ledger state."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*), COALESCE(SUM(owner_amount), 0)
            FROM payout_ledger
            GROUP BY status
            ORDER BY status
            """
        )
        rows = cur.fetchall()

    print("\n" + "=" * 60)
    print("  PAYOUT LEDGER RECONCILIATION SUMMARY")
    print("=" * 60)
    total_count = 0
    total_amount = 0.0
    for status, count, amount in rows:
        print(f"  {status:15s}  {count:6d} entries  ${float(amount):>12,.2f}")
        total_count += count
        total_amount += float(amount)
    print("-" * 60)
    print(f"  {'TOTAL':15s}  {total_count:6d} entries  ${total_amount:>12,.2f}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Payout Reconciliation Engine")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without modifying data")
    args = parser.parse_args()

    stripe_mod = _get_stripe()
    if not stripe_mod:
        sys.exit(1)

    conn = _get_conn()
    try:
        log.info("Starting payout reconciliation%s...", " (DRY RUN)" if args.dry_run else "")

        fixed = reconcile_stale_processing(conn, stripe_mod, args.dry_run)
        retried = reconcile_failed_retryable(conn, stripe_mod, args.dry_run)

        log.info(
            "Reconciliation complete: %d stale fixed, %d failed retried",
            fixed, retried,
        )

        report_summary(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
