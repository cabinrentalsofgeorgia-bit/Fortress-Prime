"""
Channex inventory sync helpers for admin-driven property mapping.

The first phase focuses on property-level shell creation and mapping persistence.
It intentionally reuses the same `ota_metadata.channex_listing_id` convention that
the webhook ingress and availability egress already depend on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.services.channex_calendar_export import CHANNEX_LISTING_METADATA_KEY

logger = structlog.get_logger(service="channex_sync")

DEFAULT_COUNTRY_CODE = "US"
DEFAULT_STATE = "GA"
DEFAULT_CITY = "Blue Ridge"
DEFAULT_ZIP_CODE = "30513"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CURRENCY = "USD"
STATE_NAME_TO_CODE = {
    "georgia": "GA",
}


class ChannexSyncInventoryRequest(BaseModel):
    dry_run: bool = False
    limit: int | None = Field(default=None, ge=1, le=500)
    property_ids: list[str] | None = None


class ChannexSyncResult(BaseModel):
    property_id: str
    slug: str
    property_name: str
    action: str
    channex_listing_id: str | None = None
    match_strategy: str | None = None
    error: str | None = None


class ChannexSyncInventoryResponse(BaseModel):
    status: str = "complete"
    dry_run: bool
    scanned_count: int
    created_count: int
    mapped_count: int
    failed_count: int
    results: list[ChannexSyncResult]


@dataclass
class _UpstreamProperty:
    listing_id: str
    title: str
    normalized_title: str


@dataclass
class _PropertyMetadataHint:
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


def normalize_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def merge_channex_listing_metadata(existing: Any, listing_id: str) -> dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged[CHANNEX_LISTING_METADATA_KEY] = listing_id
    return merged


def has_channex_listing_id(prop: Property) -> str | None:
    meta = prop.ota_metadata or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get(CHANNEX_LISTING_METADATA_KEY)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _management_api_base_url() -> str:
    raw = str(settings.channex_api_base_url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("CHANNEX_API_BASE_URL is not configured")
    parsed = urlsplit(raw)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v1"):
        return raw
    if path.endswith("/api"):
        return f"{raw}/v1"
    if path:
        return f"{raw}/api/v1"
    return f"{raw}/api/v1"


def _channex_headers() -> dict[str, str]:
    api_key = str(settings.channex_api_key or "").strip()
    if not api_key:
        raise ValueError("CHANNEX_API_KEY is not configured")
    return {
        "user-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _extract_string(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_state(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return STATE_NAME_TO_CODE.get(raw.lower())


def _normalize_zip(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", raw)
    if match:
        return match.group(1)
    return None


def _extract_upstream_property(item: Any) -> _UpstreamProperty | None:
    if not isinstance(item, dict):
        return None
    attrs = item.get("attributes")
    data = attrs if isinstance(attrs, dict) else item
    listing_id = _extract_string(item, "id", "property_id")
    title = _extract_string(data, "title", "name", "property_name")
    if not listing_id or not title:
        return None
    return _UpstreamProperty(
        listing_id=listing_id,
        title=title,
        normalized_title=normalize_name(title),
    )


async def _fetch_upstream_properties(client: httpx.AsyncClient) -> list[_UpstreamProperty]:
    response = await client.get(f"{_management_api_base_url()}/properties", headers=_channex_headers())
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("data", []) if isinstance(payload, dict) else []
    items: list[_UpstreamProperty] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            parsed = _extract_upstream_property(item)
            if parsed:
                items.append(parsed)
    return items


def _parse_address(
    address: str | None,
    *,
    default_city: str = DEFAULT_CITY,
    default_state: str = DEFAULT_STATE,
    default_zip: str = DEFAULT_ZIP_CODE,
) -> dict[str, str]:
    raw = (address or "").strip()
    if not raw:
        return {
            "address": f"{default_city}, {default_state}",
            "city": default_city,
            "state": default_state,
            "zip_code": default_zip,
        }

    city = default_city
    state = default_state
    zip_code = default_zip

    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) >= 2:
        if not re.search(r"\d", parts[-2]):
            city = parts[-2] or default_city
        tail = parts[-1]
        state_match = re.search(r"\b([A-Z]{2})\b", tail.upper())
        zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", tail)
        if state_match:
            state = state_match.group(1)
        else:
            named_state = _normalize_state(tail)
            if named_state:
                state = named_state
        if zip_match:
            zip_code = zip_match.group(1)

    return {
        "address": raw,
        "city": city,
        "state": state,
        "zip_code": zip_code,
    }


def _build_property_payload(
    prop: Property,
    *,
    metadata_hint: _PropertyMetadataHint | None = None,
) -> dict[str, Any]:
    metadata_hint = metadata_hint or _PropertyMetadataHint()
    address_parts = _parse_address(
        prop.address,
        default_city=(metadata_hint.city or DEFAULT_CITY).strip() or DEFAULT_CITY,
        default_state=(metadata_hint.state or DEFAULT_STATE).strip() or DEFAULT_STATE,
        default_zip=(metadata_hint.zip_code or DEFAULT_ZIP_CODE).strip() or DEFAULT_ZIP_CODE,
    )
    payload = {
        "property": {
            "title": prop.name,
            "currency": DEFAULT_CURRENCY,
            "timezone": DEFAULT_TIMEZONE,
            "country_code": DEFAULT_COUNTRY_CODE,
            "state": address_parts["state"],
            "city": address_parts["city"],
            "zip_code": address_parts["zip_code"],
            "address": address_parts["address"],
        }
    }
    if prop.latitude is not None:
        payload["property"]["latitude"] = str(prop.latitude)
    if prop.longitude is not None:
        payload["property"]["longitude"] = str(prop.longitude)
    return payload


def build_property_shell_payload(
    prop: Property,
    *,
    metadata_hint: _PropertyMetadataHint | None = None,
) -> dict[str, Any]:
    return _build_property_payload(prop, metadata_hint=metadata_hint)


def build_property_update_payload(
    prop: Property,
    *,
    metadata_hint: _PropertyMetadataHint | None = None,
) -> dict[str, Any]:
    return _build_property_payload(prop, metadata_hint=metadata_hint)


def _find_upstream_match(prop: Property, upstream: list[_UpstreamProperty]) -> tuple[str | None, str | None]:
    target_name = normalize_name(prop.name)
    target_slug = normalize_name(prop.slug)
    for item in upstream:
        if item.normalized_title == target_name:
            return item.listing_id, "name_exact"
    for item in upstream:
        if item.normalized_title == target_slug:
            return item.listing_id, "slug_exact"
    return None, None


async def _create_upstream_property_shell(
    client: httpx.AsyncClient,
    prop: Property,
    *,
    metadata_hint: _PropertyMetadataHint | None = None,
) -> str:
    response = await client.post(
        f"{_management_api_base_url()}/properties",
        json=build_property_shell_payload(prop, metadata_hint=metadata_hint),
        headers=_channex_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        listing_id = _extract_string(data, "id", "property_id")
        if listing_id:
            return listing_id
    raise ValueError("Channex property create response did not include a property id")


async def _update_upstream_property_shell(
    client: httpx.AsyncClient,
    listing_id: str,
    prop: Property,
    *,
    metadata_hint: _PropertyMetadataHint | None = None,
) -> None:
    payload = build_property_update_payload(prop, metadata_hint=metadata_hint)
    url = f"{_management_api_base_url()}/properties/{listing_id}"
    response = await client.patch(url, json=payload, headers=_channex_headers())
    if response.status_code in {405, 404}:
        response = await client.put(url, json=payload, headers=_channex_headers())
    response.raise_for_status()


async def _list_candidate_properties(
    db: AsyncSession,
    property_ids: list[str] | None,
    limit: int | None,
) -> list[Property]:
    stmt = select(Property).where(Property.is_active.is_(True)).order_by(Property.name)
    if property_ids:
        parsed_ids = [UUID(str(pid)) for pid in property_ids]
        stmt = stmt.where(Property.id.in_(parsed_ids))
    else:
        stmt = stmt.where(
            (Property.ota_metadata.is_(None))
            | (Property.ota_metadata[CHANNEX_LISTING_METADATA_KEY].astext.is_(None))
            | (Property.ota_metadata[CHANNEX_LISTING_METADATA_KEY].astext == "")
        )
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _persist_channex_listing_id(
    db: AsyncSession,
    prop: Property,
    listing_id: str,
) -> None:
    prop.ota_metadata = merge_channex_listing_metadata(prop.ota_metadata, listing_id)
    db.add(prop)
    await db.commit()
    await db.refresh(prop)


async def _load_streamline_metadata_hints() -> dict[str, _PropertyMetadataHint]:
    hints: dict[str, _PropertyMetadataHint] = {}
    vrs = StreamlineVRS()
    try:
        data = await vrs._call("GetPropertyList")
    finally:
        await vrs.close()

    raw_props = data.get("property", []) if isinstance(data, dict) else []
    if isinstance(raw_props, dict):
        raw_props = [raw_props]

    for item in raw_props:
        if not isinstance(item, dict):
            continue
        property_id = _extract_string(item, "id")
        property_name = _extract_string(item, "name")
        city = _extract_string(item, "city")
        state = _normalize_state(_extract_string(item, "state_name", "state_description"))
        zip_code = _normalize_zip(_extract_string(item, "zip"))
        hint = _PropertyMetadataHint(
            city=city or None,
            state=state or None,
            zip_code=zip_code or None,
        )
        if property_id:
            hints[f"id:{property_id}"] = hint
        if property_name:
            hints[f"name:{normalize_name(property_name)}"] = hint
    return hints


def _metadata_hint_for_property(
    prop: Property,
    hints: dict[str, _PropertyMetadataHint],
) -> _PropertyMetadataHint:
    streamline_property_id = str(getattr(prop, "streamline_property_id", "") or "").strip()
    streamline_key = f"id:{streamline_property_id}"
    if streamline_property_id and streamline_key in hints:
        return hints[streamline_key]
    name_key = f"name:{normalize_name(getattr(prop, 'name', None))}"
    if name_key in hints:
        return hints[name_key]
    return _PropertyMetadataHint()


def _build_response(dry_run: bool, results: list[ChannexSyncResult]) -> ChannexSyncInventoryResponse:
    created_actions = {"created_property", "would_create_property"}
    mapped_actions = {"mapped_existing", "would_map_existing"}
    failed_actions = {"failed"}
    return ChannexSyncInventoryResponse(
        dry_run=dry_run,
        scanned_count=len(results),
        created_count=sum(1 for item in results if item.action in created_actions),
        mapped_count=sum(1 for item in results if item.action in mapped_actions),
        failed_count=sum(1 for item in results if item.action in failed_actions),
        results=results,
    )


async def sync_inventory_to_channex(
    db: AsyncSession,
    request: ChannexSyncInventoryRequest,
) -> ChannexSyncInventoryResponse:
    properties = await _list_candidate_properties(db, request.property_ids, request.limit)
    if not properties:
        return ChannexSyncInventoryResponse(
            dry_run=request.dry_run,
            scanned_count=0,
            created_count=0,
            mapped_count=0,
            failed_count=0,
            results=[],
        )

    logger.info(
        "channex_sync_started",
        dry_run=request.dry_run,
        requested_property_count=len(request.property_ids or []),
        candidate_count=len(properties),
    )

    results: list[ChannexSyncResult] = []
    try:
        metadata_hints = await _load_streamline_metadata_hints()
    except Exception as exc:  # noqa: BLE001
        logger.warning("channex_sync_streamline_hints_failed", error=str(exc)[:300])
        metadata_hints = {}

    async with httpx.AsyncClient(timeout=60.0) as client:
        upstream = await _fetch_upstream_properties(client)

        for prop in properties:
            metadata_hint = _metadata_hint_for_property(prop, metadata_hints)
            existing_id = has_channex_listing_id(prop)
            if existing_id:
                results.append(
                    ChannexSyncResult(
                        property_id=str(prop.id),
                        slug=prop.slug,
                        property_name=prop.name,
                        action="skipped_existing_mapping",
                        channex_listing_id=existing_id,
                        match_strategy="local_existing",
                    )
                )
                continue

            try:
                matched_id, match_strategy = _find_upstream_match(prop, upstream)
                if matched_id:
                    if not request.dry_run:
                        await _persist_channex_listing_id(db, prop, matched_id)
                    action = "would_map_existing" if request.dry_run else "mapped_existing"
                    results.append(
                        ChannexSyncResult(
                            property_id=str(prop.id),
                            slug=prop.slug,
                            property_name=prop.name,
                            action=action,
                            channex_listing_id=matched_id,
                            match_strategy=match_strategy,
                        )
                    )
                    continue

                if request.dry_run:
                    results.append(
                        ChannexSyncResult(
                            property_id=str(prop.id),
                            slug=prop.slug,
                            property_name=prop.name,
                            action="would_create_property",
                            match_strategy="created_shell",
                        )
                    )
                    continue

                created_id = await _create_upstream_property_shell(
                    client,
                    prop,
                    metadata_hint=metadata_hint,
                )
                await _persist_channex_listing_id(db, prop, created_id)
                upstream.append(
                    _UpstreamProperty(
                        listing_id=created_id,
                        title=prop.name,
                        normalized_title=normalize_name(prop.name),
                    )
                )

                results.append(
                    ChannexSyncResult(
                        property_id=str(prop.id),
                        slug=prop.slug,
                        property_name=prop.name,
                        action="created_property",
                        channex_listing_id=created_id,
                        match_strategy="created_shell",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "channex_sync_property_failed",
                    property_id=str(prop.id),
                    slug=prop.slug,
                    error=str(exc)[:400],
                )
                if db.in_transaction():
                    await db.rollback()
                results.append(
                    ChannexSyncResult(
                        property_id=str(prop.id),
                        slug=prop.slug,
                        property_name=prop.name,
                        action="failed",
                        error=str(exc)[:400],
                    )
                )

    response = _build_response(request.dry_run, results)
    logger.info(
        "channex_sync_completed",
        dry_run=request.dry_run,
        scanned_count=response.scanned_count,
        mapped_count=response.mapped_count,
        created_count=response.created_count,
        failed_count=response.failed_count,
    )
    return response
