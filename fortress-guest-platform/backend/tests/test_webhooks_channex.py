from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
import backend.api.webhooks_channex as webhooks_channex_api
from backend.core.database import get_db


def _signature(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _result(value=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


@pytest.mark.asyncio
async def test_channex_webhook_rejects_when_secret_missing(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_channex_api.router, prefix="/api/webhooks/channex")
    monkeypatch.setattr(webhooks_channex_api.settings, "channex_webhook_secret", "")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/channex",
            content=b"{}",
            headers={"x-channex-signature": "abc"},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_channex_webhook_rejects_bad_signature(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_channex_api.router, prefix="/api/webhooks/channex")
    monkeypatch.setattr(webhooks_channex_api.settings, "channex_webhook_secret", "secret")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/channex",
            content=b"{}",
            headers={"x-channex-signature": "bad"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_channex_webhook_accepts_valid_signature(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_channex_api.router, prefix="/api/webhooks/channex")
    monkeypatch.setattr(webhooks_channex_api.settings, "channex_webhook_secret", "secret")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result("ledger-123"))
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(webhooks_channex_api, "process_channex_event_worker", AsyncMock())
    payload = json.dumps(
        {
            "event_id": "evt_123",
            "event_type": "booking_create",
            "timestamp": "2026-03-30T14:00:00Z",
            "payload": {
                "booking_id": "booking_123",
                "property_id": "property_123",
                "ota_source": "Airbnb",
                "status": "new",
                "check_in_date": "2026-04-10T16:00:00Z",
                "check_out_date": "2026-04-13T10:00:00Z",
                "customer": {
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "email": "ada@example.com",
                },
                "total_price": 1234.56,
                "currency": "USD",
                "raw_data": {},
            },
        }
    ).encode("utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/channex",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-channex-signature": _signature("secret", payload),
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_channex_legacy_path_accepts_valid_signature(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_channex_api.router, prefix="/webhooks/channex")
    monkeypatch.setattr(webhooks_channex_api.settings, "channex_webhook_secret", "secret")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result("ledger-legacy-123"))
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(webhooks_channex_api, "process_channex_event_worker", AsyncMock())
    payload = json.dumps(
        {
            "event_id": "evt_legacy_123",
            "event_type": "booking_create",
            "timestamp": "2026-03-30T14:00:00Z",
            "payload": {
                "booking_id": "booking_legacy_123",
                "property_id": "property_legacy_123",
                "ota_source": "Airbnb",
                "status": "new",
                "check_in_date": "2026-04-10T16:00:00Z",
                "check_out_date": "2026-04-13T10:00:00Z",
                "customer": {
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                },
                "total_price": 1234.56,
                "currency": "USD",
                "raw_data": {},
            },
        }
    ).encode("utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/channex",
            content=payload,
            headers={
                "content-type": "application/json",
                "x-channex-signature": _signature("secret", payload),
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
