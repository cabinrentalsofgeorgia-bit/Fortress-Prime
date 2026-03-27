"""Strike 20 — deferred_api_writes reconciliation janitor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.circuit_breaker import CircuitOpenError
from backend.models.deferred_api_write import DeferredApiWrite, DeferredWriteStatus
from backend.services.reconciliation_janitor import ReconciliationJanitor


class _ScalarResult:
    def __init__(self, rows: list[DeferredApiWrite]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[DeferredApiWrite]:
        return self._rows


def _pending_row(
    *,
    row_id: int = 1,
    retry_count: int = 0,
    payload: dict | None = None,
) -> DeferredApiWrite:
    body = payload or {
        "methodName": "PushSovereignReservation",
        "params": {"unit_id": "7", "notes": "test"},
    }
    return DeferredApiWrite(
        id=row_id,
        service="streamline",
        method="PushSovereignReservation",
        payload=body,
        status=DeferredWriteStatus.PENDING,
        retry_count=retry_count,
    )


@pytest.mark.asyncio
async def test_sweep_empty_returns_zero() -> None:
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=_ScalarResult([]))
    janitor = ReconciliationJanitor(batch_size=10, max_retries=5, client=MagicMock())
    n = await janitor.sweep_deferred_writes(db)
    assert n == 0
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_skips_when_circuit_open() -> None:
    row = _pending_row()
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=_ScalarResult([row]))
    client = MagicMock()
    client.replay_queued_rpc_payload = AsyncMock(side_effect=CircuitOpenError("open"))

    janitor = ReconciliationJanitor(batch_size=10, max_retries=5, client=client)
    n = await janitor.sweep_deferred_writes(db)
    assert n == 1
    db.execute.assert_awaited_once()
    db.commit.assert_not_awaited()
    client.replay_queued_rpc_payload.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_marks_completed_and_audits() -> None:
    row = _pending_row()
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=_ScalarResult([row]))
    client = MagicMock()
    client.replay_queued_rpc_payload = AsyncMock(return_value={"ok": True})

    janitor = ReconciliationJanitor(batch_size=10, max_retries=5, client=client)
    with patch(
        "backend.services.reconciliation_janitor.record_audit_event",
        new_callable=AsyncMock,
    ) as audit:
        n = await janitor.sweep_deferred_writes(db)

    assert n == 1
    assert db.execute.await_count == 2
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "strike20_reconciliation_success"
    assert audit.await_args.kwargs["resource_type"] == "concierge_strike20"


@pytest.mark.asyncio
async def test_sweep_increments_retry_and_abandons_at_cap() -> None:
    row = _pending_row(retry_count=4)
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=_ScalarResult([row]))
    client = MagicMock()
    client.replay_queued_rpc_payload = AsyncMock(side_effect=RuntimeError("rpc_fail"))

    janitor = ReconciliationJanitor(batch_size=10, max_retries=5, client=client)
    with patch(
        "backend.services.reconciliation_janitor.record_audit_event",
        new_callable=AsyncMock,
    ) as audit:
        n = await janitor.sweep_deferred_writes(db)

    assert n == 1
    assert db.execute.await_count == 3
    assert db.commit.await_count == 2
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "strike20_reconciliation_failed_final"


@pytest.mark.asyncio
async def test_sweep_abandons_bad_payload() -> None:
    row = _pending_row(payload="not-json")
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=_ScalarResult([row]))
    client = MagicMock()

    janitor = ReconciliationJanitor(batch_size=10, max_retries=5, client=client)
    with patch(
        "backend.services.reconciliation_janitor.record_audit_event",
        new_callable=AsyncMock,
    ) as audit:
        n = await janitor.sweep_deferred_writes(db)

    assert n == 1
    client.replay_queued_rpc_payload.assert_not_called()
    assert db.execute.await_count == 2
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "strike20_reconciliation_failed_final"
