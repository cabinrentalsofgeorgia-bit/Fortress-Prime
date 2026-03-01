#!/usr/bin/env python3
"""
Fortress Event Bus Initializer — Enterprise Topic Registry

Creates the foundational Redpanda topics for all four corporate divisions.
Idempotent: skips topics that already exist.

Usage:
    python tools/init_event_bus.py
"""

import os
import logging
from kafka.admin import KafkaAdminClient, NewTopic

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("event_bus_init")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")


def initialize_enterprise_topics():
    """Create Fortune 500 event streams across all four divisions."""
    admin_client = KafkaAdminClient(
        bootstrap_servers=REDPANDA_BROKER,
        client_id="fortress_initializer",
    )

    topics = [
        # Division 1: Physical Security (Digital Twins)
        NewTopic(name="iot.locks.state_changed", num_partitions=3, replication_factor=1),
        NewTopic(name="iot.thermostat.state_changed", num_partitions=3, replication_factor=1),
        NewTopic(name="iot.cameras.motion_detected", num_partitions=3, replication_factor=1),
        # Division 2: Macro Quant Desk
        NewTopic(name="market.crypto.ticks", num_partitions=3, replication_factor=1),
        NewTopic(name="market.macro.news", num_partitions=3, replication_factor=1),
        # Division 3: Verses in Bloom (E-Commerce)
        NewTopic(name="ecommerce.orders.created", num_partitions=3, replication_factor=1),
        NewTopic(name="ecommerce.seo.generation_requested", num_partitions=3, replication_factor=1),
        # Division 4: Wealth & Property Development
        NewTopic(name="development.expenses.logged", num_partitions=3, replication_factor=1),
        # Core Platform
        NewTopic(name="system.health.alerts", num_partitions=3, replication_factor=1),
        # Swarm Output
        NewTopic(name="market.thesis.approved", num_partitions=3, replication_factor=1),
        # Pricing Executor Output (staged for human approval per Rule 012)
        NewTopic(name="pricing.adjustment.staged", num_partitions=3, replication_factor=1),
        # Universal Financial Document Triage (Iron Dome Protocol)
        NewTopic(name="enterprise.inbox.raw", num_partitions=3, replication_factor=1),
        # Trust Accounting Swarm intake (routed by Triage Router)
        NewTopic(name="trust.accounting.staged", num_partitions=3, replication_factor=1),
        # Legal Command Center intake (routed by Triage Router)
        NewTopic(name="legal.intake.staged", num_partitions=3, replication_factor=1),
        # Revenue Swarm intake (paid reservations from Streamline sync)
        NewTopic(name="trust.revenue.staged", num_partitions=3, replication_factor=1),
        # Continuous Liquidity — payout staging (fired after revenue journaling)
        NewTopic(name="trust.payout.staged", num_partitions=3, replication_factor=1),
        # Expense Consumer intake (staged for PM markup + 3-way split)
        NewTopic(name="trust.expense.staged", num_partitions=3, replication_factor=1),
        # Dead-letter queue for payout events that failed processing
        NewTopic(name="trust.payout.dlq", num_partitions=1, replication_factor=1),
    ]

    try:
        existing_topics = admin_client.list_topics()
        new_topics = [t for t in topics if t.name not in existing_topics]

        if new_topics:
            admin_client.create_topics(new_topics=new_topics, validate_only=False)
            for t in new_topics:
                log.info("[SECURE ENCLAVE] Created event stream: %s", t.name)
        else:
            log.info("All enterprise event streams are already active.")
    except Exception as e:
        log.error("Failed to initialize topics: %s", e)
    finally:
        admin_client.close()


if __name__ == "__main__":
    initialize_enterprise_topics()
