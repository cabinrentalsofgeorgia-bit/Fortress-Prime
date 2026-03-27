"""
Competitive OTA pricing sweeps for sovereign direct-book parity signals.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import async_session_maker
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.property import Property
from backend.models.treasury import CompetitorListing, OTAProvider
from backend.services.quote_builder import build_local_rent_quote

logger = structlog.get_logger(service="competitive_sentinel")
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_SENTINEL_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=20.0, pool=10.0)
_TWO_PLACES = Decimal("0.01")
_SAVINGS_THRESHOLD = Decimal("15.00")


class CompetitiveSentinelQuote(BaseModel):
    platform: str
    nightly: float
    platform_fee: float = 0.0
    cleaning_fee: float = 0.0
    total_before_tax: float
    total_after_tax: float | None = None
    external_url: str | None = None
    external_id: str | None = None

    @property
    def nightly_rate(self) -> Decimal:
        return _to_money(self.nightly)

    @property
    def observed_total_before_tax(self) -> Decimal:
        return _to_money(self.total_before_tax)


class DiscoveredOTALink(BaseModel):
    platform: str
    url: str


@dataclass(frozen=True)
class SweepWindow:
    check_in: date
    check_out: date


@dataclass(frozen=True)
class LocalParityQuote:
    total_before_tax: Decimal
    total_after_tax: Decimal | None


def _to_money(value: Any, *, default: str = "0.00") -> Decimal:
    raw = default if value is None else str(value)
    raw = raw.replace(",", "").strip()
    try:
        return Decimal(raw).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    except Exception as exc:  # pragma: no cover - defensive normalization
        raise ValueError(f"Invalid money value: {value!r}") from exc


def _extract_response_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini Sentinel response did not include candidates")
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text_parts = [
        str(part.get("text")).strip()
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("text").strip()
    ]
    if not text_parts:
        raise RuntimeError("Gemini Sentinel response did not include textual JSON output")
    return "\n".join(text_parts)


def _extract_json_payload(raw_text: str) -> Any:
    trimmed = raw_text.strip()
    if trimmed.startswith("```"):
        trimmed = re.sub(r"^```(?:json)?\s*", "", trimmed)
        trimmed = re.sub(r"\s*```$", "", trimmed)
    return json.loads(trimmed)


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _extract_grounding_urls(payload: dict[str, Any]) -> list[str]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    urls: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        grounding = candidate.get("groundingMetadata")
        if not isinstance(grounding, dict):
            continue
        chunks = grounding.get("groundingChunks")
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            uri = web.get("uri")
            if isinstance(uri, str) and uri.strip():
                urls.append(_canonicalize_url(uri))
    return sorted(dict.fromkeys(urls))


def _extract_grounding_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        grounding = candidate.get("groundingMetadata")
        if isinstance(grounding, dict):
            return grounding
    return {}


def _rate_card_fee_total(rate_card: Any) -> Decimal:
    if not isinstance(rate_card, dict):
        return Decimal("0.00")
    total = Decimal("0.00")
    for fee in rate_card.get("fees", []):
        if not isinstance(fee, dict):
            continue
        amount = fee.get("amount")
        if amount is None:
            continue
        total += _to_money(amount)
    return total.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _rate_card_tax_total(rate_card: Any, taxable_base: Decimal) -> Decimal | None:
    if not isinstance(rate_card, dict):
        return None
    total_rate = Decimal("0.00")
    for tax in rate_card.get("taxes", []):
        if not isinstance(tax, dict):
            continue
        rate = tax.get("rate")
        tax_type = str(tax.get("type") or "").lower()
        if rate is None or "percent" not in tax_type:
            continue
        total_rate += Decimal(str(rate))
    if total_rate <= Decimal("0.00"):
        return None
    return (taxable_base * total_rate).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _authoritative_ota_links(metadata: Any) -> dict[OTAProvider, str]:
    if not isinstance(metadata, dict):
        return {}
    raw_pairs = {
        OTAProvider.AIRBNB: metadata.get("airbnb_url"),
        OTAProvider.VRBO: metadata.get("vrbo_url"),
        OTAProvider.BOOKING: metadata.get("booking_com_url") or metadata.get("booking_url"),
    }
    normalized: dict[OTAProvider, str] = {}
    for provider, raw_url in raw_pairs.items():
        if isinstance(raw_url, str) and raw_url.strip():
            normalized[provider] = raw_url.strip()
    return normalized


def _provider_domain(provider: OTAProvider) -> str:
    return {
        OTAProvider.AIRBNB: "airbnb.com",
        OTAProvider.VRBO: "vrbo.com",
        OTAProvider.BOOKING: "booking.com",
    }[provider]


def _provider_url_is_valid(provider: OTAProvider, url: str) -> bool:
    normalized = _canonicalize_url(url)
    return _provider_domain(provider) in normalized.lower()


def _first_money_amount(text: str) -> Decimal | None:
    match = re.search(r"(?:US\$|\$)\s?(\d[\d,]*(?:\.\d+)?)", text)
    if not match:
        return None
    return _to_money(match.group(1))


def _first_amount(text: str) -> Decimal | None:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text)
    if not match:
        return None
    return _to_money(match.group(1))


def _money_before_keyword(text: str, keyword: str) -> Decimal | None:
    match = re.search(
        rf"(?:US\$|\$)\s?(\d[\d,]*(?:\.\d+)?)\s+{re.escape(keyword)}",
        text,
        flags=re.I,
    )
    if not match:
        return None
    return _to_money(match.group(1))


def _amount_before_keyword(text: str, keyword: str) -> Decimal | None:
    match = re.search(
        rf"(?:(?:US\$|\$)\s?)?(\d[\d,]*(?:\.\d+)?)\s+{re.escape(keyword)}",
        text,
        flags=re.I,
    )
    if not match:
        return None
    return _to_money(match.group(1))


def _percentage_amount(text: str) -> Decimal | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    return Decimal(match.group(1)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _booking_quote_from_probe_result(
    probe_result: dict[str, Any],
    *,
    nights: int,
) -> CompetitiveSentinelQuote | None:
    if nights <= 0:
        return None

    provider = str(probe_result.get("provider") or "").strip()
    if provider and provider != OTAProvider.BOOKING.value:
        return None

    signals = [
        str(signal).strip()
        for signal in list(probe_result.get("price_signals") or [])
        if isinstance(signal, str) and signal.strip()
    ]
    if not signals:
        return None

    total_before_tax: Decimal | None = None
    nightly_rate: Decimal | None = None
    cleaning_fee = Decimal("0.00")
    excluded_tax_rate = Decimal("0.00")

    for signal in signals:
        if total_before_tax is None:
            price_match = re.search(r"Price[:\s]+(?:US\$|\$)\s?(\d[\d,]*(?:\.\d+)?)", signal, flags=re.I)
            if price_match:
                total_before_tax = _to_money(price_match.group(1))
        if nightly_rate is None and re.search(r"per night", signal, flags=re.I):
            nightly_rate = _amount_before_keyword(signal, "per night") or _first_amount(signal)
        if re.search(r"cleaning fee", signal, flags=re.I):
            money = _amount_before_keyword(signal, "Cleaning fee") or _money_before_keyword(
                signal, "Cleaning fee"
            )
            if money is not None:
                cleaning_fee = money
        if re.search(r"excluded:.*tax", signal, flags=re.I):
            excluded_segment = signal.split("Excluded:", 1)[-1]
            percent = _percentage_amount(excluded_segment)
            if percent is not None:
                excluded_tax_rate = percent

    if total_before_tax is None or nightly_rate is None:
        return None

    base_rent = (nightly_rate * Decimal(nights)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    platform_fee = max(
        Decimal("0.00"),
        (total_before_tax - base_rent - cleaning_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
    )
    total_after_tax = total_before_tax
    if excluded_tax_rate > Decimal("0.00"):
        total_after_tax = (
            total_before_tax * (Decimal("1.00") + (excluded_tax_rate / Decimal("100.00")))
        ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    return CompetitiveSentinelQuote(
        platform=OTAProvider.BOOKING.value,
        nightly=float(nightly_rate),
        platform_fee=float(platform_fee),
        cleaning_fee=float(cleaning_fee),
        total_before_tax=float(total_before_tax),
        total_after_tax=float(total_after_tax),
        external_url=str(probe_result.get("source_url") or probe_result.get("final_url") or "").strip() or None,
        external_id=None,
    )


class CompetitiveSentinelService:
    """
    Grounded OTA pricing auditor that proves direct-book parity and savings.
    """

    def __init__(self) -> None:
        self.market = str(settings.research_scout_market or "Blue Ridge, Georgia").strip()
        self.model = str(settings.gemini_model or "gemini-2.5-pro").strip()
        self.frontend_root = Path(__file__).resolve().parents[2] / "apps" / "storefront"

    def _generate_dedupe_hash(
        self,
        property_id: str,
        platform: str,
        check_in: str,
        check_out: str,
    ) -> str:
        content = f"{property_id}:{platform}:{check_in}:{check_out}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _normalize_platform(self, raw_platform: str) -> OTAProvider | None:
        normalized = raw_platform.strip().lower().replace(".", "_").replace("-", "_")
        aliases = {
            "airbnb": OTAProvider.AIRBNB,
            "vrbo": OTAProvider.VRBO,
            "homeaway": OTAProvider.VRBO,
            "booking": OTAProvider.BOOKING,
            "booking_com": OTAProvider.BOOKING,
            "bookingcom": OTAProvider.BOOKING,
        }
        return aliases.get(normalized)

    def _build_window(self, lookahead_days: int) -> SweepWindow:
        check_in = date.today() + timedelta(days=lookahead_days)
        return SweepWindow(check_in=check_in, check_out=check_in + timedelta(days=3))

    async def _probe_booking_quotes(
        self,
        properties: list[Property],
        *,
        check_in: date,
        check_out: date,
    ) -> dict[str, list[CompetitiveSentinelQuote]]:
        targets = []
        for prop in properties:
            ota_links = _authoritative_ota_links(getattr(prop, "ota_metadata", None))
            booking_url = ota_links.get(OTAProvider.BOOKING)
            if not booking_url:
                continue
            targets.append({"slug": str(prop.slug), "booking_com_url": booking_url})
        if not targets:
            return {}

        script_path = self.frontend_root / "scripts" / "probe_ota_checkout.mjs"
        if not script_path.exists():
            logger.warning("competitive_sentinel_booking_probe_missing_script", path=str(script_path))
            return {}

        async with asyncio.timeout(180):
            with tempfile.TemporaryDirectory(prefix="ota-booking-probe-") as tmp_dir:
                target_path = Path(tmp_dir) / "targets.json"
                target_path.write_text(json.dumps(targets), encoding="utf-8")
                proc = await asyncio.create_subprocess_exec(
                    "node",
                    str(script_path),
                    "--input",
                    str(target_path),
                    "--check-in",
                    check_in.isoformat(),
                    "--check-out",
                    check_out.isoformat(),
                    cwd=str(self.frontend_root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                "competitive_sentinel_booking_probe_failed",
                returncode=proc.returncode,
                stderr=stderr.decode("utf-8", errors="replace")[:1000],
            )
            return {}

        payload = json.loads(stdout.decode("utf-8", errors="replace"))
        rows = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return {}

        nights = max(1, (check_out - check_in).days)
        quotes_by_slug: dict[str, list[CompetitiveSentinelQuote]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            quote = _booking_quote_from_probe_result(row, nights=nights)
            if quote is None:
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            quotes_by_slug.setdefault(slug, []).append(quote)
        return quotes_by_slug

    async def backfill_ota_metadata(
        self,
        *,
        property_slug: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        async with async_session_maker() as db:
            stmt = select(Property).where(Property.is_active.is_(True))
            normalized_slug = str(property_slug or "").strip().lower()
            if normalized_slug:
                stmt = stmt.where(Property.slug == normalized_slug)
            properties = list((await db.execute(stmt.order_by(Property.slug.asc()))).scalars().all())

            updated: list[dict[str, Any]] = []
            skipped: list[dict[str, str]] = []
            failed: list[dict[str, str]] = []

            for prop in properties:
                prop_slug = str(prop.slug)
                try:
                    existing_links = _authoritative_ota_links(getattr(prop, "ota_metadata", None))
                    if existing_links and not overwrite:
                        skipped.append({"slug": prop_slug, "reason": "ota_metadata_already_present"})
                        continue

                    discovered_links = await self._discover_authoritative_ota_links(prop)
                    if not discovered_links:
                        skipped.append({"slug": prop_slug, "reason": "no_authoritative_ota_links_found"})
                        continue

                    prop.ota_metadata = {
                        **(dict(getattr(prop, "ota_metadata", {}) or {}) if overwrite else {}),
                        **{f"{provider.value}_url" if provider != OTAProvider.BOOKING else "booking_com_url": url for provider, url in discovered_links.items()},
                    }
                    await db.commit()
                    updated.append(
                        {
                            "slug": prop_slug,
                            "providers": sorted(provider.value for provider in discovered_links),
                        }
                    )
                except Exception as exc:  # pragma: no cover - runtime guard
                    await db.rollback()
                    failed.append({"slug": prop_slug, "error": str(exc)[:300]})
                    logger.exception("competitive_sentinel_backfill_failed", slug=prop_slug)

            return {
                "requested_property_slug": normalized_slug or None,
                "updated_count": len(updated),
                "skipped_count": len(skipped),
                "failed_count": len(failed),
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    def _build_query(
        self,
        *,
        prop: Property,
        check_in: date,
        check_out: date,
    ) -> tuple[str, dict[OTAProvider, str]]:
        ota_links = _authoritative_ota_links(getattr(prop, "ota_metadata", None))
        if not ota_links:
            return (
                f"Find the total price breakdown for '{prop.name}' in Blue Ridge, Georgia "
                f"on Airbnb and VRBO for stay {check_in.isoformat()} to {check_out.isoformat()}. "
                "Include nightly rate, platform service fee, cleaning fee, total before tax, "
                "and total after tax. Return only listings that clearly match the property.",
                {},
            )

        links_context = "\n".join(
            f"{provider.value.upper()}: {url}" for provider, url in sorted(ota_links.items(), key=lambda item: item[0].value)
        )
        return (
            "Use the following authoritative OTA listing URLs as the primary grounding hints. "
            f"Extract the current price breakdown for {check_in.isoformat()} to {check_out.isoformat()}.\n"
            f"Property name must match '{prop.name}'.\n"
            "Return only listings that clearly correspond to these URLs.\n"
            f"{links_context}",
            ota_links,
        )

    async def _build_local_parity_quote(
        self,
        db: AsyncSession,
        *,
        prop: Property,
        check_in: date,
        check_out: date,
    ) -> LocalParityQuote:
        rent_quote = await build_local_rent_quote(prop.id, check_in, check_out, db)
        fee_total = _rate_card_fee_total(prop.rate_card)
        total_before_tax = (rent_quote.rent + fee_total).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        tax_total = _rate_card_tax_total(prop.rate_card, total_before_tax)
        total_after_tax = (
            (total_before_tax + tax_total).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            if tax_total is not None
            else None
        )
        return LocalParityQuote(
            total_before_tax=total_before_tax,
            total_after_tax=total_after_tax,
        )

    async def run_parity_sweep(
        self,
        *,
        lookahead_days: int = 30,
        property_slug: str | None = None,
    ) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await self._run_parity_sweep(
                db,
                lookahead_days=lookahead_days,
                property_slug=property_slug,
            )

    async def _run_parity_sweep(
        self,
        db: AsyncSession,
        *,
        lookahead_days: int = 30,
        property_slug: str | None = None,
    ) -> dict[str, Any]:
        window = self._build_window(lookahead_days)
        stmt = select(Property).where(Property.is_active.is_(True))
        normalized_slug = str(property_slug or "").strip().lower()
        if normalized_slug:
            stmt = stmt.where(Property.slug == normalized_slug)
        properties = list((await db.execute(stmt.order_by(Property.slug.asc()))).scalars().all())
        browser_quotes_by_slug = await self._probe_booking_quotes(
            properties,
            check_in=window.check_in,
            check_out=window.check_out,
        )
        property_refs = [
            {
                "id": prop.id,
                "slug": str(prop.slug),
                "has_streamline_id": bool(str(getattr(prop, "streamline_property_id", "") or "").strip()),
            }
            for prop in properties
        ]

        audited: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []

        for prop_ref in property_refs:
            prop_slug = prop_ref["slug"]
            if not prop_ref["has_streamline_id"]:
                skipped.append({"slug": prop_slug, "reason": "missing_streamline_property_id"})
                continue
            try:
                prop = await db.get(Property, prop_ref["id"])
                if prop is None:
                    failed.append({"slug": prop_slug, "error": "property_not_found"})
                    continue
                summary = await self.audit_property(
                    db,
                    prop=prop,
                    check_in=window.check_in,
                    check_out=window.check_out,
                    prefetched_quotes=list(browser_quotes_by_slug.get(prop_slug) or []),
                )
                audited.append(summary)
            except Exception as exc:  # pragma: no cover - runtime guard
                await db.rollback()
                failed.append({"slug": prop_slug, "error": str(exc)[:300]})
                logger.exception("competitive_sentinel_property_failed", slug=prop_slug)

        return {
            "market": self.market,
            "lookahead_days": lookahead_days,
            "check_in": window.check_in.isoformat(),
            "check_out": window.check_out.isoformat(),
            "requested_property_slug": normalized_slug or None,
            "audited_count": len(audited),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "audited": audited,
            "skipped": skipped,
            "failed": failed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def audit_property(
        self,
        db: AsyncSession,
        *,
        prop: Property,
        check_in: date,
        check_out: date,
        prefetched_quotes: list[CompetitiveSentinelQuote] | None = None,
    ) -> dict[str, Any]:
        query, ota_links = self._build_query(
            prop=prop,
            check_in=check_in,
            check_out=check_out,
        )
        ota_quotes = list(prefetched_quotes or [])
        grounding = {
            "grounding_urls": [],
            "grounding_metadata": {"source": "booking_browser_probe"} if ota_quotes else {},
            "raw_payload": {},
        }
        if not ota_quotes:
            ota_quotes, grounding = await self._fetch_grounded_quotes(query)
        local_quote = None
        if isinstance(getattr(prop, "rate_card", None), dict):
            local_quote = await self._build_local_parity_quote(
                db,
                prop=prop,
                check_in=check_in,
                check_out=check_out,
            )
        inserted_platforms: list[str] = []
        savings_signals: list[dict[str, str]] = []

        for ota_quote in ota_quotes:
            platform = self._normalize_platform(ota_quote.platform)
            if platform is None:
                logger.warning(
                    "competitive_sentinel_skip_unknown_platform",
                    slug=prop.slug,
                    platform=ota_quote.platform,
                )
                continue

            await self._upsert_competitor_listing(
                db,
                prop=prop,
                platform=platform,
                ota_links=ota_links,
                ota_quote=ota_quote,
                check_in=check_in,
                check_out=check_out,
            )
            inserted_platforms.append(platform.value)

            if local_quote is not None:
                savings = self._compute_savings(
                    sovereign_total_after_tax=local_quote.total_after_tax,
                    sovereign_total_before_tax=local_quote.total_before_tax,
                    ota_quote=ota_quote,
                )
                if savings > _SAVINGS_THRESHOLD:
                    await self._inject_savings_insight(
                        db,
                        prop=prop,
                        platform=platform,
                        ota_quote=ota_quote,
                        savings=savings,
                        check_in=check_in,
                        check_out=check_out,
                        query=query,
                        grounding=grounding,
                    )
                    savings_signals.append(
                        {
                            "platform": platform.value,
                            "savings": str(savings),
                        }
                    )

        await db.commit()
        logger.info(
            "competitive_sentinel_property_audited",
            slug=prop.slug,
            platforms=inserted_platforms,
            savings_signal_count=len(savings_signals),
        )
        return {
            "property_id": str(prop.id),
            "slug": prop.slug,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "authoritative_links_used": sorted(provider.value for provider in ota_links),
            "prefetched_quote_platforms": sorted({quote.platform for quote in ota_quotes}) if prefetched_quotes else [],
            "local_quote_available": local_quote is not None,
            "platforms": inserted_platforms,
            "savings_signals": savings_signals,
        }

    def _compute_savings(
        self,
        *,
        sovereign_total_after_tax: Decimal | None,
        sovereign_total_before_tax: Decimal,
        ota_quote: CompetitiveSentinelQuote,
    ) -> Decimal:
        ota_after_tax = _to_money(ota_quote.total_after_tax) if ota_quote.total_after_tax is not None else None
        ota_before_tax = _to_money(ota_quote.total_before_tax)
        use_after_tax = ota_after_tax is not None and sovereign_total_after_tax is not None
        comparable_ota_total = ota_after_tax if use_after_tax else ota_before_tax
        comparable_sovereign_total = (
            sovereign_total_after_tax if use_after_tax and sovereign_total_after_tax is not None else sovereign_total_before_tax
        )
        return (comparable_ota_total - comparable_sovereign_total).quantize(
            _TWO_PLACES,
            rounding=ROUND_HALF_UP,
        )

    async def _discover_authoritative_ota_links(
        self,
        prop: Property,
    ) -> dict[OTAProvider, str]:
        query = (
            f"Find the authoritative Airbnb, VRBO, or Booking.com listing URLs for the property "
            f"'{prop.name}' in Blue Ridge, Georgia. Only return provider URLs that clearly match the exact property. "
            'Return a JSON array like [{"platform":"airbnb","url":"https://..."}]. Return [] if not confident.'
        )
        raw_rows, _grounding = await self._run_grounded_json_query(
            query=query,
            instruction=(
                "Return only valid JSON. Respond with a JSON array of objects using keys platform and url. "
                "Only include direct provider URLs on airbnb.com, vrbo.com, or booking.com. "
                "If the property match is uncertain, return []."
            ),
        )
        discovered: dict[OTAProvider, str] = {}
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            try:
                parsed = DiscoveredOTALink.model_validate(row)
            except ValidationError:
                continue
            platform = self._normalize_platform(parsed.platform)
            if platform is None:
                continue
            if not _provider_url_is_valid(platform, parsed.url):
                continue
            discovered[platform] = parsed.url.strip()
        return discovered

    async def _run_grounded_json_query(
        self,
        *,
        query: str,
        instruction: str,
    ) -> tuple[list[Any], dict[str, Any]]:
        if not settings.gemini_api_key.strip():
            raise RuntimeError("GEMINI_API_KEY is not configured for Competitive Sentinel")

        models_to_try: list[str] = []
        for model_name in (self.model, "gemini-2.5-flash"):
            normalized = str(model_name or "").strip()
            if normalized and normalized not in models_to_try:
                models_to_try.append(normalized)

        raw_payload: dict[str, Any] | None = None
        last_error: str | None = None
        async with httpx.AsyncClient(timeout=_SENTINEL_TIMEOUT) as client:
            for model_name in models_to_try:
                endpoint = f"{_GEMINI_API_BASE}/models/{model_name}:generateContent?key={settings.gemini_api_key}"
                payload = {
                    "system_instruction": {
                        "parts": [
                            {
                                "text": instruction
                            }
                        ]
                    },
                    "contents": [{"role": "user", "parts": [{"text": query}]}],
                    "tools": [{"google_search": {}}],
                    "generationConfig": {
                        "temperature": 0.1,
                    },
                }
                response = await client.post(endpoint, json=payload)
                if response.is_success:
                    raw_payload = response.json()
                    break
                body = response.text[:500]
                last_error = f"{response.status_code}: {body}"
                logger.warning(
                    "competitive_sentinel_grounding_model_failed",
                    model=model_name,
                    status_code=response.status_code,
                    body=body,
                )

        if raw_payload is None:
            raise RuntimeError(f"Competitive Sentinel grounding failed: {last_error or 'unknown error'}")

        response_text = _extract_response_text(raw_payload)
        try:
            parsed = _extract_json_payload(response_text)
        except JSONDecodeError:
            logger.warning(
                "competitive_sentinel_non_json_response",
                model=self.model,
                response_text=response_text[:500],
            )
            return [], {
                "grounding_urls": _extract_grounding_urls(raw_payload),
                "grounding_metadata": _extract_grounding_metadata(raw_payload),
                "raw_payload": raw_payload,
                "raw_response_text": response_text,
            }
        if isinstance(parsed, dict):
            raw_rows = parsed.get("listings") or parsed.get("results") or parsed.get("quotes") or []
        elif isinstance(parsed, list):
            raw_rows = parsed
        else:
            raise RuntimeError("Gemini Sentinel response was not a JSON array or wrapper object")

        return list(raw_rows) if isinstance(raw_rows, list) else [], {
            "grounding_urls": _extract_grounding_urls(raw_payload),
            "grounding_metadata": _extract_grounding_metadata(raw_payload),
            "raw_payload": raw_payload,
        }

    async def _fetch_grounded_quotes(
        self,
        query: str,
    ) -> tuple[list[CompetitiveSentinelQuote], dict[str, Any]]:
        try:
            raw_rows, grounding = await self._run_grounded_json_query(
                query=query,
                instruction=(
                    "Return only valid JSON. Respond with a JSON array of objects using keys "
                    "platform, nightly, platform_fee, cleaning_fee, total_before_tax, "
                    "total_after_tax, external_url, external_id. "
                    "If you cannot confidently find a matching listing, return []."
                ),
            )
        except Exception as exc:
            logger.warning(
                "competitive_sentinel_grounded_quote_fetch_failed",
                error=str(exc)[:300],
            )
            return [], {
                "grounding_urls": [],
                "grounding_metadata": {},
                "raw_payload": {},
            }

        quotes: list[CompetitiveSentinelQuote] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            try:
                quotes.append(CompetitiveSentinelQuote.model_validate(row))
            except ValidationError as exc:
                logger.warning(
                    "competitive_sentinel_invalid_quote",
                    error=str(exc)[:300],
                    row=row,
                )
        return quotes, grounding

    async def _upsert_competitor_listing(
        self,
        db: AsyncSession,
        *,
        prop: Property,
        platform: OTAProvider,
        ota_links: dict[OTAProvider, str],
        ota_quote: CompetitiveSentinelQuote,
        check_in: date,
        check_out: date,
    ) -> None:
        dedupe_hash = self._generate_dedupe_hash(
            str(prop.id),
            platform.value,
            check_in.isoformat(),
            check_out.isoformat(),
        )
        observed_total_after_tax = (
            _to_money(ota_quote.total_after_tax)
            if ota_quote.total_after_tax is not None
            else _to_money(ota_quote.total_before_tax)
        )
        now = datetime.now(timezone.utc)
        stmt = insert(CompetitorListing).values(
            property_id=prop.id,
            platform=platform,
            external_url=ota_links.get(platform) or ota_quote.external_url,
            external_id=ota_quote.external_id,
            dedupe_hash=dedupe_hash,
            observed_nightly_rate=_to_money(ota_quote.nightly),
            observed_total_before_tax=_to_money(ota_quote.total_before_tax),
            platform_fee=_to_money(ota_quote.platform_fee),
            cleaning_fee=_to_money(ota_quote.cleaning_fee),
            total_after_tax=observed_total_after_tax,
            snapshot_payload=ota_quote.model_dump(mode="json"),
            last_observed=now,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=[CompetitorListing.dedupe_hash],
            set_={
                "external_url": ota_links.get(platform) or ota_quote.external_url,
                "external_id": ota_quote.external_id,
                "observed_nightly_rate": _to_money(ota_quote.nightly),
                "observed_total_before_tax": _to_money(ota_quote.total_before_tax),
                "platform_fee": _to_money(ota_quote.platform_fee),
                "cleaning_fee": _to_money(ota_quote.cleaning_fee),
                "total_after_tax": observed_total_after_tax,
                "snapshot_payload": ota_quote.model_dump(mode="json"),
                "last_observed": now,
                "updated_at": now,
            },
        )
        await db.execute(stmt)

    async def _inject_savings_insight(
        self,
        db: AsyncSession,
        *,
        prop: Property,
        platform: OTAProvider,
        ota_quote: CompetitiveSentinelQuote,
        savings: Decimal,
        check_in: date,
        check_out: date,
        query: str,
        grounding: dict[str, Any],
    ) -> None:
        title = f"Sovereign Direct: save ${savings} vs {platform.value}"
        summary = (
            f"Direct booking for {prop.name} beats {platform.value} by ${savings} "
            f"for {check_in.isoformat()} to {check_out.isoformat()}."
        )
        dedupe_hash = hashlib.sha256(
            f"{prop.id}:savings_ribbon:{platform.value}:{check_in.isoformat()}:{check_out.isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()
        stmt = insert(IntelligenceLedgerEntry).values(
            category="market_shift",
            title=title,
            summary=summary,
            market=self.market,
            locality=self.market,
            dedupe_hash=dedupe_hash,
            confidence_score=1.0,
            query_topic="market_shift",
            scout_query=query,
            target_property_ids=[str(prop.id)],
            target_tags=["competitive_sentinel", "savings_ribbon", "direct_book_alpha"],
            source_urls=list(grounding.get("grounding_urls") or []),
            grounding_payload=grounding,
            finding_payload={
                "property_slug": prop.slug,
                "platform": platform.value,
                "savings": str(savings),
                "ota_total_before_tax": str(_to_money(ota_quote.total_before_tax)),
                "ota_total_after_tax": (
                    str(_to_money(ota_quote.total_after_tax))
                    if ota_quote.total_after_tax is not None
                    else None
                ),
            },
            discovered_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(
            index_elements=[IntelligenceLedgerEntry.dedupe_hash],
        )
        await db.execute(stmt)


competitive_sentinel = CompetitiveSentinelService()
