"""
Expense Consumer Daemon -- Historical CapEx & OpEx Engine

Consumes ``trust.expense.staged`` events published by the Historical Expense
Extractor, then commits deterministic double-entry journal lines into the
Iron Dome ledger (fortress_guest database).

Two journal patterns based on ``journal_type`` in payload:

  Pattern A -- Owner-Chargeable (maintenance billed to owner with PM markup):
    DR 2000  Trust Liability - Owners   (vendor cost + markup)
    CR 2100  Accounts Payable           (vendor cost)
    CR 4100  PM Markup Revenue          (markup portion)

  Pattern B -- Operating Expense (CROG corporate cost, no owner charge):
    DR 5XXX  Expense account            (amount, category-mapped)
    CR 1000  Cash - Operating           (amount)

Markup percentage is read from ``owner_markup_rules`` per-property.
Idempotent: uses ``reference_id = dedup_key`` on journal_entries
with ``reference_type = 'expense'`` to prevent duplicate processing.

Usage (daemon):
    python3 src/expense_consumer_daemon.py
"""

import os
import sys
import json
import asyncio
import logging
from decimal import Decimal, ROUND_HALF_UP

import psycopg2
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s -- %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("expense_consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
TOPIC = "trust.expense.staged"
GROUP_ID = "fortress-expense-consumer"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")

TWO = Decimal("0.01")

CATEGORY_ACCOUNT_MAP = {
    "CONTRACTOR": "5010",
    "OPERATIONAL_EXPENSE": "5030",
    "PROFESSIONAL_SERVICE": "5080",
}
DEFAULT_EXPENSE_ACCOUNT = "5900"

DEFAULT_MARKUP = Decimal("23.00")


def _get_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def _lookup_markup(conn, property_id: str) -> Decimal:
    """Return markup percentage for a property from owner_markup_rules."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT markup_percentage FROM owner_markup_rules WHERE property_id = %s LIMIT 1",
            (property_id,),
        )
        row = cur.fetchone()
        if row:
            return Decimal(str(row[0]))
    return DEFAULT_MARKUP


def _already_journaled(conn, dedup_key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM journal_entries WHERE reference_id = %s AND reference_type = 'expense' LIMIT 1",
            (dedup_key,),
        )
        return cur.fetchone() is not None


def execute_expense_journal(payload: dict):
    """Deterministic double-entry commit for an expense event."""
    dedup_key = payload.get("dedup_key", "")
    vendor = payload.get("vendor_normalized", "UNKNOWN")
    amount = Decimal(str(payload.get("amount", 0))).quantize(TWO, ROUND_HALF_UP)
    journal_type = payload.get("journal_type", "operating")
    property_id = payload.get("property_id", "")
    category = payload.get("category", "OPERATIONAL_EXPENSE")
    is_historical = payload.get("is_historical", False)

    if amount <= 0:
        log.warning("Skipping zero-amount expense: %s", vendor)
        return None

    conn = _get_conn()
    try:
        if _already_journaled(conn, dedup_key):
            log.info("IDEMPOTENT SKIP: %s already journaled", dedup_key)
            return None

        if journal_type == "owner_chargeable":
            markup_pct = _lookup_markup(conn, property_id)
            pm_markup = (amount * markup_pct / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
            total_owner_charge = (amount + pm_markup).quantize(TWO, ROUND_HALF_UP)

            lines = [
                {"code": "2000", "type": "debit",  "amount": float(total_owner_charge)},
                {"code": "2100", "type": "credit", "amount": float(amount)},
                {"code": "4100", "type": "credit", "amount": float(pm_markup)},
            ]
            description = (
                f"CapEx: {vendor} (${float(amount):,.2f} + {float(markup_pct)}% markup "
                f"= ${float(total_owner_charge):,.2f} charged to owner)"
            )
        else:
            expense_acct = CATEGORY_ACCOUNT_MAP.get(category, DEFAULT_EXPENSE_ACCOUNT)
            lines = [
                {"code": expense_acct, "type": "debit",  "amount": float(amount)},
                {"code": "1000",       "type": "credit", "amount": float(amount)},
            ]
            description = f"OpEx: {vendor} ({category}) ${float(amount):,.2f}"

        total_debits = sum(Decimal(str(l["amount"])) for l in lines if l["type"] == "debit")
        total_credits = sum(Decimal(str(l["amount"])) for l in lines if l["type"] == "credit")

        if abs(total_debits - total_credits) > Decimal("0.02"):
            log.error(
                "BALANCE CHECK FAILED for %s: DR=%.2f CR=%.2f",
                dedup_key, total_debits, total_credits,
            )
            return None

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (description, reference_type, reference_id, property_id,
                         posted_by, source_system)
                    VALUES (%s, 'expense', %s, %s,
                            'expense_consumer', 'historical_extraction')
                    RETURNING id
                    """,
                    (
                        description,
                        dedup_key,
                        property_id if journal_type == "owner_chargeable" else None,
                    ),
                )
                journal_id = cur.fetchone()[0]

                for line in lines:
                    is_debit = line["type"] == "debit"
                    amt = float(line["amount"])
                    cur.execute(
                        """
                        INSERT INTO journal_line_items
                            (journal_entry_id, account_id, debit, credit)
                        VALUES (
                            %s,
                            (SELECT id FROM accounts WHERE code = %s),
                            %s, %s
                        )
                        """,
                        (
                            journal_id,
                            line["code"],
                            amt if is_debit else 0.0,
                            amt if not is_debit else 0.0,
                        ),
                    )

                cur.execute(
                    "UPDATE expense_events_archive SET journal_entry_id = %s WHERE dedup_key = %s",
                    (journal_id, dedup_key),
                )

                log.info(
                    "EXPENSE JOURNAL COMMITTED -- JE %d | %s | %s | $%.2f | %d lines",
                    journal_id, journal_type.upper(), vendor,
                    float(amount), len(lines),
                )

                return {
                    "journal_entry_id": journal_id,
                    "dedup_key": dedup_key,
                    "vendor": vendor,
                    "amount": float(amount),
                    "journal_type": journal_type,
                    "is_historical": is_historical,
                }

    except Exception as e:
        log.error("IRON DOME REJECTION (expense): %s -- %s", dedup_key, e)
    finally:
        conn.close()
    return None


