"""
Stripe Payments Integration — MOTO Virtual Terminal + Standard Payment Intents.

MOTO (Mail Order / Telephone Order) payments require:
  - payment_method_options={"card": {"moto": True}}
  - Stripe account approved for MOTO transactions
  - Staff authentication (never guest-facing)

All financial mutations are logged per Rule 007 (Financial Data Governance).
"""
import stripe
import structlog
from decimal import Decimal
from typing import Optional

from backend.core.config import settings

logger = structlog.get_logger()


class StripePayments:
    def __init__(self):
        self._configured = bool(settings.stripe_secret_key)
        if self._configured:
            stripe.api_key = settings.stripe_secret_key

    def get_publishable_key(self) -> str:
        return settings.stripe_publishable_key

    def _require_configured(self):
        if not self._configured:
            raise RuntimeError("Stripe is not configured — set STRIPE_SECRET_KEY in .env")

    async def create_payment_intent(
        self,
        amount_cents: int,
        reservation_id: str,
        guest_email: str,
        guest_name: str,
        property_name: str = "",
        currency: str = "usd",
    ) -> dict:
        """Standard payment intent for guest-facing checkout."""
        self._require_configured()
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            metadata={
                "reservation_id": reservation_id,
                "guest_email": guest_email,
                "guest_name": guest_name,
                "property_name": property_name,
                "source": "direct_booking",
            },
            receipt_email=guest_email,
        )
        logger.info(
            "stripe_payment_intent_created",
            intent_id=intent.id,
            amount_cents=amount_cents,
            reservation_id=reservation_id,
            source="direct_booking",
        )
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
        }

    async def create_moto_intent(
        self,
        amount_cents: int,
        reservation_id: str,
        guest_name: str,
        description: str,
        staff_user_id: str,
        staff_email: str,
        confirmation_code: str = "",
    ) -> dict:
        """
        MOTO payment intent for staff-initiated phone/mail orders.
        The moto flag bypasses SCA (Strong Customer Authentication) since
        the cardholder is not present — the staff member enters the card.
        """
        self._require_configured()
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            payment_method_types=["card"],
            payment_method_options={
                "card": {
                    "moto": True,
                },
            },
            description=description,
            metadata={
                "reservation_id": reservation_id,
                "confirmation_code": confirmation_code,
                "guest_name": guest_name,
                "source": "moto_virtual_terminal",
                "staff_user_id": staff_user_id,
                "staff_email": staff_email,
            },
        )
        logger.info(
            "stripe_moto_intent_created",
            intent_id=intent.id,
            amount_cents=amount_cents,
            reservation_id=reservation_id,
            staff_user_id=staff_user_id,
            staff_email=staff_email,
            confirmation_code=confirmation_code,
        )
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount_cents": amount_cents,
        }

    async def confirm_moto_intent(
        self,
        payment_intent_id: str,
        payment_method_id: str,
    ) -> dict:
        """Confirm a MOTO payment intent with the collected card payment method."""
        self._require_configured()
        intent = stripe.PaymentIntent.confirm(
            payment_intent_id,
            payment_method=payment_method_id,
        )
        logger.info(
            "stripe_moto_intent_confirmed",
            intent_id=intent.id,
            status=intent.status,
        )
        return {
            "payment_intent_id": intent.id,
            "status": intent.status,
            "amount_received": intent.amount_received,
        }

    async def create_payment_link(
        self,
        amount_cents: int,
        description: str,
        property_name: str,
        property_id: str,
        staging_id: int,
        owner_name: str,
    ) -> dict:
        """
        Create a hosted Stripe Payment Link for a one-off CapEx capital call.

        Flow: ad-hoc Product -> one-time Price -> PaymentLink.
        The owner clicks the link in their email to pay via Stripe-hosted checkout.
        """
        self._require_configured()
        product = stripe.Product.create(
            name=f"Capital Call — {property_name}",
            description=description,
            metadata={
                "property_id": property_id,
                "capex_staging_id": str(staging_id),
                "type": "capital_call",
            },
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=amount_cents,
            currency="usd",
        )
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            payment_method_types=["card", "us_bank_account"],
            billing_address_collection="required",
            metadata={
                "property_id": property_id,
                "capex_staging_id": str(staging_id),
                "owner_name": owner_name,
                "type": "capital_call",
            },
        )
        logger.info(
            "stripe_payment_link_created",
            link_id=link.id,
            link_url=link.url,
            amount_cents=amount_cents,
            property_id=property_id,
            staging_id=staging_id,
        )
        return {
            "payment_link_url": link.url,
            "payment_link_id": link.id,
            "product_id": product.id,
            "price_id": price.id,
            "amount_cents": amount_cents,
        }

    async def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        """Verify and parse a Stripe webhook event."""
        self._require_configured()
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.stripe_webhook_secret,
        )
        return event
