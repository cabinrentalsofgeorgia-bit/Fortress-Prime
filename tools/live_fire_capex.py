"""
Live-Fire CapEx Drill — Inject an $8,500 HVAC invoice into the Triage Router.

The payload targets Riverview Lodge (owner: Thor James). It flows through:
  enterprise.inbox.raw -> Triage Router -> trust.accounting.staged
  -> Trust Consumer Daemon -> Trust Swarm (entity_resolver, ledger_coder,
     fiduciary_auditor) -> capex_staging (PENDING_CAPEX_APPROVAL)

Pre-requisites:
  - Triage Router daemon running (src/triage_router_swarm.py)
  - Trust Consumer daemon running (src/trust_consumer_daemon.py)
  - Redpanda broker available on KAFKA_BROKER_URL or localhost:19092

Usage:
    python3 tools/live_fire_capex.py
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer


async def execute_capex_drill():
    broker = os.getenv("REDPANDA_BROKERS", os.getenv("KAFKA_BROKER_URL", "localhost:19092"))
    print(f"[CAPEX DRILL] Connecting to Redpanda at {broker}...")

    producer = AIOKafkaProducer(bootstrap_servers=broker)
    await producer.start()

    try:
        payload = {
            "text": (
                "From: billing@appalachiancomfort.com\n"
                "Subject: Invoice #AC-2026-0892 — HVAC Replacement, Riverview Lodge\n\n"
                "Taylor,\n\n"
                "Please find attached the invoice for the complete HVAC system "
                "replacement at Riverview Lodge. The existing unit failed inspection "
                "and was replaced with a Carrier Infinity 24ANB1 5-ton heat pump.\n\n"
                "Property: Riverview Lodge\n"
                "Service Date: February 28, 2026\n"
                "Vendor: Appalachian Comfort HVAC Services\n"
                "Invoice #: AC-2026-0892\n"
                "Total Due: $8,500.00\n"
                "Payment Terms: Net 30\n\n"
                "Appalachian Comfort HVAC Services\n"
                "1247 Mountain Creek Rd, Blue Ridge, GA 30513\n"
                "billing@appalachiancomfort.com"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        print("[CAPEX DRILL] Injecting $8,500 HVAC invoice -> enterprise.inbox.raw")
        print(f"  Target: Riverview Lodge (Thor James)")
        print(f"  Vendor: Appalachian Comfort HVAC Services")
        print(f"  Amount: $8,500.00")
        print(f"  Expected path: Triage -> TRUST/MAINTENANCE -> Trust Swarm")
        print(f"  Expected outcome: capex_staging INSERT (amount > $500 threshold)")

        await producer.send_and_wait(
            "enterprise.inbox.raw",
            json.dumps(payload).encode("utf-8"),
        )

        print("[CAPEX DRILL] Payload delivered to enterprise.inbox.raw.")
        print("[CAPEX DRILL] Monitor daemon logs for classification and staging confirmation.")

    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(execute_capex_drill())
