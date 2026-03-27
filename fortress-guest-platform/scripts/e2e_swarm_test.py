#!/usr/bin/env python3
"""
Standalone live E2E ignition script for the SEO Swarm.

Flow:
1. Load backend env and DB dependencies.
2. Select one active property from local Postgres.
3. Trigger generate_initial_seo_draft(property_id).
4. Poll the resulting SEOPatch and stream status transitions.
5. Print final God Head score, feedback, and JSON-LD payload.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env.security")


def _require_fortress_postgres_contract() -> None:
    postgres_api_uri = os.getenv("POSTGRES_API_URI", "").strip()
    postgres_admin_uri = os.getenv("POSTGRES_ADMIN_URI", "").strip()
    legacy_database_url = os.getenv("DATABASE_URL", "").strip()

    if postgres_api_uri and postgres_admin_uri:
        return

    detail = (
        "Standalone swarm ignition requires POSTGRES_API_URI and POSTGRES_ADMIN_URI "
        "for the local Fortress Prime PostgreSQL 16 contract."
    )
    if legacy_database_url:
        detail = (
            f"{detail} Found legacy DATABASE_URL, but the swarm runtime will not "
            "use it because the current architecture requires explicit fortress_api "
            "and fortress_admin lanes on 127.0.0.1:5432."
        )
    raise RuntimeError(detail)


_require_fortress_postgres_contract()

from backend.core.database import AsyncSessionLocal  # noqa: E402
from backend.models.property import Property  # noqa: E402
from backend.models.seo_patch import SEOPatch, SEORubric  # noqa: E402
from backend.services.seo_extraction_service import generate_initial_seo_draft  # noqa: E402

POLL_INTERVAL_SECONDS = 2.0
MAX_WAIT_SECONDS = 180.0
TERMINAL_STATES = {"pending_human", "needs_rewrite", "failed", "deployed"}


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=str)


async def _select_active_property_id() -> tuple[UUID, str, str]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Property.id, Property.slug, Property.name)
            .where(Property.is_active == True)  # noqa: E712
            .order_by(Property.created_at.asc())
            .limit(1)
        )
        row = (await db.execute(stmt)).one_or_none()
        if row is None:
            raise RuntimeError("No active property found in local Postgres.")
        property_id, slug, name = row
        return property_id, str(slug), str(name)


async def _load_patch(patch_id: UUID) -> SEOPatch:
    async with AsyncSessionLocal() as db:
        patch = await db.get(SEOPatch, patch_id)
        if patch is None:
            raise RuntimeError(f"SEOPatch {patch_id} was not found after draft generation.")
        return patch


async def _ensure_active_rubric() -> UUID:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(SEORubric)
            .where(SEORubric.status == "active")
            .order_by(SEORubric.created_at.desc())
            .limit(1)
        )
        rubric = (await db.execute(stmt)).scalar_one_or_none()
        if rubric is not None:
            rubric_payload = rubric.rubric_payload if isinstance(rubric.rubric_payload, dict) else {}
            criteria = rubric_payload.get("criteria")
            normalized_payload = {
                **rubric_payload,
                "criteria": criteria
                if isinstance(criteria, list) and criteria
                else [
                    "title present",
                    "meta_description present",
                    "jsonld present",
                    "alt_tags present",
                ],
                "frontier_route": "local",
            }
            if rubric.rubric_payload != normalized_payload:
                rubric.rubric_payload = normalized_payload
                await db.commit()
                await db.refresh(rubric)
                print(f"[BOOT] Updated active rubric {rubric.id} to local God Head route")
            return rubric.id

        rubric = SEORubric(
            keyword_cluster="legacy-property-seo",
            rubric_payload={
                "criteria": [
                    "title present",
                    "meta_description present",
                    "jsonld present",
                    "alt_tags present",
                ],
                "frontier_route": "local",
            },
            source_model="e2e_swarm_test",
            min_pass_score=0.95,
            status="active",
        )
        db.add(rubric)
        await db.commit()
        await db.refresh(rubric)
        print(f"[BOOT] Seeded active rubric {rubric.id}")
        return rubric.id


def _print_status(status: str) -> None:
    if status == "drafted":
        print("[SWARM] Drafted payload...")
    elif status == "grading":
        print("[GOD HEAD] Grading in progress...")
    else:
        print(f"[STATE CHANGE] -> {status}")


async def main() -> None:
    await _ensure_active_rubric()
    property_id, slug, name = await _select_active_property_id()
    print(f"[BOOT] Selected property: {name} ({slug}) [{property_id}]")
    print("[SWARM] Triggering generate_initial_seo_draft(...)")

    result = await generate_initial_seo_draft(property_id)
    if not result or not result.get("patch_id"):
        raise RuntimeError("SEO extraction service did not return a patch_id.")

    patch_id = UUID(str(result["patch_id"]))
    print(f"[SWARM] Drafted payload for patch {patch_id}")
    print("[REDIS] Enqueued to fortress:seo:grade_requests...")

    elapsed = 0.0
    last_status: str | None = None
    final_patch: SEOPatch | None = None

    while elapsed <= MAX_WAIT_SECONDS:
        patch = await _load_patch(patch_id)
        final_patch = patch
        if patch.status != last_status:
            _print_status(patch.status)
            last_status = patch.status

        if patch.status in TERMINAL_STATES:
            break

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    if final_patch is None:
        raise RuntimeError("Polling loop exited before any patch state was loaded.")

    if final_patch.status not in TERMINAL_STATES:
        raise RuntimeError(
            f"Timed out after {MAX_WAIT_SECONDS:.0f}s waiting for terminal state. "
            f"Current status: {final_patch.status}"
        )

    jsonld_payload = final_patch.jsonld_payload or {}
    schema_context = jsonld_payload.get("@context")
    schema_type = jsonld_payload.get("@type")
    if schema_context != "https://schema.org":
        raise AssertionError(f"Expected @context=https://schema.org, got {schema_context!r}")
    if schema_type not in {"VacationRental", "LodgingBusiness"}:
        raise AssertionError(f"Unexpected schema @type: {schema_type!r}")

    print("")
    print("[FINAL] godhead_score:")
    print(final_patch.godhead_score)
    print("")
    print("[FINAL] godhead_feedback:")
    print(_pretty_json(final_patch.godhead_feedback or {}))
    if (final_patch.godhead_feedback or {}).get("mode") == "deterministic_fallback":
        raise AssertionError("Expected live God Head evaluation, got deterministic fallback feedback.")
    print("")
    print("[FINAL] jsonld_payload:")
    print(_pretty_json(jsonld_payload))
    print("")
    print(f"[ASSERT] @context={schema_context} @type={schema_type}")


if __name__ == "__main__":
    asyncio.run(main())
