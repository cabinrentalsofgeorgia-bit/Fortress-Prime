#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import stripe
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.config import settings  # noqa: E402
from backend.core.database import AsyncSessionLocal  # noqa: E402
from backend.models.property import Property  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.reservation_hold import ReservationHold  # noqa: E402


API_BASE = "http://127.0.0.1:8100"
QUOTE_TOKEN = (
    (settings.swarm_api_key or "").strip()
    or (getattr(settings, "internal_api_key", "") or "").strip()
)
STRIPE_SECRET_KEY = (settings.stripe_secret_key or "").strip()
STRIPE_WEBHOOK_SECRET = (settings.stripe_webhook_secret or "").strip()
TWO_PLACES = Decimal("0.01")


def telemetry(step: str, **fields: Any) -> None:
    suffix = " | ".join(f"{key}={value}" for key, value in fields.items())
    if suffix:
        print(f"[E2E TELEMETRY] {step} | {suffix}")
    else:
        print(f"[E2E TELEMETRY] {step}")


def quantize_money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES)


def quote_headers() -> dict[str, str]:
    if not QUOTE_TOKEN:
        raise RuntimeError("SWARM_API_KEY is required to call /api/quotes/calculate")
    return {
        "Authorization": f"Bearer {QUOTE_TOKEN}",
        "X-Swarm-Token": QUOTE_TOKEN,
        "Content-Type": "application/json",
    }


def build_signed_stripe_header(payload: bytes) -> str:
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is required to dispatch the webhook")
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    signature = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


async def pick_quotable_stay(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any], date, date]:
    for offset_days in range(30, 210, 7):
        check_in = date.today() + timedelta(days=offset_days)
        check_out = check_in + timedelta(days=3)
        telemetry(
            "searching_inventory",
            check_in=check_in.isoformat(),
            check_out=check_out.isoformat(),
        )
        availability = await client.get(
            "/api/direct-booking/availability",
            params={
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "guests": 2,
            },
        )
        availability.raise_for_status()
        results = availability.json().get("results", [])
        if not results:
            continue

        for candidate in results:
            quote_resp = await client.post(
                "/api/quotes/calculate",
                headers=quote_headers(),
                json={
                    "property_id": candidate["id"],
                    "check_in": check_in.isoformat(),
                    "check_out": check_out.isoformat(),
                    "adults": 2,
                    "children": 0,
                    "pets": 0,
                },
            )
            if quote_resp.status_code == 200:
                quote = quote_resp.json()
                if quote.get("is_bookable"):
                    telemetry(
                        "selected_inventory",
                        property_id=candidate["id"],
                        property_name=candidate["name"],
                        check_in=check_in.isoformat(),
                        check_out=check_out.isoformat(),
                        total_amount=quote["total_amount"],
                    )
                    return candidate, quote, check_in, check_out
                telemetry(
                    "skipping_unbookable_quote",
                    property_id=candidate["id"],
                    property_name=candidate["name"],
                )
            else:
                telemetry(
                    "quote_candidate_rejected",
                    property_id=candidate["id"],
                    status=quote_resp.status_code,
                    detail=quote_resp.text[:180],
                )

    raise RuntimeError("Unable to find a quotable and available stay window")


async def ensure_tax_ledger_seeded() -> None:
    async with AsyncSessionLocal() as db:
        active_properties = (
            await db.execute(
                select(Property)
                .where(Property.is_active.is_(True))
                .order_by(Property.name.asc())
            )
        ).scalars().all()
        if not active_properties:
            raise RuntimeError("No active property is available for E2E tax-ledger hydration")

        updated = 0
        for prop in active_properties:
            rate_card = dict(prop.rate_card or {})
            taxes = rate_card.get("taxes")
            if isinstance(taxes, list) and taxes:
                continue

            rate_card["taxes"] = [
                {
                    "name": "Fannin County Lodging Tax",
                    "type": "percent",
                    "rate": "0.12",
                    "source": "e2e_booking_checkout",
                }
            ]
            if "fees" not in rate_card or rate_card["fees"] is None:
                rate_card["fees"] = []

            prop.rate_card = rate_card
            updated += 1

        if updated == 0:
            telemetry("tax_ledger_present", active_properties=len(active_properties))
            return

        await db.commit()
        telemetry(
            "hydrated_tax_ledger",
            updated_properties=updated,
            tax_rate=0.12,
        )


def confirm_payment_intent_with_test_card(
    payment_intent_id: str,
    *,
    guest_email: str,
    guest_name: str,
) -> dict[str, Any]:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is required for the live-fire test")
    stripe.api_key = STRIPE_SECRET_KEY
    payment_method = stripe.PaymentMethod.create(
        type="card",
        card={"token": "tok_visa"},
        billing_details={
            "email": guest_email,
            "name": guest_name,
        },
    )
    intent = stripe.PaymentIntent.confirm(
        payment_intent_id,
        payment_method=payment_method.id,
    )
    return {
        "id": intent.id,
        "status": intent.status,
        "amount_received": intent.amount_received,
        "metadata": dict(intent.metadata or {}),
    }


