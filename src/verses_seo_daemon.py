"""
Verses in Bloom — SEO Copywriter Daemon

Consumes ``ecommerce.seo.generation_requested`` events from Redpanda and
generates brand-aligned marketing copy on the DGX cluster (SWARM mode),
then writes the result back to ``verses_schema.products.seo_description``.

Usage:
    python -m src.verses_seo_daemon
    FGP_DB_USER=fgp_app FGP_DB_PASS=<pw> python -m src.verses_seo_daemon
"""

import asyncio
import json
import logging
import os
import signal

import psycopg2
from aiokafka import AIOKafkaConsumer

from config import get_inference_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("verses_copywriter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "verses_seo_v1"

FGP_DB_HOST = os.getenv("FGP_DB_HOST", os.getenv("DB_HOST", "192.168.0.100"))
FGP_DB_PORT = int(os.getenv("FGP_DB_PORT", os.getenv("DB_PORT", "5432")))
FGP_DB_NAME = os.getenv("FGP_DB_NAME", "fortress_guest")
FGP_DB_USER = os.getenv("FGP_DB_USER", os.getenv("DB_USER", ""))
FGP_DB_PASS = os.getenv("FGP_DB_PASS", os.getenv("DB_PASS", ""))


def _get_conn():
    return psycopg2.connect(
        host=FGP_DB_HOST,
        port=FGP_DB_PORT,
        dbname=FGP_DB_NAME,
        user=FGP_DB_USER,
        password=FGP_DB_PASS,
    )


# ---------------------------------------------------------------------------
# LLM copywriting
# ---------------------------------------------------------------------------

COPYWRITER_PROMPT = """\
You are the lead copywriter for "Verses in Bloom", a boutique e-commerce brand \
selling premium watercolor greeting cards.

Write an elegant, SEO-optimized product description for the following card.

Product Title: {title}
Typography & Font Guidelines: {typography}
Watercolor Visual Aesthetics: {visuals}

Requirements:
1. Three paragraphs maximum.
2. Match the tone to the typography and visual aesthetics provided.
3. Include SEO keywords naturally (watercolor, premium card, boutique, handcrafted).
4. Output ONLY the marketing copy. No conversational filler or labels."""


async def generate_seo_copy(payload: dict) -> str:
    """Draft brand-aligned marketing copy via the DGX SWARM cluster."""
    client, model = get_inference_client("SWARM")

    title = payload.get("title", "Untitled Card")
    typography = json.dumps(payload.get("typography", {}))
    visuals = json.dumps(payload.get("visuals", {}))

    prompt = COPYWRITER_PROMPT.format(
        title=title, typography=typography, visuals=visuals,
    )

    def _call_llm():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return resp.choices[0].message.content.strip()

    return await asyncio.to_thread(_call_llm)


# ---------------------------------------------------------------------------
# Database update
# ---------------------------------------------------------------------------

def _update_seo_description(product_id: str, seo_copy: str):
    """Write the generated copy back to the Verses product row."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE verses_schema.products
                SET seo_description = %s,
                    status          = 'enriched',
                    updated_at      = CURRENT_TIMESTAMP
                WHERE id = %s::uuid
                """,
                (seo_copy, product_id),
            )
            conn.commit()
    except Exception as exc:
        log.error("DB update failed for product %s: %s", product_id, exc)
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

async def process_seo_request(payload: dict):
    product_id = payload.get("product_id")
    sku = payload.get("sku")

    if not product_id or not sku:
        log.warning("Malformed SEO event, skipping: %s", payload)
        return

    log.info("[VERSES] Drafting SEO copy for SKU %s ...", sku)
    try:
        seo_copy = await generate_seo_copy(payload)
        await asyncio.to_thread(_update_seo_description, product_id, seo_copy)
        log.info("[VERSES] SKU %s enriched — %d chars of copy generated", sku, len(seo_copy))
    except Exception as exc:
        log.error("[VERSES] SEO generation failed for SKU %s: %s", sku, exc)


# ---------------------------------------------------------------------------
# Consumer loop
# ---------------------------------------------------------------------------

async def consume_ecommerce_events():
    consumer = AIOKafkaConsumer(
        "ecommerce.seo.generation_requested",
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    await consumer.start()
    log.info("Verses in Bloom Copywriter online — consuming from Redpanda")

    try:
        async for msg in consumer:
            try:
                await process_seo_request(msg.value)
            except Exception as exc:
                log.error("Handler error: %s", exc)
    finally:
        await consumer.stop()
        log.info("Redpanda consumer stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown()))
    await consume_ecommerce_events()


async def _shutdown():
    log.info("Graceful shutdown requested.")
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("FORTRESS PROTOCOL: Manual shutdown of Verses Copywriter.")
