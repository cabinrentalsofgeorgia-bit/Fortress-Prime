"""
Payout Service — Continuous Liquidity Engine

Wraps Stripe Connect operations for owner disbursements. When the Revenue
Swarm journals the 65/35 split, this service fires an instant transfer to
the owner's connected Stripe account.

Account flow:
  1. Owner clicks "Enable Instant Payouts" on the Glass
  2. We create a Stripe Express Connected Account
  3. Owner completes Stripe onboarding (KYC, bank details)
  4. On every paid reservation, transfer owner_share to their account
  5. Stripe handles the instant or standard ACH to their bank
"""

import structlog
from typing import Optional

from backend.core.config import settings

logger = structlog.get_logger(service="payout_service")

_stripe = None


def _get_stripe():
    global _stripe
    if _stripe is None:
        import stripe

        stripe.api_key = settings.stripe_secret_key
        _stripe = stripe
    return _stripe


async def create_connect_account(
    owner_name: str, owner_email: str
) -> Optional[dict]:
    """Create a Stripe Express Connected Account for the property owner."""
    stripe = _get_stripe()
    if not stripe.api_key:
        logger.warning("stripe_not_configured", action="create_connect_account")
        return None
    try:
        account = stripe.Account.create(
            type="express",
            country="US",
            email=owner_email,
            business_type="individual",
            individual={"first_name": owner_name.split()[0] if owner_name else "Owner"},
            capabilities={
                "transfers": {"requested": True},
            },
            metadata={"platform": "crog-vrs", "owner_name": owner_name},
        )
        logger.info(
            "stripe_connect_account_created",
            account_id=account.id,
            email=owner_email,
        )
        return {"account_id": account.id, "status": "onboarding"}
    except Exception as e:
        logger.error("stripe_connect_create_failed", error=str(e))
        return None


async def create_onboarding_link(
    account_id: str, return_url: str
) -> Optional[str]:
    """Generate an Account Link for the owner to complete Stripe KYC."""
    stripe = _get_stripe()
    if not stripe.api_key:
        return None
    try:
        link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=f"{return_url}?refresh=true",
            return_url=return_url,
            type="account_onboarding",
        )
        return link.url
    except Exception as e:
        logger.error("stripe_onboarding_link_failed", error=str(e), account=account_id)
        return None


async def check_account_status(account_id: str) -> dict:
    """Check whether the connected account can receive transfers."""
    stripe = _get_stripe()
    if not stripe.api_key:
        return {"status": "not_configured"}
    try:
        acct = stripe.Account.retrieve(account_id)
        charges_enabled = acct.get("charges_enabled", False)
        payouts_enabled = acct.get("payouts_enabled", False)
        status = "active" if charges_enabled and payouts_enabled else "restricted"
        return {
            "status": status,
            "charges_enabled": charges_enabled,
            "payouts_enabled": payouts_enabled,
            "details_submitted": acct.get("details_submitted", False),
        }
    except Exception as e:
        logger.error("stripe_account_check_failed", error=str(e), account=account_id)
        return {"status": "error", "error": str(e)}


async def initiate_transfer(
    account_id: str,
    amount: float,
    description: str,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Transfer funds from the CROG platform account to the owner's connected account."""
    stripe = _get_stripe()
    if not stripe.api_key:
        logger.warning("stripe_not_configured", action="initiate_transfer")
        return None
    try:
        transfer = stripe.Transfer.create(
            amount=int(amount * 100),
            currency="usd",
            destination=account_id,
            description=description,
            metadata=metadata or {},
        )
        logger.info(
            "stripe_transfer_initiated",
            transfer_id=transfer.id,
            amount=amount,
            destination=account_id,
        )
        return {"transfer_id": transfer.id, "amount": amount, "status": "completed"}
    except Exception as e:
        logger.error(
            "stripe_transfer_failed",
            error=str(e),
            destination=account_id,
            amount=amount,
        )
        return {"transfer_id": None, "error": str(e), "status": "failed"}
