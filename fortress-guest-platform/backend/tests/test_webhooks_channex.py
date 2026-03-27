from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.api.webhooks_channex import router as channex_router


@pytest.fixture
def channex_app(monkeypatch: pytest.MonkeyPatch):
    published: list[tuple[str, dict, str | None]] = []

    async def capture_publish(*, topic: str, payload: dict, key: str | None = None) -> None:
        published.append((topic, payload, key))

    monkeypatch.setattr("backend.api.webhooks_channex.settings", SimpleNamespace(channex_webhook_secret="unit-test-channex-secret"))
    monkeypatch.setattr("backend.api.webhooks_channex.publish_event", capture_publish)

    app = FastAPI()
    app.include_router(channex_router, prefix="/api/webhooks/channex")
    return app, published


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_channex_webhook_rejects_missing_signature(channex_app) -> None:
    app, published = channex_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/webhooks/channex", json={"event": "booking_new"})
    assert r.status_code == 401
    assert published == []


@pytest.mark.asyncio
async def test_channex_webhook_rejects_bad_signature(channex_app) -> None:
    app, published = channex_app
    transport = ASGITransport(app=app)
    body = json.dumps({"event": "booking_new", "booking_id": "bk-1"}).encode("utf-8")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/webhooks/channex",
            content=body,
            headers={"content-type": "application/json", "x-channex-signature": "0" * 64},
        )
    assert r.status_code == 401
    assert published == []


@pytest.mark.asyncio
async def test_channex_webhook_accepts_created_and_publishes(channex_app) -> None:
    app, published = channex_app
    transport = ASGITransport(app=app)
    payload = {
        "event": "booking_new",
        "booking_id": "bk-42",
        "property_id": "prop-9",
        "payload": {"guest_email": "a@example.com"},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body, "unit-test-channex-secret")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/webhooks/channex",
            content=body,
            headers={"content-type": "application/json", "x-channex-signature": sig},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "accepted"}
    assert len(published) == 1
    topic, env, key = published[0]
    assert topic == "ota.booking.created"
    assert key == "bk-42"
    assert env["source"] == "channex"
    assert env["event"] == "booking_new"
    assert env["booking_id"] == "bk-42"
    assert env["property_id"] == "prop-9"
    assert env["payload"]["guest_email"] == "a@example.com"


@pytest.mark.asyncio
async def test_channex_webhook_routes_modification(channex_app) -> None:
    app, published = channex_app
    transport = ASGITransport(app=app)
    payload = {"event": "booking_modification", "booking_id": "x1", "property_id": "p1", "payload": {}}
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body, "unit-test-channex-secret")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/webhooks/channex",
            content=body,
            headers={"content-type": "application/json", "x-channex-signature": sig},
        )
    assert r.status_code == 200
    assert published[0][0] == "ota.booking.modified"


@pytest.mark.asyncio
async def test_channex_webhook_accepts_sha256_prefix_signature(channex_app) -> None:
    app, published = channex_app
    transport = ASGITransport(app=app)
    payload = {"event": "booking_cancellation", "booking_id": "c1", "property_id": "p1", "payload": {}}
    body = json.dumps(payload).encode("utf-8")
    digest = _sign(body, "unit-test-channex-secret")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/webhooks/channex",
            content=body,
            headers={"content-type": "application/json", "x-channex-signature": f"sha256={digest}"},
        )
    assert r.status_code == 200
    assert published[0][0] == "ota.booking.cancelled"
