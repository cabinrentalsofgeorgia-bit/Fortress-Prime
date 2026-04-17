from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from backend.models.pricing import QuoteRequest
from backend.services.pricing_service import (
    PricingError,
    _build_fee_line_items,
    calculate_fast_quote,
)
from backend.services.quote_builder import LocalLedgerRentQuote


@pytest.mark.asyncio
async def test_calculate_fast_quote_uses_local_ledger_breakdown() -> None:
    property_id = uuid.uuid4()
    request = QuoteRequest(
        property_id=property_id,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 4),
        adults=2,
        children=0,
        pets=0,
    )
    db = AsyncMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=property_id,
            is_active=True,
            max_guests=6,
        )
    )
    tax = SimpleNamespace(name="Fannin County Lodging Tax", percentage_rate=Decimal("12.00"))
    fee = SimpleNamespace(
        id=uuid.uuid4(),
        name="Standard Cleaning Fee",
        flat_amount=Decimal("150.00"),
        is_pet_fee=False,
        is_optional=False,
        fee_type="flat",
        percentage_rate=None,
    )

    with patch(
        "backend.services.pricing_service.SovereignYieldAuthority.validate_stay_constraints",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "backend.services.pricing_service.build_local_rent_quote",
        new_callable=AsyncMock,
        return_value=LocalLedgerRentQuote(
            property_id=property_id,
            property_name="Test Cabin",
            nights=3,
            rent=Decimal("900.00"),
            nightly_breakdown=(),
        ),
    ), patch(
        "backend.services.pricing_service._load_overlapping_pricing_overrides",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "backend.services.pricing_service._load_applicable_taxes",
        new_callable=AsyncMock,
        return_value=[tax],
    ), patch(
        "backend.services.pricing_service._load_applicable_fees",
        new_callable=AsyncMock,
        return_value=[fee],
    ), patch(
        "backend.services.pricing_service._load_optional_fee_ids",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "backend.services.pricing_service._load_active_learned_rules",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await calculate_fast_quote(request, db)

    assert response.property_id == property_id
    assert response.total_amount == Decimal("1176.00")
    assert response.is_bookable is True
    assert [item.description for item in response.line_items] == [
        "3 night stay @ $300.00 / night",
        "Standard Cleaning Fee",
        "Fannin County Lodging Tax",
    ]
    assert [item.amount for item in response.line_items] == [
        Decimal("900.00"),
        Decimal("150.00"),
        Decimal("126.00"),
    ]


@pytest.mark.asyncio
async def test_calculate_fast_quote_applies_pricing_override_discount() -> None:
    property_id = uuid.uuid4()
    request = QuoteRequest(
        property_id=property_id,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 4),
        adults=2,
        children=0,
        pets=0,
    )
    db = AsyncMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=property_id,
            is_active=True,
            max_guests=6,
        )
    )
    override = SimpleNamespace(
        id=uuid.uuid4(),
        property_id=property_id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 3),
        adjustment_percentage=Decimal("-15.00"),
        reason="Yield Swarm approved discount",
        approved_by="admin@example.com",
        created_at=None,
    )
    tax = SimpleNamespace(name="Fannin County Lodging Tax", percentage_rate=Decimal("12.00"))
    fee = SimpleNamespace(
        id=uuid.uuid4(),
        name="Standard Cleaning Fee",
        flat_amount=Decimal("150.00"),
        is_pet_fee=False,
        is_optional=False,
        fee_type="flat",
        percentage_rate=None,
    )

    with patch(
        "backend.services.pricing_service.SovereignYieldAuthority.validate_stay_constraints",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "backend.services.pricing_service.build_local_rent_quote",
        new_callable=AsyncMock,
        return_value=LocalLedgerRentQuote(
            property_id=property_id,
            property_name="Test Cabin",
            nights=3,
            rent=Decimal("900.00"),
            nightly_breakdown=(
                (date(2026, 8, 1), Decimal("300.00")),
                (date(2026, 8, 2), Decimal("300.00")),
                (date(2026, 8, 3), Decimal("300.00")),
            ),
        ),
    ), patch(
        "backend.services.pricing_service._load_overlapping_pricing_overrides",
        new_callable=AsyncMock,
        return_value=[override],
    ), patch(
        "backend.services.pricing_service._load_applicable_taxes",
        new_callable=AsyncMock,
        return_value=[tax],
    ), patch(
        "backend.services.pricing_service._load_applicable_fees",
        new_callable=AsyncMock,
        return_value=[fee],
    ), patch(
        "backend.services.pricing_service._load_optional_fee_ids",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "backend.services.pricing_service._load_active_learned_rules",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await calculate_fast_quote(request, db)

    assert response.total_amount == Decimal("1024.80")
    assert [item.description for item in response.line_items] == [
        "3 night stay @ $300.00 / night",
        "Yield Adjustment Discount (-15.00% 2026-08-01 to 2026-08-03)",
        "Standard Cleaning Fee",
        "Fannin County Lodging Tax",
    ]
    assert [item.amount for item in response.line_items] == [
        Decimal("900.00"),
        Decimal("-135.00"),
        Decimal("150.00"),
        Decimal("109.80"),
    ]


@pytest.mark.asyncio
async def test_calculate_fast_quote_raises_on_yield_violation() -> None:
    property_id = uuid.uuid4()
    request = QuoteRequest(
        property_id=property_id,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 4),
        adults=2,
        children=0,
        pets=0,
    )
    db = AsyncMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            id=property_id,
            is_active=True,
            max_guests=6,
        )
    )
    with patch(
        "backend.services.pricing_service.SovereignYieldAuthority.validate_stay_constraints",
        new_callable=AsyncMock,
        return_value=["Selected dates overlap with a blackout period."],
    ):
        with pytest.raises(PricingError, match="blackout"):
            await calculate_fast_quote(request, db)


