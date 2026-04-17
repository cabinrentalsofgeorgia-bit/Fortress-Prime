"""
Strike 19 — Bridge Authority: optional Streamline notification for sovereign checkout holds.

Strike 20 — Transactional settlement: after ``payment_intent.succeeded`` converts a hold to a
:class:`~backend.models.reservation.Reservation`, optional Streamline RPC can mirror finality.

Sovereign ledger of record remains ``reservation_holds`` / ``reservations`` in Postgres.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.integrations.circuit_breaker import queue_deferred_write
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.models.reservation import Reservation

logger = structlog.get_logger(service="sovereign_inventory")


def _sovereign_settlement_notes(
    reservation: Reservation,
    stripe_payment_intent_id: str | None,
    *,
    extra_note: str = "",
) -> str:
    parts = [
        "SOVEREIGN_SETTLEMENT_CONFIRMED",
        f"confirmation={reservation.confirmation_code}",
    ]
    if stripe_payment_intent_id:
        parts.append(f"pi={stripe_payment_intent_id}")
    if extra_note:
        parts.append(extra_note)
    return " ".join(parts)


def _sovereign_settlement_extra_params(
    reservation: Reservation,
    unit_id: int,
    stripe_payment_intent_id: str | None,
    *,
    notes_extra: str = "",
) -> dict[str, str]:
    params: dict[str, str] = {
        "unit_id": str(unit_id),
        "startdate": reservation.check_in_date.strftime("%m/%d/%Y"),
        "enddate": reservation.check_out_date.strftime("%m/%d/%Y"),
        "confirmation_code": str(reservation.confirmation_code or ""),
        "guest_email": str(reservation.guest_email or ""),
        "guest_name": str(reservation.guest_name or ""),
        "notes": _sovereign_settlement_notes(
            reservation,
            stripe_payment_intent_id,
            extra_note=notes_extra,
        ),
    }

    if reservation.total_amount is not None:
        from decimal import Decimal, ROUND_HALF_UP

        total_cents = int(
            (Decimal(str(reservation.total_amount)) * 100)
            .to_integral_value(rounding=ROUND_HALF_UP)
        )
        total_dollars = f"{total_cents / 100:.2f}"
        params["price"] = total_dollars
        params["rent_amount"] = total_dollars
        params["price_type"] = "fixed"

    return params


def _streamline_settlement_queue_payload(
    rpc_method: str,
    extra_params: dict[str, str],
) -> dict[str, Any] | None:
    """Full JSON-RPC body for ``deferred_api_writes`` (same shape as circuit-deferred Streamline writes)."""
    vrs = StreamlineVRS()
    m = (rpc_method or "").strip()
    if not vrs.is_configured or not m:
        return None
    return {
        "methodName": m,
        "params": {
            "token_key": vrs.token_key,
            "token_secret": vrs.token_secret,
            **extra_params,
        },
    }


def _sync_queue_streamline_payload(payload: dict[str, Any], method: str) -> int:
    return queue_deferred_write("streamline", method, payload)


@dataclass(frozen=True)
class BridgeHoldResult:
    """Outcome of a legacy bridge attempt (sovereign checkout is unaffected by ``ok``)."""

    ok: bool
    legacy_notified: bool
    detail: str
    raw: dict[str, Any] | None = None


class SovereignInventoryManager:
    """
    Forces optional alignment with Streamline when the account exposes a suitable RPC method.
    """

    def __init__(self, *, client: StreamlineVRS | None = None) -> None:
        self._client = client or StreamlineVRS()

    async def hold_dates(
        self,
        *,
        streamline_unit_id: int,
        check_in: date,
        check_out: date,
        note: str = "SOVEREIGN_CHECKOUT_IN_PROGRESS",
        hold_duration_minutes: int | None = None,
    ) -> BridgeHoldResult:
        ttl = int(
            hold_duration_minutes
            if hold_duration_minutes is not None
            else settings.reservation_hold_ttl_minutes
        )
        if not settings.streamline_sovereign_bridge_hold_enabled:
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="bridge_disabled",
            )

        method = (settings.streamline_sovereign_bridge_hold_method or "").strip()
        if not method:
            logger.warning(
                "sovereign_bridge_hold_missing_method",
                unit_id=streamline_unit_id,
                message="STREAMLINE_SOVEREIGN_BRIDGE_HOLD_METHOD empty — no RPC sent",
            )
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="method_not_configured",
            )

        raw = await self._client.push_sovereign_hold_block(
            streamline_unit_id,
            check_in,
            check_out,
            note=note,
            hold_duration_minutes=ttl,
            rpc_method=method,
        )
        if raw.get("ok") and not raw.get("skipped"):
            legacy = True
            detail = "deferred" if raw.get("deferred") else "rpc_ok"
        elif raw.get("skipped"):
            legacy = False
            detail = str(raw.get("reason") or "skipped")
        else:
            legacy = False
            detail = str(raw.get("reason") or raw.get("error") or "rpc_failed")

        logger.info(
            "sovereign_inventory_bridge_hold",
            unit_id=streamline_unit_id,
            legacy_notified=legacy,
            detail=detail,
        )
        return BridgeHoldResult(ok=True, legacy_notified=legacy, detail=detail, raw=raw)

    async def hold_dates_for_property(
        self,
        db: AsyncSession,
        *,
        property_id: UUID,
        check_in: date,
        check_out: date,
        note: str = "SOVEREIGN_CHECKOUT_IN_PROGRESS",
    ) -> BridgeHoldResult:
        prop = await db.get(Property, property_id)
        if prop is None or not (prop.streamline_property_id or "").strip():
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="no_streamline_unit_id",
            )
        try:
            unit_id = int(str(prop.streamline_property_id).strip())
        except ValueError:
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="invalid_streamline_unit_id",
            )
        return await self.hold_dates(
            streamline_unit_id=unit_id,
            check_in=check_in,
            check_out=check_out,
            note=note,
        )

    async def finalize_legacy_reservation(
        self,
        db: AsyncSession,
        *,
        reservation_id: UUID,
        stripe_payment_intent_id: str | None = None,
    ) -> BridgeHoldResult:
        """
        Strike 20 — after sovereign financial finality (reservation row), optionally notify Streamline.

        RPC shape is account-specific; params mirror read APIs where possible (unit_id, MM/DD/YYYY dates).
        """
        if not settings.streamline_sovereign_bridge_settlement_enabled:
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="settlement_bridge_disabled",
            )

        method = (settings.streamline_sovereign_bridge_reservation_method or "").strip()
        if not method:
            logger.warning(
                "sovereign_bridge_settlement_missing_method",
                reservation_id=str(reservation_id),
            )
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="reservation_method_not_configured",
            )

        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="reservation_not_found",
            )

        prop = await db.get(Property, reservation.property_id)
        if prop is None or not (prop.streamline_property_id or "").strip():
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="no_streamline_unit_id",
            )
        try:
            unit_id = int(str(prop.streamline_property_id).strip())
        except ValueError:
            return BridgeHoldResult(
                ok=True,
                legacy_notified=False,
                detail="invalid_streamline_unit_id",
            )

        extra_params = _sovereign_settlement_extra_params(
            reservation,
            unit_id,
            stripe_payment_intent_id,
        )

        raw = await self._client.dispatch_sovereign_write_rpc(
            method,
            extra_params,
            log_name="sovereign_bridge_settlement",
            log_context={"reservation_id": str(reservation_id), "unit_id": unit_id},
        )
        if raw.get("ok") and not raw.get("skipped"):
            legacy = True
            detail = "deferred" if raw.get("deferred") else "rpc_ok"
        elif raw.get("skipped"):
            legacy = False
            detail = str(raw.get("reason") or "skipped")
        else:
            legacy = False
            detail = str(raw.get("reason") or raw.get("error") or "rpc_failed")

        logger.info(
            "sovereign_inventory_bridge_settlement",
            reservation_id=str(reservation_id),
            legacy_notified=legacy,
            detail=detail,
        )
        return BridgeHoldResult(ok=True, legacy_notified=legacy, detail=detail, raw=raw)

    async def queue_strike20_settlement_for_reconciliation(
        self,
        db: AsyncSession,
        *,
        reservation_id: UUID,
        stripe_payment_intent_id: str | None,
        failure_reason: str,
    ) -> int:
        """
        Best-effort enqueue to ``deferred_api_writes`` when live settlement RPC raises.

        Reconciliation worker replays the same JSON-RPC envelope as :meth:`finalize_legacy_reservation`.
        Returns row id or ``-1`` if queuing is skipped or fails.
        """
        if not settings.streamline_sovereign_bridge_settlement_enabled:
            return -1
        method = (settings.streamline_sovereign_bridge_reservation_method or "").strip()
        if not method:
            return -1

        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            return -1
        prop = await db.get(Property, reservation.property_id)
        if prop is None or not (prop.streamline_property_id or "").strip():
            return -1
        try:
            unit_id = int(str(prop.streamline_property_id).strip())
        except ValueError:
            return -1

        suffix = f"replay_queued:{failure_reason[:180]}"
        extra = _sovereign_settlement_extra_params(
            reservation,
            unit_id,
            stripe_payment_intent_id,
            notes_extra=suffix,
        )
        payload = _streamline_settlement_queue_payload(method, extra)
        if payload is None:
            return -1

        qid = await asyncio.to_thread(_sync_queue_streamline_payload, payload, method)
        if qid > 0:
            logger.info(
                "strike20_settlement_replay_queued",
                deferred_api_write_id=qid,
                reservation_id=str(reservation_id),
                rpc_method=method,
            )
        return qid


sovereign_inventory_manager = SovereignInventoryManager()
