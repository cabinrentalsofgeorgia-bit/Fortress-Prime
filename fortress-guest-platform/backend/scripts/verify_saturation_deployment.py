#!/usr/bin/env python3
"""
Verify deployed saturation targets resolve with HTTP 200.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
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
    for env_file in (
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.scripts.run_dgx_swarm_worker import DEFAULT_TARGET_LIST_PATH


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify deployed saturation targets respond with 200 OK.",
    )
    parser.add_argument(
        "--target-list-path",
        type=Path,
        default=Path(DEFAULT_TARGET_LIST_PATH),
    )
    parser.add_argument(
        "--base-url",
        default="https://cabin-rentals-of-georgia.com",
        help="Public storefront base URL to probe.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
    )
    return parser.parse_args()


def _load_target_ids(path: Path) -> list[UUID]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError(f"Invalid target list payload: {path}")
    ids: list[UUID] = []
    for target in targets:
        raw = _normalize_text(target.get("property_id"))
        if raw:
            ids.append(UUID(raw))
    return ids


async def _run() -> int:
    args = _parse_args()
    target_ids = _load_target_ids(Path(args.target_list_path).expanduser().resolve())

    async with AsyncSessionLocal() as session:
        properties = (
            await session.execute(select(Property).where(Property.id.in_(target_ids)).order_by(Property.slug.asc()))
        ).scalars().all()
        patches = (
            await session.execute(
                select(SEOPatch)
                .where(SEOPatch.property_id.in_(target_ids))
                .order_by(SEOPatch.property_id.asc(), SEOPatch.created_at.desc(), SEOPatch.patch_version.desc())
            )
        ).scalars().all()

    latest_patch_by_property_id: dict[UUID, SEOPatch] = {}
    for patch in patches:
        if patch.property_id is None:
            continue
        latest_patch_by_property_id.setdefault(patch.property_id, patch)

    deployed_slugs: list[str] = []
    undeployed_slugs: list[str] = []
    for prop in properties:
        patch = latest_patch_by_property_id.get(prop.id)
        status = _normalize_text(patch.status).lower() if patch is not None else "awaiting_generation"
        if status == "deployed":
            deployed_slugs.append(prop.slug)
        else:
            undeployed_slugs.append(prop.slug)

    print("[verify-saturation] public storefront probe")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"deployed_targets={len(deployed_slugs)}")
    print(f"undeployed_targets={len(undeployed_slugs)}")
    for slug in undeployed_slugs:
        print(f"undeployed_slug={slug}")

    failures: list[str] = []
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(args.timeout_seconds),
        headers={"User-Agent": "Fortress-Saturation-Verify/1.0"},
    ) as client:
        for slug in deployed_slugs:
            url = f"{args.base_url.rstrip('/')}/cabins/{slug}"
            try:
                response = await client.get(url)
                status = int(response.status_code)
                print(f"probe slug={slug} status_code={status} final_url={response.url}")
                if status != 200:
                    failures.append(f"slug={slug} status_code={status}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"slug={slug} error={exc}")
                print(f"probe slug={slug} error={exc}")

    print(f"probe_failures={len(failures)}")
    for row in failures:
        print(row)
    return 0 if not undeployed_slugs and not failures else 1


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
