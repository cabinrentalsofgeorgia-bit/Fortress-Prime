#!/usr/bin/env python3
"""
List saturation-batch cabins currently awaiting human review.
"""
from __future__ import annotations

import asyncio
import json
import sys
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


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


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
    target_ids = _load_target_ids(Path(DEFAULT_TARGET_LIST_PATH))
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SEOPatch, Property.slug, Property.name)
                .join(Property, Property.id == SEOPatch.property_id)
                .where(
                    SEOPatch.property_id.in_(target_ids),
                    SEOPatch.status == "pending_human",
                )
                .order_by(Property.slug.asc(), SEOPatch.created_at.desc())
            )
        ).all()

    print("[pending-cabins] saturation review order")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"pending_human_count={len(rows)}")
    for patch, slug, name in rows:
        score = f"{float(patch.godhead_score or 0.0):.3f}" if patch.godhead_score is not None else "-"
        print(
            " | ".join(
                [
                    f"slug={slug}",
                    f"property_name={name}",
                    f"score={score}",
                    f"patch_id={patch.id}",
                    f"created_at={patch.created_at}",
                    f"reviewed_at={patch.reviewed_at}",
                ]
            )
        )
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
