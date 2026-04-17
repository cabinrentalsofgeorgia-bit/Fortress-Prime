"""Read-only NeMo Command Center aggregates for sovereign trust ledger monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from backend.api.command_c2 import PULSE_ACCESS
from backend.core.database import get_db
from backend.models.staff import StaffUser
from backend.models.trust_ledger import TrustLedgerEntry, TrustTransaction
from backend.workers.hermes_daily_auditor import verify_hash_chain

router = APIRouter()


@router.get("/")
async def trust_ledger_command_center(
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Hash-chain health (Hermes verifier) plus the 50 most recent trust transactions
    with ledger entry summaries for the Command Center dashboard.
    """
    hash_chain = await verify_hash_chain(db)

    count_stmt = select(func.count()).select_from(TrustTransaction)
    total_result = await db.execute(count_stmt)
    total_transaction_count = int(total_result.scalar_one() or 0)

    stmt = (
        select(TrustTransaction)
        .options(
            selectinload(TrustTransaction.entries).joinedload(TrustLedgerEntry.account),
        )
        .order_by(TrustTransaction.timestamp.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    rows = result.scalars().unique().all()

    transactions: list[dict] = []
    for txn in rows:
        entry_payloads: list[dict] = []
        for ent in txn.entries:
            acct = ent.account
            entry_payloads.append(
                {
                    "account_name": acct.name if acct is not None else "?",
                    "amount_cents": ent.amount_cents,
                    "entry_type": ent.entry_type.value,
                }
            )
        transactions.append(
            {
                "id": str(txn.id),
                "streamline_event_id": txn.streamline_event_id,
                "timestamp": txn.timestamp.isoformat(),
                "signature": txn.signature,
                "previous_signature": txn.previous_signature,
                "entries": entry_payloads,
            }
        )

    return {
        "hash_chain": hash_chain,
        "transactions": transactions,
        "total_transaction_count": total_transaction_count,
    }
