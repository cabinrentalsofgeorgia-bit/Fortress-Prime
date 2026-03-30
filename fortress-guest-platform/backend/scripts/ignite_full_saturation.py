#!/usr/bin/env python3
"""
Ignite full SEO saturation for properties missing canonical seo_patches rows.

Flow:
1. Refresh the dispatcher-derived swarm target list when possible.
2. Identify every active property without a canonical SEOPatch row.
3. Emit a filtered swarm target list for just the missing properties.
4. Launch the existing DGX swarm worker against that filtered list.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env.security")

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models import Property, SEOPatch
from backend.scripts import dispatch_swarm_targets
from backend.scripts.run_dgx_swarm_worker import (
    DEFAULT_LEGACY_PROXY_BASE_URL,
    DEFAULT_SEO_PATCH_API_BASE_URL,
    DEFAULT_TARGET_LIST_PATH,
    WorkerConfig,
    run_worker,
)


@dataclass(frozen=True)
class PropertyRow:
    property_id: str
    slug: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue DGX SEO saturation for active properties missing canonical seo_patches rows.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only write the filtered swarm target list; do not launch the worker.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Launch the worker in dry-run mode after preparing the target list.",
    )
    return parser.parse_args()


async def _load_active_properties() -> list[PropertyRow]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Property.id, Property.slug)
            .where(
                Property.is_active.is_(True),
                Property.slug.is_not(None),
            )
            .order_by(Property.slug.asc())
        )
        rows: list[PropertyRow] = []
        for property_id, slug in result.all():
            slug_value = str(slug or "").strip().lower()
            if not slug_value:
                continue
            rows.append(PropertyRow(property_id=str(property_id), slug=slug_value))
        return rows


async def _load_property_ids_with_canonical_patches() -> set[str]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SEOPatch.property_id)
            .where(SEOPatch.property_id.is_not(None))
            .distinct()
        )
        return {str(property_id) for (property_id,) in result.all() if property_id is not None}


def _derive_keyword(slug: str) -> str:
    return f"luxury cabin {slug.replace('-', ' ')} blue ridge"


def _fallback_target(row: PropertyRow) -> dict[str, Any]:
    return {
        "property_id": row.property_id,
        "slug": row.slug,
        "target_keyword": _derive_keyword(row.slug),
        "source_type": "property_ledger",
        "source_alias": f"cabins/{row.slug}",
    }


async def _refresh_dispatcher_targets(target_list_path: Path) -> dict[str, dict[str, Any]]:
    try:
        await dispatch_swarm_targets.main()
    except Exception as exc:
        print(f"[WARN] dispatcher refresh failed: {type(exc).__name__}: {exc}")

    if not target_list_path.exists():
        return {}

    payload = json.loads(target_list_path.read_text(encoding="utf-8"))
    targets = payload.get("targets", [])
    by_property_id: dict[str, dict[str, Any]] = {}
    for target in targets:
        property_id = str(target.get("property_id") or "").strip()
        slug = str(target.get("slug") or "").strip().lower()
        source_alias = str(target.get("source_alias") or "").strip().strip("/")
        if not property_id or not slug or not source_alias:
            continue
        by_property_id[property_id] = {
            "property_id": property_id,
            "slug": slug,
            "target_keyword": str(target.get("target_keyword") or _derive_keyword(slug)).strip(),
            "source_type": str(target.get("source_type") or "dispatcher"),
            "source_alias": source_alias,
        }
    return by_property_id


def _build_worker_config(target_list_path: Path, dry_run: bool, target_count: int) -> WorkerConfig:
    return WorkerConfig(
        target_list_path=target_list_path,
        storefront_base_url=settings.storefront_base_url.rstrip("/"),
        legacy_proxy_base_url=os.getenv("LEGACY_PROXY_BASE_URL", DEFAULT_LEGACY_PROXY_BASE_URL).rstrip("/"),
        seo_patch_api_base_url=os.getenv(
            "SEO_PATCH_API_BASE_URL",
            DEFAULT_SEO_PATCH_API_BASE_URL,
        ).rstrip("/"),
        swarm_api_key=os.getenv("SWARM_API_KEY", settings.swarm_api_key).strip(),
        max_targets=target_count,
        rubric_version=os.getenv("SWARM_RUBRIC_VERSION", "godhead-v1"),
        campaign=os.getenv("SWARM_CAMPAIGN", "full-saturation"),
        dry_run=dry_run,
    )


async def _prepare_targets(target_list_path: Path) -> list[dict[str, Any]]:
    dispatcher_targets = await _refresh_dispatcher_targets(target_list_path)
    active_properties = await _load_active_properties()
    patched_property_ids = await _load_property_ids_with_canonical_patches()

    missing_rows = [row for row in active_properties if row.property_id not in patched_property_ids]
    prepared_targets: list[dict[str, Any]] = []
    dispatcher_matches = 0
    fallback_matches = 0

    for row in missing_rows:
        dispatcher_target = dispatcher_targets.get(row.property_id)
        if dispatcher_target is not None:
            prepared_targets.append(dispatcher_target)
            dispatcher_matches += 1
        else:
            prepared_targets.append(_fallback_target(row))
            fallback_matches += 1

    payload = {
        "source": "ignite_full_saturation",
        "summary": {
            "active_properties": len(active_properties),
            "properties_with_canonical_patch": len(patched_property_ids),
            "properties_missing_canonical_patch": len(missing_rows),
            "dispatcher_matches": dispatcher_matches,
            "fallback_matches": fallback_matches,
        },
        "targets": prepared_targets,
    }
    target_list_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("Ignite full saturation target list prepared.")
    print(f"Active properties: {len(active_properties)}")
    print(f"Existing canonical patches: {len(patched_property_ids)}")
    print(f"Missing canonical patches: {len(missing_rows)}")
    print(f"Dispatcher-backed targets: {dispatcher_matches}")
    print(f"Fallback targets: {fallback_matches}")
    print(f"Target list path: {target_list_path}")

    return prepared_targets


async def _run(args: argparse.Namespace) -> int:
    target_list_path = Path(os.getenv("SWARM_TARGET_LIST_PATH", DEFAULT_TARGET_LIST_PATH))
    prepared_targets = await _prepare_targets(target_list_path)
    if not prepared_targets:
        print("No missing property SEO targets found. Saturation not required.")
        return 0

    if args.prepare_only:
        print("Prepare-only mode complete. Worker launch skipped.")
        return 0

    worker_cfg = _build_worker_config(
        target_list_path=target_list_path,
        dry_run=bool(args.dry_run),
        target_count=len(prepared_targets),
    )
    await run_worker(worker_cfg)
    return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
