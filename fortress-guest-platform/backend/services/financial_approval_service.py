"""
Financial Approval Execution Service — 1-click commander approval.

When the commander approves a pending ``FinancialApproval`` from the
sovereign queue, this service executes one of two resolution strategies:

  **absorb** — Post a variance trust entry to balance the internal
  ledger.  The guest is not billed for the discrepancy.

  **invoice** — Create a Stripe Invoice for ``delta_cents`` and email
  it to the guest.  Post an Accounts Receivable trust entry.  When the
  guest pays, the ``invoice.paid`` webhook can auto-clear the receivable.

Both strategies update ``Reservation.total_amount`` to match the
Streamline total so the shadow folio is officially balanced.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.financial_approval import FinancialApproval
from backend.models.guest import Guest
from backend.models.reservation import Reservation
from backend.services.trust_ledger import post_variance_trust_entry

logger = structlog.get_logger()

TWO_PLACES = Decimal("0.01")


async def execute_financial_approval(
    db: AsyncSession,
    approval_id: str,
    commander_username: str,
    strategy: Literal["absorb", "invoice"] = "absorb",
) -> FinancialApproval:
    """
    Execute a pending financial approval with the chosen resolution
    strategy.

    Raises ``ValueError`` when the approval is not found or not pending.
    """
    approval_uuid = UUID(approval_id)

    result = await db.execute(
        select(FinancialApproval).where(
            FinancialApproval.id == approval_uuid,
            FinancialApproval.status == "pending",
        )
    )
    approval = result.scalars().first()
    if approval is None:
        raise ValueError(
            f"FinancialApproval {approval_id} not found or not in 'pending' status"
        )

    reservation = await _resolve_reservation(db, approval.reservation_id)

    if strategy == "invoice":
        await _execute_invoice_strategy(db, approval, reservation, commander_username)
    else:
        await _execute_absorb_strategy(db, approval, commander_username)

    if reservation is not None:
        new_total = Decimal(approval.streamline_total_cents) / Decimal(100)
        new_total = new_total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        reservation.total_amount = new_total
        logger.info(
            "reservation_total_rebalanced",
            reservation_id=str(reservation.id),
            old_total_cents=approval.local_total_cents,
            new_total_cents=approval.streamline_total_cents,
        )

    now = datetime.now(timezone.utc)
    approval.status = "approved"
    approval.resolution_strategy = strategy
    approval.resolved_by = commander_username
    approval.resolved_at = now

    await db.flush()

    logger.info(
        "financial_approval_executed",
        approval_id=approval_id,
        commander=commander_username,
        strategy=strategy,
        delta_cents=approval.delta_cents,
    )
    return approval


async def _resolve_reservation(
    db: AsyncSession,
    reservation_id_str: str,
) -> Reservation | None:
    """Look up a Reservation by confirmation_code or streamline_reservation_id."""
    result = await db.execute(
        select(Reservation).where(
            Reservation.confirmation_code == reservation_id_str,
        )
    )
    reservation = result.scalars().first()
    if reservation is not None:
        return reservation

    result = await db.execute(
        select(Reservation).where(
            Reservation.streamline_reservation_id == reservation_id_str,
        )
    )
    return result.scalars().first()


async def _execute_absorb_strategy(
    db: AsyncSession,
    approval: FinancialApproval,
    commander_username: str,
) -> None:
    """Post the variance trust entry to balance the internal ledger."""
    context = approval.context_payload or {}
    auto_resolution = context.get("auto_resolution", {})
    proposed_entry = auto_resolution.get("proposed_entry")

    if proposed_entry is None:
        raise ValueError(
            f"FinancialApproval {approval.id} has no proposed_entry in context_payload"
        )

    debit_account = proposed_entry["debit_account"]
    credit_account = proposed_entry["credit_account"]
    entry_amount_cents = int(proposed_entry["amount_cents"])

    if entry_amount_cents <= 0:
        raise ValueError(
            f"proposed_entry.amount_cents must be positive, got {entry_amount_cents}"
        )

    await post_variance_trust_entry(
        db,
        reservation_id=approval.reservation_id,
        amount_cents=entry_amount_cents,
        debit_account_name=debit_account,
        credit_account_name=credit_account,
        event_id=f"approval:{approval.id}",
    )

    logger.info(
        "absorb_strategy_executed",
        approval_id=str(approval.id),
        debit_account=debit_account,
        credit_account=credit_account,
        amount_cents=entry_amount_cents,
    )


async def _execute_invoice_strategy(
    db: AsyncSession,
    approval: FinancialApproval,
    reservation: Reservation | None,
    commander_username: str,
) -> None:
    """
    Create a Stripe Invoice for the delta and post an Accounts Receivable
    trust entry.
    """
    from backend.integrations.stripe_payments import StripePayments

    delta_cents = abs(approval.delta_cents)
    if delta_cents <= 0:
        raise ValueError("Cannot invoice a zero-cent delta")

    guest = None
    if reservation is not None:
        guest = await db.get(Guest, reservation.guest_id)

    if guest is None:
        raise ValueError(
            f"Cannot invoice — no guest found for reservation "
            f"{approval.reservation_id}"
        )

    guest_email = guest.email or ""
    guest_name = getattr(guest, "full_name", "") or f"{guest.first_name} {guest.last_name}"
    if not guest_email:
        raise ValueError(
            f"Cannot invoice — guest {guest.id} has no email address"
        )

    stripe_client = StripePayments()
    customer_id = await stripe_client.get_or_create_customer(
        email=guest_email,
        name=guest_name,
        stripe_customer_id=guest.stripe_customer_id,
    )

    if not guest.stripe_customer_id:
        guest.stripe_customer_id = customer_id
        await db.flush()

    delta_dollars = Decimal(delta_cents) / Decimal(100)
    description = (
        f"Pricing adjustment for reservation {approval.reservation_id} "
        f"— ${delta_dollars:.2f}"
    )

    invoice_result = await stripe_client.create_invoice(
        customer_id=customer_id,
        amount_cents=delta_cents,
        description=description,
        reservation_id=approval.reservation_id,
        approval_id=str(approval.id),
    )

    approval.stripe_invoice_id = invoice_result["invoice_id"]

    await post_variance_trust_entry(
        db,
        reservation_id=approval.reservation_id,
        amount_cents=delta_cents,
        debit_account_name="Accounts Receivable",
        credit_account_name="Guest Advance Deposits",
        event_id=f"invoice:{invoice_result['invoice_id']}",
    )

    logger.info(
        "invoice_strategy_executed",
        approval_id=str(approval.id),
        invoice_id=invoice_result["invoice_id"],
        hosted_url=invoice_result["hosted_url"],
        amount_cents=delta_cents,
        customer_id=customer_id,
        guest_email=guest_email,
    )
