"""
Sovereign Wealth Consumer Daemon — Development Expense Persistence Layer

Listens on ``development.expenses.logged`` (published by the Triage Router
and the Wealth API), normalizes the payload, optionally invokes the Wealth
Swarm for cognitive processing, and persists the enriched record into the
``development_expenses`` table on ``fortress_guest``.

Two payload shapes arrive on this topic:
  1. From Triage Router: {receipt_text, triage_vendor, triage_amount, ...}
  2. From Wealth API:    {project_id, vendor, total_amount, tax_classification, ...}

If the payload already contains ``tax_classification`` (Wealth API path),
the graph is skipped and the record is persisted directly.

Usage (daemon):
    python3 src/wealth_consumer_daemon.py
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
log = logging.getLogger("wealth_consumer")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "wealth_expenses_v1"
TOPIC = "development.expenses.logged"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")


def persist_development_expense(record: dict):
    """Insert a processed expense record into the development_expenses table."""
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO development_expenses
                        (project_id, vendor, amount, categories, tax_class,
                         compliance_flags, property_id, source_system, audit_trail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        record.get("project_id"),
                        record.get("vendor", "UNKNOWN"),
                        record.get("amount", 0.0),
                        json.dumps(record.get("categories", [])),
                        record.get("tax_class", "Unclassified"),
                        json.dumps(record.get("compliance_flags", [])),
                        record.get("property_id"),
                        record.get("source_system", "triage_router"),
                        json.dumps(record.get("audit_trail", [])),
                    ),
                )
                row_id = cur.fetchone()[0]
                log.info(
                    "Persisted development expense #%d — vendor=%s, amount=$%.2f",
                    row_id,
                    record.get("vendor"),
                    record.get("amount", 0),
                )

                cur.execute(
                    """
                    SELECT operating_funds FROM trust_balance_cache LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    op_funds = float(row[0] or 0)
                    amt = float(record.get("amount", 0))
                    if amt > op_funds:
                        log.warning(
                            "CAPITAL ALERT: Expense $%.2f exceeds available operating funds $%.2f",
                            amt,
                            op_funds,
                        )
    except Exception as e:
        log.error("Development expense persistence failed: %s", e)
    finally:
        conn.close()


def _normalize_triage_payload(payload: dict) -> dict:
    """Normalize a Triage Router payload into the persistence shape."""
    return {
        "project_id": None,
        "vendor": payload.get("triage_vendor", payload.get("vendor", "UNKNOWN")),
        "amount": float(payload.get("triage_amount", payload.get("amount", 0))),
        "categories": [payload.get("triage_category", "general")],
        "tax_class": "Unclassified",
        "compliance_flags": [],
        "property_id": None,
        "source_system": "triage_router",
        "audit_trail": payload.get("audit_trail", []),
    }


def _normalize_wealth_api_payload(payload: dict) -> dict:
    """Normalize a Wealth API payload (already processed by Swarm) into the persistence shape."""
    return {
        "project_id": payload.get("project_id"),
        "vendor": payload.get("vendor", "UNKNOWN"),
        "amount": float(payload.get("total_amount", payload.get("amount", 0))),
        "categories": payload.get("categories", []),
        "tax_class": payload.get("tax_classification", "Unclassified"),
        "compliance_flags": payload.get("compliance_flags", []),
        "property_id": None,
        "source_system": "wealth_api",
        "audit_trail": payload.get("audit_trail", []),
    }


async def process_wealth_payload(payload: dict):
    """Normalize, optionally invoke the Swarm, then persist."""
    if payload.get("tax_classification"):
        record = _normalize_wealth_api_payload(payload)
        log.info(
            "Wealth API payload (pre-processed) — vendor=%s, $%.2f",
            record["vendor"],
            record["amount"],
        )
    else:
        record = _normalize_triage_payload(payload)
        log.info(
            "Triage payload — invoking Wealth Swarm for vendor=%s, $%.2f",
            record["vendor"],
            record["amount"],
        )
        try:
            from src.wealth_swarm_graph import wealth_swarm

            initial_state = {
                "project_id": record["project_id"] or "",
                "receipt_text": payload.get("receipt_text", payload.get("description", "")),
                "extracted_data": {},
                "tax_strategy": "",
                "compliance_flags": [],
                "ready_for_ledger": False,
                "audit_trail": record["audit_trail"]
                + ["HANDOFF: Received by Wealth Consumer Daemon"],
            }
            final_state = await asyncio.to_thread(wealth_swarm.invoke, initial_state)

            extracted = final_state.get("extracted_data", {})
            record["vendor"] = extracted.get("vendor", record["vendor"])
            record["amount"] = float(extracted.get("total", record["amount"]))
            record["categories"] = extracted.get("categories", record["categories"])
            record["tax_class"] = final_state.get("tax_strategy", "Unclassified")
            record["compliance_flags"] = final_state.get("compliance_flags", [])
            record["audit_trail"] = final_state.get("audit_trail", record["audit_trail"])

            if not final_state.get("ready_for_ledger"):
                log.warning("Wealth Swarm rejected ledger entry — persisting with flag.")
                record["compliance_flags"].append("SWARM_REJECTED_LEDGER")
        except Exception as e:
            log.error("Wealth Swarm execution failed (persisting raw): %s", e)
            record["compliance_flags"].append(f"SWARM_FAILURE: {str(e)[:200]}")

    await asyncio.to_thread(persist_development_expense, record)


async def consume_wealth_events():
    """Long-running consumer: development.expenses.logged -> Wealth Swarm -> DB."""
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
        "Sovereign Wealth Consumer online — consuming %s (group: %s)",
        TOPIC,
        CONSUMER_GROUP,
    )

    try:
        async for msg in consumer:
            try:
                await process_wealth_payload(msg.value)
            except Exception as e:
                log.error("Unhandled error processing wealth payload: %s", e)
    except asyncio.CancelledError:
        log.info("Consumer shutdown initiated.")
    finally:
        await consumer.stop()
        log.info("Consumer stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_wealth_events())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Wealth Daemon.")
