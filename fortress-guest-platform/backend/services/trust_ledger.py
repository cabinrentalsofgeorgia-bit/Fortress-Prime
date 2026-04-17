"""
Sovereign Trust Ledger — Double-entry posting service.

Posts debit/credit entries to ``trust_ledger_entries`` linked by a
``TrustTransaction``.  Supports both swarm-gated transactions (with a
``TrustDecision``) and system-initiated transactions (Stripe checkout,
approval execution) where ``decision_id`` is NULL.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time import utc_now
from backend.models.trust_ledger import (
    TrustAccount,
    TrustAccountType,
    TrustLedgerEntry,
    TrustLedgerEntryType,
    TrustTransaction,
)

logger = structlog.get_logger()


async def _sign_transaction(db: AsyncSession, txn: TrustTransaction) -> None:
    """Compute SHA-256 hash chain fields on ``txn`` (INSERT only — DB forbids UPDATE)."""
    result = await db.execute(
        select(TrustTransaction.signature)
        .where(TrustTransaction.signature.isnot(None))
        .order_by(TrustTransaction.timestamp.desc())
        .limit(1)
    )
    prev_sig = result.scalar_one_or_none() or "GENESIS"
    payload = f"{prev_sig}|{txn.streamline_event_id}|{txn.id}|{txn.timestamp.isoformat()}"
    txn.previous_signature = prev_sig if prev_sig != "GENESIS" else None
    txn.signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _add_trust_transaction_idempotent(
    db: AsyncSession,
    txn: TrustTransaction,
) -> TrustTransaction:
    """Insert ``txn`` or return the existing row when ``streamline_event_id`` collides."""
    await _sign_transaction(db, txn)
    try:
        async with db.begin_nested():
            db.add(txn)
            await db.flush()
    except IntegrityError:
        result = await db.execute(
            select(TrustTransaction).where(
                TrustTransaction.streamline_event_id == txn.streamline_event_id
            )
        )
        existing = result.scalars().first()
        if existing is not None:
            logger.info(
                "trust_transaction_idempotent_hit",
                streamline_event_id=txn.streamline_event_id,
                existing_transaction_id=str(existing.id),
            )
            db.expunge(txn)
            return existing
        raise
    return txn


async def _get_or_create_account(
    db: AsyncSession,
    name: str,
    account_type: TrustAccountType,
) -> TrustAccount:
    """Return the TrustAccount with the given name, creating it if absent."""
    result = await db.execute(
        select(TrustAccount).where(TrustAccount.name == name).limit(1)
    )
    account = result.scalars().first()
    if account is not None:
        return account

    account = TrustAccount(id=uuid4(), name=name, type=account_type)
    db.add(account)
    await db.flush()
    logger.info("trust_account_created", name=name, type=account_type.value)
    return account


async def post_checkout_trust_entry(
    db: AsyncSession,
    reservation_id: str,
    amount_cents: int,
    stripe_pi_id: str,
) -> TrustTransaction:
    """
    Post the guest-payment double-entry to the sovereign trust ledger.

    Debit:  amount_cents → "Operating Cash" (Asset)
    Credit: amount_cents → "Guest Advance Deposits" (Liability)

    Called immediately after a successful Stripe PaymentIntent confirmation
    inside ``_process_storefront_settlement()``.
    """
    if amount_cents <= 0:
        raise ValueError(f"amount_cents must be positive, got {amount_cents}")

    cash_account = await _get_or_create_account(
        db, "Operating Cash", TrustAccountType.ASSET,
    )
    deposit_account = await _get_or_create_account(
        db, "Guest Advance Deposits", TrustAccountType.LIABILITY,
    )

    txn = TrustTransaction(
        id=uuid4(),
        streamline_event_id=f"stripe:{stripe_pi_id}",
        decision_id=None,
        timestamp=utc_now(),
    )
    expected_txn_id = txn.id
    txn = await _add_trust_transaction_idempotent(db, txn)
    if txn.id != expected_txn_id:
        return txn

    debit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=cash_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.DEBIT,
    )
    credit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=deposit_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.CREDIT,
    )
    db.add(debit_entry)
    db.add(credit_entry)
    await db.flush()

    logger.info(
        "trust_entry_posted",
        transaction_id=str(txn.id),
        reservation_id=reservation_id,
        stripe_pi_id=stripe_pi_id,
        amount_cents=amount_cents,
        debit_account="Operating Cash",
        credit_account="Guest Advance Deposits",
    )
    return txn


async def post_invoice_clearing_entry(
    db: AsyncSession,
    amount_cents: int,
    stripe_invoice_id: str,
) -> TrustTransaction:
    """
    Clear the Accounts Receivable created by the invoice strategy when
    the guest pays the Stripe Invoice.

    Debit:  amount_cents → "Operating Cash" (Asset — cash received)
    Credit: amount_cents → "Accounts Receivable" (Asset — receivable zeroed)

    Called from the ``invoice.paid`` webhook handler.
    """
    if amount_cents <= 0:
        raise ValueError(f"amount_cents must be positive, got {amount_cents}")

    cash_account = await _get_or_create_account(
        db, "Operating Cash", TrustAccountType.ASSET,
    )
    ar_account = await _get_or_create_account(
        db, "Accounts Receivable", TrustAccountType.ASSET,
    )

    txn = TrustTransaction(
        id=uuid4(),
        streamline_event_id=f"invoice_paid:{stripe_invoice_id}",
        decision_id=None,
        timestamp=utc_now(),
    )
    expected_txn_id = txn.id
    txn = await _add_trust_transaction_idempotent(db, txn)
    if txn.id != expected_txn_id:
        return txn

    debit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=cash_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.DEBIT,
    )
    credit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=ar_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.CREDIT,
    )
    db.add(debit_entry)
    db.add(credit_entry)
    await db.flush()

    logger.info(
        "invoice_clearing_entry_posted",
        transaction_id=str(txn.id),
        stripe_invoice_id=stripe_invoice_id,
        amount_cents=amount_cents,
        debit_account="Operating Cash",
        credit_account="Accounts Receivable",
    )
    return txn


async def post_variance_trust_entry(
    db: AsyncSession,
    reservation_id: str,
    amount_cents: int,
    debit_account_name: str,
    credit_account_name: str,
    event_id: str,
) -> TrustTransaction:
    """
    Post an arbitrary debit/credit pair to the trust ledger.

    Used by the 1-click approval service to execute proposed variance
    adjustments from the FinancialApproval queue.
    """
    if amount_cents <= 0:
        raise ValueError(f"amount_cents must be positive, got {amount_cents}")

    debit_account = await _get_or_create_account(
        db, debit_account_name, TrustAccountType.ASSET,
    )
    credit_account = await _get_or_create_account(
        db, credit_account_name, TrustAccountType.ASSET,
    )

    txn = TrustTransaction(
        id=uuid4(),
        streamline_event_id=event_id,
        decision_id=None,
        timestamp=utc_now(),
    )
    expected_txn_id = txn.id
    txn = await _add_trust_transaction_idempotent(db, txn)
    if txn.id != expected_txn_id:
        return txn

    debit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=debit_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.DEBIT,
    )
    credit_entry = TrustLedgerEntry(
        id=uuid4(),
        transaction_id=txn.id,
        account_id=credit_account.id,
        amount_cents=amount_cents,
        entry_type=TrustLedgerEntryType.CREDIT,
    )
    db.add(debit_entry)
    db.add(credit_entry)
    await db.flush()

    logger.info(
        "variance_trust_entry_posted",
        transaction_id=str(txn.id),
        reservation_id=reservation_id,
        amount_cents=amount_cents,
        debit_account=debit_account_name,
        credit_account=credit_account_name,
        event_id=event_id,
    )
    return txn
