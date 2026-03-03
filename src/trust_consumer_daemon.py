"""
Trust Consumer Daemon — Iron Dome Integration Layer

Listens on ``trust.accounting.staged`` (published by the Triage Router),
invokes the Trust Accounting Swarm for cognitive processing, and — if
the Fiduciary Auditor returns CLEARED — physically commits the balanced
journal entry into the CF-04 Iron Dome ledger on ``fortress_guest``.

The Iron Dome's ``trg_verify_balance`` constraint trigger fires on commit.
If debits != credits, the transaction rolls back instantly.

Usage (daemon):
    python3 src/trust_consumer_daemon.py
"""

import os
import sys
import json
import asyncio
import logging
import psycopg2
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.trust_swarm_graph import trust_swarm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("trust_consumer")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "trust_accounting_v9"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")


def execute_iron_dome_transaction(state: dict):
    """Deterministic database commit into the CF-04 Iron Dome ledger."""
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (description, reference_type, property_id, posted_by, source_system)
                    VALUES (%s, 'invoice', %s, 'trust_swarm', 'ai_triage_router')
                    RETURNING id
                    """,
                    (
                        f"{state['vendor']} - {state['description']}",
                        state["property_id"],
                    ),
                )
                journal_id = cur.fetchone()[0]

                for line in state["journal_lines"]:
                    acct_code = line["code"]
                    amt = float(line["amount"])
                    is_debit = line["type"].lower() == "debit"

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
                            acct_code,
                            amt if is_debit else 0.0,
                            amt if not is_debit else 0.0,
                        ),
                    )

                log.info(
                    "Iron Dome commit successful — Journal ID %d, %d lines.",
                    journal_id,
                    len(state["journal_lines"]),
                )
    except Exception as e:
        log.error("IRON DOME REJECTION: %s", e)
    finally:
        conn.close()


def stage_capex_for_approval(state: dict):
    """Insert a high-ticket invoice into capex_staging for owner approval."""
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO capex_staging
                        (property_id, vendor, amount, total_owner_charge,
                         description, journal_lines, compliance_status, audit_trail)
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING_CAPEX_APPROVAL', %s)
                    RETURNING id
                    """,
                    (
                        state.get("property_id", ""),
                        state.get("vendor", "UNKNOWN"),
                        state.get("amount", 0),
                        state.get("total_charged_to_owner", state.get("amount", 0)),
                        state.get("description", ""),
                        json.dumps(state.get("journal_lines", [])),
                        json.dumps(state.get("audit_trail", [])),
                    ),
                )
                staging_id = cur.fetchone()[0]
                log.info(
                    "CapEx staged for owner approval — staging_id=%d, vendor=%s, amount=$%.2f",
                    staging_id,
                    state.get("vendor"),
                    state.get("total_charged_to_owner", state.get("amount", 0)),
                )
    except Exception as e:
        log.error("Failed to stage CapEx: %s", e)
    finally:
        conn.close()


async def process_trust_payload(payload: dict):
    """Run the Trust Swarm and commit if CLEARED, stage if CapEx threshold hit."""
    vendor = payload.get("vendor", "UNKNOWN")
    log.info("Trust Swarm engaged for vendor: %s", vendor)

    initial_state = {
        "raw_text": payload.get("description", ""),
        "vendor": vendor,
        "amount": payload.get("amount", 0.0),
        "description": payload.get("description", "Routine Maintenance"),
        "property_id": "",
        "property_name": "",
        "journal_lines": [],
        "compliance_status": "",
        "audit_trail": payload.get("audit_trail", []) + ["HANDOFF: Received by Trust Swarm"],
    }

    try:
        final_state = await asyncio.to_thread(trust_swarm.invoke, initial_state)
    except Exception as e:
        log.error("Trust Swarm execution failed: %s", e)
        return

    for entry in final_state.get("audit_trail", [])[-5:]:
        log.info("   -> %s", entry)

    status = final_state.get("compliance_status", "")

    if status == "CLEARED":
        log.info("Trust Swarm AUTHORIZED. Executing Iron Dome Commit...")
        await asyncio.to_thread(execute_iron_dome_transaction, final_state)
    elif status == "PENDING_CAPEX_APPROVAL":
        log.warning(
            "CAPEX GATE: Invoice for %s staged for owner approval (amount=$%.2f).",
            final_state.get("vendor"),
            final_state.get("total_charged_to_owner", final_state.get("amount", 0)),
        )
        await asyncio.to_thread(stage_capex_for_approval, final_state)
    elif status == "CAPITAL_CALL_REQUIRED":
        log.warning(
            "ACTION REQUIRED: Capital Call for %s. Transaction NOT committed.",
            final_state.get("property_id"),
        )
    else:
        log.error("Transaction REJECTED by Swarm: %s", status)


async def consume_trust_events():
    """Long-running consumer: trust.accounting.staged -> Trust Swarm -> Iron Dome."""
    consumer = AIOKafkaConsumer(
        "trust.accounting.staged",
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        max_poll_interval_ms=600_000,
        session_timeout_ms=60_000,
    )
    await consumer.start()
    log.info("Trust Accounting Swarm online — consuming trust.accounting.staged")

    try:
        async for msg in consumer:
            await process_trust_payload(msg.value)
    except asyncio.CancelledError:
        log.info("Consumer shutdown initiated.")
    finally:
        await consumer.stop()
        log.info("Consumer stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_trust_events())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Trust Daemon.")
