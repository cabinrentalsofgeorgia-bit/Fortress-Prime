"""
Translate Fortress availability into Channex ARI payloads.

Channex expects inventory updates split across:
- Room Type availability (`/api/v1/availability`)
- Rate Plan restrictions and rates (`/api/v1/restrictions`)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.channex_calendar_export import build_channex_availability_document

logger = structlog.get_logger(service="channex_ari")

PREFERRED_ROOM_TYPE_TITLE = "Entire Cabin"
PREFERRED_RATE_PLAN_TITLE = "Standard Rate"


def _extract_attributes(item: dict[str, Any]) -> dict[str, Any]:
    attrs = item.get("attributes")
    return attrs if isinstance(attrs, dict) else item


def _pick_room_type(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    for item in items:
        attrs = _extract_attributes(item)
        if str(attrs.get("title") or "").strip() == PREFERRED_ROOM_TYPE_TITLE:
            return item
    return items[0]


def _pick_rate_plan(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    for item in items:
        attrs = _extract_attributes(item)
        if str(attrs.get("title") or "").strip() == PREFERRED_RATE_PLAN_TITLE:
            return item
    for item in items:
        attrs = _extract_attributes(item)
        if not bool(attrs.get("ui_read_only")):
            return item
    return items[0]


async def fetch_channex_catalog(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    headers: dict[str, str],
    property_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    room_resp = await client.get(
        f"{api_base}/room_types",
        headers=headers,
        params={"filter[property_id]": property_id, "page[size]": 100},
    )
    room_resp.raise_for_status()
    room_items = room_resp.json().get("data", [])

    rate_resp = await client.get(
        f"{api_base}/rate_plans",
        headers=headers,
        params={"filter[property_id]": property_id, "page[size]": 100},
    )
    rate_resp.raise_for_status()
    rate_items = rate_resp.json().get("data", [])

    room_type = _pick_room_type([item for item in room_items if isinstance(item, dict)])
    rate_plan = _pick_rate_plan([item for item in rate_items if isinstance(item, dict)])
    return room_type, rate_plan


async def build_channex_ari_payloads(
    db: AsyncSession,
    property_uuid: UUID,
    *,
    room_type_id: str,
    rate_plan_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    document, skip_reason = await build_channex_availability_document(db, property_uuid)
    if skip_reason:
        raise ValueError(skip_reason)
    assert document is not None

    property_id = str(document["channex_listing_id"])
    availability_values: list[dict[str, Any]] = []
    restriction_values: list[dict[str, Any]] = []

    for day in document.get("days", []):
        if not isinstance(day, dict):
            continue
        date = str(day.get("date") or "").strip()
        if not date:
            continue
        available = bool(day.get("available"))
        nightly_rate = day.get("nightly_rate")
        availability_values.append(
            {
                "property_id": property_id,
                "room_type_id": room_type_id,
                "date": date,
                "availability": 1 if available else 0,
            }
        )
        restriction_value: dict[str, Any] = {
            "property_id": property_id,
            "rate_plan_id": rate_plan_id,
            "date": date,
            "stop_sell": not available,
        }
        if available and nightly_rate is not None:
            restriction_value["rate"] = f"{float(nightly_rate):.2f}"
        restriction_values.append(restriction_value)

    return {"values": availability_values}, {"values": restriction_values}

