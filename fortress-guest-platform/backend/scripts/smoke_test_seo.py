#!/usr/bin/env python3
"""
Temporary end-to-end smoke test for the live SEO proposal/review pipeline.

Flow:
1. Load a valid property and active review user from Postgres.
2. POST a proposal to the live API on :8100.
3. GET the queue to verify the proposal is visible.
4. POST approval through the live API.
5. GET /api/seo/live/property/{property_slug} and assert the payload matches.
6. Restore the prior live queue state so the smoke test does not leave
   permanent mock SEO content on the property surface.
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
    target_slug: str
    reviewed_by: str | None
    approved_at: Any
    approved_payload: dict[str, Any] | None
    deployed_at: Any


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
            target_slug,
            reviewed_by,
            approved_at,
            approved_payload,
            deployed_at
        FROM seo_patch_queue
        WHERE property_id = $1
          AND status IN ('approved', 'deployed')
        ORDER BY approved_at DESC NULLS LAST, updated_at DESC
        LIMIT 1
        """,
        property_id,
    )
    if row is None:
        return None
    return PriorDeployedPatch(
        id=row["id"],
        status=str(row["status"]),
        target_slug=str(row["target_slug"]),
        reviewed_by=row["reviewed_by"],
        approved_at=row["approved_at"],
        approved_payload=coerce_json_object(row["approved_payload"]),
        deployed_at=row["deployed_at"],
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
            UPDATE seo_patch_queue
            SET
                status = 'superseded',
                updated_at = NOW()
            WHERE property_id = $1
              AND id <> $2
              AND status IN ('approved', 'deployed')
            """,
            property_id,
            prior_patch.id,
        )
        await conn.execute(
            """
            UPDATE seo_patch_queue
            SET
                status = $2,
                target_slug = $3,
                approved_payload = $4::jsonb,
                deployed_at = $5,
                reviewed_by = $6,
                approved_at = $7,
                updated_at = NOW()
            WHERE id = $1
            """,
            prior_patch.id,
            prior_patch.status,
            prior_patch.target_slug,
            json.dumps(prior_patch.approved_payload or {}),
            prior_patch.deployed_at,
            prior_patch.reviewed_by,
            prior_patch.approved_at,
        )

    await conn.execute(
        """
        UPDATE seo_patch_queue
        SET
            status = 'rejected',
            reviewed_by = 'seo-smoke-cleanup',
            approved_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        smoke_patch_id,
    )


def make_mock_payload(target: PropertyTarget) -> tuple[dict[str, Any], dict[str, Any]]:
    approved_payload = {
        "title": f"SMOKE Title :: {target.name}",
        "meta_description": f"SMOKE Meta :: {target.slug}",
        "h1": f"SMOKE H1 :: {target.name}",
        "intro": f"SMOKE intro :: {target.slug}",
        "faq": [],
        "json_ld": {
            "@context": "https://schema.org",
            "@type": "VacationRental",
            "name": f"SMOKE JSONLD :: {target.name}",
            "url": f"https://cabin-rentals-of-georgia.com/cabins/{target.slug}",
            "description": f"SMOKE JSONLD DESC :: {target.slug}",
        },
        "target_keyword": f"SMOKE keyword :: {target.slug}",
        "campaign": "seo-smoke",
        "rubric_version": "v1",
    }
    ingest_payload = {
        "property_id": str(target.id),
        "target_keyword": approved_payload["target_keyword"],
        "campaign": approved_payload["campaign"],
        "rubric_version": approved_payload["rubric_version"],
        "source_snapshot": {
            "page_path": target.page_path,
            "property_slug": target.slug,
            "smoke_test": True,
        },
        "proposal": {
            "title": approved_payload["title"],
            "meta_description": approved_payload["meta_description"],
            "h1": approved_payload["h1"],
            "intro": approved_payload["intro"],
            "faq": approved_payload["faq"],
            "json_ld": approved_payload["json_ld"],
        },
        "grading": {
            "overall": 99.0,
            "breakdown": {"smoke_test": 99.0},
        },
        "proposed_by": "seo-smoke-swarm",
        "proposal_run_id": "seo-smoke-script",
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
        db_staff = await fetch_staff_auth(conn)
        prior_patch = await fetch_prior_deployed_patch(conn, target.id)

        log_pass("db-property", f"{target.slug} ({target.id})")
        log_pass("db-staff", f"{db_staff.email} ({db_staff.role})")

        ingest_payload, approved_payload = make_mock_payload(target)
        ingest_headers: dict[str, str] = {}
        if swarm_token:
            ingest_headers["X-Swarm-Token"] = swarm_token
            log_pass("auth-ingest", "using X-Swarm-Token alongside staff Bearer auth")

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            staff = await login_staff_auth(client)
            log_pass("auth-review", f"{staff.email} ({staff.role})")
            review_headers = {"Authorization": f"Bearer {staff.bearer_token}"}
            ingest_headers.setdefault("Authorization", f"Bearer {staff.bearer_token}")
            if not swarm_token:
                log_pass("auth-ingest", "using Bearer token fallback")
            ingest_res = await api_post(client, "/api/seo/proposals", ingest_payload, headers=ingest_headers)
            require(ingest_res.status_code == 200, "ingest", f"unexpected status {ingest_res.status_code}: {ingest_res.text}")
            ingest_body = ingest_res.json()
            smoke_patch_id = UUID(str((ingest_body.get("item") or {})["id"]))
            log_pass("ingest", f"patch_id={smoke_patch_id}")

            queue_res = await api_get(
                client,
                "/api/seo/queue?status=proposed&limit=100",
                headers=review_headers,
            )
            require(queue_res.status_code == 200, "queue-proposed", f"unexpected status {queue_res.status_code}: {queue_res.text}")
            queue_items = extract_queue_items(queue_res.json())
            require(
                any(str(item["id"]) == str(smoke_patch_id) for item in queue_items),
                "queue-proposed",
                "ingested patch not visible in proposed queue",
            )
            log_pass("queue-proposed", f"patch visible in proposed queue ({len(queue_items)} items returned)")

            approve_res = await api_post(
                client,
                f"/api/seo/{smoke_patch_id}/approve",
                {"note": "SEO smoke approval"},
                headers=review_headers,
            )
            require(approve_res.status_code == 200, "approve", f"unexpected status {approve_res.status_code}: {approve_res.text}")
            log_pass("approve", f"patch approved via API ({smoke_patch_id})")

            live_res = await api_get(client, f"/api/seo/live/property/{target.slug}")
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

    log_pass("pipeline", "ingest -> proposed queue -> approve -> edge live")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
