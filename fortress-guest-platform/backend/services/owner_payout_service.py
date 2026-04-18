"""
Owner Payout Service — Statement-level Stripe Connect transfers (I.5).

pay_owner_for_statement():
  - Validates the OBP is approved/emailed and payable
  - Computes payout = closing_balance - opening_balance (net period change)
  - Creates a Stripe Transfer with idempotency key "pay-obp-{obp_id}"
  - Transitions OBP to status=paid and records stripe_transfer_id + paid_amount
  - Charge save and recompute are non-atomic: payout is committed before Stripe
    is called; if Stripe fails, OBP stays in approved/emailed for retry

Double-pay prevention (2 layers):
  1. Stripe idempotency key "pay-obp-{obp_id}" — network-level dedup
  2. OBP status=paid — application-level guard; re-calling pay while paid
     returns PayoutValidationError(code="already_paid")

Architecture note (multi-OPA owners):
  Cherokee (OPA 1826) and Serendipity (OPA 1827) have stripe_account_id=NULL.
  Their pay_enabled=False prevents this function from being called for them.
  When I.5.1 ships payout aggregation, secondary OPAs will route through
  the primary OPA's Stripe account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.services.payout_service import initiate_transfer
from backend.services.statement_workflow import _LOCKED_STATUSES

logger = structlog.get_logger(service="owner_payout_service")
_UTC = timezone.utc

_PAYABLE_STATUSES = frozenset([
    StatementPeriodStatus.APPROVED.value,
    StatementPeriodStatus.EMAILED.value,
])


# ── Exceptions ────────────────────────────────────────────────────────────────

class PayoutValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class PayOwnerResult:
    success: bool
    stripe_transfer_id: Optional[str]
    amount: Decimal
    error: Optional[str] = None


# ── Service ───────────────────────────────────────────────────────────────────

async def pay_owner_for_statement(
    db: AsyncSession,
    *,
    period_id: int,
    admin_email: str,
) -> PayOwnerResult:
    """
    Transfer the net period amount to the owner's Stripe Connected account.

    Raises PayoutValidationError for pre-conditions that prevent the transfer.
    Never raises on Stripe errors — those are returned in PayOwnerResult.error.
    """
    # 1. Load OBP
    period = await db.get(OwnerBalancePeriod, period_id)
    if period is None:
        raise PayoutValidationError("not_found", f"Statement period {period_id} not found")

    # 2. Status validation
    if period.status == StatementPeriodStatus.PAID.value:
        raise PayoutValidationError(
            "already_paid",
            f"Statement {period_id} is already paid (stripe_transfer_id={period.stripe_transfer_id}). "
            "To void and retry, un-approve the statement first.",
        )
    if period.status not in _PAYABLE_STATUSES:
        raise PayoutValidationError(
            "invalid_status",
            f"Statement {period_id} has status='{period.status}'. "
            "Only 'approved' or 'emailed' statements can be paid.",
        )

    # 3. Load OPA + validate Stripe enrollment
    opa = await db.get(OwnerPayoutAccount, period.owner_payout_account_id)
    if opa is None:
        raise PayoutValidationError("no_opa", f"No payout account for OBP {period_id}")
    if not opa.stripe_account_id:
        raise PayoutValidationError(
            "no_stripe",
            f"Owner '{opa.owner_name}' (OPA {opa.id}) has no Stripe account. "
            "pay_enabled=False — cannot transfer.",
        )

    # 4. Compute payout amount (net period change only)
    opening = Decimal(str(period.opening_balance))
    closing = Decimal(str(period.closing_balance))
    payout_amount = closing - opening

    if payout_amount <= Decimal("0"):
        raise PayoutValidationError(
            "no_net_income",
            f"No positive net income this period "
            f"(opening={opening}, closing={closing}, net={payout_amount}). "
            "Nothing to transfer.",
        )

    # 5. Resolve property name for Stripe description / metadata
    import uuid as _uuid
    property_name: str = str(opa.property_id)
    try:
        prop_uuid = _uuid.UUID(str(opa.property_id))
        prop = await db.get(Property, prop_uuid)
        if prop:
            property_name = str(prop.name)
    except ValueError:
        pass

    # 6. Call Stripe Transfer (idempotency key = "pay-obp-{period_id}")
    idempotency_key = f"pay-obp-{period_id}"
    description = (
        f"Owner payout: {property_name} "
        f"{period.period_start} to {period.period_end}"
    )
    metadata = {
        "obp_id": str(period_id),
        "opa_id": str(opa.id),
        "property_name": property_name[:40],
        "period_start": str(period.period_start),
        "period_end": str(period.period_end),
        "admin": admin_email,
    }

    logger.info(
        "owner_payout_initiating",
        obp_id=period_id,
        opa_id=opa.id,
        amount=float(payout_amount),
        destination=opa.stripe_account_id,
        idempotency_key=idempotency_key,
    )

    transfer_result = await initiate_transfer(
        account_id=str(opa.stripe_account_id),
        amount=float(payout_amount),
        description=description,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )

    if transfer_result is None or transfer_result.get("status") == "failed":
        error_msg = (transfer_result or {}).get("error", "Stripe transfer returned None")
        logger.error(
            "owner_payout_failed",
            obp_id=period_id,
            error=error_msg,
        )
        return PayOwnerResult(
            success=False,
            stripe_transfer_id=None,
            amount=payout_amount,
            error=error_msg,
        )

    stripe_transfer_id: str = transfer_result["transfer_id"]

    # 7. Persist payout on OBP (status → paid + transfer metadata)
    now = datetime.now(_UTC)
    period.status             = StatementPeriodStatus.PAID.value    # type: ignore[assignment]
    period.paid_at            = now                                  # type: ignore[assignment]
    period.paid_by            = admin_email                          # type: ignore[assignment]
    period.stripe_transfer_id = stripe_transfer_id                   # type: ignore[assignment]
    period.paid_amount        = payout_amount                        # type: ignore[assignment]
    period.updated_at         = now                                  # type: ignore[assignment]

    existing_notes = period.notes or ""
    paid_note = (
        f"PAID ${float(payout_amount):,.2f} via Stripe Transfer {stripe_transfer_id} "
        f"on {now.date().isoformat()} by {admin_email}"
    )
    period.notes = (existing_notes + "\n" + paid_note).strip()  # type: ignore[assignment]

    await db.commit()
    await db.refresh(period)

    logger.info(
        "owner_payout_completed",
        obp_id=period_id,
        stripe_transfer_id=stripe_transfer_id,
        amount=float(payout_amount),
        destination=str(opa.stripe_account_id),
        admin=admin_email,
    )

    return PayOwnerResult(
        success=True,
        stripe_transfer_id=stripe_transfer_id,
        amount=payout_amount,
    )
