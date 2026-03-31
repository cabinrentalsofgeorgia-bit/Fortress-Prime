"""
AirDNA client and STR signal synchronization helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.core.config import settings
from backend.models.acquisition import AcquisitionIntelEvent, SignalSource
from backend.services.acquisition_matching import (
    create_str_signal,
    ensure_property_for_parcel,
    json_safe,
    resolve_parcel_by_id,
    resolve_property_by_address,
    resolve_property_by_coordinates,
)

logger = structlog.get_logger(service="airdna_client")


class AirDNASignalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_id: str | None = None
    apn: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    projected_adr: Decimal | None = None
    projected_annual_revenue: Decimal | None = None
    listing_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class AirDNASyncJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: str = Field(default_factory=lambda: str(settings.airdna_market or "Fannin County, Georgia").strip() or "Fannin County, Georgia")
    dry_run: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _base_url() -> str:
    value = str(settings.airdna_base_url or "").strip().rstrip("/")
    if not value:
        raise RuntimeError("AIRDNA_BASE_URL is not configured")
    return value


def _market_path() -> str:
    value = str(settings.airdna_market_path or "").strip()
    if not value:
        raise RuntimeError("AIRDNA_MARKET_PATH is not configured")
    return value if value.startswith("/") else f"/{value}"


def _headers() -> dict[str, str]:
    api_key = str(settings.airdna_api_key or "").strip()
    if not api_key:
        raise RuntimeError("AIRDNA_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _timeout() -> httpx.Timeout:
    timeout_seconds = max(10.0, float(settings.airdna_timeout_seconds or 45.0))
    return httpx.Timeout(connect=min(15.0, timeout_seconds), read=timeout_seconds, write=20.0, pool=15.0)


def _coerce_decimal(value: Any) -> Decimal | None:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_record(payload: dict[str, Any]) -> AirDNASignalRecord:
    apn = payload.get("apn") or payload.get("parcel_id") or payload.get("parcelId")
    address = payload.get("address") or payload.get("property_address") or payload.get("street")
    latitude = (
        _coerce_float(payload.get("latitude"))
        or _coerce_float(payload.get("lat"))
        or _coerce_float((payload.get("coordinates") or {}).get("lat") if isinstance(payload.get("coordinates"), dict) else None)
    )
    longitude = (
        _coerce_float(payload.get("longitude"))
        or _coerce_float(payload.get("lng"))
        or _coerce_float((payload.get("coordinates") or {}).get("lng") if isinstance(payload.get("coordinates"), dict) else None)
    )
    projected_adr = _coerce_decimal(payload.get("projected_adr") or payload.get("adr") or payload.get("average_daily_rate"))
    projected_annual_revenue = _coerce_decimal(
        payload.get("projected_annual_revenue")
        or payload.get("annual_revenue")
        or payload.get("estimated_annual_revenue")
    )
    return AirDNASignalRecord.model_validate(
        {
            "external_id": payload.get("id") or payload.get("external_id"),
            "apn": apn,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "projected_adr": projected_adr,
            "projected_annual_revenue": projected_annual_revenue,
            "listing_url": payload.get("listing_url") or payload.get("url"),
            "raw_payload": json_safe(payload),
        }
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _fetch_market_payload(market: str) -> dict[str, Any]:
    params = {"market": market}
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        response = await client.get(f"{_base_url()}{_market_path()}", params=params, headers=_headers())
        response.raise_for_status()
        return response.json()


async def fetch_airdna_signals(market: str) -> list[AirDNASignalRecord]:
    try:
        payload = await _fetch_market_payload(market)
    except RuntimeError:
        logger.info("airdna_sync_skipped", reason="not_configured")
        return []
    except httpx.HTTPError as exc:
        logger.warning("airdna_sync_http_failed", error=str(exc)[:300], market=market)
        return []

    candidates: Any = payload.get("data", payload)
    if isinstance(candidates, dict):
        for key in ("listings", "results", "properties", "items"):
            if isinstance(candidates.get(key), list):
                candidates = candidates[key]
                break
    if not isinstance(candidates, list):
        return []
    return [_normalize_record(item) for item in candidates if isinstance(item, dict)]


async def run_airdna_sync(db: AsyncSession, payload: AirDNASyncJobPayload) -> dict[str, Any]:
    dry_run_savepoint = await db.begin_nested() if payload.dry_run else None
    signals = await fetch_airdna_signals(payload.market)
    summary = {
        "market": payload.market,
        "dry_run": payload.dry_run,
        "signals_seen": len(signals),
        "signals_created": 0,
        "properties_updated": 0,
        "intel_events_created": 0,
        "unmatched_signals": 0,
        "warnings": [],
    }

    try:
        for signal in signals:
            prop = None
            matched_by = None
            parcel = await resolve_parcel_by_id(db, signal.apn)
            if parcel is not None:
                prop = await ensure_property_for_parcel(db, parcel=parcel)
                matched_by = "apn"
            if prop is None and signal.address:
                prop = await resolve_property_by_address(db, address=signal.address)
                if prop is not None:
                    matched_by = "address"
            if prop is None and signal.latitude is not None and signal.longitude is not None:
                prop, inside = await resolve_property_by_coordinates(
                    db,
                    latitude=signal.latitude,
                    longitude=signal.longitude,
                    radius_meters=int(settings.acquisition_ota_radius_meters or 75),
                )
                if prop is not None:
                    matched_by = "coordinates_contains" if inside else "coordinates_nearby"
            if prop is None:
                summary["unmatched_signals"] += 1
                summary["warnings"].append(f"Unmatched AirDNA signal: {signal.address or signal.apn or signal.external_id or '<unknown>'}")
                continue

            updated = False
            if signal.projected_adr is not None and prop.projected_adr != signal.projected_adr:
                prop.projected_adr = signal.projected_adr
                updated = True
            if signal.projected_annual_revenue is not None and prop.projected_annual_revenue != signal.projected_annual_revenue:
                prop.projected_annual_revenue = signal.projected_annual_revenue
                updated = True
            if updated:
                summary["properties_updated"] += 1

            await create_str_signal(
                db,
                property_id=prop.id,
                signal_source=SignalSource.AGGREGATOR_API,
                confidence_score=Decimal("0.90"),
                raw_payload={
                    "source": "airdna",
                    "matched_by": matched_by,
                    "market": payload.market,
                    "signal": signal.model_dump(mode="json"),
                },
            )
            summary["signals_created"] += 1

            db.add(
                AcquisitionIntelEvent(
                    property_id=prop.id,
                    event_type="AIRDNA_SIGNAL_SYNC",
                    event_description=f"AirDNA market signal synchronized for {payload.market}.",
                    raw_source_data={
                        "matched_by": matched_by,
                        "market": payload.market,
                        "external_id": signal.external_id,
                    },
                )
            )
            await db.flush()
            summary["intel_events_created"] += 1

        if payload.dry_run:
            if dry_run_savepoint is not None:
                await dry_run_savepoint.rollback()
        else:
            await db.commit()
        return summary
    except Exception:
        if dry_run_savepoint is not None:
            await dry_run_savepoint.rollback()
        await db.rollback()
        raise
