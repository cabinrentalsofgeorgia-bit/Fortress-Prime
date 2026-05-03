"""
Hermes Daily Auditor — Continuous parity verification for active reservations.

Runs once per day (or on-demand).  Queries every confirmed reservation where
check_out_date >= today, fetches the current Streamline price for each, and
routes any drift through the same 3-tier FinancialApproval pipeline used by
the real-time Hermes sync worker.

Rate-limiting:
  - 1-second sleep between API calls to respect Streamline's throttle
  - Configurable batch size (default 50)
  - Graceful backoff on consecutive failures
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal
from backend.models.financial_approval import FinancialApproval
from backend.models.parity_audit import ParityAudit
from backend.models.reservation import Reservation
from backend.models.trust_ledger import TrustTransaction

logger = structlog.get_logger(service="hermes_daily_auditor")

BATCH_SIZE = 50
INTER_CALL_DELAY = 1.0        # seconds between Streamline API calls
BACKOFF_BASE = 5.0             # seconds after a failure
BACKOFF_MAX = 60.0             # cap on exponential backoff
AUTO_RESOLVE_THRESHOLD_CENTS = 1000  # ≤ $10.00


async def verify_hash_chain(db: AsyncSession) -> dict:
    """
    Walk signed trust transactions in timestamp order and recompute SHA-256 hashes.

    Returns ``{verified_count, broken_at, status}`` where ``status`` is ``ok`` or ``broken``.
    """
    result = await db.execute(
        select(TrustTransaction)
        .where(TrustTransaction.signature.isnot(None))
        .order_by(TrustTransaction.timestamp.asc(), TrustTransaction.id.asc())
    )
    rows = result.scalars().all()
    prev_sig = "GENESIS"
    for i, txn in enumerate(rows):
        payload = f"{prev_sig}|{txn.streamline_event_id}|{txn.id}|{txn.timestamp.isoformat()}"
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if expected != txn.signature:
            logger.critical(
                "trust_hash_chain_broken",
                transaction_id=str(txn.id),
                streamline_event_id=txn.streamline_event_id,
            )
            try:
                from backend.agents.nemo_observer import NemoObserver

                observer = NemoObserver()
                await observer.analyze_discrepancy(
                    reservation_id="sovereign_ledger",
                    confirmation_id="hash_chain_verification",
                    local_total=txn.signature or "",
                    streamline_total=expected,
                    delta="0",
                    local_breakdown={
                        "event": "trust_hash_chain_breach",
                        "broken_transaction_id": str(txn.id),
                        "streamline_event_id": txn.streamline_event_id,
                    },
                    streamline_breakdown={
                        "expected_hash": expected,
                        "stored_hash": txn.signature,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "trust_hash_chain_nemo_hook_error",
                    transaction_id=str(txn.id),
                    error=str(exc)[:300],
                )
            return {
                "verified_count": i,
                "broken_at": str(txn.id),
                "status": "broken",
            }
        prev_sig = txn.signature
    return {
        "verified_count": len(rows),
        "broken_at": None,
        "status": "ok",
    }


def _decimal_to_cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _streamline_quote_has_financial_data(result: object) -> bool:
    """Return true when Streamline returned an actual non-zero price payload."""
    monetary_values = (
        getattr(result, "streamline_total", Decimal("0.00")),
        getattr(result, "streamline_taxes", Decimal("0.00")),
        getattr(result, "streamline_rent", Decimal("0.00")),
    )
    if any(_decimal_to_cents(Decimal(str(value or 0))) != 0 for value in monetary_values):
        return True
    return bool(getattr(result, "fees", None))


def _deprioritize() -> None:
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass


async def _audit_single_reservation(
    db: AsyncSession,
    res: Reservation,
    client: "StreamlineClient",
) -> str:
    """Audit one reservation against Streamline.  Returns outcome label."""
    confirmation_code = res.confirmation_code
    if not confirmation_code:
        return "skipped_no_confirmation"

    result = await client.fetch_live_quote(confirmation_code)
    if result is None:
        logger.warning(
            "daily_audit_no_data",
            reservation_id=str(res.id),
            confirmation_code=confirmation_code,
        )
        return "skipped_no_data"

    local_total = Decimal(str(res.total_amount or 0))
    local_cents = _decimal_to_cents(local_total)
    if local_cents > 0 and not _streamline_quote_has_financial_data(result):
        logger.warning(
            "daily_audit_empty_streamline_price",
            reservation_id=str(res.id),
            confirmation_code=confirmation_code,
            local_cents=local_cents,
        )
        return "skipped_empty_streamline_price"

    streamline_cents = _decimal_to_cents(result.streamline_total)
    delta_cents = abs(streamline_cents - local_cents)

    local_breakdown = {
        "total_amount": str(res.total_amount),
        "total_cents": local_cents,
        "tax_amount": str(res.tax_amount),
        "source": "reservation_table",
    }
    if isinstance(res.price_breakdown, dict):
        local_breakdown["price_breakdown"] = res.price_breakdown
    if isinstance(res.tax_breakdown, dict):
        local_breakdown["tax_breakdown"] = res.tax_breakdown

    streamline_breakdown = {
        "total": str(result.streamline_total),
        "total_cents": streamline_cents,
        "taxes": str(result.streamline_taxes),
        "rent": str(result.streamline_rent),
        "fees": [
            {"name": f.name, "amount": str(f.amount), "type": f.fee_type, "bucket": f.bucket}
            for f in result.fees
        ],
    }

    # ── Tier 1: Exact match ─────────────────────────────────────
    if delta_cents == 0:
        audit = ParityAudit(
            id=uuid4(),
            reservation_id=str(res.id),
            confirmation_id=confirmation_code,
            local_total=local_total,
            streamline_total=result.streamline_total,
            delta=Decimal("0.00"),
            local_breakdown=local_breakdown,
            streamline_breakdown=streamline_breakdown,
            status="confirmed",
        )
        db.add(audit)
        await db.flush()
        return "confirmed"

    delta_dec = Decimal(delta_cents) / Decimal(100)

    # ── Tier 2: Minor variance (≤ $10) — auto-resolve ──────────
    if delta_cents <= AUTO_RESOLVE_THRESHOLD_CENTS:
        variance_direction = "under" if streamline_cents > local_cents else "over"

        audit = ParityAudit(
            id=uuid4(),
            reservation_id=str(res.id),
            confirmation_id=confirmation_code,
            local_total=local_total,
            streamline_total=result.streamline_total,
            delta=delta_dec,
            local_breakdown=local_breakdown,
            streamline_breakdown=streamline_breakdown,
            status="auto_resolved",
        )
        db.add(audit)

        approval = FinancialApproval(
            id=uuid4(),
            reservation_id=str(res.id),
            status="auto_resolved",
            discrepancy_type="daily_audit_drift",
            local_total_cents=local_cents,
            streamline_total_cents=streamline_cents,
            delta_cents=delta_cents,
            context_payload={
                "local_breakdown": local_breakdown,
                "streamline_breakdown": streamline_breakdown,
                "variance_direction": variance_direction,
                "audit_source": "hermes_daily_auditor",
                "auto_resolution": {
                    "type": "system_variance_adjustment",
                    "description": (
                        f"Daily audit auto-resolved {variance_direction}-charge of "
                        f"${delta_dec:.2f} (Δ{delta_cents}¢)"
                    ),
                    "proposed_entry": {
                        "debit_account": "Streamline Variance" if variance_direction == "under" else "Guest Receivable",
                        "credit_account": "Guest Receivable" if variance_direction == "under" else "Streamline Variance",
                        "amount_cents": delta_cents,
                    },
                },
            },
            resolved_by="hermes_daily_auditor",
            resolved_at=datetime.now(timezone.utc),
        )
        db.add(approval)
        await db.flush()

        logger.info(
            "daily_audit_auto_resolved",
            reservation_id=str(res.id),
            delta_cents=delta_cents,
            direction=variance_direction,
        )
        return "auto_resolved"

    # ── Tier 3: Material discrepancy (> $10) — queue for review ─
    audit = ParityAudit(
        id=uuid4(),
        reservation_id=str(res.id),
        confirmation_id=confirmation_code,
        local_total=local_total,
        streamline_total=result.streamline_total,
        delta=delta_dec,
        local_breakdown=local_breakdown,
        streamline_breakdown=streamline_breakdown,
        status="discrepancy",
    )
    db.add(audit)

    approval = FinancialApproval(
        id=uuid4(),
        reservation_id=str(res.id),
        status="pending",
        discrepancy_type="daily_audit_drift",
        local_total_cents=local_cents,
        streamline_total_cents=streamline_cents,
        delta_cents=delta_cents,
        context_payload={
            "local_breakdown": local_breakdown,
            "streamline_breakdown": streamline_breakdown,
            "severity": "material",
            "audit_source": "hermes_daily_auditor",
            "requires_commander_review": True,
        },
    )
    db.add(approval)
    await db.flush()

    logger.critical(
        "daily_audit_discrepancy_queued",
        reservation_id=str(res.id),
        confirmation_code=confirmation_code,
        local_cents=local_cents,
        streamline_cents=streamline_cents,
        delta_cents=delta_cents,
    )
    return "pending"


async def run_daily_audit() -> dict:
    """Audit all active reservations against Streamline.  Returns summary."""
    from backend.services.streamline_client import StreamlineClient

    today = date.today()
    stats: dict = {
        "total": 0,
        "confirmed": 0,
        "auto_resolved": 0,
        "pending": 0,
        "errors": 0,
        "skipped": 0,
        "trust_chain": None,
    }

    client = StreamlineClient()
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(Reservation)
                .where(
                    and_(
                        Reservation.check_out_date >= today,
                        Reservation.status == "confirmed",
                        Reservation.confirmation_code.isnot(None),
                    )
                )
                .order_by(Reservation.check_in_date.asc())
                .limit(BATCH_SIZE)
            )
            rows = (await db.execute(stmt)).scalars().all()
            stats["total"] = len(rows)

            if not rows:
                logger.info("daily_audit_no_active_reservations")
                await db.commit()
                stats["trust_chain"] = await verify_hash_chain(db)
                return stats

            consecutive_failures = 0

            for res in rows:
                try:
                    outcome = await _audit_single_reservation(db, res, client)
                    if outcome.startswith("skipped"):
                        stats["skipped"] += 1
                    else:
                        stats[outcome] = stats.get(outcome, 0) + 1
                    consecutive_failures = 0
                except Exception as exc:
                    stats["errors"] += 1
                    consecutive_failures += 1
                    logger.warning(
                        "daily_audit_reservation_error",
                        reservation_id=str(res.id),
                        error=str(exc)[:300],
                    )
                    backoff = min(BACKOFF_BASE * (2 ** (consecutive_failures - 1)), BACKOFF_MAX)
                    await asyncio.sleep(backoff)
                    continue

                await asyncio.sleep(INTER_CALL_DELAY)

            await db.commit()
            stats["trust_chain"] = await verify_hash_chain(db)

    finally:
        await client.close()

    logger.info("daily_audit_complete", **stats)
    return stats


async def hermes_daily_auditor_loop() -> None:
    """Run the daily auditor at 00:00 UTC every day (FastAPI lifespan / standalone)."""
    _deprioritize()
    logger.info(
        "hermes_continuous_auditor_scheduled",
        schedule="00:00 daily",
        message="🛡️ Hermes Continuous Auditor scheduled for 00:00 daily.",
    )

    while True:
        now = datetime.now(timezone.utc)
        next_midnight = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        sleep_seconds = max(0.0, (next_midnight - now).total_seconds())
        logger.info(
            "hermes_auditor_sleeping_until_midnight",
            seconds=int(sleep_seconds),
            next_run_utc=next_midnight.isoformat(),
        )
        await asyncio.sleep(sleep_seconds)

        try:
            result = await run_daily_audit()
            logger.info("hermes_daily_audit_finished", **result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("hermes_daily_auditor_loop_error", error=str(exc)[:400])
