"""
Revenue Consumer Daemon — CROG Alpha Commission Standard

Consumes ``trust.revenue.staged`` events and commits deterministic
double-entry journal lines into the Iron Dome ledger using the CROG
Alpha Commission Standard:

    Commission Base = base_price + additional_party_fee (from JSONB)
    Owner Share     = commission_base * owner_pct (e.g. 65%)
    CROG Revenue    = total_amount - tax - owner_share (35% commission
                      + 100% cleaning, damage waiver, processing, pet fees)

    DR 1010  Cash - Trust             (total amount received)
    CR 2000  Trust Liability - Owners (owner share of commission base)
    CR 4100  PM Revenue               (commission + all pass-throughs)
    CR 2200  Sales Tax Payable        (tax amount, when > 0)

Idempotent: uses ``reference_id = confirmation_code`` on journal_entries
to prevent duplicate processing.

Usage (daemon):
    python3 src/revenue_consumer_daemon.py
"""

import os
import sys
import json
import asyncio
import logging
from decimal import Decimal, ROUND_HALF_UP

import psycopg2
import psycopg2.extras
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.event_publisher import EventPublisher, close_event_publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("revenue_consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
TOPIC = "trust.revenue.staged"
GROUP_ID = "fortress-revenue-consumer"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")

TWO = Decimal("0.01")


def _get_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def _lookup_split(conn, property_id: str) -> tuple[Decimal, Decimal]:
    """Return (owner_pct, pm_pct) for a property. Defaults to 65/35."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT owner_pct, pm_pct FROM management_splits WHERE property_id = %s",
            (property_id,),
        )
        row = cur.fetchone()
        if row:
            return Decimal(str(row[0])), Decimal(str(row[1]))
    return Decimal("65.00"), Decimal("35.00")


def _lookup_marketing_pct(conn, property_id: str) -> Decimal:
    """Return the owner's marketing allocation % (0-25). 0 = not enrolled."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT marketing_pct FROM owner_marketing_preferences "
            "WHERE property_id = %s AND enabled = TRUE",
            (property_id,),
        )
        row = cur.fetchone()
        if row:
            return Decimal(str(row[0]))
    return Decimal("0")


