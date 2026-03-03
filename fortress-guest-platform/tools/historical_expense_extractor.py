"""
Historical Expense Extractor -- Vector 3

Reads curated expense data from two sources:
  1. ``fortress_db.finance_invoices`` (AI-extracted from emails, filtered and deduped)
  2. ``fortress_guest.work_orders`` (Streamline sync, logged for audit completeness)

Normalizes vendor names, applies vendor-property mapping from
``vendor_property_map.json``, archives into ``expense_events_archive``,
and publishes ``is_historical: true`` events to the ``trust.expense.staged``
Redpanda topic for the Expense Consumer Daemon to journal.

Data quality note: finance_invoices amounts are AI-extracted from emails.
Rows are filtered to CONTRACTOR/OPERATIONAL_EXPENSE/PROFESSIONAL_SERVICE
categories and capped at <$50K per row to remove obvious inflation.
Deduplication via GROUP BY (vendor, amount, date) removes repeated extractions
of the same invoice from multiple email threads.

Usage:
    cd fortress-guest-platform && python3 -m tools.historical_expense_extractor
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from decimal import Decimal

import psycopg2
import psycopg2.extras
from aiokafka import AIOKafkaProducer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

REDPANDA_BROKER = os.getenv("REDPANDA_BROKERS", "192.168.0.100:19092")
TOPIC = "trust.expense.staged"

FGP_DSN = os.getenv(
    "FGP_DB_DSN",
    "dbname=fortress_guest user=fgp_app password=F0rtr3ss_Gu3st_2026! host=localhost",
)
FORTRESS_DSN = os.getenv(
    "FORTRESS_DB_DSN",
    "dbname=fortress_db user=fgp_app password=F0rtr3ss_Gu3st_2026! host=localhost",
)

BATCH_SIZE = 25
INTER_BATCH_DELAY = 0.3
MAX_AMOUNT = 50000


def _normalize_vendor(raw: str) -> str:
    """Strip email angle-bracket suffix and normalize to lowercase."""
    cleaned = re.sub(r'\s*<[^>]*>?\s*$', '', raw)
    cleaned = cleaned.strip().strip('"').strip("'").lower()
    return cleaned


def _make_dedup_key(vendor_norm: str, amount: float, date_str: str) -> str:
    """MD5 hash of vendor+amount+date for idempotency."""
    raw = f"{vendor_norm}|{amount:.2f}|{date_str}"
    return hashlib.md5(raw.encode()).hexdigest()


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _load_vendor_map():
    map_path = os.path.join(os.path.dirname(__file__), "vendor_property_map.json")
    with open(map_path, "r") as f:
        return json.load(f)


async def extract_historical_expenses():
    print("=" * 70)
    print("  VECTOR 3: HISTORICAL EXPENSE LEDGER EXTRACTION")
    print("=" * 70)

    vendor_config = _load_vendor_map()
    default_jtype = vendor_config.get("default_journal_type", "operating")

    # ---- Phase 1: Streamline Work Orders (audit log only) ----
    print("\n  Phase 1: Streamline Work Orders")
    print("  " + "-" * 40)

    fgp_conn = psycopg2.connect(FGP_DSN)
    fgp_cur = fgp_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    fgp_cur.execute("""
        SELECT wo.ticket_number, wo.title, wo.description, wo.cost_amount,
               wo.created_at, p.streamline_property_id as unit_id, p.name as property_name
        FROM work_orders wo
        JOIN properties p ON p.id = wo.property_id
        ORDER BY wo.created_at
    """)
    work_orders = fgp_cur.fetchall()
    print(f"  Found {len(work_orders)} Streamline work orders")
    for wo in work_orders:
        cost = wo["cost_amount"] or 0
        print(f"    {wo['ticket_number']}: {wo['property_name']} | cost=${float(cost):,.2f}")
    print("  (All have $0 cost -- logged for audit completeness, not journaled)")

    # ---- Phase 2: Curate finance_invoices ----
    print(f"\n  Phase 2: Curate finance_invoices (dedup + filter)")
    print("  " + "-" * 40)

    fort_conn = psycopg2.connect(FORTRESS_DSN)
    fort_cur = fort_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    fort_cur.execute("""
        SELECT vendor, amount, date as expense_date, category
        FROM (
            SELECT DISTINCT vendor, amount, date, category
            FROM finance_invoices
            WHERE category IN ('CONTRACTOR', 'OPERATIONAL_EXPENSE', 'PROFESSIONAL_SERVICE')
              AND amount > 0
              AND amount < %s
        ) deduped
        ORDER BY date DESC
    """, (MAX_AMOUNT,))
    expenses = fort_cur.fetchall()
    fort_conn.close()

    total_value = sum(float(r["amount"]) for r in expenses)
    print(f"  Deduplicated expenses: {len(expenses)}")
    print(f"  Total value:           ${total_value:,.2f}")
    print(f"  Date range:            {expenses[-1]['expense_date'] if expenses else 'N/A'} to {expenses[0]['expense_date'] if expenses else 'N/A'}")

    # Count already-journaled expenses
    fgp_cur2 = fgp_conn.cursor()
    fgp_cur2.execute("SELECT COUNT(*) FROM journal_entries WHERE reference_type = 'expense'")
    already_journaled = fgp_cur2.fetchone()[0]
    fgp_cur2.close()
    print(f"  Already journaled:     {already_journaled}")
    print(f"  New entries expected:   ~{len(expenses) - already_journaled}")

    # ---- Phase 3: Map vendors to properties ----
    print(f"\n  Phase 3: Vendor-Property Mapping")
    print("  " + "-" * 40)

    mappings = vendor_config.get("mappings", {})
    owner_chargeable_count = 0
    operating_count = 0
    mapped_events = []

    for row in expenses:
        vendor_raw = row["vendor"]
        vendor_norm = _normalize_vendor(vendor_raw)
        amount = float(row["amount"])
        date_str = str(row["expense_date"]) if row["expense_date"] else "unknown"
        category = row["category"]

        dedup_key = _make_dedup_key(vendor_norm, amount, date_str)

        mapping = mappings.get(vendor_norm, {})
        prop_ids = mapping.get("property_ids", [])

        if prop_ids:
            journal_type = "owner_chargeable"
            property_id = prop_ids[0]
            owner_chargeable_count += 1
        else:
            journal_type = default_jtype
            property_id = "CORPORATE"
            operating_count += 1

        mapped_events.append({
            "dedup_key": dedup_key,
            "vendor_raw": vendor_raw,
            "vendor_normalized": vendor_norm,
            "amount": amount,
            "expense_date": date_str,
            "category": category,
            "property_id": property_id,
            "journal_type": journal_type,
        })

    print(f"  Owner-chargeable (CapEx): {owner_chargeable_count}")
    print(f"  Operating (OpEx):         {operating_count}")

    # ---- Phase 4: Archive + Publish to Redpanda ----
    print(f"\n  Phase 4: Archive & Publish to Redpanda")
    print("  " + "-" * 40)
    print(f"  Target topic:  {TOPIC}")
    print(f"  Broker:        {REDPANDA_BROKER}")
    print(f"  Batch size:    {BATCH_SIZE}\n")

    fgp_cur_write = fgp_conn.cursor()
    producer = AIOKafkaProducer(
        bootstrap_servers=REDPANDA_BROKER,
        value_serializer=lambda v: json.dumps(v, default=_decimal_default).encode("utf-8"),
    )
    await producer.start()

    published = 0
    archived = 0
    skipped_archive = 0
    errors = 0
    t_start = time.time()

    try:
        for i, evt in enumerate(mapped_events):
            try:
                fgp_cur_write.execute(
                    """
                    INSERT INTO expense_events_archive
                        (dedup_key, vendor_raw, vendor_normalized, amount, expense_date,
                         category, source, property_id, journal_type, is_historical)
                    VALUES (%s, %s, %s, %s, %s, %s, 'finance_invoice', %s, %s, TRUE)
                    ON CONFLICT (dedup_key) DO NOTHING
                    """,
                    (
                        evt["dedup_key"], evt["vendor_raw"], evt["vendor_normalized"],
                        evt["amount"], evt["expense_date"] if evt["expense_date"] != "unknown" else None,
                        evt["category"], evt["property_id"], evt["journal_type"],
                    ),
                )
                if fgp_cur_write.rowcount > 0:
                    archived += 1
                else:
                    skipped_archive += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] Archive failed for {evt['dedup_key']}: {e}")
                fgp_conn.rollback()
                continue

            payload = {
                "dedup_key": evt["dedup_key"],
                "vendor_normalized": evt["vendor_normalized"],
                "amount": evt["amount"],
                "journal_type": evt["journal_type"],
                "property_id": evt["property_id"],
                "category": evt["category"],
                "is_historical": True,
            }

            try:
                await producer.send_and_wait(TOPIC, payload)
                published += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] Publish failed for {evt['dedup_key']}: {e}")

            if published > 0 and published % BATCH_SIZE == 0:
                fgp_conn.commit()
                elapsed = time.time() - t_start
                rate = published / elapsed if elapsed > 0 else 0
                print(
                    f"  [{published:>5}/{len(mapped_events)}] "
                    f"Last: {evt['vendor_normalized'][:30]} "
                    f"(${evt['amount']:,.2f} {evt['journal_type']}) | "
                    f"{rate:.0f} events/sec"
                )
                await asyncio.sleep(INTER_BATCH_DELAY)

        fgp_conn.commit()

    finally:
        await producer.stop()

    elapsed = time.time() - t_start
    fgp_cur.close()
    fgp_cur_write.close()
    fgp_conn.close()

    # ---- Phase 5: After-Action Report ----
    print(f"\n{'=' * 70}")
    print(f"  VECTOR 3: EXTRACTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Streamline Work Orders:  {len(work_orders)} (logged, $0 cost)")
    print(f"  Expenses Archived:       {archived} new + {skipped_archive} already archived")
    print(f"  Events Published:        {published}")
    print(f"  Owner-Chargeable (CapEx): {owner_chargeable_count}")
    print(f"  Corporate Operating:      {operating_count}")
    print(f"  Errors:                   {errors}")
    print(f"  Total Ledger Value:       ${total_value:,.2f}")
    print(f"  Elapsed:                  {elapsed:.1f}s ({published/max(elapsed,1):.0f} events/sec)")
    print(f"\n  The Expense Consumer Daemon will now process these events.")
    print(f"  Each will be committed to the Iron Dome ledger with the")
    print(f"  correct journal pattern (CapEx with markup / OpEx direct).")
    print(f"  is_historical=True ensures ZERO AP notifications are triggered.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(extract_historical_expenses())