async def consume_expense_events():
    """Main event loop: consume trust.expense.staged from Redpanda."""
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    log.info("Starting Expense Consumer Daemon on topic: %s", TOPIC)
    await consumer.start()

    try:
        async for msg in consumer:
            payload = msg.value
            dedup_key = payload.get("dedup_key", "UNKNOWN")
            is_historical = payload.get("is_historical", False)
            log.info(
                "Expense event received: %s | vendor=%s | $%s | type=%s | historical=%s",
                dedup_key,
                payload.get("vendor_normalized"),
                payload.get("amount"),
                payload.get("journal_type"),
                is_historical,
            )
            try:
                result = await asyncio.to_thread(execute_expense_journal, payload)
                if result:
                    if is_historical:
                        log.info(
                            "HISTORICAL BYPASS: JE %d committed for %s ($%.2f). AP notification skipped.",
                            result["journal_entry_id"],
                            result["vendor"],
                            result["amount"],
                        )
                    else:
                        log.info(
                            "LIVE EXPENSE: JE %d committed for %s ($%.2f).",
                            result["journal_entry_id"],
                            result["vendor"],
                            result["amount"],
                        )
            except Exception as e:
                log.error("Expense processing failed for %s: %s", dedup_key, e)
    finally:
        await consumer.stop()
        log.info("Expense Consumer Daemon stopped.")


if __name__ == "__main__":
    asyncio.run(consume_expense_events())
