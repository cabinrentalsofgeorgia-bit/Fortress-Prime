#!/usr/bin/env python3
"""
Temporary end-to-end smoke test for the Phase 1 SEO Swarm-to-Edge pipeline.

Flow:
1. Load a valid property + rubric + active admin from Postgres.
2. POST a drafted SEO patch to the live API on :8100.
3. GET the queue to verify the patch is visible.
4. Promote to pending_human for deterministic HITL approval.
5. POST approval through the live API.
6. GET /api/seo/live/{property_slug} and assert the payload matches.
7. Restore the prior deployed patch state so the smoke test does not leave
   permanent mock SEO live on the edge surface.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env.security")

from backend.core.config import settings
API_BASE = os.getenv("SEO_SMOKE_API_BASE", "http://127.0.0.1:8100").rstrip("/")
HTTP_TIMEOUT = httpx.Timeout(connect=10, read=60, write=30, pool=30)
SMOKE_PREFIX = "[seo-smoke]"
DEFAULT_E2E_EMAIL = "cabin.rentals.of.georgia@gmail.com"
DEFAULT_E2E_PASSWORD = "FortressPrime2026!"
DEPLOY_POLL_ATTEMPTS = 20
DEPLOY_POLL_INTERVAL_SECONDS = 0.5


@dataclass
class PropertyTarget:
    id: UUID
    slug: str
    name: str
    page_path: str


@dataclass
class StaffAuth:
    id: UUID
    email: str
    role: str
    bearer_token: str


@dataclass
class RubricTarget:
    id: UUID
    keyword_cluster: str


@dataclass
class PriorDeployedPatch:
    id: UUID
    status: str
    reviewed_by: str | None
    reviewed_at: Any
    final_payload: dict[str, Any] | None
    deployed_at: Any
    godhead_score: float | None
    godhead_model: str | None
    godhead_feedback: dict[str, Any] | None
    grade_attempts: int


class SmokeFailure(RuntimeError):
    pass


def normalize_asyncpg_dsn(value: str) -> str:
    normalized = (value or "").strip()
    if normalized.startswith("postgresql+asyncpg://"):
        return f"postgresql://{normalized.split('://', 1)[1]}"
    return normalized


def coerce_json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        require(isinstance(parsed, dict), "json-coerce", "expected JSON object payload")
        return parsed
    raise SmokeFailure(f"json-coerce: unsupported payload type {type(value)!r}")


def log_pass(step: str, detail: str) -> None:
    print(f"PASS {step}: {detail}")


def log_fail(step: str, detail: str) -> None:
    print(f"FAIL {step}: {detail}")


def require(condition: bool, step: str, detail: str) -> None:
    if not condition:
        raise SmokeFailure(f"{step}: {detail}")


async def fetch_property(conn: asyncpg.Connection) -> PropertyTarget:
    row = await conn.fetchrow(
        """
        SELECT id, slug, name
        FROM properties
        WHERE is_active = true
        ORDER BY CASE WHEN slug = 'aska-escape-lodge' THEN 0 ELSE 1 END, created_at ASC
        LIMIT 1
        """
    )
    require(row is not None, "db-property", "no active property found")
    return PropertyTarget(
        id=row["id"],
        slug=str(row["slug"]),
        name=str(row["name"]),
        page_path=f"/cabins/{row['slug']}",
    )


async def fetch_rubric(conn: asyncpg.Connection) -> RubricTarget:
    row = await conn.fetchrow(
        """
        SELECT id, keyword_cluster
        FROM seo_rubrics
        WHERE status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    require(row is not None, "db-rubric", "no active seo_rubrics row found")
    return RubricTarget(id=row["id"], keyword_cluster=str(row["keyword_cluster"]))


async def fetch_staff_auth(conn: asyncpg.Connection) -> StaffAuth:
    row = await conn.fetchrow(
        """
        SELECT id, email, role
        FROM staff_users
        WHERE is_active = true
          AND role IN ('admin', 'manager')
        ORDER BY created_at ASC
        LIMIT 1
        """
    )
    require(row is not None, "db-staff", "no active admin or manager user found")
    return StaffAuth(
        id=row["id"],
        email=str(row["email"]),
        role=str(row["role"]),
        bearer_token="",
    )


