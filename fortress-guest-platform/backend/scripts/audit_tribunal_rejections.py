#!/usr/bin/env python3
"""
Audit God-Head rejection feedback for the current saturation batch.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit needs_rewrite tribunal feedback for the current saturation batch.",
    )
    parser.add_argument(
        "--target-list-path",
        type=Path,
        default=Path(DEFAULT_TARGET_LIST_PATH),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max detailed rows to print.",
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


def _collect_messages(feedback: dict[str, object], key: str) -> list[str]:
    value = feedback.get(key)
    if isinstance(value, list):
        return [_normalize_text(item) for item in value if _normalize_text(item)]
    return []


async def _run() -> int:
    args = _parse_args()
    target_ids = _load_target_ids(Path(args.target_list_path).expanduser().resolve())

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SEOPatch, Property.slug, Property.name)
                .join(Property, Property.id == SEOPatch.property_id)
                .where(
                    SEOPatch.property_id.in_(target_ids),
                    SEOPatch.status == "needs_rewrite",
                )
                .order_by(Property.slug.asc(), SEOPatch.created_at.desc())
            )
        ).all()

    critical_counter: Counter[str] = Counter()
    moderate_counter: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()
    score_buckets: Counter[str] = Counter()
    schema_issue_count = 0
    alt_tag_issue_count = 0

    detailed: list[str] = []
    for patch, slug, name in rows:
        feedback = patch.godhead_feedback if isinstance(patch.godhead_feedback, dict) else {}
        criticals = _collect_messages(feedback, "critical_failures")
        moderates = _collect_messages(feedback, "moderate_issues")
        for item in criticals:
            critical_counter[item] += 1
            lowered = item.lower()
            if "schema" in lowered or "json-ld" in lowered:
                schema_issue_count += 1
            if "alt tag" in lowered or "alt_tags" in lowered:
                alt_tag_issue_count += 1
        for item in moderates:
            moderate_counter[item] += 1

        model_counter[_normalize_text(patch.godhead_model) or "unknown"] += 1
        score_value = float(patch.godhead_score or 0.0)
        if score_value >= 0.8:
            score_buckets["0.80-0.89"] += 1
        elif score_value >= 0.75:
            score_buckets["0.75-0.79"] += 1
        elif score_value >= 0.7:
            score_buckets["0.70-0.74"] += 1
        else:
            score_buckets["<0.70"] += 1

        detailed.append(
            json.dumps(
                {
                    "slug": slug,
                    "property_name": name,
                    "score": patch.godhead_score,
                    "grade_attempts": patch.grade_attempts,
                    "model": patch.godhead_model,
                    "critical_failures": criticals,
                    "moderate_issues": moderates,
                },
                ensure_ascii=True,
            )
        )

    print("[tribunal-audit] rejection summary")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"needs_rewrite_count={len(rows)}")
    print("score_buckets=" + json.dumps(dict(score_buckets), sort_keys=True))
    print("models=" + json.dumps(dict(model_counter), sort_keys=True))
    print(f"schema_issue_mentions={schema_issue_count}")
    print(f"alt_tag_issue_mentions={alt_tag_issue_count}")
    print("top_critical_failures=" + json.dumps(critical_counter.most_common(10), ensure_ascii=True))
    print("top_moderate_issues=" + json.dumps(moderate_counter.most_common(10), ensure_ascii=True))
    print("detailed_rows_begin")
    for line in detailed[: max(int(args.limit), 0)]:
        print(line)
    print("detailed_rows_end")
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
