#!/usr/bin/env python3
"""
Backfill surviving legacy property SEO overlays into canonical seo_patches.

Scope:
- Migrates only `seo_patch_queue` rows with `target_type='property'`
- Leaves `archive_review` rows on the temporary legacy read-through bridge
- Defaults to dry-run; pass `--apply` to persist inserts
"""

from __future__ import annotations

import argparse
import asyncio
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
from backend.models import Property, SEOPatch, SEORubric, SeoPatchQueue


@dataclass
class BackfillCandidate:
    legacy_id: str
    property_slug: str
    canonical_status: str
    page_path: str
    final_payload: dict[str, Any]
    legacy_status: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill legacy property seo_patch_queue rows into canonical seo_patches.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist inserts. Defaults to dry-run preview.",
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Restrict migration to a single property slug.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of legacy rows to inspect.",
    )
    return parser.parse_args()


def _normalize_legacy_payload(payload: dict[str, Any] | None, patch: SeoPatchQueue) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    title = str(source.get("title") or patch.proposed_title or "").strip()
    meta_description = str(
        source.get("meta_description") or patch.proposed_meta_description or ""
    ).strip()
    h1 = str(
        source.get("h1") or source.get("h1_suggestion") or patch.proposed_h1 or ""
    ).strip()
    intro = str(source.get("intro") or patch.proposed_intro or "").strip()
    faq = source.get("faq") if isinstance(source.get("faq"), list) else (patch.proposed_faq or [])
    json_ld = (
        source.get("json_ld")
        if isinstance(source.get("json_ld"), dict)
        else source.get("jsonld")
        if isinstance(source.get("jsonld"), dict)
        else patch.proposed_json_ld
        if isinstance(patch.proposed_json_ld, dict)
        else {}
    )

    normalized: dict[str, Any] = {
        "title": title,
        "meta_description": meta_description,
        "h1_suggestion": h1,
        "intro": intro,
        "faq": faq,
        "jsonld": json_ld,
    }
    for optional_key in ("canonical_url", "og_title", "og_description", "alt_tags"):
        value = source.get(optional_key)
        if value is not None:
            normalized[optional_key] = value
    return normalized


def _build_page_path(property_slug: str) -> str:
    return f"/cabins/{property_slug.strip().lower()}"


def _build_canonical_url(property_slug: str) -> str:
    return f"{settings.storefront_base_url.rstrip('/')}{_build_page_path(property_slug)}"


def _build_final_payload(property_slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": payload.get("title") or "",
        "meta_description": payload.get("meta_description") or "",
        "og_title": payload.get("og_title"),
        "og_description": payload.get("og_description"),
        "h1_suggestion": payload.get("h1_suggestion") or "",
        "jsonld": payload.get("jsonld") if isinstance(payload.get("jsonld"), dict) else {},
        "canonical_url": payload.get("canonical_url") or _build_canonical_url(property_slug),
        "alt_tags": payload.get("alt_tags") if isinstance(payload.get("alt_tags"), dict) else {},
    }


def _canonical_status_for_legacy(patch: SeoPatchQueue) -> str:
    if patch.status == "deployed" or patch.deployed_at is not None:
        return "deployed"
    return "approved"


