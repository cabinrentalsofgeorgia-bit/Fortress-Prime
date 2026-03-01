#!/usr/bin/env python3
"""
Payout DLQ Replay Tool — Operator utility for inspecting and replaying
dead-lettered payout events from trust.payout.dlq.

Usage:
    # Inspect (read-only): show all DLQ events without replaying
    python tools/replay_payout_dlq.py --inspect

    # Replay all DLQ events back to trust.payout.staged
    python tools/replay_payout_dlq.py --replay

    # Replay a single event by confirmation code
    python tools/replay_payout_dlq.py --replay --code CROG-12345
"""

import os
import sys
import json
import argparse
import asyncio
import logging
from datetime import datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("payout_dlq_replay")

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
DLQ_TOPIC = "trust.payout.dlq"
REPLAY_TOPIC = "trust.payout.staged"
INSPECT_GROUP = "fortress-payout-dlq-inspect"


async def inspect_dlq():
    """Read all DLQ events and display them without replaying."""
    consumer = AIOKafkaConsumer(
        DLQ_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=f"{INSPECT_GROUP}-{int(datetime.now().timestamp())}",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=5000,
    )

    await consumer.start()
    events = []
    try:
        async for msg in consumer:
            events.append(msg.value)
    except asyncio.TimeoutError:
        pass
    finally:
        await consumer.stop()

    if not events:
        log.info("DLQ is empty — no dead-lettered payout events found.")
        return

    log.info("Found %d dead-lettered payout events:", len(events))
    print("\n" + "=" * 80)
    for i, evt in enumerate(events, 1):
        original = evt.get("original_payload", {})
        print(f"\n[{i}] confirmation_code: {original.get('confirmation_code', 'N/A')}")
        print(f"    property_id:       {original.get('property_id', 'N/A')}")
        print(f"    owner_amount:      ${original.get('owner_amount', 0):.2f}")
        print(f"    gross_amount:      ${original.get('gross_amount', 0):.2f}")
        print(f"    error:             {evt.get('error', 'N/A')[:120]}")
        ts = evt.get("timestamp")
        if ts:
            print(f"    dlq_time:          {datetime.fromtimestamp(ts).isoformat()}")
    print("\n" + "=" * 80)
    print(f"\nTotal: {len(events)} events. Use --replay to re-publish to {REPLAY_TOPIC}.")


async def replay_dlq(filter_code: str | None = None):
    """Read DLQ events and re-publish their original payloads to the staging topic."""
    consumer = AIOKafkaConsumer(
        DLQ_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=f"fortress-payout-dlq-replay-{int(datetime.now().timestamp())}",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=5000,
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    await consumer.start()
    await producer.start()

    replayed = 0
    skipped = 0

    try:
        async for msg in consumer:
            evt = msg.value
            original = evt.get("original_payload", {})
            code = original.get("confirmation_code", "")

            if filter_code and code != filter_code:
                skipped += 1
                continue

            await producer.send_and_wait(REPLAY_TOPIC, original)
            replayed += 1
            log.info(
                "REPLAYED: %s | $%.2f → %s",
                code,
                original.get("owner_amount", 0),
                REPLAY_TOPIC,
            )
    except asyncio.TimeoutError:
        pass
    finally:
        await consumer.stop()
        await producer.stop()

    log.info(
        "Replay complete: %d replayed, %d skipped%s",
        replayed, skipped,
        f" (filter: {filter_code})" if filter_code else "",
    )


def main():
    parser = argparse.ArgumentParser(description="Payout DLQ Replay Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true", help="Inspect DLQ events (read-only)")
    group.add_argument("--replay", action="store_true", help="Replay DLQ events to staging topic")
    parser.add_argument("--code", type=str, default=None, help="Filter replay by confirmation code")
    args = parser.parse_args()

    if args.inspect:
        asyncio.run(inspect_dlq())
    elif args.replay:
        asyncio.run(replay_dlq(filter_code=args.code))


if __name__ == "__main__":
    main()
