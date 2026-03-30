#!/usr/bin/env python3
"""
Emergency-clear the current saturation batch for human review.
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

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.scripts.run_dgx_swarm_worker import DEFAULT_TARGET_LIST_PATH


ELIGIBLE_STATUSES = {"needs_rewrite"}


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move tribunal-rejected saturation patches into pending_human for manual salvage.",
    )
    parser.add_argument(
        "--target-list-path",
        type=Path,
        default=Path(DEFAULT_TARGET_LIST_PATH),
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.70,
        help="Emergency clearance score floor.",
    )
    parser.add_argument(
        "--reviewer",
        default="threshold-calibration-strike",
        help="Reviewer marker written onto cleared patches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the clearance set without committing.",
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
    min_score = float(args.min_score)
    reviewer = _normalize_text(args.reviewer) or "threshold-calibration-strike"

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SEOPatch, Property.slug)
                .join(Property, Property.id == SEOPatch.property_id)
                .where(SEOPatch.property_id.in_(target_ids))
                .order_by(Property.slug.asc(), SEOPatch.created_at.desc())
            )
        ).all()

        promoted: list[str] = []
        skipped: list[str] = []
        seen_patch_ids: set[UUID] = set()
        for patch, slug in rows:
            if patch.id in seen_patch_ids:
                continue
            seen_patch_ids.add(patch.id)

            status = _normalize_text(patch.status).lower()
            score = float(patch.godhead_score or 0.0)
            if status not in ELIGIBLE_STATUSES or score < min_score:
                skipped.append(
                    f"slug={slug} status={status or 'unknown'} score={score:.3f}"
                )
                continue

            feedback = patch.godhead_feedback if isinstance(patch.godhead_feedback, dict) else {}
            feedback["emergency_clearance"] = {
                "applied": True,
                "previous_status": patch.status,
                "previous_score": score,
                "clearance_threshold": min_score,
                "reviewer": reviewer,
                "cleared_at": datetime.now(timezone.utc).isoformat(),
                "reason": "Tribunal failures are primarily technical completeness gaps suitable for human salvage.",
            }
            patch.godhead_feedback = feedback
            patch.status = "pending_human"
            patch.reviewed_by = reviewer
            patch.reviewed_at = datetime.now(timezone.utc)
            promoted.append(
                f"slug={slug} status=pending_human score={score:.3f} patch_id={patch.id}"
            )

        if args.dry_run:
            await session.rollback()
            print("[dry-run] emergency clearance plan prepared")
        else:
            await session.commit()
            print("[ok] emergency clearance committed")

    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"eligible_statuses={','.join(sorted(ELIGIBLE_STATUSES))}")
    print(f"min_score={min_score:.3f}")
    print(f"promoted={len(promoted)}")
    print(f"skipped={len(skipped)}")
    if promoted:
        print("promoted_begin")
        for line in promoted:
            print(line)
        print("promoted_end")
    if skipped:
        print("skipped_begin")
        for line in skipped:
            print(line)
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