async def login_staff_auth(client: httpx.AsyncClient) -> StaffAuth:
    email = os.getenv("E2E_LOGIN_EMAIL", DEFAULT_E2E_EMAIL).strip()
    password = os.getenv("E2E_LOGIN_PASSWORD", DEFAULT_E2E_PASSWORD)
    response = await api_post(
        client,
        "/api/auth/login",
        {"email": email, "password": password},
        headers={"Content-Type": "application/json"},
    )
    require(response.status_code == 200, "auth-review", f"unexpected status {response.status_code}: {response.text}")
    payload = response.json()
    user = payload.get("user") or {}
    token = str(payload.get("access_token") or "").strip()
    require(bool(token), "auth-review", "login response did not include access_token")
    return StaffAuth(
        id=UUID(str(user.get("id"))) if user.get("id") else UUID("00000000-0000-0000-0000-000000000000"),
        email=str(user.get("email") or email),
        role=str(user.get("role") or "authenticated"),
        bearer_token=token,
    )


async def fetch_prior_deployed_patch(
    conn: asyncpg.Connection,
    property_id: UUID,
) -> PriorDeployedPatch | None:
    row = await conn.fetchrow(
        """
        SELECT
            id,
            status,
            reviewed_by,
            reviewed_at,
            final_payload,
            deployed_at,
            godhead_score,
            godhead_model,
            godhead_feedback,
            grade_attempts
        FROM seo_patches
        WHERE property_id = $1
          AND status = 'deployed'
        ORDER BY deployed_at DESC NULLS LAST, updated_at DESC
        LIMIT 1
        """,
        property_id,
    )
    if row is None:
        return None
    return PriorDeployedPatch(
        id=row["id"],
        status=str(row["status"]),
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        final_payload=coerce_json_object(row["final_payload"]),
        deployed_at=row["deployed_at"],
        godhead_score=row["godhead_score"],
        godhead_model=row["godhead_model"],
        godhead_feedback=coerce_json_object(row["godhead_feedback"]),
        grade_attempts=int(row["grade_attempts"] or 0),
    )


async def promote_for_hitl(conn: asyncpg.Connection, patch_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE seo_patches
        SET
            status = 'pending_human',
            godhead_score = 0.99,
            godhead_model = 'seo-smoke-godhead',
            godhead_feedback = $2::jsonb,
            grade_attempts = GREATEST(COALESCE(grade_attempts, 0), 1),
            updated_at = NOW()
        WHERE id = $1
        """,
        patch_id,
        json.dumps(
            {
                "smoke_test": True,
                "decision": "promoted_for_hitl",
                "note": "Deterministic smoke-test escalation",
            }
        ),
    )


async def restore_prior_state(
    conn: asyncpg.Connection,
    property_id: UUID,
    smoke_patch_id: UUID,
    prior_patch: PriorDeployedPatch | None,
) -> None:
    if prior_patch is not None:
        await conn.execute(
            """
            UPDATE seo_patches
            SET
                status = 'superseded',
                updated_at = NOW()
            WHERE property_id = $1
              AND id <> $2
              AND status = 'deployed'
            """,
            property_id,
            prior_patch.id,
        )
        await conn.execute(
            """
            UPDATE seo_patches
            SET
                status = $2,
                reviewed_by = $3,
                reviewed_at = $4,
                final_payload = $5::jsonb,
                deployed_at = $6,
                godhead_score = $7,
                godhead_model = $8,
                godhead_feedback = $9::jsonb,
                grade_attempts = $10,
                updated_at = NOW()
            WHERE id = $1
            """,
            prior_patch.id,
            prior_patch.status,
            prior_patch.reviewed_by,
            prior_patch.reviewed_at,
            json.dumps(prior_patch.final_payload or {}),
            prior_patch.deployed_at,
            prior_patch.godhead_score,
            prior_patch.godhead_model,
            json.dumps(prior_patch.godhead_feedback or {}),
            prior_patch.grade_attempts,
        )

    await conn.execute(
        """
        UPDATE seo_patches
        SET
            status = 'rejected',
            reviewed_by = 'seo-smoke-cleanup',
            reviewed_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        smoke_patch_id,
    )


