#!/usr/bin/env python3
"""Promote verified archive-backed legacy destinations to sovereign status."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

for env_file in (
    REPO_ROOT / ".env",
    PROJECT_ROOT / ".env",
    REPO_ROOT / ".env.security",
):
    if env_file.exists():
        load_dotenv(env_file, override=True)

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.functional_node import FunctionalNode

SHADOW_12: tuple[str, ...] = (
    "/about-blue-ridge-ga",
    "/about-us",
    "/blue-ridge-georgia-activities",
    "/choose-from-our-gorgeous-venues-below",
    "/christmas-new-year’s-cabin-rentals-blue-ridge-ga",
    "/event/santa-train-ride",
    "/experience-north-georgia",
    "/lady-bugs-blue-ridge-ga-cabins",
    "/large-groups-family-reunions",
    "/north-georgia-cabin-rentals",
    "/rental-policies",
    "/specials-discounts",
)

ARCHIVE_COMPONENT_PATH = "apps/storefront/src/app/[...slug]/page.tsx"


async def _run() -> int:
    now = datetime.now(timezone.utc).isoformat()
    updated: list[str] = []
    missing: list[str] = []

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(FunctionalNode)
                .where(FunctionalNode.canonical_path.in_(SHADOW_12))
                .order_by(FunctionalNode.canonical_path.asc())
            )
        ).scalars().all()

        found_paths = {row.canonical_path for row in rows}
        missing = sorted(set(SHADOW_12) - found_paths)

        for row in rows:
            metadata = dict(row.source_metadata or {})
            metadata.update(
                {
                    "routing_signal": "SOVEREIGN_ARCHIVE",
                    "cutover_script": "backend/scripts/promote_shadow_12.py",
                    "cutover_completed_at": now,
                }
            )
            row.cutover_status = "sovereign"
            row.mirror_status = "deployed"
            row.mirror_route_path = row.canonical_path
            row.mirror_component_path = ARCHIVE_COMPONENT_PATH
            row.source_metadata = metadata
            updated.append(row.canonical_path)

        await db.commit()

    print("[ok] shadow 12 promotion committed")
    print(f"targets={len(SHADOW_12)}")
    print(f"found={len(updated)}")
    print(f"missing={len(missing)}")
    if updated:
        print("updated_detail_begin")
        for path in updated:
            print(path)
        print("updated_detail_end")
    if missing:
        print("missing_detail_begin")
        for path in missing:
            print(path)
        print("missing_detail_end")
    return 0 if not missing else 1


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
