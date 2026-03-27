#!/usr/bin/env python3
"""
Fleet-wide SEO ignition entrypoint.

Runs the DGX SEO extraction swarm across the active portfolio for properties that
do not already have an in-flight or completed patch under the active rubric.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")

from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.scripts.run_seo_extraction_batch import ACTIVE_PATCH_STATUSES, run_batch


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ignite_seo_fleet")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ignite the SEO swarm across the active fleet.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on the number of properties to process. Default 0 means whole fleet.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.5,
        help="Delay between properties to avoid over-saturating local inference.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview fleet size without running extraction.",
    )
    return parser.parse_args()


async def _resolve_active_rubric_id() -> str | None:
    async with AsyncSessionLocal() as db:
        rubric = await db.scalar(
            select(SEORubric)
            .where(SEORubric.status == "active")
            .order_by(SEORubric.created_at.desc())
            .limit(1)
        )
        return str(rubric.id) if rubric is not None else None


async def _count_active_properties() -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count()).select_from(Property).where(Property.is_active.is_(True))
            )
            or 0
        )


async def _count_existing_patches(rubric_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(func.distinct(SEOPatch.property_id))).where(
                    SEOPatch.rubric_id == rubric_id,
                    SEOPatch.property_id.is_not(None),
                    SEOPatch.status.in_(ACTIVE_PATCH_STATUSES),
                )
            )
            or 0
        )


async def main_async() -> None:
    args = _parse_args()
    rubric_id = await _resolve_active_rubric_id()
    if rubric_id is None:
        logger.error("No active rubric found. Aborting ignition.")
        return

    active_count = await _count_active_properties()
    existing_count = await _count_existing_patches(rubric_id)
    fleet_limit = args.limit if args.limit > 0 else max(active_count - existing_count, 0)

    logger.info(
        "FLEET IGNITION | active_properties=%s existing_property_patches=%s target_limit=%s rubric=%s dry_run=%s",
        active_count,
        existing_count,
        fleet_limit,
        rubric_id,
        args.dry_run,
    )

    if fleet_limit <= 0:
        logger.info("No pending active properties detected for the current rubric. Ignition complete.")
        return

    await run_batch(
        limit=fleet_limit,
        rubric_id_str=rubric_id,
        dry_run=bool(args.dry_run),
        sleep_seconds=max(0.0, float(args.sleep_seconds)),
    )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