def make_mock_payload(target: PropertyTarget, rubric: RubricTarget) -> tuple[dict[str, Any], dict[str, Any]]:
    approved_payload = {
        "title": f"SMOKE Title :: {target.name}",
        "meta_description": f"SMOKE Meta :: {target.slug}",
        "og_title": f"SMOKE OG :: {target.name}",
        "og_description": f"SMOKE OG Desc :: {target.slug}",
        "h1_suggestion": f"SMOKE H1 :: {target.name}",
        "canonical_url": f"https://cabin-rentals-of-georgia.com/cabins/{target.slug}",
        "jsonld": {
            "@context": "https://schema.org",
            "@type": "VacationRental",
            "name": f"SMOKE JSONLD :: {target.name}",
            "url": f"https://cabin-rentals-of-georgia.com/cabins/{target.slug}",
            "description": f"SMOKE JSONLD DESC :: {target.slug}",
        },
        "alt_tags": {
            "hero": f"SMOKE alt tag for {target.slug}",
        },
    }
    ingest_payload = {
        "property_id": str(target.id),
        "rubric_id": str(rubric.id),
        "page_path": target.page_path,
        "title": approved_payload["title"],
        "meta_description": approved_payload["meta_description"],
        "og_title": approved_payload["og_title"],
        "og_description": approved_payload["og_description"],
        "jsonld_payload": approved_payload["jsonld"],
        "canonical_url": approved_payload["canonical_url"],
        "h1_suggestion": approved_payload["h1_suggestion"],
        "alt_tags": approved_payload["alt_tags"],
        "swarm_model": "seo-smoke-swarm",
        "swarm_node": "spark-node-2",
        "generation_ms": 1234,
    }
    return ingest_payload, approved_payload


