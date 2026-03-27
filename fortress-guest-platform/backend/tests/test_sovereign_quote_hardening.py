"""Sovereign quote signing, rate_card fee split, and checkout enforcement."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.direct_booking import router as direct_booking_router
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.time import utc_now
from backend.services.quote_builder import _rate_card_cleaning_and_admin_fees
from backend.services.sovereign_checkout_quote import validate_signed_quote_for_hold
from backend.services.sovereign_quote_signing import build_signed_quote, verify_signed_quote


def test_rate_card_splits_cleaning_and_admin_fees() -> None:
    rc = {
        "fees": [
            {"name": "Cleaning Fee", "amount": "100.00"},
            {"name": "Admin Fee", "amount": "25.00"},
        ],
    }
    cleaning, admin = _rate_card_cleaning_and_admin_fees(rc)
    assert cleaning == Decimal("100.00")
    assert admin == Decimal("25.00")


def test_hmac_sign_verify_roundtrip() -> None:
    secret = "k" * 40
    body = {
        "v": 1,
        "total": "10.00",
        "line_items": [{"type": "rent", "description": "stay", "amount": "10.00"}],
    }
    signed = build_signed_quote(body, secret)
    assert signed["signature"]
    assert verify_signed_quote(signed, secret)
    signed["total"] = "11.00"
    assert not verify_signed_quote(signed, secret)


def test_validate_signed_quote_for_hold_ok() -> None:
    secret = "z" * 40
    pid = uuid.uuid4()
    now = utc_now()
    exp = now + timedelta(minutes=15)
    body = {
        "v": 1,
        "property_id": str(pid),
        "check_in": "2026-08-01",
        "check_out": "2026-08-05",
        "guests": 2,
        "adults": 2,
        "children": 0,
        "pets": 0,
        "currency": "USD",
        "pricing_source": "local_ledger",
        "line_items": [
            {"type": "rent", "description": "4 night stay", "amount": "800.00"},
            {"type": "fee", "description": "Cleaning fee", "amount": "50.00"},
            {"type": "tax", "description": "Tax", "amount": "110.50"},
        ],
        "rent": "800.00",
        "cleaning": "50.00",
        "admin_fee": "0.00",
        "pet_fee": "0.00",
        "taxes": "110.50",
        "total": "960.50",
        "issued_at": now.isoformat(),
        "expires_at": exp.isoformat(),
    }
    signed = build_signed_quote(body, secret)
    validate_signed_quote_for_hold(
        signed,
        property_id=pid,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        num_guests=2,
        pets=0,
        secret=secret,
    )


def test_validate_signed_quote_rejects_bad_signature() -> None:
    secret = "z" * 40
    pid = uuid.uuid4()
    now = utc_now()
    body = {
        "v": 1,
        "property_id": str(pid),
        "check_in": "2026-08-01",
        "check_out": "2026-08-05",
        "guests": 2,
        "adults": 2,
        "children": 0,
        "pets": 0,
        "currency": "USD",
        "pricing_source": "local_ledger",
        "line_items": [{"type": "rent", "description": "x", "amount": "10.00"}],
        "rent": "10.00",
        "cleaning": "0.00",
        "admin_fee": "0.00",
        "pet_fee": "0.00",
        "taxes": "0.00",
        "total": "10.00",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "signature": "deadbeef",
    }
    with pytest.raises(ValueError, match="signed_quote_invalid_signature"):
        validate_signed_quote_for_hold(
            body,
            property_id=pid,
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            num_guests=2,
            pets=0,
            secret=secret,
        )


def build_direct_booking_test_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(direct_booking_router, prefix="/api/direct-booking")
    return app


@pytest.mark.asyncio
async def test_direct_booking_book_requires_signed_quote_when_key_configured() -> None:
    app = build_direct_booking_test_app()
    mock_session = AsyncMock()
    property_id = uuid.uuid4()
    prop = MagicMock()
    prop.id = property_id
    prop.name = "Test"
    prop.is_active = True
    mock_session.get = AsyncMock(return_value=prop)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    with patch.object(settings, "sovereign_quote_signing_key", "s" * 40):
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
    assert resp.status_code == 422
    assert "Signed quote" in resp.json()["detail"]
