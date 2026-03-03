#!/usr/bin/env python3
"""
Division 2: Quant Swarm Consumer Daemon

Long-lived async worker that subscribes to market.crypto.ticks and
market.macro.news Redpanda streams. Implements a 30-second tick debounce
to batch sentinel bursts, then triggers the Multi-Agent Quant Swarm
(LangGraph) on the DGX cluster.

Architecture:
    Redpanda tick -> 30s debounce accumulator -> Qdrant RAG retrieval
    -> LangGraph Swarm (Data Scientist -> Macro Strategist <-> Risk Manager)
    -> Publish approved thesis to market.thesis.approved

Usage:
    python -m src.quant_consumer_daemon

Deployment:
    nohup python -m src.quant_consumer_daemon >> /tmp/quant_swarm.log 2>&1 &
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from aiokafka import AIOKafkaConsumer

from src.event_publisher import EventPublisher, close_event_publisher
from src.quant_swarm_graph import quant_swarm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("quant_swarm_daemon")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "macro_swarm_v1"
DEBOUNCE_SECONDS = 30

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100:11434")
EMBED_MODEL = "nomic-embed-text"
RAG_COLLECTION = "fortress_knowledge"
RAG_LIMIT = 5


# ---------------------------------------------------------------------------
# Qdrant RAG Retrieval (async)
# ---------------------------------------------------------------------------

async def retrieve_macro_context(event_data: dict) -> str:
    """Embed a macro query derived from tick data and search Qdrant."""
    assets = ", ".join(
        f"{v['asset']} @ ${v['price']}"
        for v in event_data.values()
        if isinstance(v, dict) and "asset" in v
    )
    if not assets:
        assets = json.dumps(event_data)[:200]

    query = (
        f"macroeconomic analysis: {assets} — "
        "global liquidity trends, exponential technology curves, "
        "luxury real estate demand correlation, monetary policy impact"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            embed_resp = await client.post(
                f"{EMBED_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": query},
            )
            embed_resp.raise_for_status()
            embedding = embed_resp.json().get("embedding")
            if not embedding:
                log.warning("Empty embedding returned. Skipping RAG.")
                return "(No sovereign memory context available)"

            search_resp = await client.post(
                f"{QDRANT_URL}/collections/{RAG_COLLECTION}/points/search",
                json={
                    "vector": embedding,
                    "limit": RAG_LIMIT,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            search_resp.raise_for_status()
            hits = search_resp.json().get("result", [])

        if not hits:
            return "(No matching context found in sovereign memory)"

        chunks = []
        for hit in hits:
            payload = hit.get("payload", {})
            source = payload.get("source", payload.get("filename", "Unknown"))
            text = payload.get("text", payload.get("content", ""))
            if text:
                chunks.append(f"[Source: {source}]\n{text}")

        log.info("Retrieved %d RAG chunks from %s", len(chunks), RAG_COLLECTION)
        return "\n\n".join(chunks)

    except Exception as e:
        log.warning("Qdrant RAG retrieval failed: %s. Proceeding without context.", e)
        return "(Sovereign memory unavailable — proceeding with raw event data only)"


# ---------------------------------------------------------------------------
# Swarm Execution (sync LangGraph via thread pool)
# ---------------------------------------------------------------------------

async def run_swarm(initial_state: dict) -> dict:
    """Execute the LangGraph swarm in a background thread."""
    def _invoke():
        return quant_swarm.invoke(initial_state)
    return await asyncio.to_thread(_invoke)


async def synthesize_batch(tick_buffer: dict):
    """Run the full pipeline: RAG retrieval -> Swarm debate -> publish thesis."""
    batch_size = len(tick_buffer)
    log.info("Debounce window closed. Synthesizing batch of %d ticks.", batch_size)

    context = await retrieve_macro_context(tick_buffer)

    tick_summary = {
        asset: {"asset": data["asset"], "price": data["price"], "source": data.get("source", "unknown")}
        for asset, data in tick_buffer.items()
    }

    initial_state = {
        "event_data": tick_summary,
        "market_context": context,
        "quantitative_analysis": "",
        "macro_thesis": "",
        "risk_assessment": "",
        "iterations": 0,
        "approved": False,
    }

    log.info("Deploying Multi-Agent Quant Swarm to DGX cluster...")
    final_state = await run_swarm(initial_state)

    if final_state.get("approved"):
        log.info("SWARM CONSENSUS REACHED. Publishing approved thesis.")
        await EventPublisher.publish(
            topic="market.thesis.approved",
            payload={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_ticks": tick_summary,
                "thesis": final_state["macro_thesis"],
                "risk_assessment": final_state["risk_assessment"],
                "iterations": final_state["iterations"],
            },
            key="swarm_consensus",
        )
    else:
        log.warning(
            "Swarm rejected thesis after %d iterations. Risk: %s",
            final_state.get("iterations", 0),
            final_state.get("risk_assessment", "N/A")[:200],
        )


# ---------------------------------------------------------------------------
# Macro News (immediate, no debounce)
# ---------------------------------------------------------------------------

async def process_macro_news(payload: dict):
    """Macro news events bypass the debounce and trigger immediate synthesis."""
    log.info("[MACRO NEWS] Immediate synthesis triggered: %s", payload.get("headline", "unknown")[:100])
    await synthesize_batch({"macro_news": payload})


# ---------------------------------------------------------------------------
# Consumer with 30-second tick debounce
# ---------------------------------------------------------------------------

async def consume_events():
    """Main consumer loop with debounce accumulator for tick batching."""
    consumer = AIOKafkaConsumer(
        "market.crypto.ticks",
        "market.macro.news",
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
    )

    await consumer.start()
    log.info("Quant Swarm Daemon online — listening on %s", REDPANDA_BROKER)

    tick_buffer: dict[str, dict] = {}
    tick_received = asyncio.Event()

    async def debounce_synthesizer():
        """Waits for first tick, then batches until 30s of silence."""
        while True:
            await tick_received.wait()
            tick_received.clear()

            while True:
                try:
                    await asyncio.wait_for(tick_received.wait(), timeout=DEBOUNCE_SECONDS)
                    tick_received.clear()
                except asyncio.TimeoutError:
                    break

            if tick_buffer:
                batch = dict(tick_buffer)
                tick_buffer.clear()
                try:
                    await synthesize_batch(batch)
                except Exception as e:
                    log.error("Swarm synthesis failed: %s", e)

    synth_task = asyncio.create_task(debounce_synthesizer())

    try:
        async for msg in consumer:
            if msg.topic == "market.crypto.ticks":
                tick_buffer[msg.value.get("asset", "unknown")] = msg.value
                tick_received.set()
            elif msg.topic == "market.macro.news":
                await process_macro_news(msg.value)
    except asyncio.CancelledError:
        log.info("Consumer shutdown initiated.")
    except Exception as e:
        log.error("Consumer loop error: %s", e)
    finally:
        synth_task.cancel()
        await consumer.stop()
        await close_event_publisher()
        log.info("Quant Swarm Daemon shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_events())
    except KeyboardInterrupt:
        log.info("Manual shutdown of Quant Swarm Daemon.")
