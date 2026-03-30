"""Sovereign quote builder: Streamline min-stay and seasonal yield (rate_card) parity."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from backend.services.quote_builder import QuoteBuilderError, build_local_rent_quote
from backend.services.strike17_yield_parity_harness import (
    rent_totals_close,
    sovereign_rent_snapshot_from_ledger,
)


def _mock_db_with_property(rate_card: dict) -> AsyncMock:
    pid = uuid.uuid4()
    prop = MagicMock()
    prop.id = pid
    prop.name = "Yield Test Cabin"
    prop.rate_card = rate_card

    result = MagicMock()
    result.scalar_one_or_none.return_value = prop
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db, pid


@pytest.mark.asyncio
async def test_rejects_stay_shorter_than_streamline_min_nights() -> None:
    rate_card = {
        "rates": [
            {
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "nightly": "100.00",
                "min_nights": 3,
            },
        ],
    }
    db, pid = _mock_db_with_property(rate_card)
    with pytest.raises(QuoteBuilderError, match="minimum stay 3"):
        await build_local_rent_quote(pid, date(2026, 6, 1), date(2026, 6, 2), db)


@pytest.mark.asyncio
async def test_accepts_stay_meeting_max_min_nights_across_nights() -> None:
    """If any night requires 3 nights, entire booking must be at least 3 nights."""
    rate_card = {
        "rates": [
            {
                "start_date": "2026-06-01",
                "end_date": "2026-06-10",
                "nightly": "100.00",
                "min_nights": 2,
            },
            {
                "start_date": "2026-06-11",
                "end_date": "2026-06-20",
                "nightly": "120.00",
                "min_nights": 3,
            },
        ],
    }
    db, pid = _mock_db_with_property(rate_card)
    q = await build_local_rent_quote(pid, date(2026, 6, 9), date(2026, 6, 12), db)
    assert q.nights == 3
    assert q.rent == Decimal("320.00")


@pytest.mark.asyncio
async def test_seasonal_rate_windows_match_streamline_shape() -> None:
    """Two disjoint seasonal segments; stay spans boundary — rent is sum of nightly rows."""
    rate_card = {
        "rates": [
            {
                "name": "shoulder",
                "start_date": "2026-05-01",
                "end_date": "2026-05-31",
                "nightly": "150.00",
                "min_nights": 1,
            },
            {
                "name": "peak",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "nightly": "250.00",
                "min_nights": 1,
            },
        ],
    }
    db, pid = _mock_db_with_property(rate_card)
    q = await build_local_rent_quote(pid, date(2026, 5, 30), date(2026, 6, 2), db)
    assert q.nights == 3
    assert q.rent == Decimal("550.00")


@pytest.mark.asyncio
async def test_minimum_days_alias_from_streamline_sync() -> None:
    rate_card = {
        "rates": [
            {
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "nightly": "200.00",
                "minimum_days": 4,
            },
        ],
    }
    db, pid = _mock_db_with_property(rate_card)
    with pytest.raises(QuoteBuilderError, match="minimum stay 4"):
        await build_local_rent_quote(pid, date(2026, 7, 1), date(2026, 7, 3), db)


@pytest.mark.asyncio
async def test_yield_parity_harness_snapshot_matches_build_local_rent() -> None:
    rate_card = {
        "rates": [
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "nightly": "99.00",
                "min_nights": 1,
            },
        ],
    }
    db, pid = _mock_db_with_property(rate_card)
    snap = await sovereign_rent_snapshot_from_ledger(
        db, property_id=pid, check_in=date(2026, 8, 1), check_out=date(2026, 8, 3)
    )
    assert snap["nights"] == 2
    assert snap["rent"] == "198.00"
    assert rent_totals_close(sovereign_rent=snap["rent"], streamline_rent="198.00")


def test_rent_totals_close_false_on_large_drift() -> None:
    assert not rent_totals_close(sovereign_rent="100.00", streamline_rent="200.00", max_delta=Decimal("0.02"))
