from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.stripe_webhooks import router as stripe_webhooks_router
from backend.core.database import get_db
from backend.services.sovereign_inventory_manager import sovereign_inventory_manager


def build_stripe_webhook_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(stripe_webhooks_router, prefix="/api/webhooks")
    return app


@pytest.mark.asyncio
async def test_canonical_stripe_webhook_finalizes_direct_booking_hold() -> None:
    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

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
    convert_hold.assert_awaited_once_with(
        "pi_test_123",
        mock_session,
        metadata_hold_id=None,
    )


@pytest.mark.asyncio
async def test_stripe_webhook_settlement_orphan_when_no_reservation() -> None:
    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.stripe_webhooks.StripePayments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_orphan",
                        "metadata": {"source": "direct_booking_hold"},
                    }
                },
            },
        ),
        patch(
            "backend.api.stripe_webhooks.convert_hold_to_reservation",
            new_callable=AsyncMock,
            return_value=None,
        ),
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


@pytest.mark.asyncio
async def test_stripe_webhook_legacy_sync_failure_queues_reconciliation() -> None:
    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()
    rid = uuid.uuid4()
    settled = SimpleNamespace(id=rid)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.stripe_webhooks.StripePayments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_bridge_fail",
                        "metadata": {"source": "direct_booking_hold"},
                    }
                },
            },
        ),
        patch(
            "backend.api.stripe_webhooks.convert_hold_to_reservation",
            new_callable=AsyncMock,
            return_value=settled,
        ),
        patch(
            "backend.api.stripe_webhooks.settings.streamline_sovereign_bridge_settlement_enabled",
            True,
        ),
        patch.object(
            sovereign_inventory_manager,
            "finalize_legacy_reservation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("streamline_unreachable"),
        ),
        patch.object(
            sovereign_inventory_manager,
            "queue_strike20_settlement_for_reconciliation",
            new_callable=AsyncMock,
            return_value=4401,
        ) as queue_recon,
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
    queue_recon.assert_awaited_once_with(
        mock_session,
        reservation_id=rid,
        stripe_payment_intent_id="pi_bridge_fail",
        failure_reason="streamline_unreachable",
    )


# ── Idempotency tests (fix: audit finding A-01) ───────────────────────────────

@pytest.mark.asyncio
async def test_stripe_webhook_duplicate_delivery_returns_200_without_converting() -> None:
    """
    Stripe retries a webhook that was already successfully processed.
    db.scalar pre-check returns "converted" → returns 200 immediately.
    convert_hold_to_reservation must NOT be called (would attempt double settlement).
    """
    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()

    # db.scalar returns "converted" — hold was already settled
    mock_session.scalar.return_value = "converted"

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.stripe_webhooks.StripePayments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_already_settled",
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
    assert resp.json()["status"] == "already_processed"
    convert_hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_stripe_webhook_already_finalized_error_returns_200_not_409() -> None:
    """
    convert_hold_to_reservation raises BookingHoldError("Hold already finalized", 409)
    because a race was won by the client-side confirm flow or a concurrent webhook.
    The handler must return HTTP 200 (not 409) so Stripe stops retrying.

    CLAUDE.md invariant: duplicate event is success, not an error.
    HTTP 409 from the handler causes Stripe retry storms.
    """
    from backend.services.booking_hold_service import BookingHoldError

    app = build_stripe_webhook_test_app()
    mock_session = AsyncMock()

    # db.scalar returns None — hold not found yet (race: convert raises "already finalized")
    mock_session.scalar.return_value = None

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.stripe_webhooks.StripePayments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_race_condition",
                        "metadata": {"source": "direct_booking_hold"},
                    }
                },
            },
        ),
        patch(
            "backend.api.stripe_webhooks.convert_hold_to_reservation",
            new_callable=AsyncMock,
            side_effect=BookingHoldError("Hold already finalized", 409),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "sig_test"},
            )

    app.dependency_overrides.clear()

    # Must be 200, not 409 — Stripe treats 4xx as retriable
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_processed"
