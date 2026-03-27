#!/usr/bin/env python3
"""
Ingest legacy property catalog rows from the local CSV mapping into properties.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


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


DEFAULT_MAPPING_PATH = REPO_ROOT / "docs" / "legacy_streamline_id_map.csv"
DEFAULT_PROPERTY_TYPE = "cabin"
DEFAULT_BEDROOMS = 2
DEFAULT_BATHROOMS = Decimal("1.0")
DEFAULT_MAX_GUESTS = 6


@dataclass(frozen=True)
class CatalogRow:
    slug: str
    streamline_property_id: str
    title: str
    alias: str


@dataclass(frozen=True)
class IngestPlan:
    mapping_path: Path
    dry_run: bool


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_slug(value: object) -> str:
    return _normalize_text(value).lower().strip("/")


def _parse_args() -> IngestPlan:
    parser = argparse.ArgumentParser(
        description="Ingest missing legacy property catalog rows into properties.",
    )
    parser.add_argument(
        "--mapping-path",
        type=Path,
        default=DEFAULT_MAPPING_PATH,
        help=f"CSV mapping path. Defaults to {DEFAULT_MAPPING_PATH}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the upsert plan without committing changes.",
    )
    args = parser.parse_args()
    return IngestPlan(
        mapping_path=Path(args.mapping_path).expanduser().resolve(),
        dry_run=bool(args.dry_run),
    )


def _load_rows(mapping_path: Path) -> list[CatalogRow]:
    if not mapping_path.exists():
        raise FileNotFoundError(f"Mapping CSV not found: {mapping_path}")

    with mapping_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Mapping CSV is missing a header row: {mapping_path}")

        rows: list[CatalogRow] = []
        seen_keys: set[tuple[str, str]] = set()
        for index, raw_row in enumerate(reader, start=2):
            slug = _normalize_slug(raw_row.get("slug"))
            streamline_property_id = _normalize_text(raw_row.get("streamline_id"))
            title = _normalize_text(raw_row.get("title"))
            alias = _normalize_text(raw_row.get("alias")).strip("/")

            if not slug or not streamline_property_id or not title:
                raise ValueError(
                    f"Mapping CSV row {index} must include slug, streamline_id, and title."
                )

            dedupe_key = (slug, streamline_property_id)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            rows.append(
                CatalogRow(
                    slug=slug,
                    streamline_property_id=streamline_property_id,
                    title=title,
                    alias=alias,
                )
            )

    if not rows:
        raise ValueError(f"Mapping CSV is empty: {mapping_path}")
    return rows


async def _load_existing_properties(
    session: AsyncSession,
    rows: list[CatalogRow],
) -> tuple[dict[str, Property], dict[str, Property]]:
    slugs = sorted({row.slug for row in rows})
    streamline_ids = sorted({row.streamline_property_id for row in rows})

    result = await session.execute(
        select(Property).where(
            or_(
                Property.slug.in_(slugs),
                Property.streamline_property_id.in_(streamline_ids),
            )
        )
    )
    properties = result.scalars().all()

    by_slug: dict[str, Property] = {}
    by_streamline_id: dict[str, Property] = {}
    for prop in properties:
        slug = _normalize_slug(prop.slug)
        streamline_property_id = _normalize_text(prop.streamline_property_id)
        if slug:
            by_slug[slug] = prop
        if streamline_property_id:
            by_streamline_id[streamline_property_id] = prop

    return by_slug, by_streamline_id


def _build_new_property(row: CatalogRow) -> Property:
    return Property(
        name=row.title,
        slug=row.slug,
        property_type=DEFAULT_PROPERTY_TYPE,
        bedrooms=DEFAULT_BEDROOMS,
        bathrooms=DEFAULT_BATHROOMS,
        max_guests=DEFAULT_MAX_GUESTS,
        streamline_property_id=row.streamline_property_id,
        is_active=True,
    )


async def _run(plan: IngestPlan) -> int:
    rows = _load_rows(plan.mapping_path)

    async with AsyncSessionLocal() as session:
        by_slug, by_streamline_id = await _load_existing_properties(session, rows)

        conflicts: list[str] = []
        created = 0
        updated = 0
        unchanged = 0

        for row in rows:
            slug_match = by_slug.get(row.slug)
            streamline_match = by_streamline_id.get(row.streamline_property_id)

            if (
                slug_match is not None
                and streamline_match is not None
                and slug_match.id != streamline_match.id
            ):
                conflicts.append(
                    "Conflict for "
                    f"slug={row.slug} streamline_id={row.streamline_property_id}: "
                    f"slug maps to {slug_match.id}, streamline_id maps to {streamline_match.id}"
                )
                continue

            existing = slug_match or streamline_match
            if existing is None:
                prop = _build_new_property(row)
                session.add(prop)
                created += 1
                continue

            changed = False
            current_streamline_id = _normalize_text(existing.streamline_property_id)
            if current_streamline_id and current_streamline_id != row.streamline_property_id:
                conflicts.append(
                    "Identifier mismatch for "
                    f"slug={row.slug}: existing streamline_id={current_streamline_id}, "
                    f"csv streamline_id={row.streamline_property_id}"
                )
                continue

            if not current_streamline_id:
                existing.streamline_property_id = row.streamline_property_id
                changed = True

            if not existing.name.strip():
                existing.name = row.title
                changed = True

            if existing.is_active is not True:
                existing.is_active = True
                changed = True

            if changed:
                updated += 1
            else:
                unchanged += 1

        if conflicts:
            for conflict in conflicts:
                print(f"[conflict] {conflict}")
            await session.rollback()
            return 1

        if plan.dry_run:
            await session.rollback()
            print("[dry-run] legacy property ingestion plan prepared")
        else:
            await session.commit()
            print("[ok] legacy property ingestion committed")

        print(f"mapping_path={plan.mapping_path}")
        print(f"mapping_rows={len(rows)}")
        print(f"created={created}")
        print(f"updated={updated}")
        print(f"unchanged={unchanged}")
        print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
        return 0


async def amain() -> int:
    plan = _parse_args()
    try:
        return await _run(plan)
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
