#!/usr/bin/env python3
"""Resolve the last legacy functional-node rows for Strike 15."""

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

REDIRECT_MAP: dict[str, str] = {
    "/2-bedroom-cabins": "/cabins?bedrooms=2",
    "/3-bedroom-cabin-rentals": "/cabins?bedrooms=3",
    "/4-bedroom-cabin-rentals": "/cabins?bedrooms=4",
    "/5-bedroom-cabin-rentals": "/cabins?bedrooms=5",
    "/lakefront-cabin-rentals": "/cabins?amenities=lakefront",
    "/lake-view-cabin-rentals": "/cabins?amenities=lake-view",
    "/luxury-river-cabins": "/cabins?amenities=riverfront",
    "/mountain-view-cabin-rentals": "/cabins?amenities=mountain-view",
    "/our-pet-friendly-cabins": "/cabins?amenities=pet-friendly",
    "/riverfront-cabin-rentals": "/cabins?amenities=riverfront",
    "/river-view-cabin-rentals": "/cabins?amenities=river-view",
    "/book-now-before-its-too-late": "/cabins",
    "/book-one-now-while-you-still-can": "/cabins",
    "/only-3-cabins-left": "/cabins",
    "/access-denied": "/",
}

RETIRED_PATH = "/node/2719"
REDIRECT_COMPONENT_PATH = "apps/storefront/src/proxy.ts"


async def _run() -> int:
    now = datetime.now(timezone.utc).isoformat()
    updated_redirects: list[str] = []
    retired = False
    missing: list[str] = []

    target_paths = tuple(sorted((*REDIRECT_MAP.keys(), RETIRED_PATH)))

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(FunctionalNode)
                .where(FunctionalNode.canonical_path.in_(target_paths))
                .order_by(FunctionalNode.canonical_path.asc())
            )
        ).scalars().all()

        found_paths = {row.canonical_path for row in rows}
        missing = sorted(set(target_paths) - found_paths)

        for row in rows:
            if row.canonical_path == RETIRED_PATH:
                metadata = dict(row.source_metadata or {})
                metadata.update(
                    {
                        "routing_signal": "RETIRED",
                        "cutover_script": "backend/scripts/resolve_shadow_16.py",
                        "cutover_completed_at": now,
                        "retired_reason": "legacy_webform_decommissioned",
                    }
                )
                row.cutover_status = "retired"
                row.mirror_status = "decommissioned"
                row.mirror_route_path = None
                row.mirror_component_path = None
                row.source_metadata = metadata
                retired = True
                continue

            redirect_target = REDIRECT_MAP[row.canonical_path]
            metadata = dict(row.source_metadata or {})
            metadata.update(
                {
                    "routing_signal": "SOVEREIGN_REDIRECT",
                    "cutover_script": "backend/scripts/resolve_shadow_16.py",
                    "cutover_completed_at": now,
                    "redirect_target": redirect_target,
                }
            )
            row.cutover_status = "sovereign"
            row.mirror_status = "mapped_redirect"
            row.mirror_route_path = redirect_target
            row.mirror_component_path = REDIRECT_COMPONENT_PATH
            row.source_metadata = metadata
            updated_redirects.append(f"{row.canonical_path} -> {redirect_target}")

        await db.commit()

    print("[ok] shadow 16 resolution committed")
    print(f"targets={len(target_paths)}")
    print(f"redirects_updated={len(updated_redirects)}")
    print(f"retired={'1' if retired else '0'}")
    print(f"missing={len(missing)}")
    if updated_redirects:
        print("redirect_detail_begin")
        for item in updated_redirects:
            print(item)
        print("redirect_detail_end")
    if retired:
        print(f"retired_detail={RETIRED_PATH}")
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
