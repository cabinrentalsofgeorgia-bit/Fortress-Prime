"""
Deterministic Streamline quote and calendar bridge.

Uses the existing authenticated StreamlineVRS integration for upstream RPC calls,
then normalizes and caches rate cards and blocked-day payloads in Redis so the
Command Center can render live availability and pricing without browser-side
scraping or third-party embeds.

fetch_live_quote() provides async parity auditing by extracting the exact
fee/tax array from Streamline's GetReservationPrice for a given confirmation_id,
parsing it into DisplayFee objects, and returning the Streamline total for
comparison against the local ledger.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.services.ledger import classify_item

live_quote_logger = structlog.get_logger(service="live_quote")

TWO_PLACES = Decimal("0.01")
DEFAULT_TAX_RATE = Decimal("0.13")
WEEKEND_DAYS = {4, 5}
PEAK_MONTHS = {6, 7, 8, 10, 12}

PROPERTY_CATALOG_TTL_SECONDS = 900
RATE_CARD_TTL_SECONDS = 900
BLOCKED_DAYS_TTL_SECONDS = 300
QUOTE_TTL_SECONDS = 300
LIVE_QUOTE_TTL_SECONDS = 300


@dataclass(frozen=True)
class DisplayFee:
    """A single fee/tax/deposit parsed from Streamline's GetReservationPrice."""
    name: str
    amount: Decimal
    fee_type: str
    streamline_id: str
    is_taxable: bool
    bucket: str


@dataclass(frozen=True)
class LiveQuoteResult:
    """Parsed result from Streamline's GetReservationPrice for parity auditing."""
    confirmation_id: str
    fees: list[DisplayFee]
    streamline_total: Decimal
    streamline_taxes: Decimal
    streamline_rent: Decimal
    raw_payload: dict[str, Any]

BEDROOM_BASE_RATES: dict[int, Decimal] = {
    1: Decimal("149.00"),
    2: Decimal("199.00"),
    3: Decimal("269.00"),
    4: Decimal("329.00"),
    5: Decimal("399.00"),
    6: Decimal("449.00"),
    7: Decimal("549.00"),
    8: Decimal("649.00"),
}
DEFAULT_BEDROOM_RATE = Decimal("299.00")

LEGACY_PROPERTY_MAP = {
    "14": "f66def25-6b88-4a72-a023-efa575281a59",
}


@dataclass(slots=True)
class ResolvedStreamlineProperty:
    property_record: Property
    requested_property_id: str
    streamline_unit_id: int


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _parse_streamline_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        if "-" in normalized:
            return date.fromisoformat(normalized)
        month, day, year = normalized.split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def _base_rate_for_property(property_record: Property) -> Decimal:
    return BEDROOM_BASE_RATES.get(property_record.bedrooms, DEFAULT_BEDROOM_RATE)


def _fallback_nightly_rate(property_record: Property, stay_date: date) -> Decimal:
    rate = _base_rate_for_property(property_record)
    if stay_date.weekday() in WEEKEND_DAYS:
        rate = (rate * Decimal("1.20")).quantize(TWO_PLACES, ROUND_HALF_UP)
    if stay_date.month in PEAK_MONTHS:
        rate = (rate * Decimal("1.15")).quantize(TWO_PLACES, ROUND_HALF_UP)
    return rate


def _nightly_from_rate_card(rate_card: dict[str, Any], stay_date: date) -> Decimal | None:
    for entry in rate_card.get("rates", []):
        start = _parse_streamline_date(str(entry.get("start_date") or ""))
        end = _parse_streamline_date(str(entry.get("end_date") or ""))
        if not start or not end or not (start <= stay_date <= end):
            continue
        nightly = entry.get("nightly")
        if nightly in (None, ""):
            continue
        try:
            return Decimal(str(nightly)).quantize(TWO_PLACES, ROUND_HALF_UP)
        except Exception:
            continue
    return None


def _fees_from_rate_card(rate_card: dict[str, Any]) -> Decimal:
    total = Decimal("0.00")
    for fee in rate_card.get("fees", []):
        amount = fee.get("amount")
        if amount in (None, ""):
            continue
        total += Decimal(str(amount)).quantize(TWO_PLACES, ROUND_HALF_UP)
    return total