async def fetch_checkout_ledger(
    hold_id: UUID,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[ReservationHold, Reservation]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            hold = await db.get(ReservationHold, hold_id)
            if hold is None:
                raise RuntimeError(f"Hold {hold_id} disappeared during verification")

            reservation_query = (
                select(Reservation)
                .where(Reservation.guest_id == hold.guest_id)
                .where(Reservation.property_id == hold.property_id)
                .where(Reservation.check_in_date == hold.check_in_date)
                .where(Reservation.check_out_date == hold.check_out_date)
                .order_by(Reservation.created_at.desc())
            )
            reservation = (await db.execute(reservation_query)).scalars().first()
            if reservation is not None:
                return hold, reservation

        await asyncio.sleep(0.5)

    raise RuntimeError("Reservation was not materialized before timeout")


async def main() -> None:
    telemetry("boot", api_base=API_BASE)
    await ensure_tax_ledger_seeded()

    guest_nonce = uuid4().hex[:10]
    guest_email = f"e2e-booking-{guest_nonce}@fortress-prime.local"
    guest_name = "Fortress E2E"
    session_id = f"e2e-checkout-{uuid4()}"

    async with httpx.AsyncClient(base_url=API_BASE, timeout=45.0) as client:
        candidate, quote, check_in, check_out = await pick_quotable_stay(client)

        quote_rent = next(item["amount"] for item in quote["line_items"] if item["type"] == "rent")
        quote_cleaning = next(
            item["amount"]
            for item in quote["line_items"]
            if item["type"] == "fee" and item["description"] == "Cleaning Fee"
        )
        quote_taxes = next(item["amount"] for item in quote["line_items"] if item["type"] == "tax")
        quote_total = quote["total_amount"]
        telemetry(
            "quote_received",
            property_id=candidate["id"],
            rent=quote_rent,
            cleaning=quote_cleaning,
            taxes=quote_taxes,
            total=quote_total,
        )

        book_resp = await client.post(
            "/api/direct-booking/book",
            json={
                "property_id": candidate["id"],
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "num_guests": 2,
                "session_id": session_id,
                "guest_first_name": "Fortress",
                "guest_last_name": "E2E",
                "guest_email": guest_email,
                "guest_phone": "7065550100",
                "special_requests": f"[E2E TEST] session={session_id}",
            },
        )
        book_resp.raise_for_status()
        hold_payload = book_resp.json()
        hold_id = UUID(hold_payload["hold_id"])
        payment_intent_id = hold_payload["payment"]["payment_intent_id"]
        telemetry(
            "checkout_hold_created",
            hold_id=str(hold_id),
            payment_intent_id=payment_intent_id,
            total_amount=hold_payload["total_amount"],
            expires_at=hold_payload["expires_at"],
        )

        intent = await asyncio.to_thread(
            confirm_payment_intent_with_test_card,
            payment_intent_id,
            guest_email=guest_email,
            guest_name=guest_name,
        )
        telemetry(
            "stripe_payment_confirmed",
            payment_intent_id=intent["id"],
            stripe_status=intent["status"],
            amount_received_cents=intent.get("amount_received", 0),
        )
        if intent["status"] != "succeeded":
            raise RuntimeError(f"PaymentIntent {intent['id']} did not succeed")

        event = {
            "id": f"evt_e2e_{uuid4().hex}",
            "object": "event",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": intent["id"],
                    "metadata": intent.get("metadata", {}),
                }
            },
        }
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        webhook_resp = await client.post(
            "/api/webhooks/stripe",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "stripe-signature": build_signed_stripe_header(payload),
            },
        )
        webhook_resp.raise_for_status()
        telemetry(
            "stripe_webhook_dispatched",
            event_type=event["type"],
            backend_response=webhook_resp.json(),
        )

        hold, reservation = await fetch_checkout_ledger(hold_id)
        snapshot = reservation.price_breakdown or {}

        telemetry(
            "ledger_materialized",
            hold_status=hold.status,
            reservation_id=reservation.id,
            confirmation_code=reservation.confirmation_code,
            reservation_status=reservation.status,
        )

        assert hold.status == "converted", f"Expected hold to be converted, got {hold.status}"
        assert reservation.status == "confirmed", (
            f"Expected reservation status confirmed, got {reservation.status}"
        )
        assert quantize_money(snapshot.get("rent")) == quantize_money(quote_rent)
        assert quantize_money(snapshot.get("cleaning")) == quantize_money(quote_cleaning)
        assert quantize_money(snapshot.get("taxes")) == quantize_money(quote_taxes)
        assert quantize_money(snapshot.get("total")) == quantize_money(quote_total)
        assert quantize_money(reservation.total_amount) == quantize_money(quote_total)
        assert quantize_money(reservation.paid_amount) == quantize_money(quote_total)
        assert quantize_money(reservation.balance_due or 0) == Decimal("0.00")

        telemetry(
            "financials_verified",
            quote_total=quote_total,
            reservation_total=reservation.total_amount,
            paid_amount=reservation.paid_amount,
            balance_due=reservation.balance_due,
        )
        telemetry(
            "guest_ledger_verified",
            guest_email=reservation.guest_email,
            guest_name=reservation.guest_name,
            guest_phone=reservation.guest_phone,
        )
        telemetry(
            "success",
            reservation_id=reservation.id,
            confirmation_code=reservation.confirmation_code,
            note="hold converted and reservation confirmed",
        )


if __name__ == "__main__":
    asyncio.run(main())
