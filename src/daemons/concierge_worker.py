"""
Omni-Channel Concierge Inference Daemon
=======================================

Continuously scans pending concierge queue rows that are missing an AI draft,
generates a reply via local OpenAI-compatible vLLM, and writes the draft back.

Run once:
    python -m src.daemons.concierge_worker --once

Run forever:
    python -m src.daemons.concierge_worker
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FGP_ROOT = PROJECT_ROOT / "fortress-guest-platform"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(FGP_ROOT))

from dotenv import load_dotenv
load_dotenv(FGP_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.security")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fortress.concierge_worker")

VLLM_BASE_URL     = os.getenv("CONCIERGE_VLLM_BASE_URL", "http://192.168.0.106:8000/v1")
VLLM_MODEL        = os.getenv("CONCIERGE_VLLM_MODEL", "meta/llama-3.1-8b-instruct")
VLLM_TIMEOUT      = float(os.getenv("CONCIERGE_VLLM_TIMEOUT_SECONDS", "45"))
FAILURE_COOLDOWN  = float(os.getenv("CONCIERGE_FAILURE_COOLDOWN_SECONDS", "60"))
POLL_INTERVAL     = float(os.getenv("CONCIERGE_POLL_INTERVAL_SECONDS", "10"))
BATCH_SIZE        = int(os.getenv("CONCIERGE_BATCH_SIZE", "5"))
DATABASE_URL      = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://fgp_app:fortress2024@localhost:5432/fortress_guest"
).replace("postgresql://", "postgresql+asyncpg://")

SYSTEM_PROMPT = (
    "You are a highly professional, warm, and hospitable luxury cabin concierge "
    "for Cabin Rentals of Georgia. Draft one concise guest-facing SMS reply. "
    "Be clear, actionable, and polite. Use retrieved context as source of truth. "
    "If context is incomplete, acknowledge and offer immediate follow-up. "
    "Do not hallucinate property details."
)

_COOLDOWN_UNTIL: dict[str, float] = {}

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def fetch_pending(session: AsyncSession, limit: int) -> list[Any]:
    result = await session.execute(
        select(
            "id", "guest_phone", "inbound_message", "retrieved_context"
        ).select_from("concierge_queue").where(
            "status = 'pending_review' AND (ai_draft_reply = '' OR ai_draft_reply IS NULL)"
        ).limit(limit)
    )
    return result.fetchall()


async def fetch_pending_raw(session: AsyncSession, limit: int) -> list[dict]:
    result = await session.execute(
        __import__("sqlalchemy").text("""
            SELECT id, guest_phone, inbound_message, retrieved_context
            FROM concierge_queue
            WHERE status = 'pending_review'
              AND (ai_draft_reply = '' OR ai_draft_reply IS NULL OR ai_draft_reply = 'pending')
            ORDER BY created_at ASC
            LIMIT :limit
        """),
        {"limit": limit}
    )
    return [dict(r._mapping) for r in result.fetchall()]


async def generate_draft(inbound: str, context: dict) -> str:
    context_str = ""
    if context:
        import json
        context_str = f"\n\nContext: {json.dumps(context, default=str)[:1000]}"

    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Guest message: {inbound}{context_str}"},
        ],
        "max_tokens": 200,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=VLLM_TIMEOUT) as client:
        resp = await client.post(f"{VLLM_BASE_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


async def write_draft(session: AsyncSession, row_id: str, draft: str) -> None:
    from sqlalchemy import text
    await session.execute(
        text("""
            UPDATE concierge_queue
            SET ai_draft_reply = :draft,
                updated_at = now()
            WHERE id = :id
        """),
        {"draft": draft, "id": row_id}
    )
    await session.commit()


async def process_batch(once: bool = False) -> None:
    async with SessionLocal() as session:
        rows = await fetch_pending_raw(session, BATCH_SIZE)

    if not rows:
        if not once:
            log.debug("No pending rows — sleeping %ss", POLL_INTERVAL)
        return

    log.info("Processing %d concierge queue rows", len(rows))

    for row in rows:
        row_id = str(row["id"])
        now = time.time()
        if _COOLDOWN_UNTIL.get(row_id, 0) > now:
            continue

        try:
            draft = await generate_draft(
                row["inbound_message"],
                row["retrieved_context"] or {}
            )
            async with SessionLocal() as session:
                await write_draft(session, row_id, draft)
            log.info("✅ Draft written for queue row %s", row_id)

        except Exception as exc:
            log.warning("❌ Failed to generate draft for %s: %s", row_id, exc)
            _COOLDOWN_UNTIL[row_id] = time.time() + FAILURE_COOLDOWN


async def run(once: bool = False) -> None:
    log.info("🛡️  Concierge Worker starting — vLLM: %s model: %s", VLLM_BASE_URL, VLLM_MODEL)
    if once:
        await process_batch(once=True)
        log.info("✅ One-shot run complete")
        return

    while True:
        try:
            await process_batch()
        except Exception as exc:
            log.error("Unhandled error in process_batch: %s", exc)
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Concierge Inference Daemon")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    asyncio.run(run(once=args.once))
