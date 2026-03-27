#!/usr/bin/env python3
"""
Bulk-approve the current saturation batch from pending_human to approved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
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

from backend.api.seo_patches import _default_final_payload
from backend.core.database import AsyncSessionLocal, close_db
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.scripts.run_dgx_swarm_worker import DEFAULT_TARGET_LIST_PATH


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk-approve pending_human patches in the current saturation batch.",
    )
    parser.add_argument(
        "--reviewer",
        default="bulk-approval-strike",
        help="Reviewer marker written onto approved patches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview approvals without committing.",
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
    reviewer = _normalize_text(args.reviewer) or "bulk-approval-strike"
    target_ids = _load_target_ids(Path(DEFAULT_TARGET_LIST_PATH))

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SEOPatch, Property.slug)
                .join(Property, Property.id == SEOPatch.property_id)
                .where(SEOPatch.property_id.in_(target_ids))
                .order_by(Property.slug.asc(), SEOPatch.created_at.desc())
            )
        ).all()

        approved_rows: list[str] = []
        skipped_rows: list[str] = []
        seen_patch_ids: set[UUID] = set()
        now = datetime.now(timezone.utc)
        for patch, slug in rows:
            if patch.id in seen_patch_ids:
                continue
            seen_patch_ids.add(patch.id)
            status = _normalize_text(patch.status).lower()
            if status != "pending_human":
                skipped_rows.append(f"slug={slug} status={status or 'unknown'}")
                continue

            patch.status = "approved"
            patch.reviewed_by = reviewer
            patch.reviewed_at = now
            patch.final_payload = patch.final_payload or _default_final_payload(patch)
            patch.deploy_task_id = None
            patch.deploy_status = None
            patch.deploy_queued_at = None
            patch.deploy_acknowledged_at = None
            patch.deploy_last_error = None
            patch.deploy_last_http_status = None
            approved_rows.append(
                f"slug={slug} status=approved score={float(patch.godhead_score or 0.0):.3f} patch_id={patch.id}"
            )

        if args.dry_run:
            await session.rollback()
            print("[dry-run] bulk approval plan prepared")
        else:
            await session.commit()
            print("[ok] bulk approval committed")

    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"approved={len(approved_rows)}")
    print(f"skipped={len(skipped_rows)}")
    if approved_rows:
        print("approved_begin")
        for row in approved_rows:
            print(row)
        print("approved_end")
    if skipped_rows:
        print("skipped_begin")
        for row in skipped_rows:
            print(row)
        print("skipped_end")
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
