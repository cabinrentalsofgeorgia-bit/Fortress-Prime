"""
Strike 20 — reconciliation worker for ``deferred_api_writes``.

Sovereign hold→reservation finality lives in Postgres; Streamline RPC is best-effort. Rows are
queued when the circuit is open or when live settlement raises after conversion. This janitor
replays them in FIFO order with a bounded retry counter so permanent API validation failures
do not spin forever.

OpenShell audit entries use ``resource_type="concierge_strike20"`` on terminal outcomes; retries
are structlog-only to avoid ledger noise.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import async_session_maker
from backend.integrations.circuit_breaker import CircuitOpenError
from backend.integrations.streamline_vrs import StreamlineVRS, StreamlineVRSError, streamline_vrs
from backend.models.deferred_api_write import DeferredApiWrite, DeferredWriteStatus
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger(service="reconciliation_janitor")


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    raise StreamlineVRSError("Deferred write payload is not JSON object")


def _strike20_audit_metadata(
    rpc_body: dict[str, Any],
    *,
    deferred_api_write_id: int,
    rpc_method: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "deferred_api_write_id": deferred_api_write_id,
        "rpc_method": rpc_method,
    }
    params = rpc_body.get("params")
    if isinstance(params, dict):
        for key in ("confirmation_code", "unit_id", "guest_email"):
            val = params.get(key)
            if val is not None and str(val).strip():
                meta[key] = val
        notes = params.get("notes")
        if isinstance(notes, str) and notes.strip():
            meta["notes_preview"] = notes.strip()[:240]
    if extra:
        meta.update(extra)
    return meta


class ReconciliationJanitor:
    """
    STRIKE 20 — consumes ``deferred_api_writes`` for Streamline RPC replay.

    Does not increment ``retry_count`` when the circuit breaker is open (same as your sketch:
    wait for the next sweep).
    """

    def __init__(
        self,
        *,
        max_retries: int | None = None,
        batch_size: int | None = None,
        client: StreamlineVRS | None = None,
    ) -> None:
        self.max_retries = max_retries or int(settings.deferred_api_reconciliation_max_retries)
        self.batch_size = batch_size or int(settings.deferred_api_reconciliation_batch_size)
        self._client = client or streamline_vrs

    async def sweep_deferred_writes(self, db: AsyncSession | None = None) -> int:
        """
        Process up to ``batch_size`` pending Streamline rows, oldest first.

        If ``db`` is omitted, opens a session via :data:`~backend.core.database.async_session_maker`.

        Returns the number of rows loaded into the batch (including no-ops for open circuit).
        """
        if db is not None:
            return await self._sweep_with_session(db)
        async with async_session_maker() as session:
            return await self._sweep_with_session(session)

    async def _sweep_with_session(self, db: AsyncSession) -> int:
        stmt = (
            select(DeferredApiWrite)
            .where(
                and_(
                    DeferredApiWrite.service == "streamline",
                    DeferredApiWrite.status == DeferredWriteStatus.PENDING,
                )
            )
            .order_by(DeferredApiWrite.created_at.asc())
            .limit(self.batch_size)
        )
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            return 0

        logger.info("reconciliation_janitor_sweep", pending_batch=len(rows))
        for row in rows:
            await self._process_row(db, row)
        return len(rows)

    async def _process_row(self, db: AsyncSession, row: DeferredApiWrite) -> None:
        rid = row.id
        retry_count = int(row.retry_count or 0)
        method = (row.method or "").strip()

        if retry_count >= self.max_retries:
            await self._mark_abandoned(db, row, "max_retries_exceeded")
            return

        try:
            body = _payload_to_dict(row.payload)
        except (json.JSONDecodeError, StreamlineVRSError, TypeError) as exc:
            await self._mark_abandoned(db, row, f"bad_payload:{exc}")
            return

        mo = method or None
        try:
            await self._client.replay_queued_rpc_payload(payload=body, method_override=mo)
        except CircuitOpenError:
            logger.info(
                "reconciliation_janitor_skip_circuit_open",
                deferred_api_write_id=rid,
                method=method,
            )
            return
        except Exception as exc:  # noqa: BLE001
            retry_count += 1
            err = str(exc)[:2000]
            await db.execute(
                update(DeferredApiWrite)
                .where(DeferredApiWrite.id == rid)
                .values(retry_count=retry_count, last_error=err)
            )
            await db.commit()
            logger.warning(
                "reconciliation_janitor_retry",
                deferred_api_write_id=rid,
                method=method,
                retry_count=retry_count,
                error=err[:500],
            )
            if retry_count >= self.max_retries:
                row.retry_count = retry_count
                row.last_error = err
                await self._mark_abandoned(db, row, err)
            return

        now = datetime.now(timezone.utc)
        await db.execute(
            update(DeferredApiWrite)
            .where(DeferredApiWrite.id == rid)
            .values(
                status=DeferredWriteStatus.COMPLETED.value,
                reconciled_at=now,
                last_error=None,
            )
        )
        await db.commit()
        logger.info(
            "reconciliation_janitor_success",
            deferred_api_write_id=rid,
            method=method,
        )
        await record_audit_event(
            action="strike20_reconciliation_success",
            resource_type="concierge_strike20",
            resource_id=str(rid),
            tool_name="reconciliation_janitor",
            outcome="success",
            metadata_json=_strike20_audit_metadata(
                body,
                deferred_api_write_id=rid,
                rpc_method=method,
                extra={"reconciled_at": now.isoformat()},
            ),
        )

    async def _mark_abandoned(self, db: AsyncSession, row: DeferredApiWrite, reason: str) -> None:
        rid = row.id
        method = (row.method or "").strip()
        await db.execute(
            update(DeferredApiWrite)
            .where(DeferredApiWrite.id == rid)
            .values(status=DeferredWriteStatus.FAILED_FINAL.value, last_error=reason[:2000])
        )
        await db.commit()
        logger.error(
            "reconciliation_janitor_abandoned",
            deferred_api_write_id=rid,
            method=method,
            reason=reason[:500],
        )
        try:
            body = _payload_to_dict(row.payload)
        except (json.JSONDecodeError, StreamlineVRSError, TypeError):
            body = {}
        await record_audit_event(
            action="strike20_reconciliation_failed_final",
            resource_type="concierge_strike20",
            resource_id=str(rid),
            tool_name="reconciliation_janitor",
            outcome="failure",
            metadata_json=_strike20_audit_metadata(
                body,
                deferred_api_write_id=rid,
                rpc_method=method,
                extra={"reason": reason[:500]},
            ),
        )


reconciliation_janitor = ReconciliationJanitor()
