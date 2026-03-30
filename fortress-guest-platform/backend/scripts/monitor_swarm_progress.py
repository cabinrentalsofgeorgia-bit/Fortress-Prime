#!/usr/bin/env python3
"""
Monitor DGX swarm progress for the current saturation target list.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
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


FIRST_LIGHT_STATUSES = ("approved", "deployed")
IN_FLIGHT_STATUSES = ("drafted", "needs_rewrite", "pending_human", "approved", "edited", "deployed")


@dataclass(frozen=True)
class TargetRow:
    property_id: UUID
    slug: str
    source_alias: str
    target_keyword: str


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor current DGX swarm progress for the saturation target list.",
    )
    parser.add_argument(
        "--target-list-path",
        type=Path,
        default=Path(DEFAULT_TARGET_LIST_PATH),
        help=f"Target list JSON path. Defaults to {DEFAULT_TARGET_LIST_PATH}",
    )
    parser.add_argument(
        "--show-targets",
        type=int,
        default=23,
        help="How many target rows to print in the detailed section.",
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
        rows.append(
            TargetRow(
                property_id=UUID(property_id),
                slug=slug,
                source_alias=_normalize_text(target.get("source_alias")),
                target_keyword=_normalize_text(target.get("target_keyword")),
            )
        )
    return rows


def _format_ts(value: object) -> str:
    if value is None:
        return "-"
    return _normalize_text(value)


async def _run() -> int:
    args = _parse_args()
    target_list_path = Path(args.target_list_path).expanduser().resolve()
    targets = _load_targets(target_list_path)
    if not targets:
        print("[info] target list is empty")
        return 0

    property_ids = [target.property_id for target in targets]
    async with AsyncSessionLocal() as session:
        property_rows = (
            await session.execute(select(Property).where(Property.id.in_(property_ids)))
        ).scalars().all()
        patch_rows = (
            await session.execute(
                select(SEOPatch)
                .where(SEOPatch.property_id.in_(property_ids))
                .order_by(SEOPatch.property_id.asc(), SEOPatch.created_at.desc(), SEOPatch.patch_version.desc())
            )
        ).scalars().all()

    property_by_id = {prop.id: prop for prop in property_rows}
    latest_patch_by_property_id: dict[UUID, SEOPatch] = {}
    for patch in patch_rows:
        if patch.property_id is None:
            continue
        latest_patch_by_property_id.setdefault(patch.property_id, patch)

    status_counts: Counter[str] = Counter()
    lines: list[str] = []
    first_light_rows: list[str] = []

    for target in targets:
        prop = property_by_id.get(target.property_id)
        patch = latest_patch_by_property_id.get(target.property_id)
        if patch is None:
            status = "awaiting_generation"
        else:
            status = _normalize_text(patch.status) or "unknown"
        status_counts[status] += 1

        property_name = _normalize_text(prop.name) if prop is not None else target.slug
        is_active = bool(prop.is_active) if prop is not None else False
        patch_id = str(patch.id) if patch is not None else "-"
        score = f"{patch.godhead_score:.3f}" if patch is not None and patch.godhead_score is not None else "-"
        created_at = _format_ts(patch.created_at if patch is not None else None)
        reviewed_at = _format_ts(patch.reviewed_at if patch is not None else None)
        deployed_at = _format_ts(patch.deployed_at if patch is not None else None)

        lines.append(
            " | ".join(
                [
                    f"slug={target.slug}",
                    f"property_name={property_name}",
                    f"status={status}",
                    f"active={str(is_active).lower()}",
                    f"score={score}",
                    f"patch_id={patch_id}",
                    f"created_at={created_at}",
                    f"reviewed_at={reviewed_at}",
                    f"deployed_at={deployed_at}",
                ]
            )
        )

        if status in FIRST_LIGHT_STATUSES and patch is not None:
            first_light_rows.append(
                " | ".join(
                    [
                        f"slug={target.slug}",
                        f"status={status}",
                        f"score={score}",
                        f"reviewed_at={reviewed_at}",
                        f"patch_id={patch_id}",
                    ]
                )
            )

    in_flight = sum(status_counts.get(status, 0) for status in IN_FLIGHT_STATUSES)
    completed = status_counts.get("deployed", 0)
    waiting = status_counts.get("awaiting_generation", 0)

    print("[swarm-monitor] saturation progress")
    print(f"target_list_path={target_list_path}")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"targets={len(targets)}")
    print(f"in_flight={in_flight}")
    print(f"completed={completed}")
    print(f"awaiting_generation={waiting}")
    print("status_counts=" + json.dumps(dict(sorted(status_counts.items())), sort_keys=True))

    if first_light_rows:
        print("first_light=YES")
        for row in first_light_rows:
            print(f"[first-light] {row}")
    else:
        print("first_light=NO")

    limit = max(int(args.show_targets), 0)
    if limit:
        print("targets_detail_begin")
        for row in lines[:limit]:
            print(row)
        print("targets_detail_end")

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