def test_build_fee_line_items_excludes_optional_until_selected() -> None:
    fid_m = uuid.uuid4()
    fid_o = uuid.uuid4()
    fee_mandatory = SimpleNamespace(
        id=fid_m,
        name="Standard Cleaning Fee",
        flat_amount=Decimal("100.00"),
        is_pet_fee=False,
        is_optional=False,
        fee_type="flat",
        percentage_rate=None,
    )
    fee_optional = SimpleNamespace(
        id=fid_o,
        name="Firewood Bundle",
        flat_amount=Decimal("50.00"),
        is_pet_fee=False,
        is_optional=True,
        fee_type="flat",
        percentage_rate=None,
    )
    items, total, _ = _build_fee_line_items(
        pets=0,
        fees=[fee_mandatory, fee_optional],
        optional_fee_ids={str(fid_o)},
        selected_optional_ids=set(),
    )
    assert total == Decimal("100.00")
    assert len(items) == 1
    assert items[0].description == "Standard Cleaning Fee"

    items2, total2, _ = _build_fee_line_items(
        pets=0,
        fees=[fee_mandatory, fee_optional],
        optional_fee_ids={str(fid_o)},
        selected_optional_ids={str(fid_o)},
    )
    assert total2 == Decimal("150.00")
    assert len(items2) == 2


def test_build_fee_line_items_hard_intercept_check_in_without_optional_flag() -> None:
    """Early/late check-in/out must not be mandatory even if ORM is_optional is false."""
    fid_m = uuid.uuid4()
    fid_early = uuid.uuid4()
    fee_mandatory = SimpleNamespace(
        id=fid_m,
        name="Standard Cleaning Fee",
        flat_amount=Decimal("100.00"),
        is_pet_fee=False,
        is_optional=False,
        fee_type="flat",
        percentage_rate=None,
    )
    fee_early = SimpleNamespace(
        id=fid_early,
        name="Early Check-In",
        flat_amount=Decimal("75.00"),
        is_pet_fee=False,
        is_optional=False,
        fee_type="flat",
        percentage_rate=None,
    )
    items, total, _ = _build_fee_line_items(
        pets=0,
        fees=[fee_mandatory, fee_early],
        optional_fee_ids=set(),
        selected_optional_ids=set(),
    )
    assert total == Decimal("100.00")
    assert all("Early" not in i.description for i in items)

    items_sel, total_sel, _ = _build_fee_line_items(
        pets=0,
        fees=[fee_mandatory, fee_early],
        optional_fee_ids=set(),
        selected_optional_ids={str(fid_early)},
    )
    assert total_sel == Decimal("175.00")
    assert any("Early Check-In" in i.description for i in items_sel)
