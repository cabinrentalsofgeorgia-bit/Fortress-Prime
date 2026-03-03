"""
Historical Revenue Extractor — Vector 2

Reads all historical reservations (2020-present) from the local Postgres
database and publishes them as ``is_historical: true`` events to the
``trust.revenue.staged`` Redpanda topic. The Revenue Consumer Daemon
commits GAAP journal entries to the Iron Dome ledger but SKIPS Stripe
payout emission for historical records.

Data source: ``reservations`` table (already enriched by the Streamline
sync engine's Phase 6 GetReservationPrice enrichment). No Streamline API
calls required — all 2,100+ reservations with financial detail are local.

Usage:
    cd fortress-guest-platform && python3 -m tools.historical_revenue_extractor
"""

import asyncio
import json
import os
import sys
import time
from decimal import Decimal

import psycopg2
import psycopg2.extras
from aiokafka import AIOKafkaProducer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

REDPANDA_BROKER = os.getenv("REDPANDA_BROKERS", "192.168.0.100:19092")
TOPIC = "trust.revenue.staged"

DB_DSN = os.getenv(
    "ENTITY_DB_DSN",
    "dbname=fortress_guest user=fgp_app password=F0rtr3ss_Gu3st_2026! host=localhost",
)

BATCH_SIZE = 50
INTER_BATCH_DELAY = 0.5


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def extract_historical_revenue():
    print("=" * 70)
    print("  VECTOR 2: HISTORICAL REVENUE LEDGER EXTRACTION")
    print("=" * 70)

    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Count what we're about to process
    cur.execute("""
        SELECT COUNT(*) as cnt, SUM(total_amount) as gross
        FROM reservations r
        JOIN properties p ON p.id = r.property_id
        WHERE r.total_amount > 0
          AND r.status NOT IN ('cancelled', 'declined')
    """)
    stats = cur.fetchone()
    total_count = stats["cnt"]
    total_gross = float(stats["gross"] or 0)

    print(f"\n  Reservations to journal: {total_count:,}")
    print(f"  Total gross revenue:    ${total_gross:,.2f}")
    print(f"  Target topic:           {TOPIC}")
    print(f"  Redpanda broker:        {REDPANDA_BROKER}")

    # Check how many are already journaled (idempotency guard)
    cur2 = conn.cursor()
    cur2.execute("""
        SELECT COUNT(*) FROM journal_entries
        WHERE reference_type = 'reservation_revenue'
    """)
    already_journaled = cur2.fetchone()[0]
    cur2.close()
    print(f"  Already journaled:      {already_journaled}")
    print(f"  New entries expected:    ~{total_count - already_journaled}")

    # Fetch all eligible reservations
    cur.execute("""
        SELECT
            r.confirmation_code,
            p.streamline_property_id as property_id,
            r.total_amount,
            COALESCE(r.cleaning_fee, 0) as cleaning_fee,
            COALESCE(r.tax_amount, 0) as tax_amount,
            r.check_in_date,
            r.status,
            p.name as property_name
        FROM reservations r
        JOIN properties p ON p.id = r.property_id
        WHERE r.total_amount > 0
          AND r.status NOT IN ('cancelled', 'declined')
        ORDER BY r.check_in_date ASC
    """)
    rows = cur.fetchall()

    print(f"\n  Fetched {len(rows)} reservation records from local DB.")
    print(f"  Publishing to Redpanda in batches of {BATCH_SIZE}...\n")

    producer = AIOKafkaProducer(
        bootstrap_servers=REDPANDA_BROKER,
        value_serializer=lambda v: json.dumps(v, default=_decimal_default).encode("utf-8"),
    )
    await producer.start()

    published = 0
    skipped = 0
    errors = 0
    t_start = time.time()

    try:
        for i, row in enumerate(rows):
            conf_code = row["confirmation_code"]
            if not conf_code:
                skipped += 1
                continue

            payload = {
                "property_id": row["property_id"],
                "confirmation_code": str(conf_code),
                "total_amount": float(row["total_amount"]),
                "cleaning_fee": float(row["cleaning_fee"]),
                "tax_amount": float(row["tax_amount"]),
                "is_historical": True,
            }

            try:
                await producer.send_and_wait(TOPIC, payload)
                published += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] Failed to publish {conf_code}: {e}")

            if published % BATCH_SIZE == 0 and published > 0:
                elapsed = time.time() - t_start
                rate = published / elapsed if elapsed > 0 else 0
                print(
                    f"  [{published:>5}/{len(rows)}] "
                    f"Last: {conf_code} @ {row['property_name']} "
                    f"(${float(row['total_amount']):,.2f}) | "
                    f"{rate:.0f} events/sec"
                )
                await asyncio.sleep(INTER_BATCH_DELAY)

    finally:
        await producer.stop()

    elapsed = time.time() - t_start
    conn.close()

    print(f"\n{'=' * 70}")
    print(f"  VECTOR 2: EXTRACTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Published:    {published:,} events")
    print(f"  Skipped:      {skipped:,} (no confirmation code)")
    print(f"  Errors:       {errors:,}")
    print(f"  Elapsed:      {elapsed:.1f}s ({published/elapsed:.0f} events/sec)")
    print(f"  Gross total:  ${total_gross:,.2f}")
    print(f"\n  The Revenue Consumer Daemon will now process these events.")
    print(f"  Each will be committed to the Iron Dome ledger with the")
    print(f"  correct management split from management_splits.")
    print(f"  is_historical=True ensures ZERO Stripe payouts are triggered.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(extract_historical_revenue())
