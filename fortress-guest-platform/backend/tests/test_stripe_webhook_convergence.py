from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.stripe_webhooks import router as stripe_webhooks_router
from backend.core.database import get_db


def build_stripe_webhook_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(stripe_webhooks_router, prefix="/api/webhooks")
    return app


@pytest.mark.asyncio
async def test_canonical_stripe_webhook_finalizes_direct_booking_hold() -> None:
    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()

    async def override_get_db():
        return mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.stripe_webhooks.StripePayments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_test_123",
                        "metadata": {"source": "direct_booking_hold"},
                    }
                },
            },
        ),
        patch(
            "backend.api.stripe_webhooks.convert_hold_to_reservation",
            new_callable=AsyncMock,
        ) as convert_hold,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "sig_test"},
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["event_type"] == "payment_intent.succeeded"
    convert_hold.assert_awaited_once_with("pi_test_123", mock_session)