def _tax_rate_from_rate_card(rate_card: dict[str, Any]) -> Decimal:
    total = Decimal("0.00")
    for tax in rate_card.get("taxes", []):
        rate = tax.get("rate")
        tax_type = str(tax.get("type") or "").lower()
        if rate in (None, "") or "percent" not in tax_type:
            continue
        total += Decimal(str(rate))
    return total if total > 0 else DEFAULT_TAX_RATE


def _is_booked_block(block: dict[str, Any]) -> bool:
    if block.get("confirmation_id"):
        return True
    block_name = str(block.get("type_name") or "").lower()
    return any(token in block_name for token in ("reservation", "book", "stay"))


class StreamlineClient:
    def __init__(self) -> None:
        self._vrs = StreamlineVRS()
        self._redis: Redis | None = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        await self._vrs.close()

    async def _vault_log(
        self,
        event_type: str,
        raw_payload: Any,
        reservation_id: str | None = None,
    ) -> None:
        """Write raw Streamline API response to the payload vault.

        Uses its own session so a vault write failure never disrupts the
        caller's transaction or control flow.
        """
        try:
            from backend.core.database import AsyncSessionLocal
            from backend.models.streamline_payload_vault import StreamlinePayloadVault

            async with AsyncSessionLocal() as session:
                session.add(StreamlinePayloadVault(
                    event_type=event_type,
                    raw_payload=raw_payload if isinstance(raw_payload, (dict, list)) else {},
                    reservation_id=reservation_id,
                ))
                await session.commit()
        except Exception as exc:
            live_quote_logger.warning(
                "vault_write_failed",
                event_type=event_type,
                error=str(exc)[:200],
            )

    async def _get_cached_json(self, cache_key: str) -> dict[str, Any] | None:
        redis = await self._get_redis()
        payload = await redis.get(cache_key)
        if not payload:
            return None
        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    async def _set_cached_json(
        self,
        cache_key: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        redis = await self._get_redis()
        await redis.set(
            cache_key,
            json.dumps(payload, default=_json_default, separators=(",", ":")),
            ex=ttl_seconds,
        )

    async def resolve_property(
        self,
        requested_property_id: str | UUID,
        db: AsyncSession,
    ) -> ResolvedStreamlineProperty:
        raw_property_id = str(requested_property_id).strip()
        if not raw_property_id:
            raise ValueError("property_id is required")

        resolved_identifier = LEGACY_PROPERTY_MAP.get(raw_property_id, raw_property_id)
        property_record: Property | None = None

        try:
            property_uuid = UUID(resolved_identifier)
        except ValueError:
            property_uuid = None

        if property_uuid is not None:
            result = await db.execute(select(Property).where(Property.id == property_uuid))
            property_record = result.scalar_one_or_none()

        if property_record is None:
            result = await db.execute(
                select(Property).where(Property.streamline_property_id == resolved_identifier)
            )
            property_record = result.scalar_one_or_none()

        if property_record is None:
            raise ValueError(
                "Property not found. Expected a mapped legacy ID, property UUID, "
                "or Streamline property ID."
            )

        streamline_property_id = str(property_record.streamline_property_id or "").strip()
        if not streamline_property_id:
            raise ValueError("Resolved property is not mapped to a Streamline unit")

        try:
            streamline_unit_id = int(streamline_property_id)
        except ValueError as exc:
            raise ValueError("Resolved property has an invalid Streamline unit id") from exc

        return ResolvedStreamlineProperty(
            property_record=property_record,
            requested_property_id=raw_property_id,
            streamline_unit_id=streamline_unit_id,
        )

    async def get_property_catalog(
        self,
        db: AsyncSession,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        cache_key = "streamline:catalog:v1"
        if not force_refresh:
            cached = await self._get_cached_json(cache_key)
            if cached is not None:
                cached["cache_hit"] = True
                return cached

        result = await db.execute(
            select(Property)
            .where(Property.streamline_property_id.is_not(None))
            .order_by(Property.name.asc())
        )
        local_properties = result.scalars().all()
        local_by_streamline = {
            str(prop.streamline_property_id): prop
            for prop in local_properties
            if prop.streamline_property_id
        }

        remote_properties = await self._vrs.fetch_properties()
        await self._vault_log("fetch_properties", remote_properties)
        merged_properties: list[dict[str, Any]] = []

        for remote in remote_properties:
            streamline_id = str(remote.get("streamline_property_id") or "").strip()
            local = local_by_streamline.get(streamline_id)
            if local is None:
                continue
            merged_properties.append(
                {
                    "id": str(local.id),
                    "name": local.name,
                    "slug": local.slug,
                    "streamline_property_id": streamline_id,
                    "bedrooms": local.bedrooms,
                    "bathrooms": float(local.bathrooms or 0),
                    "max_guests": local.max_guests,
                    "address": local.address,
                    "is_active": bool(local.is_active),
                    "source": "streamline_catalog",
                }
            )

        if not merged_properties:
            for local in local_properties:
                merged_properties.append(
                    {
                        "id": str(local.id),
                        "name": local.name,
                        "slug": local.slug,
                        "streamline_property_id": str(local.streamline_property_id),
                        "bedrooms": local.bedrooms,
                        "bathrooms": float(local.bathrooms or 0),
                        "max_guests": local.max_guests,
                        "address": local.address,
                        "is_active": bool(local.is_active),
                        "source": "database_fallback",
                    }
                )

        payload = {
            "properties": merged_properties,
            "fetched_at": _timestamp(),
            "cache_hit": False,
        }
        await self._set_cached_json(cache_key, payload, PROPERTY_CATALOG_TTL_SECONDS)
        return payload

    async def _get_live_rate_card(
        self,
        resolved: ResolvedStreamlineProperty,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        cache_key = f"streamline:rate-card:{resolved.streamline_unit_id}:v1"
        if not force_refresh:
            cached = await self._get_cached_json(cache_key)
            if cached is not None:
                return cached

        source = "streamline_live"
        rate_card = await self._vrs.fetch_property_rates(resolved.streamline_unit_id)
        await self._vault_log("fetch_property_rates", rate_card)
        if not rate_card and isinstance(resolved.property_record.rate_card, dict):
            rate_card = resolved.property_record.rate_card
            source = "database_rate_card_fallback"

        payload = {
            "rate_card": rate_card or {},
            "source": source,
            "fetched_at": _timestamp(),
        }
        await self._set_cached_json(cache_key, payload, RATE_CARD_TTL_SECONDS)
        return payload

    async def _get_live_blocked_days(
        self,
        resolved: ResolvedStreamlineProperty,
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        cache_key = (
            "streamline:blocked-days:"
            f"{resolved.streamline_unit_id}:{start_date.isoformat()}:{end_date.isoformat()}:v1"
        )
        if not force_refresh:
            cached = await self._get_cached_json(cache_key)
            if cached is not None:
                return cached

        blocks = await self._vrs.fetch_blocked_days(
            resolved.streamline_unit_id,
            start_date=start_date,
            end_date=end_date,
        )
        await self._vault_log("fetch_blocked_days", blocks)
        payload = {
            "blocked_days": blocks,
            "source": "streamline_live",
            "fetched_at": _timestamp(),
        }
        await self._set_cached_json(cache_key, payload, BLOCKED_DAYS_TTL_SECONDS)
        return payload

    async def get_master_calendar(
        self,
        property_id: str | UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        resolved = await self.resolve_property(property_id, db)
        rate_card_payload, blocked_days_payload = await asyncio.gather(
            self._get_live_rate_card(resolved, force_refresh=force_refresh),
            self._get_live_blocked_days(
                resolved,
                start_date,
                end_date,
                force_refresh=force_refresh,
            ),
        )

        rate_card = rate_card_payload.get("rate_card", {})
        raw_blocks = blocked_days_payload.get("blocked_days", [])
        blocked_map: dict[date, dict[str, Any]] = {}
        normalized_blocks: list[dict[str, Any]] = []

        for block in raw_blocks:
            block_start = block.get("start_date")
            block_end = block.get("end_date")
            checkout_date = block.get("checkout_date")
            if not isinstance(block_start, date) or not isinstance(block_end, date):
                continue

            cursor = max(block_start, start_date)
            exclusive_end = min(
                checkout_date if isinstance(checkout_date, date) else block_end + timedelta(days=1),
                end_date + timedelta(days=1),
            )
            status = "booked" if _is_booked_block(block) else "blocked"

            while cursor < exclusive_end:
                blocked_map[cursor] = {
                    "status": status,
                    "confirmation_id": str(block.get("confirmation_id") or "") or None,
                    "block_type": str(block.get("type_name") or "") or None,
                    "source": "streamline_live",
                }
                cursor += timedelta(days=1)

            normalized_blocks.append(
                {
                    "start_date": block_start.isoformat(),
                    "end_date": block_end.isoformat(),
                    "checkout_date": checkout_date.isoformat() if isinstance(checkout_date, date) else None,
                    "status": status,
                    "confirmation_id": str(block.get("confirmation_id") or "") or None,
                    "block_type": str(block.get("type_name") or "") or None,
                    "type_description": str(block.get("type_description") or "") or None,
                }
            )

        days: dict[str, Any] = {}
        available_days = 0
        booked_days = 0
        blocked_days = 0
        nightly_rates: list[Decimal] = []

        cursor = start_date
        while cursor <= end_date:
            nightly_rate = _nightly_from_rate_card(rate_card, cursor)
            pricing_source = str(rate_card_payload.get("source") or "streamline_live")
            if nightly_rate is None:
                nightly_rate = _fallback_nightly_rate(resolved.property_record, cursor)
                pricing_source = f"{pricing_source}:fallback"

            status_payload = blocked_map.get(
                cursor,
                {"status": "available", "source": "streamline_live"},
            )
            status = str(status_payload["status"])
            if status == "available":
                available_days += 1
            elif status == "booked":
                booked_days += 1
            else:
                blocked_days += 1

            nightly_rates.append(nightly_rate)
            days[cursor.isoformat()] = {
                "status": status,
                "nightly_rate": float(nightly_rate),
                "is_peak": cursor.month in PEAK_MONTHS,
                "confirmation_id": status_payload.get("confirmation_id"),
                "block_type": status_payload.get("block_type"),
                "source": status_payload.get("source"),
                "pricing_source": pricing_source,
            }
            cursor += timedelta(days=1)

        avg_rate = (
            (sum(nightly_rates, Decimal("0.00")) / Decimal(len(nightly_rates))).quantize(TWO_PLACES)
            if nightly_rates
            else Decimal("0.00")
        )

        return {
            "property_id": str(resolved.property_record.id),
            "property_name": resolved.property_record.name,
            "streamline_property_id": str(resolved.property_record.streamline_property_id),
            "requested_property_id": resolved.requested_property_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
            "blocks": normalized_blocks,
            "summary": {
                "available_days": available_days,
                "booked_days": booked_days,
                "blocked_days": blocked_days,
                "average_nightly_rate": float(avg_rate),
            },
            "rate_source": rate_card_payload.get("source"),
            "availability_source": blocked_days_payload.get("source"),
            "fetched_at": _timestamp(),
            "cache_hit": False,
        }

    def _fees_from_property_record(
        self,
        prop: Property,
        pets: int,
    ) -> Decimal:
        """
        Read the flat fee total from the property's stored cleaning_fee column.

        GetPropertyRates returns a daily_rate_list for all properties and carries
        no fee data. The cleaning_fee column is populated from historical reservation
        data (seeded by migration j5e6f7a8b9c0) and kept current by the Streamline
        sync.  Returns Decimal("0.00") when no fee is configured.
        """
        cleaning = Decimal(str(prop.cleaning_fee or "0"))
        live_quote_logger.debug(
            "fees_from_property_record",
            property_id=str(prop.id),
            property_name=prop.name,
            cleaning_fee=str(cleaning),
            pets=pets,
        )
        return cleaning.quantize(TWO_PLACES, ROUND_HALF_UP)

    async def get_deterministic_quote(
        self,
        property_id: str | UUID,
        check_in: date,
        check_out: date,
        db: AsyncSession,
        *,
        adults: int = 2,
        children: int = 0,
        pets: int = 0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if check_out <= check_in:
            raise ValueError("check_out must be after check_in")

        resolved = await self.resolve_property(property_id, db)
        cache_key = (
            "streamline:quote:"
            f"{resolved.streamline_unit_id}:{check_in.isoformat()}:{check_out.isoformat()}:"
            f"{adults}:{children}:{pets}:v2"
        )
        if not force_refresh:
            cached = await self._get_cached_json(cache_key)
            if cached is not None:
                cached["cache_hit"] = True
                return cached

        calendar = await self.get_master_calendar(
            resolved.property_record.id,
            check_in,
            check_out - timedelta(days=1),
            db,
            force_refresh=force_refresh,
        )
        rate_card_payload = await self._get_live_rate_card(resolved, force_refresh=force_refresh)
        rate_card = rate_card_payload.get("rate_card", {})

        unavailable_dates = [
            day
            for day, payload in calendar["days"].items()
            if payload.get("status") != "available"
        ]

        nightly_breakdown: list[dict[str, Any]] = []
        base_rent = Decimal("0.00")
        cursor = check_in
        while cursor < check_out:
            nightly_rate = _nightly_from_rate_card(rate_card, cursor)
            nightly_source = str(rate_card_payload.get("source") or "streamline_live")
            if nightly_rate is None:
                nightly_rate = _fallback_nightly_rate(resolved.property_record, cursor)
                nightly_source = f"{nightly_source}:fallback"

            nightly_breakdown.append(
                {
                    "date": cursor.isoformat(),
                    "rate": float(nightly_rate),
                    "source": nightly_source,
                    "is_peak": cursor.month in PEAK_MONTHS,
                }
            )
            base_rent += nightly_rate
            cursor += timedelta(days=1)

        fees = _fees_from_rate_card(rate_card)
        live_quote_logger.debug(
            "deterministic_quote_fee_debug",
            property_id=str(resolved.property_record.id),
            property_name=resolved.property_record.name,
            payload_shape=rate_card.get("payload_shape"),
            rate_card_fee_count=len(rate_card.get("fees", [])),
            fees_from_rate_card=str(fees),
            cache_key=cache_key,
        )
        if fees == Decimal("0.00"):
            # GetPropertyRates returns a daily_rate_list for these properties —
            # that format carries no fee data. Read the cleaning_fee stored on
            # the property record (seeded from historical reservation history).
            fees = self._fees_from_property_record(resolved.property_record, pets)
        tax_rate = _tax_rate_from_rate_card(rate_card)
        taxes = ((base_rent + fees) * tax_rate).quantize(TWO_PLACES, ROUND_HALF_UP)
        total = (base_rent + fees + taxes).quantize(TWO_PLACES, ROUND_HALF_UP)

        payload = {
            "property_id": str(resolved.property_record.id),
            "property_name": resolved.property_record.name,
            "streamline_property_id": str(resolved.property_record.streamline_property_id),
            "requested_property_id": resolved.requested_property_id,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "nights": (check_out - check_in).days,
            "adults": adults,
            "children": children,
            "pets": pets,
            "availability_status": "available" if not unavailable_dates else "unavailable",
            "unavailable_dates": unavailable_dates,
            "base_rent": float(base_rent.quantize(TWO_PLACES, ROUND_HALF_UP)),
            "fees": float(fees.quantize(TWO_PLACES, ROUND_HALF_UP)),
            "tax_rate": float(tax_rate),
            "taxes": float(taxes),
            "total_amount": float(total),
            "pricing_source": rate_card_payload.get("source"),
            "nightly_breakdown": nightly_breakdown,
            "calendar_summary": calendar.get("summary"),
            "fetched_at": _timestamp(),
            "cache_hit": False,
        }
        await self._set_cached_json(cache_key, payload, QUOTE_TTL_SECONDS)
        return payload

    async def refresh_property_cache(
        self,
        property_id: str | UUID,
        db: AsyncSession,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        resolved = await self.resolve_property(property_id, db)
        await asyncio.gather(
            self._get_live_rate_card(resolved, force_refresh=True),
            self._get_live_blocked_days(
                resolved,
                start_date=start_date,
                end_date=end_date,
                force_refresh=True,
            ),
        )
        return {
            "status": "refreshed",
            "property_id": str(resolved.property_record.id),
            "streamline_property_id": str(resolved.property_record.streamline_property_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "refreshed_at": _timestamp(),
        }

    # ------------------------------------------------------------------
    # Live Quote — async parity auditing via GetReservationPrice
    # ------------------------------------------------------------------

    async def fetch_live_quote(
        self,
        confirmation_id: str,
    ) -> LiveQuoteResult | None:
        """Fetch the exact fee/tax array from Streamline for parity comparison.

        Returns None if Streamline is unreachable or returns no data.
        """
        cache_key = f"streamline:live-quote:{confirmation_id}:v1"
        cached = await self._get_cached_json(cache_key)
        if cached is not None:
            return self._parse_live_quote(confirmation_id, cached)

        raw = await self._vrs.fetch_reservation_price(confirmation_id)
        await self._vault_log("fetch_reservation_price", raw, reservation_id=confirmation_id)
        if not raw:
            live_quote_logger.warning(
                "live_quote_empty_response",
                confirmation_id=confirmation_id,
            )
            return None

        await self._set_cached_json(cache_key, raw, LIVE_QUOTE_TTL_SECONDS)
        return self._parse_live_quote(confirmation_id, raw)

    @staticmethod
    def _safe_decimal(value: Any) -> Decimal:
        if value is None or value == "":
            return Decimal("0.00")
        try:
            return Decimal(str(value)).quantize(TWO_PLACES, ROUND_HALF_UP)
        except Exception:
            return Decimal("0.00")

    @staticmethod
    def _parse_live_quote(
        confirmation_id: str,
        data: dict[str, Any],
    ) -> LiveQuoteResult:
        fees: list[DisplayFee] = []

        required_fees = data.get("required_fees", [])
        if isinstance(required_fees, dict):
            required_fees = [required_fees]
        for fee in required_fees:
            if not fee.get("active"):
                continue
            name = str(fee.get("name") or "").strip()
            amount = StreamlineClient._safe_decimal(fee.get("value"))
            if not name or amount == Decimal("0.00"):
                continue
            bucket = classify_item("fee", name).value
            fees.append(DisplayFee(
                name=name,
                amount=amount,
                fee_type="fee",
                streamline_id=str(fee.get("id") or fee.get("fee_id") or ""),
                is_taxable=True,
                bucket=bucket,
            ))

        taxes_section = data.get("taxes_detail", [])
        if isinstance(taxes_section, dict):
            taxes_section = [taxes_section]
        for tax in taxes_section if isinstance(taxes_section, list) else []:
            name = str(tax.get("name") or "").strip()
            amount = StreamlineClient._safe_decimal(tax.get("value") or tax.get("amount"))
            if not name or amount == Decimal("0.00"):
                continue
            fees.append(DisplayFee(
                name=name,
                amount=amount,
                fee_type="tax",
                streamline_id=str(tax.get("id") or tax.get("tax_id") or ""),
                is_taxable=False,
                bucket="tax",
            ))

        security_deposits = data.get("security_deposits", [])
        if isinstance(security_deposits, dict):
            security_deposits = [security_deposits]
        for dep in security_deposits if isinstance(security_deposits, list) else []:
            name = str(dep.get("name") or "Security Deposit").strip()
            amount = StreamlineClient._safe_decimal(dep.get("value") or dep.get("amount"))
            if amount == Decimal("0.00"):
                continue
            fees.append(DisplayFee(
                name=name,
                amount=amount,
                fee_type="deposit",
                streamline_id=str(dep.get("id") or ""),
                is_taxable=False,
                bucket="exempt",
            ))

        streamline_total = StreamlineClient._safe_decimal(data.get("total"))
        streamline_taxes = StreamlineClient._safe_decimal(data.get("taxes"))
        streamline_rent = StreamlineClient._safe_decimal(data.get("price"))

        return LiveQuoteResult(
            confirmation_id=confirmation_id,
            fees=fees,
            streamline_total=streamline_total,
            streamline_taxes=streamline_taxes,
            streamline_rent=streamline_rent,
            raw_payload=data,
        )
