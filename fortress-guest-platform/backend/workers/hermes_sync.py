"""
Hermes Sync Worker — Offline booking buffer retry agent.

When a storefront checkout succeeds at the Stripe layer but the
Streamline PMS push fails, the booking is saved to `pending_sync`.
Hermes retries every 60 seconds until Streamline acknowledges.

After 10 failed attempts the record is flagged 'failed' and an
alert is logged for manual intervention — the guest's payment was
already captured by Stripe, so the booking WILL be honoured regardless.

After a successful sync, Hermes runs a parity audit: it calls
fetch_live_quote() with the confirmation_id to compare Streamline's
total against the local ledger.  Discrepancies are routed through a
3-tier queue:
  - delta == 0          → INFO log, ParityAudit confirmed
  - 0 < |delta| ≤ $10  → auto-resolved FinancialApproval + variance adjustment
  - |delta| > $10       → pending FinancialApproval + NeMo Observer alert
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.financial_approval import FinancialApproval
from backend.models.pending_sync import PendingSync
from backend.models.parity_audit import ParityAudit

logger = structlog.get_logger(service="hermes_sync")

INTERVAL_SECONDS = 60
MAX_ATTEMPTS = 10
AUTO_RESOLVE_THRESHOLD_CENTS = 1000  # ≤ $10.00


def _deprioritize() -> None:
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass


def _decimal_to_cents(value: Decimal) -> int:
    """Convert a dollar Decimal to integer cents with half-up rounding."""
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


async def _run_parity_audit(
    db: AsyncSession,
    reservation_id: str,
    confirmation_code: str,
    local_total: Decimal,
    local_breakdown: dict,
) -> None:
    """Compare local ledger total with Streamline's GetReservationPrice total.

    3-tier resolution:
      1. delta_cents == 0           → confirmed (INFO)
      2. 0 < |delta_cents| ≤ 1000  → auto_resolved FinancialApproval + variance line
      3. |delta_cents| > 1000       → pending FinancialApproval + NeMo Observer alert
    """
    try:
        from backend.services.streamline_client import StreamlineClient

        client = StreamlineClient()
        try:
            result = await client.fetch_live_quote(confirmation_code)
        finally:
            await client.close()

        if result is None:
            logger.warning(
                "parity_audit_skipped_no_data",
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
            )
            return

        local_cents = _decimal_to_cents(local_total)
        streamline_cents = _decimal_to_cents(result.streamline_total)
        delta_cents = abs(streamline_cents - local_cents)

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
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                local_total=local_total,
                streamline_total=result.streamline_total,
                delta=Decimal("0.00"),
                local_breakdown=local_breakdown,
                streamline_breakdown=streamline_breakdown,
                status="confirmed",
            )
            db.add(audit)
            await db.commit()
            logger.info(
                "parity_confirmed",
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
            )

        # ── Tier 2: Minor variance (≤ $10) — auto-resolve ──────────
        elif delta_cents <= AUTO_RESOLVE_THRESHOLD_CENTS:
            delta_dec = Decimal(delta_cents) / Decimal(100)

            audit = ParityAudit(
                id=uuid4(),
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                local_total=local_total,
                streamline_total=result.streamline_total,
                delta=delta_dec,
                local_breakdown=local_breakdown,
                streamline_breakdown=streamline_breakdown,
                status="auto_resolved",
            )
            db.add(audit)

            variance_direction = "under" if streamline_cents > local_cents else "over"
            context = {
                "local_breakdown": local_breakdown,
                "streamline_breakdown": streamline_breakdown,
                "variance_direction": variance_direction,
                "auto_resolution": {
                    "type": "system_variance_adjustment",
                    "description": (
                        f"Auto-resolved {variance_direction}-charge of "
                        f"${delta_dec:.2f} (Δ{delta_cents}¢)"
                    ),
                    "proposed_entry": {
                        "debit_account": "Streamline Variance" if variance_direction == "under" else "Guest Receivable",
                        "credit_account": "Guest Receivable" if variance_direction == "under" else "Streamline Variance",
                        "amount_cents": delta_cents,
                    },
                },
            }

            approval = FinancialApproval(
                id=uuid4(),
                reservation_id=reservation_id,
                status="auto_resolved",
                discrepancy_type="parity_drift",
                local_total_cents=local_cents,
                streamline_total_cents=streamline_cents,
                delta_cents=delta_cents,
                context_payload=context,
                resolved_by="hermes_auto_resolver",
                resolved_at=datetime.now(timezone.utc),
            )
            db.add(approval)
            await db.commit()

            logger.info(
                "parity_auto_resolved",
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                delta_cents=delta_cents,
                direction=variance_direction,
            )

        # ── Tier 3: Material discrepancy (> $10) — queue for review ─
        else:
            delta_dec = Decimal(delta_cents) / Decimal(100)

            audit = ParityAudit(
                id=uuid4(),
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                local_total=local_total,
                streamline_total=result.streamline_total,
                delta=delta_dec,
                local_breakdown=local_breakdown,
                streamline_breakdown=streamline_breakdown,
                status="discrepancy",
            )
            db.add(audit)

            context = {
                "local_breakdown": local_breakdown,
                "streamline_breakdown": streamline_breakdown,
                "severity": "material",
                "requires_commander_review": True,
            }

            approval = FinancialApproval(
                id=uuid4(),
                reservation_id=reservation_id,
                status="pending",
                discrepancy_type="parity_drift",
                local_total_cents=local_cents,
                streamline_total_cents=streamline_cents,
                delta_cents=delta_cents,
                context_payload=context,
            )
            db.add(approval)
            await db.commit()

            logger.critical(
                "parity_breach_queued",
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                local_cents=local_cents,
                streamline_cents=streamline_cents,
                delta_cents=delta_cents,
            )

            await _stream_to_nemo_observer(
                reservation_id=reservation_id,
                confirmation_id=confirmation_code,
                local_total=str(local_total),
                streamline_total=str(result.streamline_total),
                delta=str(delta_dec),
                local_breakdown=local_breakdown,
                streamline_breakdown=streamline_breakdown,
            )

        await _auto_learn_fees(db, result.fees)

    except Exception as exc:
        logger.error(
            "parity_audit_error",
            reservation_id=reservation_id,
            confirmation_id=confirmation_code,
            error=str(exc)[:400],
        )


async def _stream_to_nemo_observer(
    reservation_id: str,
    confirmation_id: str,
    local_total: str,
    streamline_total: str,
    delta: str,
    local_breakdown: dict,
    streamline_breakdown: dict,
) -> None:
    """Fire-and-forget: send discrepancy to the NeMo Observer for root-cause analysis."""
    try:
        from backend.agents.nemo_observer import NemoObserver

        observer = NemoObserver()
        analysis = await observer.analyze_discrepancy(
            reservation_id=reservation_id,
            confirmation_id=confirmation_id,
            local_total=local_total,
            streamline_total=streamline_total,
            delta=delta,
            local_breakdown=local_breakdown,
            streamline_breakdown=streamline_breakdown,
        )

        if analysis:
            logger.info(
                "nemo_observer_verdict",
                reservation_id=reservation_id,
                root_cause=analysis.get("root_cause"),
                confidence=analysis.get("confidence"),
                recommendation=analysis.get("recommendation"),
                discrepant_items=len(analysis.get("discrepant_items", [])),
            )
    except Exception as exc:
        logger.warning(
            "nemo_observer_hook_error",
            reservation_id=reservation_id,
            error=str(exc)[:300],
        )


async def _auto_learn_fees(db: AsyncSession, fees: list) -> None:
    """Insert any unknown fee names into the local fees table with is_active=false."""
    for fee in fees:
        if fee.fee_type != "fee":
            continue
        try:
            existing = await db.execute(
                text("SELECT id FROM fees WHERE LOWER(name) = LOWER(:name) LIMIT 1"),
                {"name": fee.name},
            )
            if existing.scalar_one_or_none() is None:
                await db.execute(
                    text(
                        "INSERT INTO fees (id, name, flat_amount, fee_type, is_active, created_at, updated_at) "
                        "VALUES (:id, :name, :amount, 'flat', false, NOW(), NOW()) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": str(uuid4()),
                        "name": fee.name,
                        "amount": float(fee.amount),
                    },
                )
                await db.commit()
                logger.warning(
                    "new_streamline_fee_discovered",
                    fee_name=fee.name,
                    fee_amount=str(fee.amount),
                    streamline_id=fee.streamline_id,
                )
        except Exception as exc:
            logger.warning(
                "auto_learn_fee_error",
                fee_name=fee.name,
                error=str(exc)[:200],
            )


async def _process_one(db: AsyncSession, row: PendingSync) -> bool:
    """Attempt to sync a single pending record to Streamline.

    The Reverse Push (Phase 4): Instead of letting Streamline calculate
    its own price, we push the local ``grand_total_cents`` as a fixed
    price override.  This reduces Streamline to a dumb calendar/reporting
    database — the sovereign ledger dictates the financial terms.

    Returns True if sync succeeded (or was skipped because Streamline
    is not configured), False on failure.
    """
    if not settings.streamline_api_key or not settings.streamline_api_secret:
        row.status = "synced"
        row.resolved_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("hermes_sync_skipped_no_streamline", reservation_id=str(row.reservation_id))
        return True

    from backend.integrations.streamline_vrs import StreamlineVRS
    vrs = StreamlineVRS()

    try:
        payload = row.payload or {}
        confirmation_code = payload.get("confirmation_code")

        if row.sync_type == "create_reservation" and settings.streamline_sovereign_bridge_settlement_enabled:
            pushed = await _reverse_push_to_streamline(db, row, vrs, payload)
            if pushed:
                return True

        if confirmation_code:
            result = await vrs.fetch_reservation_info(confirmation_code)
            if result:
                row.status = "synced"
                row.resolved_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info(
                    "hermes_sync_confirmed",
                    reservation_id=str(row.reservation_id),
                    confirmation=confirmation_code,
                )

                local_total = Decimal(str(payload.get("total_amount", "0.00")))
                local_breakdown = payload.get("price_breakdown", {})
                await _run_parity_audit(
                    db,
                    str(row.reservation_id),
                    confirmation_code,
                    local_total,
                    local_breakdown,
                )

                return True

        row.status = "synced"
        row.resolved_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "hermes_sync_local_only",
            reservation_id=str(row.reservation_id),
            note="Reservation exists in local DB; Streamline sync deferred to batch worker",
        )
        return True

    except Exception as exc:
        row.attempt_count += 1
        row.last_error = str(exc)[:500]

        if row.attempt_count >= MAX_ATTEMPTS:
            row.status = "failed"
            logger.critical(
                "hermes_sync_exhausted",
                reservation_id=str(row.reservation_id),
                attempts=row.attempt_count,
                error=str(exc)[:300],
            )
        else:
            logger.warning(
                "hermes_sync_retry",
                reservation_id=str(row.reservation_id),
                attempt=row.attempt_count,
                error=str(exc)[:300],
            )

        await db.commit()
        return False


async def _reverse_push_to_streamline(
    db: AsyncSession,
    row: PendingSync,
    vrs: "StreamlineVRS",
    payload: dict,
) -> bool:
    """Push the sovereign reservation to Streamline with a fixed price override.

    Sends the local ``amount_cents`` as ``price`` / ``rent_amount`` with
    ``price_type=fixed`` so Streamline records our total instead of
    computing its own.
    """
    from backend.models.property import Property
    from backend.models.reservation import Reservation

    reservation = await db.get(Reservation, row.reservation_id)
    if reservation is None:
        return False

    prop = await db.get(Property, reservation.property_id)
    if prop is None or not (prop.streamline_property_id or "").strip():
        return False

    try:
        unit_id = int(str(prop.streamline_property_id).strip())
    except ValueError:
        return False

    method = (settings.streamline_sovereign_bridge_reservation_method or "").strip()
    if not method:
        return False

    amount_cents = payload.get("amount_cents")
    if amount_cents is None and reservation.total_amount is not None:
        amount_cents = int(
            (Decimal(str(reservation.total_amount)) * 100)
            .to_integral_value(rounding=ROUND_HALF_UP)
        )

    push_params: dict[str, str] = {
        "unit_id": str(unit_id),
        "startdate": reservation.check_in_date.strftime("%m/%d/%Y"),
        "enddate": reservation.check_out_date.strftime("%m/%d/%Y"),
        "confirmation_code": str(reservation.confirmation_code or ""),
        "guest_email": str(reservation.guest_email or ""),
        "guest_name": str(reservation.guest_name or ""),
        "notes": (
            f"SOVEREIGN_REVERSE_PUSH confirmation={reservation.confirmation_code} "
            f"pi={payload.get('stripe_payment_intent_id', 'N/A')}"
        ),
    }

    if amount_cents and amount_cents > 0:
        total_dollars = f"{amount_cents / 100:.2f}"
        push_params["price"] = total_dollars
        push_params["rent_amount"] = total_dollars
        push_params["price_type"] = "fixed"

    raw = await vrs.dispatch_sovereign_write_rpc(
        method,
        push_params,
        log_name="hermes_reverse_push",
        log_context={
            "reservation_id": str(row.reservation_id),
            "unit_id": unit_id,
        },
    )

    if raw.get("ok") and not raw.get("skipped"):
        row.status = "synced"
        row.resolved_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "hermes_reverse_push_success",
            reservation_id=str(row.reservation_id),
            unit_id=unit_id,
            amount_cents=amount_cents,
            confirmation=reservation.confirmation_code,
        )

        local_total = Decimal(str(reservation.total_amount or "0.00"))
        await _run_parity_audit(
            db,
            str(row.reservation_id),
            str(reservation.confirmation_code),
            local_total,
            payload.get("price_breakdown", {}),
        )
        return True

    logger.warning(
        "hermes_reverse_push_failed",
        reservation_id=str(row.reservation_id),
        raw_reason=str(raw.get("reason") or raw.get("error") or "unknown")[:300],
    )
    return False


async def run_hermes_cycle() -> dict:
    """Process all pending sync records. Returns summary stats."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(PendingSync)
            .where(PendingSync.status == "pending")
            .order_by(PendingSync.created_at.asc())
            .limit(20)
        )
        rows = (await db.execute(stmt)).scalars().all()

        if not rows:
            return {"pending": 0, "synced": 0, "failed": 0}

        synced = 0
        failed = 0
        for row in rows:
            success = await _process_one(db, row)
            if success:
                synced += 1
            else:
                failed += 1
            await asyncio.sleep(0.5)

        logger.info(
            "hermes_cycle_complete",
            processed=len(rows),
            synced=synced,
            failed=failed,
        )
        return {"pending": len(rows), "synced": synced, "failed": failed}


async def hermes_sync_loop() -> None:
    """Infinite loop — run from ARQ worker startup."""
    _deprioritize()
    logger.info("hermes_sync_started", interval=INTERVAL_SECONDS)

    while True:
        try:
            await run_hermes_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("hermes_sync_loop_error", error=str(exc)[:400])
        await asyncio.sleep(INTERVAL_SECONDS)
