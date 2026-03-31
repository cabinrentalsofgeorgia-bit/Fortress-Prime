#!/usr/bin/env python3
"""
Audit and apply Channex listing IDs for the current live property set.

Usage examples:

  python -m backend.scripts.channex_property_wiring --write-template backend/artifacts/channex_mappings.template.json
  python -m backend.scripts.channex_property_wiring --mapping-file ./mappings.json --apply --verify

The script uses the current Streamline property list as the authoritative set of
"currently live" cabins, then matches those against local ``properties`` rows by
``streamline_property_id`` or name.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from dotenv import load_dotenv
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal, close_db, init_db
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.services.channex_calendar_export import build_channex_availability_document
from backend.services.channex_sync import merge_channex_listing_metadata


def load_environment() -> None:
    for env_file in (
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
        PROJECT_ROOT / ".env.dgx",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wire current live properties to Channex listing IDs.")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        help="JSON mapping file with entries containing channex_listing_id plus one of: slug, streamline_property_id, or name.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the provided mapping file into properties.ota_metadata.channex_listing_id.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify each mapped property can build a Channex availability document.",
    )
    parser.add_argument(
        "--write-template",
        type=Path,
        help="Write a JSON template for the current live property set.",
    )
    return parser.parse_args()


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


async def _load_current_streamline_properties(vrs: StreamlineVRS) -> list[dict[str, str]]:
    data = await vrs._call("GetPropertyList")
    raw_props = data.get("property", []) if isinstance(data, dict) else []
    if isinstance(raw_props, dict):
        raw_props = [raw_props]
    return [
        {
            "streamline_property_id": str(prop.get("id", "")).strip(),
            "name": str(prop.get("name", "")).strip(),
            "city": str(prop.get("city", "")).strip(),
        }
        for prop in raw_props
    ]


async def _load_local_properties() -> list[Property]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Property)
            .where(Property.is_active.is_(True))
            .where(Property.streamline_property_id.isnot(None))
            .order_by(Property.name)
        )
        return list(result.scalars().all())


def _build_audit_rows(
    streamline_props: list[dict[str, str]],
    local_props: list[Property],
) -> list[dict[str, Any]]:
    by_streamline = {_norm(prop.streamline_property_id): prop for prop in local_props}
    by_name = {_norm(prop.name): prop for prop in local_props}

    rows: list[dict[str, Any]] = []
    for sp in streamline_props:
        local = by_streamline.get(_norm(sp["streamline_property_id"])) or by_name.get(_norm(sp["name"]))
        rows.append(
            {
                "name": sp["name"],
                "city": sp["city"],
                "streamline_property_id": sp["streamline_property_id"],
                "local_property_id": str(local.id) if local else None,
                "slug": local.slug if local else None,
                "channex_listing_id": (
                    (local.ota_metadata or {}).get("channex_listing_id")
                    if local and isinstance(local.ota_metadata, dict)
                    else None
                ),
            }
        )
    return rows


def _write_template(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = [
        {
            "slug": row["slug"],
            "name": row["name"],
            "streamline_property_id": row["streamline_property_id"],
            "channex_listing_id": row["channex_listing_id"] or "",
        }
        for row in rows
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_mapping_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Mapping file must contain a JSON array")
    return payload


async def _apply_mappings(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Property)
            .where(Property.is_active.is_(True))
            .where(Property.streamline_property_id.isnot(None))
        )
        props = list(result.scalars().all())
        by_slug = {_norm(prop.slug): prop for prop in props}
        by_streamline = {_norm(prop.streamline_property_id): prop for prop in props}
        by_name = {_norm(prop.name): prop for prop in props}

        for item in mappings:
            listing_id = str(item.get("channex_listing_id", "")).strip()
            if not listing_id:
                continue
            prop = (
                by_slug.get(_norm(item.get("slug")))
                or by_streamline.get(_norm(item.get("streamline_property_id")))
                or by_name.get(_norm(item.get("name")))
            )
            if not prop:
                applied.append({"status": "unmatched", "mapping": item})
                continue

            prop.ota_metadata = merge_channex_listing_metadata(prop.ota_metadata, listing_id)
            applied.append(
                {
                    "status": "applied",
                    "property_id": str(prop.id),
                    "slug": prop.slug,
                    "streamline_property_id": prop.streamline_property_id,
                    "channex_listing_id": listing_id,
                }
            )

        await db.commit()
    return applied


async def _verify_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        for row in rows:
            property_id = row.get("local_property_id")
            listing_id = row.get("channex_listing_id")
            if not property_id or not listing_id:
                checks.append(
                    {
                        "slug": row.get("slug"),
                        "streamline_property_id": row.get("streamline_property_id"),
                        "status": "skipped",
                        "reason": "missing_property_or_listing_id",
                    }
                )
                continue
            document, skip_reason = await build_channex_availability_document(db, property_id)
            checks.append(
                {
                    "slug": row.get("slug"),
                    "streamline_property_id": row.get("streamline_property_id"),
                    "channex_listing_id": listing_id,
                    "status": "ok" if document and not skip_reason else "failed",
                    "skip_reason": skip_reason,
                    "days": len((document or {}).get("days") or []),
                }
            )
    return checks


async def async_main(args: argparse.Namespace) -> int:
    load_environment()
    await init_db()
    vrs = StreamlineVRS()
    try:
        streamline_props = await _load_current_streamline_properties(vrs)
        local_props = await _load_local_properties()
        audit_rows = _build_audit_rows(streamline_props, local_props)

        if args.write_template:
            _write_template(args.write_template, audit_rows)

        applied: list[dict[str, Any]] = []
        if args.mapping_file and args.apply:
            mappings = _load_mapping_file(args.mapping_file)
            applied = await _apply_mappings(mappings)
            local_props = await _load_local_properties()
            audit_rows = _build_audit_rows(streamline_props, local_props)

        verification: list[dict[str, Any]] = []
        if args.verify:
            verification = await _verify_rows(audit_rows)

        print(
            json.dumps(
                {
                    "current_live_property_count": len(streamline_props),
                    "mapped_count": sum(1 for row in audit_rows if row["channex_listing_id"]),
                    "unmapped_count": sum(1 for row in audit_rows if not row["channex_listing_id"]),
                    "properties": audit_rows,
                    "applied": applied,
                    "verification": verification,
                },
                indent=2,
            )
        )
        return 0
    finally:
        await vrs.close()
        await close_db()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