async def api_get(client: httpx.AsyncClient, path: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return await client.get(f"{API_BASE}{path}", headers=headers)


async def api_post(
    client: httpx.AsyncClient,
    path: str,
    payload: dict[str, Any] | None,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(f"{API_BASE}{path}", json=payload, headers=headers)


async def wait_for_deploy_success(
    client: httpx.AsyncClient,
    patch_id: UUID,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    last_payload: dict[str, Any] | None = None
    for _ in range(DEPLOY_POLL_ATTEMPTS):
        response = await api_get(client, f"/api/seo/queue/{patch_id}", headers=headers)
        require(response.status_code == 200, "deploy-status", f"unexpected status {response.status_code}: {response.text}")
        payload = response.json()
        require(isinstance(payload, dict), "deploy-status", "queue detail payload must be an object")
        last_payload = payload
        deploy_status = str(payload.get("deploy_status") or "").strip().lower()
        if deploy_status == "succeeded":
            return payload
        if deploy_status == "failed":
            detail = str(payload.get("deploy_last_error") or "deploy worker reported failure")
            raise SmokeFailure(f"deploy-status: {detail}")
        await asyncio.sleep(DEPLOY_POLL_INTERVAL_SECONDS)
    raise SmokeFailure(f"deploy-status: timed out waiting for deploy success ({last_payload})")


def extract_queue_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    raise SmokeFailure(f"queue-shape: unexpected payload {type(payload)!r}")


async def main() -> int:
    db_url = normalize_asyncpg_dsn(settings.postgres_api_uri or "")
    require(bool(db_url), "config", "POSTGRES_API_URI is not configured")

    swarm_token = (settings.swarm_seo_api_key or settings.swarm_api_key or "").strip()
    conn = await asyncpg.connect(db_url)
    smoke_patch_id: UUID | None = None
    prior_patch: PriorDeployedPatch | None = None
    target: PropertyTarget | None = None

    try:
        target = await fetch_property(conn)
        rubric = await fetch_rubric(conn)
        db_staff = await fetch_staff_auth(conn)
        prior_patch = await fetch_prior_deployed_patch(conn, target.id)

        log_pass("db-property", f"{target.slug} ({target.id})")
        log_pass("db-rubric", f"{rubric.keyword_cluster} ({rubric.id})")
        log_pass("db-staff", f"{db_staff.email} ({db_staff.role})")

        ingest_payload, approved_payload = make_mock_payload(target, rubric)
        ingest_headers: dict[str, str] = {}
        if swarm_token:
            ingest_headers["Authorization"] = f"Bearer {swarm_token}"
            ingest_headers["X-Swarm-Token"] = swarm_token
            log_pass("auth-ingest", "using Bearer + X-Swarm-Token swarm auth")

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            staff = await login_staff_auth(client)
            log_pass("auth-review", f"{staff.email} ({staff.role})")
            if not swarm_token:
                ingest_headers["Authorization"] = f"Bearer {staff.bearer_token}"
                log_pass("auth-ingest", "using Bearer token fallback")
            review_headers = {"Authorization": f"Bearer {staff.bearer_token}"}
            ingest_res = await api_post(client, "/api/seo/patches", ingest_payload, headers=ingest_headers)
            require(ingest_res.status_code == 201, "ingest", f"unexpected status {ingest_res.status_code}: {ingest_res.text}")
            ingest_body = ingest_res.json()
            smoke_patch_id = UUID(str(ingest_body["id"]))
            log_pass("ingest", f"patch_id={smoke_patch_id}")

            queue_res = await api_get(
                client,
                "/api/seo/queue?status=drafted&limit=100",
                headers=review_headers,
            )
            require(queue_res.status_code == 200, "queue-drafted", f"unexpected status {queue_res.status_code}: {queue_res.text}")
            queue_items = extract_queue_items(queue_res.json())
            require(
                any(str(item["id"]) == str(smoke_patch_id) for item in queue_items),
                "queue-drafted",
                "ingested patch not visible in drafted queue",
            )
            log_pass("queue-drafted", f"patch visible in drafted queue ({len(queue_items)} items returned)")

            await promote_for_hitl(conn, smoke_patch_id)
            log_pass("promote-hitl", "patch promoted to pending_human for deterministic approval")

            pending_res = await api_get(
                client,
                "/api/seo/queue?status=pending_human&limit=100",
                headers=review_headers,
            )
            require(pending_res.status_code == 200, "queue-pending_human", f"unexpected status {pending_res.status_code}: {pending_res.text}")
            pending_items = extract_queue_items(pending_res.json())
            require(
                any(str(item["id"]) == str(smoke_patch_id) for item in pending_items),
                "queue-pending_human",
                "promoted patch not visible in pending_human queue",
            )
            log_pass("queue-pending_human", "patch visible for HITL review")

            approve_res = await api_post(
                client,
                f"/api/seo/queue/{smoke_patch_id}/approve",
                {"final_payload": approved_payload, "note": "SEO smoke approval"},
                headers=review_headers,
            )
            require(approve_res.status_code == 200, "approve", f"unexpected status {approve_res.status_code}: {approve_res.text}")
            log_pass("approve", f"patch approved via API ({smoke_patch_id})")

            deploy_payload = await wait_for_deploy_success(client, smoke_patch_id, headers=review_headers)
            log_pass(
                "deploy-status",
                f"succeeded ({deploy_payload.get('deploy_acknowledged_at') or 'acknowledged'})",
            )

            live_res = await api_get(client, f"/api/seo/live/{target.slug}")
            require(live_res.status_code == 200, "edge-live", f"unexpected status {live_res.status_code}: {live_res.text}")
            live_body = live_res.json()
            require(live_body.get("property_slug") == target.slug, "edge-live", "property_slug mismatch")
            require(
                live_body.get("payload") == approved_payload,
                "edge-live",
                f"live payload does not match approved payload: live={live_body.get('payload')!r}",
            )
            log_pass("edge-live", f"live payload matches approved payload for {target.slug}")

    except SmokeFailure as exc:
        log_fail("pipeline", str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        log_fail("pipeline", repr(exc))
        return 1
    finally:
        if smoke_patch_id and target:
            try:
                await restore_prior_state(conn, target.id, smoke_patch_id, prior_patch)
                log_pass("cleanup", f"restored prior deployed SEO state for {target.slug}")
            except Exception as exc:  # noqa: BLE001
                log_fail("cleanup", repr(exc))
                await conn.close()
                return 1
        await conn.close()

    log_pass("pipeline", "ingest -> queue -> approve -> edge live")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
