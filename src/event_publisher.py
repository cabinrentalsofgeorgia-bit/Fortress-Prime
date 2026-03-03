"""
Fortress Event Publisher — Enterprise Event Streaming Client

Canonical async publisher for the Redpanda event bus. Used by all src/ scripts
(Market Sentinel, Quant Consumer, Command Center) to publish events across
the four corporate divisions.

The FGP backend maintains its own producer instance at
backend/core/event_publisher.py for FastAPI lifespan management.
"""

import os
import json
import logging
from aiokafka import AIOKafkaProducer

log = logging.getLogger("fortress_event_publisher")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")


class EventPublisher:
    _producer: AIOKafkaProducer | None = None

    @classmethod
    async def get_producer(cls) -> AIOKafkaProducer:
        if cls._producer is None:
            cls._producer = AIOKafkaProducer(
                bootstrap_servers=REDPANDA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await cls._producer.start()
            log.info("AIOKafkaProducer connected to %s", REDPANDA_BROKER)
        return cls._producer

    @classmethod
    async def publish(cls, topic: str, payload: dict, key: str | None = None):
        """Fire-and-forget async event publishing with graceful degradation."""
        try:
            producer = await cls.get_producer()
            b_key = key.encode("utf-8") if key else None
            await producer.send_and_wait(topic, value=payload, key=b_key)
        except Exception as e:
            log.error("Failed to publish to %s: %s", topic, e)


async def close_event_publisher():
    """Gracefully stop the producer. Call at process exit."""
    if EventPublisher._producer:
        await EventPublisher._producer.stop()
        EventPublisher._producer = None
        log.info("Event publisher stopped.")