async def _resolve_active_rubric_id() -> Any:
    async with AsyncSessionLocal() as db:
        rubric = (
            await db.execute(
                select(SEORubric)
                .where(SEORubric.status == "active")
                .order_by(SEORubric.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return rubric.id if rubric is not None else None


async def _load_candidates(args: argparse.Namespace) -> list[tuple[SeoPatchQueue, Property]]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(SeoPatchQueue, Property)
            .join(Property, Property.id == SeoPatchQueue.property_id)
            .where(
                SeoPatchQueue.target_type == "property",
                SeoPatchQueue.status.in_(("approved", "deployed")),
            )
            .order_by(
                Property.slug.asc(),
                SeoPatchQueue.deployed_at.desc(),
                SeoPatchQueue.approved_at.desc(),
                SeoPatchQueue.updated_at.desc(),
            )
        )
        if args.slug:
            stmt = stmt.where(Property.slug == args.slug.strip().lower())
        if args.limit:
            stmt = stmt.limit(args.limit)
        return list((await db.execute(stmt)).all())


async def _has_matching_canonical_patch(
    property_id: Any,
    final_payload: dict[str, Any],
    canonical_status: str,
) -> bool:
    async with AsyncSessionLocal() as db:
        existing_rows = (
            await db.execute(
                select(SEOPatch)
                .where(SEOPatch.property_id == property_id)
                .order_by(SEOPatch.updated_at.desc())
            )
        ).scalars().all()
        for row in existing_rows:
            if row.status not in {"approved", "edited", "deployed"}:
                continue
            if row.final_payload != final_payload:
                continue
            if canonical_status == "deployed" and row.status != "deployed":
                continue
            return True
        return False


async def _insert_candidate(
    patch: SeoPatchQueue,
    property_row: Property,
    rubric_id: Any,
    final_payload: dict[str, Any],
    canonical_status: str,
) -> None:
    async with AsyncSessionLocal() as db:
        deployed = canonical_status == "deployed"
        reviewed_at = patch.approved_at or patch.deployed_at
        record = SEOPatch(
            property_id=property_row.id,
            rubric_id=rubric_id,
            page_path=_build_page_path(property_row.slug),
            patch_version=1,
            title=str(final_payload.get("title") or "") or None,
            meta_description=str(final_payload.get("meta_description") or "") or None,
            og_title=str(final_payload.get("og_title") or "").strip() or None,
            og_description=str(final_payload.get("og_description") or "").strip() or None,
            jsonld_payload=final_payload.get("jsonld") if isinstance(final_payload.get("jsonld"), dict) else {},
            canonical_url=str(final_payload.get("canonical_url") or "").strip() or _build_canonical_url(property_row.slug),
            h1_suggestion=str(final_payload.get("h1_suggestion") or "").strip() or None,
            alt_tags=final_payload.get("alt_tags") if isinstance(final_payload.get("alt_tags"), dict) else {},
            godhead_score=1.0 if deployed else None,
            godhead_model="legacy-seo-patch-queue-backfill",
            godhead_feedback={"legacy_queue_id": str(patch.id), "backfilled": True},
            grade_attempts=1 if deployed else 0,
            status=canonical_status,
            reviewed_by=patch.reviewed_by or "legacy-seo-patch-queue-backfill",
            reviewed_at=reviewed_at,
            final_payload=final_payload,
            deployed_at=patch.deployed_at if deployed else None,
            deploy_status="succeeded" if deployed else None,
            deploy_queued_at=patch.approved_at if deployed else None,
            deploy_acknowledged_at=patch.deployed_at if deployed else None,
            deploy_attempts=1 if deployed else 0,
            deploy_last_error=None,
            deploy_last_http_status=200 if deployed else None,
            swarm_model="legacy-seo-patch-queue-backfill",
            swarm_node="migration-script",
            generation_ms=None,
        )
        db.add(record)
        await db.commit()


async def _run(args: argparse.Namespace) -> int:
    rubric_id = await _resolve_active_rubric_id()
    rows = await _load_candidates(args)
    if not rows:
        print("No legacy property SEO rows matched the requested scope.")
        return 0

    candidates: list[BackfillCandidate] = []
    skipped_duplicates = 0
    inserted = 0

    for patch, property_row in rows:
        normalized_payload = _normalize_legacy_payload(patch.approved_payload, patch)
        final_payload = _build_final_payload(property_row.slug, normalized_payload)
        canonical_status = _canonical_status_for_legacy(patch)

        duplicate = await _has_matching_canonical_patch(
            property_row.id,
            final_payload,
            canonical_status,
        )
        if duplicate:
            skipped_duplicates += 1
            continue

        candidate = BackfillCandidate(
            legacy_id=str(patch.id),
            property_slug=property_row.slug,
            canonical_status=canonical_status,
            page_path=_build_page_path(property_row.slug),
            final_payload=final_payload,
            legacy_status=patch.status,
        )
        candidates.append(candidate)

        if args.apply:
            await _insert_candidate(
                patch,
                property_row,
                rubric_id,
                final_payload,
                canonical_status,
            )
            inserted += 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] inspected={len(rows)} candidates={len(candidates)} skipped_duplicates={skipped_duplicates}")
    for candidate in candidates[:20]:
        print(
            f"- slug={candidate.property_slug} legacy={candidate.legacy_status} "
            f"canonical={candidate.canonical_status} path={candidate.page_path} legacy_id={candidate.legacy_id}"
        )
    if len(candidates) > 20:
        print(f"... {len(candidates) - 20} additional candidate(s) not shown")
    if args.apply:
        print(f"Inserted {inserted} canonical seo_patches row(s).")
    else:
        print("No rows inserted. Re-run with --apply to persist.")
    return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
