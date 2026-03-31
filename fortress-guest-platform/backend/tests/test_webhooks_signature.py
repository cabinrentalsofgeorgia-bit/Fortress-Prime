from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
import backend.api.webhooks as webhooks_api
from backend.core.database import get_db


@pytest.mark.asyncio
async def test_incoming_sms_rejects_invalid_signature_when_token_configured(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_api.router, prefix="/api/webhooks")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(webhooks_api.settings, "twilio_auth_token", "test-auth-token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/sms/incoming",
            data={"From": "+15555550123", "Body": "hello", "MessageSid": "SM123"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_sms_status_rejects_invalid_signature_when_token_configured(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_api.router, prefix="/api/webhooks")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(webhooks_api.settings, "twilio_auth_token", "test-auth-token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/sms/status",
            data={"MessageSid": "SM123", "MessageStatus": "delivered"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_incoming_sms_rejects_when_twilio_token_missing(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(webhooks_api.router, prefix="/api/webhooks")
    session = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(webhooks_api.settings, "twilio_auth_token", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/sms/incoming",
            data={"From": "+15555550123", "Body": "hello", "MessageSid": "SM123"},
        )

    assert response.status_code == 403
