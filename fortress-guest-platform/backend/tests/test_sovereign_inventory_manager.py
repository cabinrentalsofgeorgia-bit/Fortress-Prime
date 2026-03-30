"""Strike 19 — SovereignInventoryManager / Streamline bridge."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.sovereign_inventory_manager import (
    BridgeHoldResult,
    SovereignInventoryManager,
)


@pytest.mark.asyncio
async def test_hold_dates_bridge_disabled() -> None:
    client = AsyncMock()
    mgr = SovereignInventoryManager(client=client)
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_hold_enabled",
        False,
    ):
        r = await mgr.hold_dates(
            streamline_unit_id=123,
            check_in=date(2026, 7, 1),
            check_out=date(2026, 7, 5),
        )
    assert r == BridgeHoldResult(ok=True, legacy_notified=False, detail="bridge_disabled", raw=None)
    client.push_sovereign_hold_block.assert_not_called()


@pytest.mark.asyncio
async def test_hold_dates_sends_rpc_when_configured() -> None:
    client = AsyncMock()
    client.push_sovereign_hold_block = AsyncMock(
        return_value={"ok": True, "deferred": False, "method": "TestSetBlock"},
    )
    mgr = SovereignInventoryManager(client=client)
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_hold_enabled",
        True,
    ), patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_hold_method",
        "TestSetBlock",
    ), patch(
        "backend.services.sovereign_inventory_manager.settings.reservation_hold_ttl_minutes",
        15,
    ):
        r = await mgr.hold_dates(
            streamline_unit_id=999,
            check_in=date(2026, 7, 1),
            check_out=date(2026, 7, 5),
        )
    assert r.legacy_notified is True
    assert r.detail == "rpc_ok"
    client.push_sovereign_hold_block.assert_awaited_once()


@pytest.mark.asyncio
async def test_hold_dates_for_property_resolves_unit_id() -> None:
    pid = uuid.uuid4()
    db = AsyncMock(spec=AsyncSession)
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            streamline_property_id="42",
        )
    )
    client = AsyncMock()
    client.push_sovereign_hold_block = AsyncMock(
        return_value={"ok": True, "skipped": True, "reason": "method_not_allowed"},
    )
    mgr = SovereignInventoryManager(client=client)
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_hold_enabled",
        True,
    ), patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_hold_method",
        "X",
    ):
        r = await mgr.hold_dates_for_property(
            db,
            property_id=pid,
            check_in=date(2026, 7, 1),
            check_out=date(2026, 7, 5),
        )
    assert r.legacy_notified is False
    assert r.detail == "method_not_allowed"


@pytest.mark.asyncio
async def test_finalize_legacy_reservation_settlement_disabled() -> None:
    client = AsyncMock()
    mgr = SovereignInventoryManager(client=client)
    db = AsyncMock()
    rid = uuid.uuid4()
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_settlement_enabled",
        False,
    ):
        r = await mgr.finalize_legacy_reservation(db, reservation_id=rid)
    assert r.detail == "settlement_bridge_disabled"
    client.dispatch_sovereign_write_rpc.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_legacy_reservation_dispatches_when_enabled() -> None:
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db = AsyncMock()
    reservation = SimpleNamespace(
        id=rid,
        property_id=pid,
        confirmation_code="FGP-99",
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 5),
        guest_email="g@t.com",
        guest_name="Test Guest",
    )
    prop = SimpleNamespace(streamline_property_id="77")
    db.get = AsyncMock(side_effect=[reservation, prop])

    client = AsyncMock()
    client.dispatch_sovereign_write_rpc = AsyncMock(
        return_value={"ok": True, "deferred": False, "method": "X"},
    )
    mgr = SovereignInventoryManager(client=client)
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_settlement_enabled",
        True,
    ), patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_reservation_method",
        "PushSovereignReservation",
    ):
        r = await mgr.finalize_legacy_reservation(
            db,
            reservation_id=rid,
            stripe_payment_intent_id="pi_xyz",
        )
    assert r.legacy_notified is True
    client.dispatch_sovereign_write_rpc.assert_awaited_once()


@pytest.mark.asyncio
async def test_queue_strike20_settlement_for_reconciliation_returns_negative_when_disabled() -> None:
    rid = uuid.uuid4()
    db = AsyncMock()
    mgr = SovereignInventoryManager(client=AsyncMock())
    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_settlement_enabled",
        False,
    ):
        qid = await mgr.queue_strike20_settlement_for_reconciliation(
            db,
            reservation_id=rid,
            stripe_payment_intent_id="pi_x",
            failure_reason="test",
        )
    assert qid == -1


@pytest.mark.asyncio
async def test_queue_strike20_settlement_for_reconciliation_enqueues_when_configured() -> None:
    rid = uuid.uuid4()
    pid = uuid.uuid4()
    db = AsyncMock()
    reservation = SimpleNamespace(
        id=rid,
        property_id=pid,
        confirmation_code="FGP-100",
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
        guest_email="g@t.com",
        guest_name="Guest",
    )
    prop = SimpleNamespace(streamline_property_id="55")
    db.get = AsyncMock(side_effect=[reservation, prop])

    mgr = SovereignInventoryManager(client=AsyncMock())
    fake_payload = {"methodName": "PushSovereignReservation", "params": {"a": 1}}

    with patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_settlement_enabled",
        True,
    ), patch(
        "backend.services.sovereign_inventory_manager.settings.streamline_sovereign_bridge_reservation_method",
        "PushSovereignReservation",
    ), patch(
        "backend.services.sovereign_inventory_manager._streamline_settlement_queue_payload",
        return_value=fake_payload,
    ), patch(
        "backend.services.sovereign_inventory_manager.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=901,
    ) as tt:
        qid = await mgr.queue_strike20_settlement_for_reconciliation(
            db,
            reservation_id=rid,
            stripe_payment_intent_id="pi_replay",
            failure_reason="rpc_timeout",
        )

    assert qid == 901
    tt.assert_awaited_once()
    call = tt.await_args
    assert call.args[0].__name__ == "_sync_queue_streamline_payload"
    assert call.args[1] == fake_payload
    assert call.args[2] == "PushSovereignReservation"
