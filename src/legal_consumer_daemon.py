"""
Legal Consumer Daemon — Litigation Expense Intake Layer

Listens on ``legal.intake.staged`` (published by the Triage Router when
a payload is classified as LEGAL / LITIGATION_RECOVERY), attempts to match
the vendor against active cases in ``legal.cases``, and persists the
expense into ``legal.expense_intake`` for burn-rate tracking.

If a case match is found, a ``case_action`` is also inserted to maintain
the full litigation timeline.

Target DB: ``fortress_db`` (the ``legal.*`` schema lives here).

Usage (daemon):
    python3 src/legal_consumer_daemon.py
"""

import os
import sys
import json
import asyncio
import logging
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("legal_consumer")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "legal_intake_v1"
TOPIC = "legal.intake.staged"

LEGAL_DB_HOST = os.getenv("DB_HOST", "localhost")
LEGAL_DB_NAME = "fortress_db"
LEGAL_DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
LEGAL_DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")


def _get_legal_conn():
    return psycopg2.connect(
        host=LEGAL_DB_HOST,
        dbname=LEGAL_DB_NAME,
        user=LEGAL_DB_USER,
        password=LEGAL_DB_PASS,
    )


def _match_case(cur, vendor: str, description: str) -> dict | None:
    """Attempt to match a vendor/description against active legal cases.

    Scans case_name, case_slug, opposing_counsel, and notes for a substring
    match against the vendor name.  Returns the first match or None.
    """
    if not vendor or vendor == "UNKNOWN":
        return None

    vendor_lower = vendor.lower()
    cur.execute(
        """
        SELECT id, case_slug, case_name
        FROM legal.cases
        WHERE status = 'active'
          AND (
              LOWER(case_name) LIKE %s
              OR LOWER(case_slug) LIKE %s
              OR LOWER(COALESCE(opposing_counsel, '')) LIKE %s
              OR LOWER(COALESCE(notes, '')) LIKE %s
          )
        LIMIT 1
        """,
        (
            f"%{vendor_lower}%",
            f"%{vendor_lower}%",
            f"%{vendor_lower}%",
            f"%{vendor_lower}%",
        ),
    )
    row = cur.fetchone()
    if row:
        return {"id": row[0], "slug": row[1], "name": row[2]}
    return None


def persist_legal_intake(payload: dict):
    """Insert into legal.expense_intake and optionally legal.case_actions."""
    conn = _get_legal_conn()
    vendor = payload.get("vendor", "UNKNOWN")
    amount = float(payload.get("amount", 0))
    description = payload.get("description", "")
    rag_category = payload.get("rag_category", "")
    rag_reasoning = payload.get("rag_reasoning", "")
    audit_trail = payload.get("audit_trail", [])

    try:
        with conn:
            with conn.cursor() as cur:
                case = _match_case(cur, vendor, description)
                case_slug = case["slug"] if case else "unmatched"

                cur.execute(
                    """
                    INSERT INTO legal.expense_intake
                        (case_slug, vendor, amount, description,
                         rag_category, rag_reasoning, audit_trail, source_system)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'triage_router')
                    RETURNING id
                    """,
                    (
                        case_slug,
                        vendor,
                        amount,
                        description,
                        rag_category,
                        rag_reasoning,
                        json.dumps(audit_trail),
                    ),
                )
                intake_id = cur.fetchone()[0]

                if case:
                    cur.execute(
                        """
                        INSERT INTO legal.case_actions
                            (case_id, action_type, description, status, notes)
                        VALUES (%s, 'expense_intake', %s, 'logged', %s)
                        """,
                        (
                            case["id"],
                            f"Legal expense intake: {vendor} — ${amount:.2f}",
                            f"Auto-matched to case '{case['name']}'. "
                            f"RAG category: {rag_category}. Intake ID: {intake_id}.",
                        ),
                    )
                    log.info(
                        "Legal intake #%d MATCHED case '%s' — vendor=%s, $%.2f",
                        intake_id,
                        case["slug"],
                        vendor,
                        amount,
                    )
                else:
                    log.info(
                        "Legal intake #%d UNMATCHED — vendor=%s, $%.2f (queued for human review)",
                        intake_id,
                        vendor,
                        amount,
                    )

                cur.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) AS total_burn
                    FROM legal.expense_intake
                    WHERE case_slug != 'unmatched'
                    """
                )
                total_burn = float(cur.fetchone()[0])
                log.info("Legal burn rate (all matched cases): $%.2f", total_burn)

    except Exception as e:
        log.error("Legal intake persistence failed: %s", e)
    finally:
        conn.close()


async def process_legal_payload(payload: dict):
    """Process a single legal intake payload."""
    vendor = payload.get("vendor", "UNKNOWN")
    amount = payload.get("amount", 0)
    log.info("Legal intake received — vendor=%s, $%.2f", vendor, amount)
    await asyncio.to_thread(persist_legal_intake, payload)


async def consume_legal_events():
    """Long-running consumer: legal.intake.staged -> case matching -> DB."""
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        max_poll_interval_ms=600_000,
        session_timeout_ms=60_000,
    )
    await consumer.start()
    log.info(
        "Legal Consumer Daemon online — consuming %s (group: %s)",
        TOPIC,
        CONSUMER_GROUP,
    )

    try:
        async for msg in consumer:
            try:
                await process_legal_payload(msg.value)
            except Exception as e:
                log.error("Unhandled error processing legal payload: %s", e)
    except asyncio.CancelledError:
        log.info("Consumer shutdown initiated.")
    finally:
        await consumer.stop()
        log.info("Consumer stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_legal_events())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Legal Daemon.")
