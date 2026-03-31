from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.channex_ari import (
    PREFERRED_RATE_PLAN_TITLE,
    PREFERRED_ROOM_TYPE_TITLE,
    build_channex_ari_payloads,
    fetch_channex_catalog,
)


@pytest.mark.asyncio
async def test_build_channex_ari_payloads_maps_available_and_blocked_days() -> None:
    property_id = uuid.uuid4()
    db = AsyncMock()

    with patch(
        "backend.services.channex_ari.build_channex_availability_document",
        AsyncMock(
            return_value=(
                {
                    "channex_listing_id": "listing-123",
                    "days": [
                        {"date": "2026-04-01", "available": True, "nightly_rate": 275.0},
                        {"date": "2026-04-02", "available": False, "nightly_rate": None},
                    ],
                },
                None,
            )
        ),
    ):
        availability_body, restrictions_body = await build_channex_ari_payloads(
            db,
            property_id,
            room_type_id="room-123",
            rate_plan_id="rate-123",
        )

    assert availability_body == {
        "values": [
            {
                "property_id": "listing-123",
                "room_type_id": "room-123",
                "date": "2026-04-01",
                "availability": 1,
            },
            {
                "property_id": "listing-123",
                "room_type_id": "room-123",
                "date": "2026-04-02",
                "availability": 0,
            },
        ]
    }
    assert restrictions_body == {
        "values": [
            {
                "property_id": "listing-123",
                "rate_plan_id": "rate-123",
                "date": "2026-04-01",
                "stop_sell": False,
                "rate": "275.00",
            },
            {
                "property_id": "listing-123",
                "rate_plan_id": "rate-123",
                "date": "2026-04-02",
                "stop_sell": True,
            },
        ]
    }


@pytest.mark.asyncio
async def test_fetch_channex_catalog_prefers_standard_titles() -> None:
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=[
            _resp(
                [
                    {"id": "room-other", "attributes": {"title": "Something Else"}},
                    {"id": "room-pref", "attributes": {"title": PREFERRED_ROOM_TYPE_TITLE}},
                ]
            ),
            _resp(
                [
                    {"id": "rate-other", "attributes": {"title": "Fallback Rate", "ui_read_only": False}},
                    {"id": "rate-pref", "attributes": {"title": PREFERRED_RATE_PLAN_TITLE, "ui_read_only": False}},
                ]
            ),
        ]
    )

    room_type, rate_plan = await fetch_channex_catalog(
        client,
        api_base="https://staging.channex.io/api/v1",
        headers={"user-api-key": "x"},
        property_id="property-123",
    )

    assert room_type["id"] == "room-pref"
    assert rate_plan["id"] == "rate-pref"


def _resp(data):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": data}
    return response
