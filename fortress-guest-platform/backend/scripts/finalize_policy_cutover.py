#!/usr/bin/env python3
"""
Finalize policy cutover in the functional node ledger.

Marks the sovereign policy mirrors as deployed so downstream systems have an
authoritative ledger signal that these public routes should no longer be
treated as legacy-only Drupal paths.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
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


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    env_files = [
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.functional_node import FunctionalNode


@dataclass(frozen=True)
class PolicyRoute:
    canonical_path: str
    title: str
    component_path: str


POLICY_ROUTES: tuple[PolicyRoute, ...] = (
    PolicyRoute(
        canonical_path="/privacy-policy",
        title="Privacy Policy",
        component_path="apps/storefront/src/app/(storefront)/privacy-policy/page.tsx",
    ),
    PolicyRoute(
        canonical_path="/terms-and-conditions",
        title="Terms and Conditions",
        component_path="apps/storefront/src/app/(storefront)/terms-and-conditions/page.tsx",
    ),
    PolicyRoute(
        canonical_path="/faq",
        title="FAQ",
        component_path="apps/storefront/src/app/(storefront)/faq/page.tsx",
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark sovereign policy mirrors as cut over in the functional ledger.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview ledger mutations without committing them.",
    )
    return parser.parse_args()


async def _run() -> int:
    args = _parse_args()
    route_by_path = {route.canonical_path: route for route in POLICY_ROUTES}
    target_paths = list(route_by_path)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FunctionalNode)
                .where(FunctionalNode.canonical_path.in_(target_paths))
                .order_by(FunctionalNode.canonical_path.asc())
            )
        ).scalars().all()

        found_paths = {row.canonical_path for row in rows}
        missing_paths = sorted(set(target_paths) - found_paths)
        updated_rows: list[str] = []

        for row in rows:
            route = route_by_path[row.canonical_path]
            metadata = dict(row.source_metadata or {})
            metadata.update(
                {
                    "routing_signal": "SOVEREIGN",
                    "cutover_script": "backend/scripts/finalize_policy_cutover.py",
                    "cutover_completed_at": now.isoformat(),
                }
            )
            row.title = row.title or route.title
            row.mirror_status = "deployed"
            row.cutover_status = "sovereign"
            row.mirror_route_path = route.canonical_path
            row.mirror_component_path = route.component_path
            row.source_metadata = metadata
            updated_rows.append(
                " ".join(
                    [
                        f"path={row.canonical_path}",
                        f"mirror_status={row.mirror_status}",
                        f"cutover_status={row.cutover_status}",
                        f"mirror_route_path={row.mirror_route_path}",
                        f"routing_signal={metadata['routing_signal']}",
                    ]
                )
            )

        if args.dry_run:
            await session.rollback()
            print("[dry-run] policy cutover plan prepared")
        else:
            await session.commit()
            print("[ok] policy cutover committed")

    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"targets={len(target_paths)}")
    print(f"found={len(rows)}")
    print(f"updated={len(updated_rows)}")
    print(f"missing={len(missing_paths)}")

    if updated_rows:
        print("updated_detail_begin")
        for row in updated_rows:
            print(row)
        print("updated_detail_end")

    if missing_paths:
        print("missing_detail_begin")
        for path in missing_paths:
            print(f"path={path}")
        print("missing_detail_end")

    return 0 if not missing_paths else 1


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
