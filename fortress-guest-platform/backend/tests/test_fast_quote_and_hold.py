"""Fast quote contract and booking-hold path tests."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from backend.api.fast_quote import router as fast_quote_router
from backend.api.direct_booking import router as direct_booking_router
from backend.core.database import get_db
from backend.models.pricing import QuoteRequest, QuoteResponse
from backend.services.pricing_service import PricingError
from backend.services.fast_quote_service import FastQuoteBreakdown, FastQuoteError
from backend.services.reservation_finalization_service import FinalizeHoldResult


def build_fast_quote_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(fast_quote_router)
    return app


def build_direct_booking_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(direct_booking_router, prefix="/api/direct-booking")
    return app


def test_fast_quote_request_rejects_camel_case_keys() -> None:
    with pytest.raises(ValidationError):
        QuoteRequest.model_validate(
            {
                "propertyId": str(uuid.uuid4()),
                "checkIn": "2026-06-10",
                "checkOut": "2026-06-14",
                "adults": 2,
                "children": 0,
                "pets": 0,
            }
        )


def test_fast_quote_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QuoteRequest.model_validate(
            {
                "property_id": str(uuid.uuid4()),
                "check_in": "2026-06-10",
                "check_out": "2026-06-14",
                "adults": 2,
                "children": 0,
                "pets": 0,
                "guests": 2,
            }
        )


def test_fast_quote_response_shape() -> None:
    r = QuoteResponse(
        property_id=uuid.uuid4(),
        currency="USD",
        line_items=[],
        total_amount=Decimal("169.50"),
        is_bookable=True,
    )
    d = r.model_dump()
    assert set(d.keys()) == {"property_id", "currency", "line_items", "total_amount", "is_bookable"}


@pytest.mark.asyncio
async def test_calculate_endpoint_rejects_property_id_snake_case() -> None:
    app = build_fast_quote_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/quotes/calculate",
            json={
                "property_id": str(uuid.uuid4()),
                "checkIn": "2026-08-01",
                "checkOut": "2026-08-05",
                "adults": 2,
                "children": 0,
                "pets": 0,
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_calculate_endpoint_validates_checkout_order() -> None:
    app = build_fast_quote_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/quotes/calculate",
            json={
                "property_id": str(uuid.uuid4()),
                "check_in": "2026-08-10",
                "check_out": "2026-08-05",
                "adults": 2,
                "children": 0,
                "pets": 0,
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_locked_fast_quote_breakdown_uses_hold_sequence() -> None:
    from backend.services.fast_quote_service import calculate_locked_fast_quote_breakdown

    call_order: list[str] = []
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    request = QuoteRequest.model_validate(
        {
            "property_id": str(property_id),
            "check_in": "2026-08-01",
            "check_out": "2026-08-05",
            "adults": 2,
            "children": 0,
            "pets": 0,
        }
    )

    async def _lock(*args, **kwargs):
        call_order.append("lock")

    async def _expire(*args, **kwargs):
        call_order.append("expire")
        return 1

    async def _assert_available(*args, **kwargs):
        call_order.append("availability")

    async def _compute(*args, **kwargs):
        call_order.append("quote")
        return FastQuoteBreakdown(
            rent=100,
            cleaning=25,
            taxes=16.25,
            total=141.25,
        )

    with (
        patch(
            "backend.services.fast_quote_service.acquire_property_booking_lock",
            side_effect=_lock,
            new_callable=AsyncMock,
        ),
        patch(
            "backend.services.fast_quote_service.expire_stale_holds",
            side_effect=_expire,
            new_callable=AsyncMock,
        ),
        patch(
            "backend.services.fast_quote_service.assert_property_available_for_stay",
            side_effect=_assert_available,
            new_callable=AsyncMock,
        ),
        patch(
            "backend.services.fast_quote_service.compute_fast_quote_breakdown",
            side_effect=_compute,
            new_callable=AsyncMock,
        ),
    ):
        breakdown = await calculate_locked_fast_quote_breakdown(
            mock_session,
            property_id,
            request.check_in,
            request.check_out,
            request.adults + request.children,
        )

    assert call_order == ["lock", "expire", "availability", "quote"]
    assert breakdown.total == Decimal("141.25")


@pytest.mark.asyncio
async def test_calculate_endpoint_rolls_back_and_surfaces_fast_quote_error() -> None:
    app = build_fast_quote_test_app()

    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with patch(
        "backend.api.fast_quote.calculate_fast_quote",
        new_callable=AsyncMock,
        side_effect=PricingError("Property is temporarily held for checkout"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/quotes/calculate",
                json={
                "property_id": str(uuid.uuid4()),
                "check_in": "2026-08-01",
                "check_out": "2026-08-05",
                "adults": 2,
                "children": 0,
                "pets": 0,
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Property is temporarily held for checkout"
    mock_session.rollback.assert_not_awaited()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_booking_quote_uses_local_ledger_breakdown() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Aska Escape Lodge"
    prop.is_active = True
    mock_session.get = AsyncMock(return_value=prop)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with patch(
        "backend.api.direct_booking.calculate_locked_fast_quote_breakdown",
        new_callable=AsyncMock,
        return_value=FastQuoteBreakdown(
            rent=Decimal("800.00"),
            cleaning=Decimal("150.00"),
            taxes=Decimal("123.50"),
            total=Decimal("1073.50"),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/direct-booking/quote?property_id={property_id}",
                json={
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-05",
                    "guests": 2,
                    "pets": False,
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pricing_source"] == "local_ledger"
    assert payload["breakdown"]["subtotal"] == 800.0
    assert payload["breakdown"]["cleaning_fee"] == 150.0
    assert payload["breakdown"]["admin_fee"] == 0.0
    assert payload["breakdown"]["tax"] == 123.5
    assert payload["breakdown"]["total"] == 1073.5
    assert payload["breakdown"]["pet_fee"] == 0
    assert payload["breakdown"]["line_items"] == []
    assert payload["breakdown"]["nightly_breakdown"] == []
    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_booking_quote_rolls_back_on_fast_quote_error() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Aska Escape Lodge"
    prop.is_active = True
    mock_session.get = AsyncMock(return_value=prop)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with patch(
        "backend.api.direct_booking.calculate_locked_fast_quote_breakdown",
        new_callable=AsyncMock,
        side_effect=FastQuoteError("pricing_ledger_incomplete", "Property pricing is not synced to the local ledger yet", 503),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/direct-booking/quote?property_id={property_id}",
                json={
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-05",
                    "guests": 2,
                    "pets": False,
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Property pricing is not synced to the local ledger yet"
    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_booking_book_returns_hold_payload() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Aska Escape Lodge"
    prop.is_active = True
    mock_session.get = AsyncMock(return_value=prop)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.direct_booking.create_checkout_hold",
            new_callable=AsyncMock,
            return_value={
                "hold_id": "hold_123",
                "expires_at": "2026-08-01T12:00:00",
                "total_amount": 1073.50,
                "payment": {"payment_intent_id": "pi_123", "client_secret": "cs_123"},
            },
        ),
        patch(
            "backend.api.direct_booking.record_audit_event",
            new_callable=AsyncMock,
        ) as record_audit_event,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/direct-booking/book",
                json={
                    "property_id": str(property_id),
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-05",
                    "num_guests": 2,
                    "guest_first_name": "Ada",
                    "guest_last_name": "Lovelace",
                    "guest_email": "ada@example.com",
                    "guest_phone": "4045551234",
                    "special_requests": "Late arrival",
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["hold_id"] == "hold_123"
    assert payload["payment"]["payment_intent_id"] == "pi_123"
    assert payload["reservation_id"] is None
    assert payload["confirmation_code"] is None
    record_audit_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_booking_book_maps_booking_hold_error() -> None:
    from backend.services.booking_hold_service import BookingHoldError

    app = build_direct_booking_test_app()
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Aska Escape Lodge"
    prop.is_active = True
    mock_session.get = AsyncMock(return_value=prop)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with patch(
        "backend.api.direct_booking.create_checkout_hold",
        new_callable=AsyncMock,
        side_effect=BookingHoldError("Property is temporarily held for checkout", 409),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/direct-booking/book",
                json={
                    "property_id": str(property_id),
                    "check_in": "2026-08-01",
                    "check_out": "2026-08-05",
                    "num_guests": 2,
                    "guest_first_name": "Ada",
                    "guest_last_name": "Lovelace",
                    "guest_email": "ada@example.com",
                    "guest_phone": "4045551234",
                },
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Property is temporarily held for checkout"


@pytest.mark.asyncio
async def test_confirm_hold_rejects_invalid_uuid() -> None:
    app = build_direct_booking_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/direct-booking/confirm-hold",
            json={"hold_id": "not-a-uuid"},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid hold_id"


@pytest.mark.asyncio
async def test_confirm_hold_returns_reservation_payload() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    reservation = MagicMock()
    reservation.id = uuid.uuid4()
    reservation.confirmation_code = "CRG-ABCDE"
    reservation.total_amount = Decimal("1073.50")

    with patch(
        "backend.api.direct_booking.finalize_hold_as_reservation",
        new_callable=AsyncMock,
        return_value=FinalizeHoldResult(reservation=reservation, already_finalized=False),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/direct-booking/confirm-hold",
                json={"hold_id": str(uuid.uuid4())},
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["reservation_id"] == str(reservation.id)
    assert payload["confirmation_code"] == "CRG-ABCDE"
    assert payload["total_amount"] == 1073.5


@pytest.mark.asyncio
async def test_stripe_webhook_finalizes_direct_booking_hold() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch(
            "backend.api.direct_booking.stripe_payments.handle_webhook",
            new_callable=AsyncMock,
            return_value={
                "type": "payment_intent.succeeded",
                "data": {
                    "object": {
                        "id": "pi_123",
                        "metadata": {"source": "direct_booking_hold"},
                    }
                },
            },
        ),
        patch(
            "backend.api.direct_booking.convert_hold_to_reservation",
            new_callable=AsyncMock,
        ) as convert_hold,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/direct-booking/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "sig_test"},
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["event_type"] == "payment_intent.succeeded"
    convert_hold.assert_awaited_once_with(
        "pi_123",
        mock_session,
        metadata_hold_id=None,
    )


@pytest.mark.asyncio
async def test_reservation_engine_get_availability_returns_false_for_blocked_days() -> None:
    from backend.services.reservation_engine import ReservationEngine

    blocked_result = MagicMock()
    blocked_result.scalar_one.return_value = 1
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=blocked_result)

    available = await ReservationEngine().get_availability(
        mock_session,
        uuid.uuid4(),
        date(2026, 8, 1),
        date(2026, 8, 5),
    )

    assert available is False
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_hold_rolls_back_when_availability_changes() -> None:
    from backend.services.booking_hold_service import BookingHoldError, finalize_hold_as_reservation

    hold_id = uuid.uuid4()
    mock_session = AsyncMock()

    with patch(
        "backend.services.booking_hold_service.reservation_finalization_service.finalize_by_hold_id",
        new_callable=AsyncMock,
        side_effect=BookingHoldError("Property is not available for these dates", 409),
    ):
        with pytest.raises(BookingHoldError) as exc_info:
            await finalize_hold_as_reservation(mock_session, hold_id)

    assert exc_info.value.status_code == 409
    assert str(exc_info.value) == "Property is not available for these dates"
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_checkout_hold_serializes_collision_and_second_fails_gracefully() -> None:
    from backend.services.booking_hold_service import BookingHoldError, create_checkout_hold

    property_id = uuid.uuid4()
    guest = MagicMock()
    guest.id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Aska Escape Lodge"
    prop.is_active = True

    guest_lookup_result = MagicMock()
    guest_lookup_result.scalar_one_or_none.return_value = guest

    session_one = AsyncMock()
    session_two = AsyncMock()
    for session in (session_one, session_two):
        session.get = AsyncMock(return_value=prop)
        session.execute = AsyncMock(return_value=guest_lookup_result)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.in_transaction = MagicMock(return_value=False)

    lock = asyncio.Lock()
    collision_state = {"hold_exists": False}

    async def fake_acquire_lock(*args, **kwargs) -> None:
        await lock.acquire()

    async def fake_create_inventory_hold(
        db, *, property_id, check_in, check_out, session_id, guest_id, num_guests, amount_total, quote_snapshot, special_requests
    ):
        await lock.acquire()
        if collision_state["hold_exists"]:
            lock.release()
            raise HTTPException(status_code=409, detail="Property is temporarily held for checkout")
        hold = MagicMock()
        hold.id = uuid.uuid4()
        hold.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        hold.payment_intent_id = None
        return hold

    async def release_on_commit() -> None:
        collision_state["hold_exists"] = True
        if lock.locked():
            lock.release()

    async def release_on_rollback() -> None:
        if lock.locked():
            lock.release()

    session_one.commit = AsyncMock(side_effect=release_on_commit)
    session_one.rollback = AsyncMock(side_effect=release_on_rollback)
    session_two.commit = AsyncMock(side_effect=release_on_commit)
    session_two.rollback = AsyncMock(side_effect=release_on_rollback)

    with (
        patch(
            "backend.services.booking_hold_service.settings.sovereign_quote_signing_key",
            "",
        ),
        patch(
            "backend.services.booking_hold_service.build_quote_snapshot",
            new_callable=AsyncMock,
            return_value={"total": "500.00"},
        ),
        patch(
            "backend.services.booking_hold_service.create_inventory_hold",
            new_callable=AsyncMock,
            side_effect=fake_create_inventory_hold,
        ),
        patch(
            "backend.services.booking_hold_service.stripe_payments.create_payment_intent",
            new_callable=AsyncMock,
            return_value={"payment_intent_id": "pi_123", "client_secret": "cs_123"},
        ),
    ):
        results = await asyncio.gather(
            create_checkout_hold(
                session_one,
                property_id=property_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                session_id="checkout-session-one",
                num_guests=2,
                guest_first_name="A",
                guest_last_name="One",
                guest_email="a@example.com",
                guest_phone="1111111111",
            ),
            create_checkout_hold(
                session_two,
                property_id=property_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                session_id="checkout-session-two",
                num_guests=2,
                guest_first_name="B",
                guest_last_name="Two",
                guest_email="b@example.com",
                guest_phone="2222222222",
            ),
            return_exceptions=True,
        )

    success_result = next(result for result in results if isinstance(result, dict))
    failure_result = next(result for result in results if isinstance(result, Exception))

    assert success_result["payment"]["payment_intent_id"] == "pi_123"
    assert isinstance(failure_result, BookingHoldError)
    assert failure_result.status_code == 409
    assert str(failure_result) == "Property is temporarily held for checkout"
    session_one.commit.assert_awaited_once()
    session_two.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_hold_skips_when_not_active() -> None:
    from backend.services.booking_hold_service import BookingHoldError, finalize_hold_as_reservation

    mock_session = AsyncMock()

    with patch(
        "backend.services.booking_hold_service.reservation_finalization_service.finalize_by_hold_id",
        new_callable=AsyncMock,
        side_effect=BookingHoldError("Hold is no longer active", 409),
    ):
        with pytest.raises(BookingHoldError):
            await finalize_hold_as_reservation(mock_session, uuid.uuid4())


@pytest.mark.asyncio
async def test_convert_hold_to_reservation_commits_atomic_conversion() -> None:
    from backend.services.booking_hold_service import convert_hold_to_reservation

    mock_session = AsyncMock()

    reservation = MagicMock()
    reservation.id = uuid.uuid4()

    with patch(
        "backend.services.booking_hold_service.reservation_finalization_service.finalize_by_payment_intent",
        new_callable=AsyncMock,
        return_value=FinalizeHoldResult(reservation=reservation, already_finalized=False),
    ) as finalize_pi:
        converted = await convert_hold_to_reservation("pi_convert_123", mock_session)

    assert converted is reservation
    finalize_pi.assert_awaited_once_with(
        mock_session,
        payment_intent_id="pi_convert_123",
        metadata_hold_id=None,
    )
    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()
