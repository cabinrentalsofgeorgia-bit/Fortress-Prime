from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.privacy_router import sanitize_for_cloud


BASE_URL = os.getenv("FOCUSED_SMOKE_BASE_URL", "http://127.0.0.1:8110")
PRIVATE_KEY_PATH = os.getenv("FOCUSED_SMOKE_PRIVATE_KEY", "/tmp/hitl-keys/private.pem")
JWT_KID = os.getenv("FOCUSED_SMOKE_JWT_KID", "fgp-rs256-v1")


def _require_live_backend() -> None:
    try:
        with httpx.Client(timeout=2.0) as client:
            client.get(BASE_URL)
    except httpx.HTTPError as exc:
        pytest.skip(f"focused smoke backend unavailable at {BASE_URL}: {exc}")


def _token() -> str:
    private_key = open(PRIVATE_KEY_PATH).read()
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "super_admin",
        "email": "smoke@fortress.local",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": JWT_KID})


def test_tool_discovery_availability_schema() -> None:
    _require_live_backend()
    token = _token()
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(
            f"{BASE_URL}/api/v1/properties/availability",
            params={"check_in": "2026-04-10", "check_out": "2026-04-13", "guests": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("check_in", "check_out", "guests", "results"):
        assert key in body
    assert isinstance(body["results"], list)


def test_redaction_aliases_name_to_guest_alpha() -> None:
    decision = sanitize_for_cloud(
        {"guest_name": "John Doe", "note": "Guest John Doe requested late check-in"}
    )
    assert decision.redacted_payload["guest_name"] == "GUEST_ALPHA"
    assert "GUEST_ALPHA" in decision.redacted_payload["note"]


def test_chain_of_custody_signature_present_after_redirect_write() -> None:
    _require_live_backend()
    token = _token()
    source_path = f"/pytest-smoke-{int(time.time())}"
    payload = {
        "source_path": source_path,
        "destination_path": "/pytest-smoke-new",
        "is_permanent": True,
        "reason": "pytest-focused-smoke",
    }

    with httpx.Client(timeout=20.0) as client:
        create_resp = client.post(
            f"{BASE_URL}/api/v1/seo/redirects",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201, create_resp.text

        audit_resp = client.get(
            f"{BASE_URL}/api/openshell/audit/log",
            params={"limit": 200},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert audit_resp.status_code == 200, audit_resp.text

    rows = audit_resp.json()
    row = next(
        (
            x
            for x in rows
            if x.get("action") == "seo.redirect.write"
            and x.get("metadata_json", {}).get("source_path") == source_path
        ),
        None,
    )
    assert row is not None
    assert row.get("entry_hash")
    assert row.get("signature")
