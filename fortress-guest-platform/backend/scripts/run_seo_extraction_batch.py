#!/usr/bin/env python3
"""
Manual DGX SEO extraction batch runner.

Operators run this on a DGX host to submit property SEO drafts into the God
Head pipeline with optional dry-run previewing and clear terminal telemetry.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import exists, select

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")

from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.services.seo_extraction_service import SEOExtractionSwarm


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seo_batch")

ACTIVE_PATCH_STATUSES = (
    "drafted",
    "grading",
    "needs_rewrite",
    "pending_human",
    "deployed",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fire the DGX SEO Extraction Swarm.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of properties to process.",
    )
    parser.add_argument(
        "--rubric",
        type=str,
        default=None,
        help="Specific SEORubric UUID to execute against.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview target properties without running local inference or submitting drafts.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.5,
        help="Delay between properties to avoid saturating the local inference queue.",
    )
    return parser.parse_args()


def _extract_legacy_context(prop: Property) -> str:
    for attr in ("legacy_seo_description", "seo_description", "description"):
        value = getattr(prop, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _resolve_rubric(db, rubric_id_str: Optional[str]) -> Optional[SEORubric]:
    if rubric_id_str:
        try:
            rubric_id = UUID(rubric_id_str)
        except ValueError:
            logger.error("Invalid rubric UUID: %s", rubric_id_str)
            return None
        stmt = select(SEORubric).where(SEORubric.id == rubric_id)
    else:
        stmt = (
            select(SEORubric)
            .where(SEORubric.status == "active")
            .order_by(SEORubric.created_at.desc())
            .limit(1)
        )

    return await db.scalar(stmt)


async def _load_target_properties(db, rubric_id: UUID, limit: int) -> list[Property]:
    stmt = (
        select(Property)
        .where(
            Property.is_active.is_(True),
            ~exists(
                select(SEOPatch.id).where(
                    SEOPatch.property_id == Property.id,
                    SEOPatch.rubric_id == rubric_id,
                    SEOPatch.status.in_(ACTIVE_PATCH_STATUSES),
                )
            ),
        )
        .order_by(Property.name.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def run_batch(
    *,
    limit: int,
    rubric_id_str: Optional[str],
    dry_run: bool,
    sleep_seconds: float,
) -> None:
    logger.info(
        "INITIALIZING DGX SWARM EXTRACTION BATCH | limit=%s dry_run=%s",
        limit,
        dry_run,
    )

    async with AsyncSessionLocal() as db:
        rubric = await _resolve_rubric(db, rubric_id_str)
        if rubric is None:
            logger.error("No active SEORubric found. Aborting batch.")
            return

        logger.info(
            "Target Rubric | id=%s cluster=%s min_pass_score=%.3f",
            rubric.id,
            rubric.keyword_cluster,
            rubric.min_pass_score,
        )

        properties = await _load_target_properties(db, rubric.id, limit)
        if not properties:
            logger.info("Zero pending properties found for rubric %s. Batch complete.", rubric.id)
            return

        logger.info("Acquired %s properties for extraction.", len(properties))

        if dry_run:
            logger.info("DRY RUN MODE ENABLED | no inference or transmissions will occur")
            for index, prop in enumerate(properties, start=1):
                legacy_context = _extract_legacy_context(prop)
                logger.info(
                    "[%s/%s] PREVIEW | property=%s slug=%s legacy_context_chars=%s",
                    index,
                    len(properties),
                    prop.name,
                    prop.slug,
                    len(legacy_context),
                )
            logger.info("DRY RUN COMPLETE | previewed=%s", len(properties))
            return

        logger.info("Spooling DGX Swarm...")
        swarm = SEOExtractionSwarm(db)
        success_count = 0

        for index, prop in enumerate(properties, start=1):
            logger.info("[%s/%s] Processing | property=%s slug=%s", index, len(properties), prop.name, prop.slug)
            legacy_context = _extract_legacy_context(prop)

            result = await swarm.run_extraction(
                property_id=prop.id,
                rubric_id=rubric.id,
                legacy_drupal_context=legacy_context,
            )

            if result:
                success_count += 1
                logger.info(
                    "[%s/%s] SUCCESS | property=%s response_id=%s",
                    index,
                    len(properties),
                    prop.slug,
                    result.get("id") or result.get("patch_id") or "n/a",
                )
            else:
                logger.error("[%s/%s] FAILED | property=%s", index, len(properties), prop.slug)

            if index < len(properties) and sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

        logger.info("========================================")
        logger.info(
            "BATCH COMPLETE | success=%s total=%s failed=%s",
            success_count,
            len(properties),
            len(properties) - success_count,
        )
        logger.info("========================================")


def main() -> None:
    args = _parse_args()
    asyncio.run(
        run_batch(
            limit=max(1, int(args.limit)),
            rubric_id_str=args.rubric,
            dry_run=bool(args.dry_run),
            sleep_seconds=max(0.0, float(args.sleep_seconds)),
        )
    )


if __name__ == "__main__":
    main()