def _already_journaled(conn, confirmation_code: str) -> bool:
    """Check if this confirmation code has already been committed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM journal_entries WHERE reference_id = %s AND reference_type = 'reservation_revenue' LIMIT 1",
            (confirmation_code,),
        )
        return cur.fetchone() is not None


def _lookup_commission_base(conn, confirmation_code: str, property_id: str) -> tuple[Decimal, Decimal] | None:
    """Extract the CROG Alpha commission base from streamline_financial_detail.

    Returns (base_price, additional_party_fee) or None if JSONB unavailable.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                (r.streamline_financial_detail->>'price')::numeric as base_price,
                r.streamline_financial_detail->'required_fees' as req_fees,
                jsonb_typeof(r.streamline_financial_detail->'required_fees') as fees_type
            FROM reservations r
            JOIN properties p ON p.id = r.property_id
            WHERE r.confirmation_code = %s
              AND p.streamline_property_id = %s
              AND r.streamline_financial_detail IS NOT NULL
              AND (r.streamline_financial_detail->>'price') IS NOT NULL
        """, (confirmation_code, property_id))
        row = cur.fetchone()

    if not row or row["base_price"] is None:
        return None

    base_price = Decimal(str(row["base_price"])).quantize(TWO, ROUND_HALF_UP)
    additional_party = Decimal("0")

    fees_data = row["req_fees"]
    if fees_data is not None:
        if row["fees_type"] == "object":
            fees_data = [fees_data]
        elif row["fees_type"] != "array":
            fees_data = []

        if isinstance(fees_data, str):
            fees_data = json.loads(fees_data)

        for fee in fees_data:
            name = (fee.get("name") or "").lower()
            if "additional party" in name:
                additional_party += Decimal(str(fee.get("value", 0)))

    additional_party = additional_party.quantize(TWO, ROUND_HALF_UP)
    return base_price, additional_party


def execute_revenue_journal(payload: dict):
    """CROG Alpha: deterministic double-entry commit for reservation income.

    Commission base = base_price + additional_party_fee (from JSONB).
    Owner share = commission_base * owner_pct.
    CROG revenue = total_amount - tax - owner_share (captures all pass-throughs).
    """
    property_id = payload.get("property_id", "")
    confirmation_code = payload.get("confirmation_code", "")
    total_amount = Decimal(str(payload.get("total_amount", 0))).quantize(TWO, ROUND_HALF_UP)
    tax_amount = Decimal(str(payload.get("tax_amount", 0))).quantize(TWO, ROUND_HALF_UP)

    if total_amount <= 0:
        log.warning("Skipping zero-amount reservation %s", confirmation_code)
        return

    conn = _get_conn()
    try:
        if _already_journaled(conn, confirmation_code):
            log.info("IDEMPOTENT SKIP: %s already journaled", confirmation_code)
            return

        owner_pct, pm_pct = _lookup_split(conn, property_id)

        commission_detail = _lookup_commission_base(conn, confirmation_code, property_id)

        if commission_detail:
            base_price, additional_party = commission_detail
            commission_base = (base_price + additional_party).quantize(TWO, ROUND_HALF_UP)
            owner_share = (commission_base * owner_pct / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
            crog_revenue = (total_amount - tax_amount - owner_share).quantize(TWO, ROUND_HALF_UP)
            formula = "ALPHA"
        else:
            log.warning(
                "JSONB unavailable for %s — falling back to legacy formula",
                confirmation_code,
            )
            net_revenue = (total_amount - tax_amount).quantize(TWO, ROUND_HALF_UP)
            if net_revenue <= 0:
                net_revenue = total_amount
                tax_amount = Decimal("0")
            owner_share = (net_revenue * owner_pct / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
            crog_revenue = (net_revenue - owner_share).quantize(TWO, ROUND_HALF_UP)
            commission_base = net_revenue
            formula = "LEGACY"

        if crog_revenue < 0:
            log.error(
                "NEGATIVE CROG REVENUE for %s: total=$%.2f tax=$%.2f owner=$%.2f crog=$%.2f",
                confirmation_code, total_amount, tax_amount, owner_share, crog_revenue,
            )
            return

        marketing_pct = _lookup_marketing_pct(conn, property_id)
        marketing_escrow = Decimal("0")
        if marketing_pct > 0:
            marketing_escrow = (owner_share * marketing_pct / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
        payout_share = (owner_share - marketing_escrow).quantize(TWO, ROUND_HALF_UP)

        lines = [
            {"code": "1010", "debit": float(total_amount), "credit": 0.0},
            {"code": "2000", "debit": 0.0, "credit": float(payout_share)},
            {"code": "4100", "debit": 0.0, "credit": float(crog_revenue)},
        ]
        if marketing_escrow > 0:
            lines.append({"code": "2400", "debit": 0.0, "credit": float(marketing_escrow)})
        if tax_amount > 0:
            lines.append({"code": "2200", "debit": 0.0, "credit": float(tax_amount)})

        total_debits = sum(Decimal(str(l["debit"])) for l in lines)
        total_credits = sum(Decimal(str(l["credit"])) for l in lines)

        if abs(total_debits - total_credits) > Decimal("0.02"):
            log.error(
                "BALANCE CHECK FAILED for %s: DR=%.2f CR=%.2f (formula=%s)",
                confirmation_code, total_debits, total_credits, formula,
            )
            return

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (description, reference_type, reference_id, property_id,
                         posted_by, source_system)
                    VALUES (%s, 'reservation_revenue', %s, %s,
                            'revenue_consumer', 'crog_alpha')
                    RETURNING id
                    """,
                    (
                        f"Revenue [{formula}]: {confirmation_code} "
                        f"(${float(total_amount):,.2f} | base=${float(commission_base):,.2f} "
                        f"| owner {float(owner_pct)}%=${float(owner_share):,.2f} "
                        f"| CROG=${float(crog_revenue):,.2f})",
                        confirmation_code,
                        property_id,
                    ),
                )
                journal_id = cur.fetchone()[0]

                for line in lines:
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
                        (journal_id, line["code"], line["debit"], line["credit"]),
                    )

                log.info(
                    "REVENUE JOURNAL [%s] — JE %d | %s | $%.2f "
                    "(base=$%.2f | owner=$%.2f | payout=$%.2f | mktg=$%.2f "
                    "| CROG=$%.2f | tax=$%.2f) | %d lines",
                    formula,
                    journal_id,
                    confirmation_code,
                    float(total_amount),
                    float(commission_base),
                    float(owner_share),
                    float(payout_share),
                    float(marketing_escrow),
                    float(crog_revenue),
                    float(tax_amount),
                    len(lines),
                )

                return {
                    "property_id": property_id,
                    "confirmation_code": confirmation_code,
                    "journal_entry_id": journal_id,
                    "gross_amount": float(total_amount),
                    "owner_amount": float(payout_share),
                }
    except Exception as e:
        log.error("IRON DOME REJECTION (revenue): %s — %s", confirmation_code, e)
    finally:
        conn.close()
    return None


async def consume_revenue_events():
    """Main event loop: consume trust.revenue.staged from Redpanda."""
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    log.info("Starting Revenue Consumer Daemon on topic: %s", TOPIC)
    await consumer.start()

    try:
        async for msg in consumer:
            payload = msg.value
            conf_code = payload.get("confirmation_code", "UNKNOWN")
            is_historical = payload.get("is_historical", False)
            log.info(
                "Revenue event received: %s | property=%s | amount=$%s | historical=%s",
                conf_code,
                payload.get("property_id"),
                payload.get("total_amount"),
                is_historical,
            )
            try:
                payout_data = await asyncio.to_thread(execute_revenue_journal, payload)
                if payout_data:
                    if is_historical:
                        log.info(
                            "HISTORICAL BYPASS: JE %d committed for %s ($%.2f). Payout skipped.",
                            payout_data["journal_entry_id"],
                            payout_data["confirmation_code"],
                            payout_data["gross_amount"],
                        )
                    else:
                        await EventPublisher.publish("trust.payout.staged", payout_data)
                        log.info(
                            "PAYOUT EVENT STAGED: %s | owner=$%.2f",
                            payout_data["confirmation_code"],
                            payout_data["owner_amount"],
                        )
            except Exception as e:
                log.error("Revenue processing failed for %s: %s", conf_code, e)
    finally:
        await close_event_publisher()
        await consumer.stop()
        log.info("Revenue Consumer Daemon stopped.")


if __name__ == "__main__":
    asyncio.run(consume_revenue_events())
