from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from backend.models import ReservationHold
from backend.services.channex_calendar_export import (
    CALENDAR_BLOCKING_RESERVATION_STATUSES,
    load_blocked_dates_window,
)


class DummyRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def test_backend_models_exports_reservation_hold() -> None:
    assert ReservationHold.__name__ == "ReservationHold"


@pytest.mark.asyncio
async def test_load_blocked_dates_window_includes_pending_payment_and_active_holds() -> None:
    property_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            DummyRows([(date(2026, 3, 2), date(2026, 3, 3))]),
            DummyRows([(date(2026, 3, 3), date(2026, 3, 5))]),
            DummyRows([(date(2026, 3, 5), date(2026, 3, 7))]),
        ]
    )

    with patch(
        "backend.services.channex_calendar_export.utc_now",
        return_value=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    ):
        blocked = await load_blocked_dates_window(
            db,
            property_id,
            date(2026, 3, 1),
            date(2026, 3, 8),
        )

    assert CALENDAR_BLOCKING_RESERVATION_STATUSES == (
        "pending",
        "confirmed",
        "checked_in",
        "pending_payment",
    )
    assert blocked == {
        date(2026, 3, 2),
        date(2026, 3, 3),
        date(2026, 3, 4),
        date(2026, 3, 5),
        date(2026, 3, 6),
    }
    assert db.execute.await_count == 3
