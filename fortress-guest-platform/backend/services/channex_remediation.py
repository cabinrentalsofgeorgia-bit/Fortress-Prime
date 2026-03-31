"""
Safe Channex remediation actions for admin-operated drift repair.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.channex_ari import (
    PREFERRED_RATE_PLAN_TITLE,
    PREFERRED_ROOM_TYPE_TITLE,
    build_channex_ari_payloads,
    fetch_channex_catalog,
)
from backend.services.channex_health import _api_base, _headers, _load_live_local_properties
from backend.services.channex_sync import (
    _create_upstream_property_shell,
    _load_streamline_metadata_hints,
    _metadata_hint_for_property,
    has_channex_listing_id,
)


class ChannexRemediationRequest(BaseModel):
    property_ids: list[str] | None = None
    ari_window_days: int = Field(default=30, ge=1, le=90)


class ChannexRemediationResult(BaseModel):
    property_id: str
    slug: str
    property_name: str
    channex_listing_id: str | None = None
    shell_action: str
    catalog_action: str
    ari_action: str
    room_type_id: str | None = None
    rate_plan_id: str | None = None
    error: str | None = None


class ChannexRemediationResponse(BaseModel):
    status: str = "complete"
    property_count: int
    remediated_count: int
    failed_count: int
    results: list[ChannexRemediationResult]


async def _fetch_cancellation_policy_id(client: httpx.AsyncClient, api_base: str, headers: dict[str, str]) -> str:
    response = await client.get(f"{api_base}/cancellation_policies", headers=headers, params={"page[size]": 20})
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        raise ValueError("No Channex cancellation policy available for remediation")
    policy = data[0]
    policy_id = str(policy.get("id") or "").strip()
    if not policy_id:
        raise ValueError("Channex cancellation policy response missing id")
    return policy_id


def _room_type_payload(property_id: str, occupancy: int) -> dict[str, Any]:
    return {
        "room_type": {
            "property_id": property_id,
            "title": PREFERRED_ROOM_TYPE_TITLE,
            "count_of_rooms": 1,
            "occ_adults": occupancy,
            "occ_children": 0,
            "occ_infants": 0,
            "default_occupancy": occupancy,
            "facilities": [],
            "room_kind": "room",
            "capacity": None,
            "content": {"description": None, "photos": []},
        }
    }


def _rate_plan_payload(
    *,
    property_id: str,
    room_type_id: str,
    cancellation_policy_id: str,
    occupancy: int,
) -> dict[str, Any]:
    return {
        "rate_plan": {
            "title": PREFERRED_RATE_PLAN_TITLE,
            "property_id": property_id,
            "room_type_id": room_type_id,
            "cancellation_policy_id": cancellation_policy_id,
            "children_fee": "0.00",
            "infant_fee": "0.00",
            "max_stay": [0, 0, 0, 0, 0, 0, 0],
            "min_stay_arrival": [1, 1, 1, 1, 1, 1, 1],
            "min_stay_through": [1, 1, 1, 1, 1, 1, 1],
            "closed_to_arrival": [False, False, False, False, False, False, False],
            "closed_to_departure": [False, False, False, False, False, False, False],
            "stop_sell": [False, False, False, False, False, False, False],
            "options": [{"occupancy": occupancy, "is_primary": True, "rate": 0}],
            "currency": "USD",
            "sell_mode": "per_room",
            "rate_mode": "manual",
            "inherit_rate": False,
            "inherit_closed_to_arrival": False,
            "inherit_closed_to_departure": False,
            "inherit_stop_sell": False,
            "inherit_min_stay_arrival": False,
            "inherit_min_stay_through": False,
            "inherit_max_stay": False,
            "inherit_max_sell": False,
            "inherit_max_availability": False,
            "inherit_availability_offset": False,
            "auto_rate_settings": None,
        }
    }


async def remediate_channex_fleet(
    db: AsyncSession,
    request: ChannexRemediationRequest,
) -> ChannexRemediationResponse:
    props = await _load_live_local_properties(db)
    if request.property_ids:
        wanted = {str(pid) for pid in request.property_ids}
        props = [prop for prop in props if str(prop.id) in wanted]

    hints = await _load_streamline_metadata_hints()
    api_base = _api_base()
    headers = {
        **_headers(),
        "Content-Type": "application/json",
    }
    results: list[ChannexRemediationResult] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        cancellation_policy_id = await _fetch_cancellation_policy_id(client, api_base, headers)

        for prop in props:
            listing_id = has_channex_listing_id(prop)
            shell_action = "ok"
            catalog_action = "ok"
            ari_action = "ok"
            room_type_id: str | None = None
            rate_plan_id: str | None = None

            try:
                metadata_hint = _metadata_hint_for_property(prop, hints)

                shell_present = False
                if listing_id:
                    shell_resp = await client.get(f"{api_base}/properties/{listing_id}", headers=headers)
                    shell_present = shell_resp.status_code == 200

                if not listing_id or not shell_present:
                    new_listing_id = await _create_upstream_property_shell(
                        client,
                        prop,
                        metadata_hint=metadata_hint,
                    )
                    prop.ota_metadata = dict(prop.ota_metadata or {}) if isinstance(prop.ota_metadata, dict) else {}
                    prop.ota_metadata["channex_listing_id"] = new_listing_id
                    db.add(prop)
                    await db.commit()
                    await db.refresh(prop)
                    listing_id = new_listing_id
                    shell_action = "created_shell" if not shell_present else "repaired_shell"

                room_type, rate_plan = await fetch_channex_catalog(
                    client=client,
                    api_base=api_base,
                    headers=headers,
                    property_id=listing_id,
                )

                occupancy = max(int(prop.max_guests or 1), 1)

                if room_type is None:
                    room_resp = await client.post(
                        f"{api_base}/room_types",
                        headers=headers,
                        json=_room_type_payload(listing_id, occupancy),
                    )
                    room_resp.raise_for_status()
                    room_type = room_resp.json().get("data", {})
                    catalog_action = "created_room_type"
                room_type_id = str(room_type.get("id") or "")

                if rate_plan is None:
                    rate_resp = await client.post(
                        f"{api_base}/rate_plans",
                        headers=headers,
                        json=_rate_plan_payload(
                            property_id=listing_id,
                            room_type_id=room_type_id,
                            cancellation_policy_id=cancellation_policy_id,
                            occupancy=occupancy,
                        ),
                    )
                    rate_resp.raise_for_status()
                    rate_plan = rate_resp.json().get("data", {})
                    catalog_action = (
                        "created_catalog"
                        if catalog_action == "created_room_type"
                        else "created_rate_plan"
                    )
                rate_plan_id = str(rate_plan.get("id") or "")

                availability_body, restrictions_body = await build_channex_ari_payloads(
                    db,
                    prop.id,
                    room_type_id=room_type_id,
                    rate_plan_id=rate_plan_id,
                )
                availability_body["values"] = availability_body["values"][: request.ari_window_days]
                restrictions_body["values"] = restrictions_body["values"][: request.ari_window_days]
                availability_push = await client.post(
                    f"{api_base}/availability",
                    headers=headers,
                    json=availability_body,
                )
                availability_push.raise_for_status()
                restrictions_push = await client.post(
                    f"{api_base}/restrictions",
                    headers=headers,
                    json=restrictions_body,
                )
                restrictions_push.raise_for_status()
                ari_action = "pushed"

                results.append(
                    ChannexRemediationResult(
                        property_id=str(prop.id),
                        slug=prop.slug,
                        property_name=prop.name,
                        channex_listing_id=listing_id,
                        shell_action=shell_action,
                        catalog_action=catalog_action,
                        ari_action=ari_action,
                        room_type_id=room_type_id or None,
                        rate_plan_id=rate_plan_id or None,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                if db.in_transaction():
                    await db.rollback()
                results.append(
                    ChannexRemediationResult(
                        property_id=str(prop.id),
                        slug=prop.slug,
                        property_name=prop.name,
                        channex_listing_id=listing_id,
                        shell_action=shell_action,
                        catalog_action=catalog_action,
                        ari_action="failed",
                        room_type_id=room_type_id,
                        rate_plan_id=rate_plan_id,
                        error=str(exc)[:400],
                    )
                )

    return ChannexRemediationResponse(
        property_count=len(results),
        remediated_count=sum(1 for row in results if row.ari_action != "failed"),
        failed_count=sum(1 for row in results if row.ari_action == "failed"),
        results=results,
    )
