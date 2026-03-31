"""
Fleet-level Channex health/compliance reporting for admin surfaces.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.services.channex_ari import PREFERRED_RATE_PLAN_TITLE, PREFERRED_ROOM_TYPE_TITLE
from backend.services.channex_sync import has_channex_listing_id, normalize_name


class ChannexHealthPropertyStatus(BaseModel):
    property_id: str
    streamline_property_id: str
    slug: str
    property_name: str
    channex_listing_id: str | None
    shell_present: bool
    preferred_room_type_present: bool
    preferred_rate_plan_present: bool
    room_type_count: int
    rate_plan_count: int
    duplicate_rate_plan_count: int
    ari_availability_present: bool
    ari_restrictions_present: bool
    healthy: bool


class ChannexHealthResponse(BaseModel):
    property_count: int
    healthy_count: int
    shell_ready_count: int
    catalog_ready_count: int
    ari_ready_count: int
    duplicate_rate_plan_count: int
    properties: list[ChannexHealthPropertyStatus]


@dataclass
class _LivePropertyRef:
    streamline_property_id: str
    name: str


def _api_base() -> str:
    base = str(settings.channex_api_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api/v1"):
        return base
    if base.endswith("/api"):
        return f"{base}/v1"
    return f"{base}/api/v1"


def _headers() -> dict[str, str]:
    return {
        "user-api-key": str(settings.channex_api_key or "").strip(),
        "Accept": "application/json",
    }


async def _load_live_streamline_refs() -> list[_LivePropertyRef]:
    vrs = StreamlineVRS()
    try:
        data = await vrs._call("GetPropertyList")
    finally:
        await vrs.close()
    raw_props = data.get("property", []) if isinstance(data, dict) else []
    if isinstance(raw_props, dict):
        raw_props = [raw_props]
    return [
        _LivePropertyRef(
            streamline_property_id=str(prop.get("id", "")).strip(),
            name=str(prop.get("name", "")).strip(),
        )
        for prop in raw_props
        if isinstance(prop, dict)
    ]


async def _load_live_local_properties(db: AsyncSession) -> list[Property]:
    refs = await _load_live_streamline_refs()
    live_ids = {ref.streamline_property_id for ref in refs if ref.streamline_property_id}
    live_names = {normalize_name(ref.name) for ref in refs if ref.name}

    result = await db.execute(select(Property).where(Property.is_active.is_(True)).order_by(Property.name))
    props = list(result.scalars().all())
    return [
        prop
        for prop in props
        if str(prop.streamline_property_id or "").strip() in live_ids
        or normalize_name(prop.name) in live_names
    ]


async def channex_health_snapshot(db: AsyncSession) -> ChannexHealthResponse:
    props = await _load_live_local_properties(db)
    api_base = _api_base()
    headers = _headers()

    rows: list[ChannexHealthPropertyStatus] = []
    today = date.today().isoformat()

    async with httpx.AsyncClient(timeout=60.0) as client:
        room_options_resp = await client.get(f"{api_base}/room_types/options", headers=headers)
        room_options_resp.raise_for_status()
        room_options = [item for item in room_options_resp.json().get("data", []) if isinstance(item, dict)]

        rate_options_resp = await client.get(f"{api_base}/rate_plans/options", headers=headers)
        rate_options_resp.raise_for_status()
        rate_options = [item for item in rate_options_resp.json().get("data", []) if isinstance(item, dict)]

        room_options_by_property: dict[str, list[dict[str, Any]]] = {}
        for item in room_options:
            attrs = item.get("attributes") or {}
            property_id = str(attrs.get("property_id") or "").strip()
            if property_id:
                room_options_by_property.setdefault(property_id, []).append(item)

        rate_options_by_property: dict[str, list[dict[str, Any]]] = {}
        for item in rate_options:
            attrs = item.get("attributes") or {}
            property_id = str(attrs.get("property_id") or "").strip()
            if property_id:
                rate_options_by_property.setdefault(property_id, []).append(item)

        semaphore = asyncio.Semaphore(8)

        async def build_row(prop: Property) -> ChannexHealthPropertyStatus:
            listing_id = has_channex_listing_id(prop)
            shell_present = False
            room_type_count = 0
            rate_plan_count = 0
            duplicate_rate_plan_count = 0
            preferred_room_type_present = False
            preferred_rate_plan_present = False
            ari_availability_present = False
            ari_restrictions_present = False

            if listing_id and api_base and headers["user-api-key"]:
                room_items = room_options_by_property.get(listing_id, [])
                rate_items = rate_options_by_property.get(listing_id, [])

                room_type_count = len(room_items)
                preferred_room_type_present = any(
                    str(((item.get("attributes") or {}).get("title")) or "").strip() == PREFERRED_ROOM_TYPE_TITLE
                    for item in room_items
                )

                rate_plan_count = len(rate_items)
                duplicate_rate_plan_count = sum(
                    1
                    for item in rate_items
                    if str(((item.get("attributes") or {}).get("title")) or "").strip() != PREFERRED_RATE_PLAN_TITLE
                )
                preferred_rate_plan_present = any(
                    str(((item.get("attributes") or {}).get("title")) or "").strip() == PREFERRED_RATE_PLAN_TITLE
                    for item in rate_items
                )

                async with semaphore:
                    shell_resp = await client.get(f"{api_base}/properties/{listing_id}", headers=headers)
                    shell_present = shell_resp.status_code == 200

                    if shell_present and preferred_room_type_present and preferred_rate_plan_present:
                        availability_resp, restrictions_resp = await asyncio.gather(
                            client.get(
                                f"{api_base}/availability",
                                headers=headers,
                                params={
                                    "filter[property_id]": listing_id,
                                    "filter[date]": today,
                                },
                            ),
                            client.get(
                                f"{api_base}/restrictions",
                                headers=headers,
                                params={
                                    "filter[property_id]": listing_id,
                                    "filter[date]": today,
                                    "filter[restrictions]": "rate,stop_sell",
                                },
                            ),
                        )
                        availability_resp.raise_for_status()
                        restrictions_resp.raise_for_status()
                        ari_availability_present = bool(availability_resp.json().get("data", {}))
                        ari_restrictions_present = bool(restrictions_resp.json().get("data", {}))

            healthy = (
                shell_present
                and preferred_room_type_present
                and preferred_rate_plan_present
                and ari_availability_present
                and ari_restrictions_present
                and duplicate_rate_plan_count == 0
            )

            return ChannexHealthPropertyStatus(
                property_id=str(prop.id),
                streamline_property_id=str(prop.streamline_property_id or ""),
                slug=prop.slug,
                property_name=prop.name,
                channex_listing_id=listing_id,
                shell_present=shell_present,
                preferred_room_type_present=preferred_room_type_present,
                preferred_rate_plan_present=preferred_rate_plan_present,
                room_type_count=room_type_count,
                rate_plan_count=rate_plan_count,
                duplicate_rate_plan_count=duplicate_rate_plan_count,
                ari_availability_present=ari_availability_present,
                ari_restrictions_present=ari_restrictions_present,
                healthy=healthy,
            )

        rows = await asyncio.gather(*(build_row(prop) for prop in props))

    return ChannexHealthResponse(
        property_count=len(rows),
        healthy_count=sum(1 for row in rows if row.healthy),
        shell_ready_count=sum(1 for row in rows if row.shell_present),
        catalog_ready_count=sum(
            1 for row in rows if row.preferred_room_type_present and row.preferred_rate_plan_present
        ),
        ari_ready_count=sum(
            1 for row in rows if row.ari_availability_present and row.ari_restrictions_present
        ),
        duplicate_rate_plan_count=sum(row.duplicate_rate_plan_count for row in rows),
        properties=rows,
    )
