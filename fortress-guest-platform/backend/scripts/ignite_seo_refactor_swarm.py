#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env.security")

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, close_db
from backend.core.queue import create_arq_pool
from backend.models.functional_node import FunctionalNode

MIRRORED_CONTENT_CATEGORIES = ("area_guide", "blog_article")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("SEORefactorSwarm")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enqueue mirrored legacy nodes for sovereign HTML refactor.")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on nodes to enqueue. Default 0 means all.")
    parser.add_argument("--dry-run", action="store_true", help="Preview the queue plan without enqueuing jobs.")
    return parser.parse_args()


async def main_async() -> int:
    args = _parse_args()

    async with AsyncSessionLocal() as db:
        stmt = (
            select(FunctionalNode.canonical_path)
            .where(
                FunctionalNode.content_category.in_(MIRRORED_CONTENT_CATEGORIES),
                FunctionalNode.cutover_status == "legacy",
                FunctionalNode.is_published.is_(True),
                FunctionalNode.body_html.is_not(None),
            )
            .order_by(FunctionalNode.priority_tier.asc(), FunctionalNode.canonical_path.asc())
        )
        if args.limit > 0:
            stmt = stmt.limit(args.limit)

        paths = list((await db.execute(stmt)).scalars().all())

    print("\n--- SEO REFACTOR SWARM: IGNITION REPORT ---")
    print(f"queue_name={settings.arq_queue_name}")
    print(f"refactor_model={str(settings.gemini_model or '').strip() or 'unset'}")
    print(f"candidate_nodes={len(paths)}")
    print(f"dry_run={str(bool(args.dry_run)).lower()}")

    if not paths:
        print("No mirrored legacy nodes are eligible for refactor.")
        print("-------------------------------------------\n")
        return 0

    preview = paths[:15]
    for path in preview:
        print(f"  - {path}")
    if len(paths) > len(preview):
        print(f"  ... +{len(paths) - len(preview)} more")

    if args.dry_run:
        print("-------------------------------------------\n")
        return 0

    pool = await create_arq_pool()
    enqueued = 0
    try:
        for path in paths:
            job = await pool.enqueue_job(
                "refactor_legacy_html_task",
                path,
                _queue_name=settings.arq_queue_name,
            )
            if job is not None:
                enqueued += 1
    finally:
        await pool.aclose()

    print(f"enqueued={enqueued}")
    print("-------------------------------------------\n")
    logger.info("Refactor swarm ignition complete: enqueued=%s", enqueued)
    return 0 if enqueued == len(paths) else 1


async def amain() -> int:
    try:
        return await main_async()
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
