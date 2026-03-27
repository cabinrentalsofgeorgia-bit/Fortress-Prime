from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.dispatch import CONTACT_RATE_LIMIT, get_redis_client, router as dispatch_router


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


def build_dispatch_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(dispatch_router, prefix="/api/dispatch")
    return app


def contact_payload() -> dict[str, str]:
    return {
        "first_name": "Ava",
        "last_name": "Stone",
        "email_address": "ava@example.com",
        "phone": "706-555-0147",
        "property_street_address": "123 Blue Ridge Way",
        "message": "Need more info about management services.",
        "session_id": str(uuid4()),
    }


@pytest.mark.asyncio
async def test_contact_form_dispatches_notifications() -> None:
    app = build_dispatch_test_app()
    redis = FakeRedis()

    async def override_get_redis_client():
        yield redis

    app.dependency_overrides[get_redis_client] = override_get_redis_client

    with (
        patch("backend.api.dispatch.notifications_configured", return_value=True),
        patch("backend.api.dispatch.send_system_email", new_callable=AsyncMock, return_value=True) as send_system_email,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/dispatch/contact-form", json=contact_payload())

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["queued_notifications"] == 2
    send_system_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_contact_form_enforces_redis_rate_limit() -> None:
    app = build_dispatch_test_app()
    redis = FakeRedis()

    async def override_get_redis_client():
        yield redis

    app.dependency_overrides[get_redis_client] = override_get_redis_client

    with (
        patch("backend.api.dispatch.notifications_configured", return_value=True),
        patch("backend.api.dispatch.send_system_email", new_callable=AsyncMock, return_value=True),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(CONTACT_RATE_LIMIT):
                response = await client.post("/api/dispatch/contact-form", json=contact_payload())
                assert response.status_code == 200

            blocked = await client.post("/api/dispatch/contact-form", json=contact_payload())

    app.dependency_overrides.clear()

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3600"
