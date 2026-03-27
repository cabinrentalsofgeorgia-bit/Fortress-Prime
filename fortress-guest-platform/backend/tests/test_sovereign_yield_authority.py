"""Strike 18 — SovereignYieldAuthority blackouts and weekday stay rules."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from sqlalchemy.exc import ProgrammingError

from backend.services.sovereign_yield_authority import SovereignYieldAuthority


def _restriction(**kwargs: object) -> MagicMock:
    row = MagicMock()
    row.is_blackout = kwargs.get("is_blackout", False)
    row.must_check_in_on_day = kwargs.get("must_check_in_on_day")
    row.must_check_out_on_day = kwargs.get("must_check_out_on_day")
    row.must_check_in_day_name = kwargs.get("must_check_in_day_name")
    row.must_check_out_day_name = kwargs.get("must_check_out_day_name")
    return row


@pytest.mark.asyncio
async def test_validate_empty_when_no_restrictions() -> None:
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    pid = uuid.uuid4()
    v = await SovereignYieldAuthority.validate_stay_constraints(
        db, pid, date(2026, 6, 1), date(2026, 6, 5)
    )
    assert v == []


@pytest.mark.asyncio
async def test_blackout_overlap_violation() -> None:
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = [_restriction(is_blackout=True)]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    pid = uuid.uuid4()
    v = await SovereignYieldAuthority.validate_stay_constraints(
        db, pid, date(2026, 6, 1), date(2026, 6, 5)
    )
    assert v == ["Selected dates overlap with a blackout period."]


@pytest.mark.asyncio
async def test_check_in_weekday_violation() -> None:
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = [
        _restriction(
            must_check_in_on_day=4,
            must_check_in_day_name="Friday",
        )
    ]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    pid = uuid.uuid4()
    # 2026-06-01 is Monday (weekday 0)
    v = await SovereignYieldAuthority.validate_stay_constraints(
        db, pid, date(2026, 6, 1), date(2026, 6, 5)
    )
    assert any("Friday" in msg for msg in v)


@pytest.mark.asyncio
async def test_check_out_weekday_violation() -> None:
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = [
        _restriction(
            must_check_out_on_day=0,
            must_check_out_day_name="Monday",
        )
    ]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    pid = uuid.uuid4()
    # Checkout 2026-06-05 is Friday
    v = await SovereignYieldAuthority.validate_stay_constraints(
        db, pid, date(2026, 6, 1), date(2026, 6, 5)
    )
    assert any("Check-out must be on a Monday" in msg for msg in v)


@pytest.mark.asyncio
async def test_missing_table_returns_empty() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=ProgrammingError("stmt", {}, Exception("undefinedtable")))
    db.rollback = AsyncMock()
    pid = uuid.uuid4()
    with patch(
        "backend.services.sovereign_yield_authority._missing_runtime_table",
        return_value=True,
    ):
        v = await SovereignYieldAuthority.validate_stay_constraints(
            db, pid, date(2026, 6, 1), date(2026, 6, 5)
        )
    assert v == []
    db.rollback.assert_awaited_once()
