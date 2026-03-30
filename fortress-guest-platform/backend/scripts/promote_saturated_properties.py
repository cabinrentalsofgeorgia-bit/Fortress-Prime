#!/usr/bin/env python3
"""
Promote approved saturation patches to deployed state for KV sync.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

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
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.scripts.run_dgx_swarm_worker import DEFAULT_TARGET_LIST_PATH


PROMOTION_READY_STATUSES = ("approved",)


@dataclass(frozen=True)
class TargetRow:
    property_id: UUID
    slug: str


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote target-list patches from approved to deployed.",
    )
    parser.add_argument(
        "--target-list-path",
        type=Path,
        default=Path(DEFAULT_TARGET_LIST_PATH),
        help=f"Target list JSON path. Defaults to {DEFAULT_TARGET_LIST_PATH}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview property activations without committing.",
    )
    parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        help="Promotion-eligible patch status. Repeatable. Defaults to approved.",
    )
    return parser.parse_args()


def _load_targets(path: Path) -> list[TargetRow]:
    if not path.exists():
        raise FileNotFoundError(f"Target list not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError(f"Target list payload is invalid: {path}")

    rows: list[TargetRow] = []
    for target in targets:
        property_id = _normalize_text(target.get("property_id"))
        slug = _normalize_text(target.get("slug")).lower()
        if not property_id or not slug:
            continue
        rows.append(TargetRow(property_id=UUID(property_id), slug=slug))
    return rows


async def _run() -> int:
    args = _parse_args()
    target_list_path = Path(args.target_list_path).expanduser().resolve()
    eligible_statuses = tuple(
        sorted({_normalize_text(status).lower() for status in (args.statuses or PROMOTION_READY_STATUSES) if _normalize_text(status)})
    )
    targets = _load_targets(target_list_path)
    property_ids = [target.property_id for target in targets]

    async with AsyncSessionLocal() as session:
        properties = (
            await session.execute(select(Property).where(Property.id.in_(property_ids)).order_by(Property.slug.asc()))
        ).scalars().all()
        patches = (
            await session.execute(
                select(SEOPatch)
                .where(SEOPatch.property_id.in_(property_ids))
                .order_by(SEOPatch.property_id.asc(), SEOPatch.created_at.desc(), SEOPatch.patch_version.desc())
            )
        ).scalars().all()

        latest_patch_by_property_id: dict[UUID, SEOPatch] = {}
        for patch in patches:
            if patch.property_id is None:
                continue
            latest_patch_by_property_id.setdefault(patch.property_id, patch)

        deployed_rows: list[str] = []
        skipped_rows: list[str] = []
        deployed = 0
        already_deployed = 0
        not_ready = 0
        now = datetime.now(timezone.utc)

        for prop in properties:
            patch = latest_patch_by_property_id.get(prop.id)
            patch_status = _normalize_text(patch.status).lower() if patch is not None else ""
            if patch_status not in eligible_statuses:
                not_ready += 1
                skipped_rows.append(
                    f"slug={prop.slug} active={str(bool(prop.is_active)).lower()} patch_status={patch_status or 'none'}"
                )
                continue

            if patch is None:
                not_ready += 1
                skipped_rows.append(
                    f"slug={prop.slug} active={str(bool(prop.is_active)).lower()} patch_status=none"
                )
                continue

            if patch.status == "deployed":
                already_deployed += 1
                skipped_rows.append(
                    f"slug={prop.slug} patch_status=deployed action=already_deployed"
                )
                continue

            patch.status = "deployed"
            patch.deployed_at = now
            patch.deploy_status = "succeeded"
            patch.deploy_acknowledged_at = now
            patch.deploy_attempts = max(int(patch.deploy_attempts or 0), 1)
            patch.deploy_last_error = None
            patch.deploy_last_http_status = 200
            if patch.final_payload is None:
                patch.final_payload = {
                    "title": patch.title,
                    "meta_description": patch.meta_description,
                    "og_title": patch.og_title,
                    "og_description": patch.og_description,
                    "h1_suggestion": patch.h1_suggestion,
                    "jsonld": patch.jsonld_payload or {},
                    "canonical_url": patch.canonical_url,
                    "alt_tags": patch.alt_tags or {},
                }

            prop.is_active = True
            deployed += 1
            deployed_rows.append(
                f"slug={prop.slug} patch_status=deployed patch_id={patch.id} property_active={str(bool(prop.is_active)).lower()}"
            )

        if args.dry_run:
            await session.rollback()
            print("[dry-run] promotion plan prepared")
        else:
            await session.commit()
            print("[ok] promotion committed")

    print(f"target_list_path={target_list_path}")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"eligible_statuses={','.join(eligible_statuses)}")
    print(f"targets={len(targets)}")
    print(f"deployed={deployed}")
    print(f"already_deployed={already_deployed}")
    print(f"not_ready={not_ready}")

    if deployed_rows:
        print("deployed_detail_begin")
        for row in deployed_rows:
            print(row)
        print("deployed_detail_end")

    if skipped_rows:
        print("skipped_detail_begin")
        for row in skipped_rows:
            print(row)
        print("skipped_detail_end")

    return 0


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
