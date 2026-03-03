import asyncio
import json
from datetime import datetime, timezone
from aiokafka import AIOKafkaProducer
import os


async def execute_live_fire():
    print("[COMMAND CENTER] Initiating Corrected Live-Fire Drill...")

    producer = AIOKafkaProducer(
        bootstrap_servers=os.getenv("REDPANDA_BROKERS", "localhost:19092")
    )
    await producer.start()

    try:
        # VECTOR ALPHA: $4,200 Guest Payment
        # Schema aligned to revenue_consumer_daemon.py execute_revenue_journal()
        revenue_payload = {
            "property_id": "235641",
            "confirmation_code": "RES-LIVE-FIRE-002",
            "total_amount": 4200.00,
            "cleaning_fee": 250.00,
            "tax_amount": 420.00,
            "source": "direct_booking",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        print("[ALPHA] Firing $4,200 Revenue Event -> trust.revenue.staged")
        await producer.send_and_wait(
            "trust.revenue.staged",
            json.dumps(revenue_payload).encode("utf-8"),
        )

        await asyncio.sleep(3)

        # VECTOR BETA: $5,200 Emergency Roof Repair Invoice
        # Schema aligned to triage_router_swarm.py consume_inbox() — single "text" field
        chaos_payload = {
            "text": (
                "From: billing@blueridgeroofing.com\n"
                "Subject: URGENT: Roof Repair Invoice - Aska Escape Lodge\n\n"
                "Taylor, attached is the invoice for the emergency tarp and "
                "patch job at Aska Escape Lodge following the storm. "
                "Total is $5,200.00. Please remit payment immediately to "
                "avoid late fees.\n\n"
                "Blue Ridge Roofing & Restoration\n"
                "Invoice #BRR-2026-0471\n"
                "Amount Due: $5,200.00"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        print("[BETA] Firing $5,200 Chaos Invoice -> enterprise.inbox.raw")
        await producer.send_and_wait(
            "enterprise.inbox.raw",
            json.dumps(chaos_payload).encode("utf-8"),
        )

        print("[COMMAND CENTER] Both payloads delivered. Observing consumer reactions...")

    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(execute_live_fire())
