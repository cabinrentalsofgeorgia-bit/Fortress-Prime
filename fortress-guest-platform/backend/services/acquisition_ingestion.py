"""
CROG acquisition ingestion worker and Firecrawl extraction helpers.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.acquisition import (
    AcquisitionIntelEvent,
    AcquisitionOwner,
    AcquisitionOwnerContact,
    AcquisitionParcel,
    AcquisitionPipeline,
    AcquisitionProperty,
    FunnelStage,
    MarketState,
    SignalSource,
)
from backend.services.acquisition_matching import create_str_signal, resolve_property_by_coordinates

logger = structlog.get_logger(service="acquisition_ingestion")


class AcquisitionOwnerContactSeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_type: Literal["CELL", "LANDLINE", "EMAIL"]
    contact_value: str = Field(..., min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=100)
    confidence_score: Decimal | None = Field(default=None, ge=0, le=1)
    is_dnc: bool = False

    @field_validator("contact_value", mode="before")
    @classmethod
    def _strip_contact_value(cls, value: Any) -> str:
        return str(value or "").strip()


class AcquisitionParcelSeedRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    county_name: str = Field(default_factory=lambda: str(settings.acquisition_default_county or "Fannin").strip() or "Fannin")
    parcel_id: str = Field(..., min_length=1, max_length=100)
    assessed_value: Decimal = Field(..., ge=0)
    zoning_code: str | None = Field(default=None, max_length=50)
    is_waterfront: bool = False
    is_ridgeline: bool = False
    geom_wkt: str | None = None
    owner_legal_name: str | None = Field(default=None, max_length=255)
    tax_mailing_address: str | None = None
    primary_residence_state: str | None = Field(default=None, min_length=2, max_length=2)
    psychological_profile: dict[str, Any] | None = None
    owner_contacts: list[AcquisitionOwnerContactSeed] = Field(default_factory=list)
    management_company: str | None = Field(default=None, max_length=255)
    status: MarketState | None = None
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: Decimal | None = Field(default=None, ge=0)
    projected_adr: Decimal | None = Field(default=None, ge=0)
    projected_annual_revenue: Decimal | None = Field(default=None, ge=0)
    llm_viability_score: Decimal | None = Field(default=None, ge=0, le=1)
    next_action_date: date | None = None
    rejection_reason: str | None = None
    raw_source_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("county_name", "parcel_id", mode="before")
    @classmethod
    def _strip_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("owner_legal_name", "tax_mailing_address", "management_company", "zoning_code", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("primary_residence_state", mode="before")
    @classmethod
    def _normalize_state(cls, value: Any) -> str | None:
        text = str(value or "").strip().upper()
        return text or None


class AcquisitionStrPermitSeedRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    county_name: str = Field(default_factory=lambda: str(settings.acquisition_default_county or "Fannin").strip() or "Fannin")
    parcel_id: str = Field(..., min_length=1, max_length=100)
    owner_legal_name: str | None = Field(default=None, max_length=255)
    tax_mailing_address: str | None = None
    primary_residence_state: str | None = Field(default=None, min_length=2, max_length=2)
    psychological_profile: dict[str, Any] | None = None
    owner_contacts: list[AcquisitionOwnerContactSeed] = Field(default_factory=list)
    fannin_str_cert_id: str | None = Field(default=None, max_length=100)
    blue_ridge_str_permit: str | None = Field(default=None, max_length=100)
    zillow_zpid: str | None = Field(default=None, max_length=100)
    google_place_id: str | None = Field(default=None, max_length=255)
    airbnb_listing_id: str | None = Field(default=None, max_length=100)
    vrbo_listing_id: str | None = Field(default=None, max_length=100)
    management_company: str | None = Field(default=None, max_length=255)
    status: MarketState | None = None
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: Decimal | None = Field(default=None, ge=0)
    projected_adr: Decimal | None = Field(default=None, ge=0)
    projected_annual_revenue: Decimal | None = Field(default=None, ge=0)
    llm_viability_score: Decimal | None = Field(default=None, ge=0, le=1)
    stage: FunnelStage | None = None
    next_action_date: date | None = None
    rejection_reason: str | None = None
    raw_source_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "county_name",
        "parcel_id",
        "owner_legal_name",
        "tax_mailing_address",
        "fannin_str_cert_id",
        "blue_ridge_str_permit",
        "zillow_zpid",
        "google_place_id",
        "airbnb_listing_id",
        "vrbo_listing_id",
        "management_company",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("primary_residence_state", mode="before")
    @classmethod
    def _normalize_state(cls, value: Any) -> str | None:
        text = str(value or "").strip().upper()
        return text or None


class AcquisitionOTASignalSeedRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    listing_source: str = Field(default="ota_firecrawl_heuristic", max_length=100)
    title: str | None = Field(default=None, max_length=500)
    listing_url: str | None = Field(default=None, max_length=1000)
    external_listing_id: str | None = Field(default=None, max_length=255)
    airbnb_listing_id: str | None = Field(default=None, max_length=100)
    vrbo_listing_id: str | None = Field(default=None, max_length=100)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    projected_adr: Decimal | None = Field(default=None, ge=0)
    projected_annual_revenue: Decimal | None = Field(default=None, ge=0)
    raw_source_data: dict[str, Any] = Field(default_factory=dict)


class AcquisitionIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    county_name: str = Field(default_factory=lambda: str(settings.acquisition_default_county or "Fannin").strip() or "Fannin")
    qpublic_url: str | None = Field(default_factory=lambda: str(settings.acquisition_qpublic_url or "").strip() or None)
    str_permits_url: str | None = Field(default_factory=lambda: str(settings.acquisition_str_permits_url or "").strip() or None)
    dry_run: bool = False
    parcel_limit: int | None = Field(default=None, ge=1, le=5000)
    permit_limit: int | None = Field(default=None, ge=1, le=5000)
    ota_limit: int | None = Field(default=None, ge=1, le=5000)
    parcel_seed_records: list[AcquisitionParcelSeedRecord] = Field(default_factory=list)
    str_seed_records: list[AcquisitionStrPermitSeedRecord] = Field(default_factory=list)
    ota_search_urls: list[str] = Field(
        default_factory=lambda: [
            item.strip()
            for item in str(settings.acquisition_ota_search_urls or "").split(",")
            if item.strip()
        ]
    )
    ota_seed_records: list["AcquisitionOTASignalSeedRecord"] = Field(default_factory=list)

    @field_validator("county_name", mode="before")
    @classmethod
    def _normalize_county(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text or "Fannin"

    @field_validator("qpublic_url", "str_permits_url", mode="before")
    @classmethod
    def _strip_url(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _ensure_inputs(self) -> "AcquisitionIngestionRequest":
        if (
            not self.parcel_seed_records
            and not self.str_seed_records
            and not self.ota_seed_records
            and not self.qpublic_url
            and not self.str_permits_url
            and not self.ota_search_urls
        ):
            raise ValueError(
                "Provide parcel/permit/OTA seed records or configure qPublic/STR/OTA source URLs."
            )
        return self


def _firecrawl_headers() -> dict[str, str]:
    api_key = str(settings.firecrawl_api_key or "").strip()
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _firecrawl_base_url() -> str:
    return str(settings.firecrawl_base_url or "https://api.firecrawl.dev").strip().rstrip("/")


def _firecrawl_timeout() -> httpx.Timeout:
    timeout_seconds = max(10.0, float(settings.firecrawl_timeout_seconds or 120.0))
    return httpx.Timeout(connect=min(15.0, timeout_seconds), read=timeout_seconds, write=30.0, pool=15.0)


def _market_state_from_company(company_name: str | None) -> MarketState:
    normalized = (company_name or "").strip().lower()
    if not normalized:
        return MarketState.UNMANAGED
    if "cabin rentals of georgia" in normalized or normalized == "crog":
        return MarketState.CROG_MANAGED
    return MarketState.COMPETITOR_MANAGED


def _merge_profile(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any] | None:
    if not existing and not incoming:
        return None
    merged: dict[str, Any] = {}
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(incoming, dict):
        merged.update(incoming)
    return merged


async def _firecrawl_extract(url: str, *, prompt: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    payload = {
        "urls": [url],
        "prompt": prompt,
        "schema": schema,
    }
    endpoint = f"{_firecrawl_base_url()}/v1/extract"
    async with httpx.AsyncClient(timeout=_firecrawl_timeout()) as client:
        response = await client.post(endpoint, json=payload, headers=_firecrawl_headers())
        response.raise_for_status()
        data = response.json()
    records = _normalize_firecrawl_records(data)
    logger.info("firecrawl_extract_completed", url=url, record_count=len(records))
    return records


async def _firecrawl_scrape(
    url: str,
    *,
    formats: list[Any],
    actions: list[dict[str, Any]] | None = None,
    only_main_content: bool = False,
    wait_for_ms: int = 0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": url,
        "formats": formats,
        "onlyMainContent": only_main_content,
        "timeout": int(max(30000, float(settings.firecrawl_timeout_seconds or 120.0) * 1000)),
    }
    if wait_for_ms > 0:
        payload["waitFor"] = wait_for_ms
    if actions:
        payload["actions"] = actions
    endpoint = f"{_firecrawl_base_url()}/v1/scrape"
    async with httpx.AsyncClient(timeout=_firecrawl_timeout()) as client:
        response = await client.post(endpoint, json=payload, headers=_firecrawl_headers())
        response.raise_for_status()
        data = response.json()
    return data.get("data", {}) if isinstance(data, dict) else {}


def _normalize_firecrawl_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict):
            for key in ("records", "items", "results", "entries"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    return [row for row in candidate if isinstance(row, dict)]
            if all(isinstance(value, list) for value in data.values()):
                combined: list[dict[str, Any]] = []
                for value in data.values():
                    combined.extend(row for row in value if isinstance(row, dict))
                return combined
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _is_qpublic_search_url(url: str | None) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    query = parse_qs(parsed.query or "")
    return "qpublic.schneidercorp.com" in host and (
        query.get("PageType", [""])[0].lower() == "search"
        or query.get("PageTypeID", [""])[0] == "2"
    )


def _normalize_qpublic_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query or "")
    return urlunparse(
        parsed._replace(
            query=urlencode({key: values[0] for key, values in query.items()}, doseq=False),
        )
    )


def _extract_qpublic_neighborhood_options(raw_html: str) -> list[str]:
    match = re.search(
        r'<select[^>]*id="ctlBodyPane_ctl07_ctl01_ddlNeighborhoods"[^>]*>(.*?)</select>',
        raw_html,
        re.I | re.S,
    )
    if not match:
        return []
    values = re.findall(r'<option[^>]*value="([^"]*)"', match.group(1), re.I)
    cleaned = [value.strip() for value in values if value.strip()]
    return cleaned


def _clean_money(value: str) -> Decimal | None:
    text = value.replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _clean_decimal(value: str) -> Decimal | None:
    text = value.replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _parse_qpublic_results_markdown(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in markdown.splitlines():
        if "View Parcel Report for" not in line or ("PageType=4" not in line and "PageTypeID=4" not in line):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 10:
            continue
        report_urls = re.findall(r"\((https://qpublic\.schneidercorp\.com/Application\.aspx\?[^)\s]+PageType(?:ID)?=4[^)\s]*)", line)
        map_match = re.search(r"\[Map\]\((https://qpublic\.schneidercorp\.com/Application\.aspx\?[^)\s]+PageTypeID=1[^)\s]*)", line)
        parcel_match = re.search(r"\]\(([^\)]*PageTypeID=4[^\)]*)\s+\"View Parcel Report for,\s*([^\"]+)\"", line)
        parcel_id = parcel_match.group(2).strip() if parcel_match else cells[1].strip() if len(cells) > 1 else ""
        alt_id = cells[2] if len(cells) > 2 else ""
        owner = cells[3] if len(cells) > 3 else ""
        property_address = cells[4] if len(cells) > 4 else ""
        acres = _clean_decimal(cells[6]) if len(cells) > 6 else None
        prop_class = cells[7] if len(cells) > 7 else ""
        if not parcel_id or not report_urls:
            continue
        rows.append(
            {
                "parcel_id": parcel_id,
                "alternate_id": alt_id,
                "owner_summary": owner,
                "property_address": property_address,
                "acres": acres,
                "property_class": prop_class,
                "report_url": report_urls[-1],
                "map_url": map_match.group(1) if map_match else None,
            }
        )
    return rows


def _parse_qpublic_report_markdown(
    markdown: str,
    *,
    county_name: str,
    neighborhood: str,
    result_row: dict[str, Any],
    report_url: str,
) -> AcquisitionParcelSeedRecord | None:
    parcel_match = re.search(r"\|\s*\*\*Parcel Number\*\*\s*\|\s*([^\|]+)\|", markdown)
    current_value_match = re.search(r"\|\s*=\s*\|\s*Current Value\s*\|\s*\$([0-9,]+(?:\.[0-9]+)?)\s*\|", markdown)
    owner_match = re.search(r"\[Owner\][\s\S]*?\|\s*(.+?)\s*\|\s*\|", markdown)
    legal_description_match = re.search(r"\|\s*\*\*Legal Description\*\*\s*\|\s*([^\|]+)\|", markdown)
    class_match = re.search(r"\|\s*\*\*Class\*\*\s*\|\s*([^\|]+)\|", markdown)
    acres_match = re.search(r"\|\s*\*\*Acres\*\*\s*\|\s*([^\|]+)\|", markdown)
    address_match = re.search(r"\|\s*\*\*Location Address\*\*\s*\|\s*([^\|]+)\|", markdown)
    neighborhood_match = re.search(r"\|\s*\*\*Neighborhood\*\*\s*\|\s*([^\|]+)\|", markdown)
    if parcel_match is None or current_value_match is None:
        return None

    owner_block = owner_match.group(1) if owner_match else result_row.get("owner_summary") or ""
    owner_lines = [segment.strip() for segment in re.split(r"<br>|\n", owner_block) if segment.strip()]
    owner_name = owner_lines[0] if owner_lines else None
    mailing_address = ", ".join(owner_lines[1:]) if len(owner_lines) > 1 else None
    location_address = (address_match.group(1).strip() if address_match else result_row.get("property_address") or None)
    psychological_profile = {
        "source": "qpublic_firecrawl",
        "angle": "Property Pride" if location_address else "Owner Legacy",
        "neighborhood": neighborhood_match.group(1).strip() if neighborhood_match else neighborhood,
    }

    return AcquisitionParcelSeedRecord(
        county_name=county_name,
        parcel_id=parcel_match.group(1).strip(),
        assessed_value=_clean_money(current_value_match.group(1)) or Decimal("0"),
        zoning_code=(class_match.group(1).strip() if class_match else None),
        owner_legal_name=owner_name,
        tax_mailing_address=mailing_address,
        psychological_profile=psychological_profile,
        raw_source_data={
            "source": "qpublic_firecrawl_browser_actions",
            "report_url": report_url,
            "search_result": _json_safe(result_row),
            "legal_description": legal_description_match.group(1).strip() if legal_description_match else None,
            "property_address": location_address,
            "acres": str(_clean_decimal(acres_match.group(1)) or result_row.get("acres") or "") if acres_match else (str(result_row.get("acres")) if result_row.get("acres") is not None else None),
        },
    )


async def _qpublic_report_records(request: AcquisitionIngestionRequest) -> list[AcquisitionParcelSeedRecord]:
    search_url = _normalize_qpublic_url(str(request.qpublic_url))
    search_page = await _firecrawl_scrape(
        search_url,
        formats=["rawHtml"],
        only_main_content=False,
        wait_for_ms=3000,
    )
    raw_html = str(search_page.get("rawHtml") or "")
    neighborhoods = _extract_qpublic_neighborhood_options(raw_html)
    if not neighborhoods:
        logger.warning("qpublic_neighborhoods_not_found", url=search_url)
        return []

    target_count = request.parcel_limit or 10
    seeds: list[AcquisitionParcelSeedRecord] = []
    for neighborhood in neighborhoods[: max(3, target_count)]:
        result_page = await _firecrawl_scrape(
            search_url,
            formats=["markdown"],
            only_main_content=False,
            wait_for_ms=3000,
            actions=[
                {"type": "wait", "milliseconds": 7000},
                {
                    "type": "executeJavascript",
                    "script": (
                        "document.getElementById('ctlBodyPane_ctl07_ctl01_ddlNeighborhoods').value="
                        + json.dumps(neighborhood)
                        + ";"
                    ),
                },
                {"type": "click", "selector": "#ctlBodyPane_ctl07_ctl01_btnSearch"},
                {"type": "wait", "milliseconds": 7000},
            ],
        )
        markdown = str(result_page.get("markdown") or "")
        result_rows = _parse_qpublic_results_markdown(markdown)
        if not result_rows:
            continue
        for row in result_rows:
            report_url = row["report_url"]
            report_page = await _firecrawl_scrape(
                report_url,
                formats=["markdown"],
                only_main_content=False,
                wait_for_ms=3000,
            )
            seed = _parse_qpublic_report_markdown(
                str(report_page.get("markdown") or ""),
                county_name=request.county_name,
                neighborhood=neighborhood,
                result_row=row,
                report_url=report_url,
            )
            if seed is None:
                continue
            seeds.append(seed)
            if len(seeds) >= target_count:
                logger.info("qpublic_browser_fallback_completed", record_count=len(seeds), neighborhood=neighborhood)
                return seeds

    logger.info("qpublic_browser_fallback_completed", record_count=len(seeds))
    return seeds


def _parcel_extract_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "county_name": {"type": "string"},
                        "parcel_id": {"type": "string"},
                        "assessed_value": {"type": "number"},
                        "zoning_code": {"type": "string"},
                        "is_waterfront": {"type": "boolean"},
                        "is_ridgeline": {"type": "boolean"},
                        "geom_wkt": {"type": "string"},
                        "owner_legal_name": {"type": "string"},
                        "tax_mailing_address": {"type": "string"},
                        "primary_residence_state": {"type": "string"},
                        "management_company": {"type": "string"},
                        "bedrooms": {"type": "integer"},
                        "bathrooms": {"type": "number"},
                        "projected_adr": {"type": "number"},
                        "projected_annual_revenue": {"type": "number"},
                        "llm_viability_score": {"type": "number"},
                        "raw_source_data": {"type": "object"},
                    },
                    "required": ["parcel_id", "assessed_value"],
                },
            }
        },
        "required": ["records"],
    }


def _permit_extract_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "county_name": {"type": "string"},
                        "parcel_id": {"type": "string"},
                        "owner_legal_name": {"type": "string"},
                        "tax_mailing_address": {"type": "string"},
                        "primary_residence_state": {"type": "string"},
                        "fannin_str_cert_id": {"type": "string"},
                        "blue_ridge_str_permit": {"type": "string"},
                        "zillow_zpid": {"type": "string"},
                        "google_place_id": {"type": "string"},
                        "airbnb_listing_id": {"type": "string"},
                        "vrbo_listing_id": {"type": "string"},
                        "management_company": {"type": "string"},
                        "bedrooms": {"type": "integer"},
                        "bathrooms": {"type": "number"},
                        "projected_adr": {"type": "number"},
                        "projected_annual_revenue": {"type": "number"},
                        "llm_viability_score": {"type": "number"},
                        "raw_source_data": {"type": "object"},
                    },
                    "required": ["parcel_id"],
                },
            }
        },
        "required": ["records"],
    }


def _ota_extract_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "listing_source": {"type": "string"},
                        "title": {"type": "string"},
                        "listing_url": {"type": "string"},
                        "external_listing_id": {"type": "string"},
                        "airbnb_listing_id": {"type": "string"},
                        "vrbo_listing_id": {"type": "string"},
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                        "projected_adr": {"type": "number"},
                        "projected_annual_revenue": {"type": "number"},
                        "raw_source_data": {"type": "object"},
                    },
                    "required": ["latitude", "longitude"],
                },
            }
        },
        "required": ["records"],
    }


async def _load_parcel_records(request: AcquisitionIngestionRequest) -> list[AcquisitionParcelSeedRecord]:
    records = list(request.parcel_seed_records)
    if request.qpublic_url:
        extracted = await _firecrawl_extract(
            request.qpublic_url,
            prompt=(
                "Extract parcel records for a property acquisition database. "
                "Return parcel boundaries as WKT POLYGON strings when present, "
                "owner mailing details, terrain/waterfront flags, and assessment values."
            ),
            schema=_parcel_extract_schema(),
        )
        records.extend(AcquisitionParcelSeedRecord.model_validate(row) for row in extracted)
        if not extracted and _is_qpublic_search_url(request.qpublic_url):
            records.extend(await _qpublic_report_records(request))
    if request.parcel_limit is not None:
        records = records[: request.parcel_limit]
    return records


async def _load_permit_records(request: AcquisitionIngestionRequest) -> list[AcquisitionStrPermitSeedRecord]:
    records = list(request.str_seed_records)
    if request.str_permits_url:
        extracted = await _firecrawl_extract(
            request.str_permits_url,
            prompt=(
                "Extract short-term rental registry records for CROG acquisition intelligence. "
                "Return permit identifiers, listing identifiers, owner details, competitor management, "
                "and underwriting hints tied to the parcel id."
            ),
            schema=_permit_extract_schema(),
        )
        records.extend(AcquisitionStrPermitSeedRecord.model_validate(row) for row in extracted)
    if request.permit_limit is not None:
        records = records[: request.permit_limit]
    return records


async def _load_ota_records(request: AcquisitionIngestionRequest) -> list[AcquisitionOTASignalSeedRecord]:
    records = list(request.ota_seed_records)
    for url in request.ota_search_urls:
        extracted = await _firecrawl_extract(
            url,
            prompt=(
                "Extract active short-term rental listings for acquisition intelligence. "
                "Return latitude, longitude, listing URL, OTA source, listing identifiers, "
                "and any nightly rate or annual revenue estimate present on the page."
            ),
            schema=_ota_extract_schema(),
        )
        records.extend(AcquisitionOTASignalSeedRecord.model_validate(row) for row in extracted)
    if request.ota_limit is not None:
        records = records[: request.ota_limit]
    return records


async def _get_owner(
    db: AsyncSession,
    *,
    legal_name: str,
    tax_mailing_address: str,
) -> AcquisitionOwner | None:
    stmt = (
        select(AcquisitionOwner)
        .where(AcquisitionOwner.legal_name == legal_name)
        .where(AcquisitionOwner.tax_mailing_address == tax_mailing_address)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_parcel(db: AsyncSession, *, parcel_id: str) -> AcquisitionParcel | None:
    stmt = select(AcquisitionParcel).where(AcquisitionParcel.parcel_id == parcel_id).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_property_by_identifiers(
    db: AsyncSession,
    *,
    parcel: AcquisitionParcel | None = None,
    identifiers: dict[str, str | None] | None = None,
) -> AcquisitionProperty | None:
    clauses = []
    if parcel is not None:
        clauses.append(AcquisitionProperty.parcel_id == parcel.id)
    identifiers = identifiers or {}
    field_map = {
        "fannin_str_cert_id": AcquisitionProperty.fannin_str_cert_id,
        "blue_ridge_str_permit": AcquisitionProperty.blue_ridge_str_permit,
        "zillow_zpid": AcquisitionProperty.zillow_zpid,
        "google_place_id": AcquisitionProperty.google_place_id,
        "airbnb_listing_id": AcquisitionProperty.airbnb_listing_id,
        "vrbo_listing_id": AcquisitionProperty.vrbo_listing_id,
    }
    for key, column in field_map.items():
        value = (identifiers.get(key) or "").strip()
        if value:
            clauses.append(column == value)
    if not clauses:
        return None
    stmt = select(AcquisitionProperty).where(or_(*clauses)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def _assign_if_present(instance: Any, field_name: str, value: Any) -> bool:
    if value is None:
        return False
    if getattr(instance, field_name) == value:
        return False
    setattr(instance, field_name, value)
    return True


async def _upsert_owner(
    db: AsyncSession,
    *,
    legal_name: str | None,
    tax_mailing_address: str | None,
    primary_residence_state: str | None,
    psychological_profile: dict[str, Any] | None,
    contacts: list[AcquisitionOwnerContactSeed],
    summary: dict[str, int],
) -> AcquisitionOwner | None:
    if not legal_name or not tax_mailing_address:
        return None
    owner = await _get_owner(db, legal_name=legal_name, tax_mailing_address=tax_mailing_address)
    created = owner is None
    if owner is None:
        owner = AcquisitionOwner(
            legal_name=legal_name,
            tax_mailing_address=tax_mailing_address,
            primary_residence_state=primary_residence_state,
            psychological_profile=psychological_profile,
        )
        db.add(owner)
        await db.flush()
        summary["owners_created"] += 1
    else:
        changed = False
        changed |= _assign_if_present(owner, "primary_residence_state", primary_residence_state)
        merged_profile = _merge_profile(owner.psychological_profile, psychological_profile)
        if merged_profile != owner.psychological_profile:
            owner.psychological_profile = merged_profile
            changed = True
        if changed:
            summary["owners_updated"] += 1

    for contact in contacts:
        await _upsert_owner_contact(db, owner=owner, contact=contact)
    if created and not contacts:
        await db.flush()
    return owner


async def _upsert_owner_contact(
    db: AsyncSession,
    *,
    owner: AcquisitionOwner,
    contact: AcquisitionOwnerContactSeed,
) -> None:
    stmt = (
        select(AcquisitionOwnerContact)
        .where(AcquisitionOwnerContact.owner_id == owner.id)
        .where(AcquisitionOwnerContact.contact_value == contact.contact_value)
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        db.add(
            AcquisitionOwnerContact(
                owner_id=owner.id,
                contact_type=contact.contact_type,
                contact_value=contact.contact_value,
                source=contact.source,
                confidence_score=contact.confidence_score,
                is_dnc=contact.is_dnc,
            )
        )
        await db.flush()
        return
    _assign_if_present(existing, "contact_type", contact.contact_type)
    _assign_if_present(existing, "source", contact.source)
    _assign_if_present(existing, "confidence_score", contact.confidence_score)
    existing.is_dnc = bool(contact.is_dnc)


async def _upsert_parcel(
    db: AsyncSession,
    *,
    record: AcquisitionParcelSeedRecord,
    summary: dict[str, int],
) -> AcquisitionParcel:
    parcel = await _get_parcel(db, parcel_id=record.parcel_id)
    if parcel is None:
        parcel = AcquisitionParcel(
            county_name=record.county_name,
            parcel_id=record.parcel_id,
            assessed_value=record.assessed_value,
            zoning_code=record.zoning_code,
            is_waterfront=record.is_waterfront,
            is_ridgeline=record.is_ridgeline,
        )
        if record.geom_wkt:
            parcel.geom = record.geom_wkt
        db.add(parcel)
        await db.flush()
        summary["parcels_created"] += 1
        return parcel

    changed = False
    changed |= _assign_if_present(parcel, "county_name", record.county_name)
    changed |= _assign_if_present(parcel, "assessed_value", record.assessed_value)
    changed |= _assign_if_present(parcel, "zoning_code", record.zoning_code)
    if parcel.is_waterfront != bool(record.is_waterfront):
        parcel.is_waterfront = bool(record.is_waterfront)
        changed = True
    if parcel.is_ridgeline != bool(record.is_ridgeline):
        parcel.is_ridgeline = bool(record.is_ridgeline)
        changed = True
    if record.geom_wkt:
        parcel.geom = record.geom_wkt
        changed = True
    if changed:
        summary["parcels_updated"] += 1
    return parcel


async def _ensure_property(
    db: AsyncSession,
    *,
    parcel: AcquisitionParcel,
    owner: AcquisitionOwner | None,
    identifiers: dict[str, str | None],
    management_company: str | None,
    status: MarketState | None,
    bedrooms: int | None,
    bathrooms: Decimal | None,
    projected_adr: Decimal | None,
    projected_annual_revenue: Decimal | None,
    summary: dict[str, int],
) -> AcquisitionProperty:
    prop = await _get_property_by_identifiers(db, parcel=parcel, identifiers=identifiers)
    if prop is None:
        prop = AcquisitionProperty(
            parcel_id=parcel.id,
            owner_id=owner.id if owner is not None else None,
            management_company=management_company,
            status=status or _market_state_from_company(management_company),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            projected_adr=projected_adr,
            projected_annual_revenue=projected_annual_revenue,
            **{key: value for key, value in identifiers.items() if value},
        )
        db.add(prop)
        await db.flush()
        summary["properties_created"] += 1
        return prop

    changed = False
    if owner is not None and prop.owner_id != owner.id:
        prop.owner_id = owner.id
        changed = True
    changed |= _assign_if_present(prop, "management_company", management_company)
    if status is not None and prop.status != status:
        prop.status = status
        changed = True
    elif status is None:
        derived_status = _market_state_from_company(management_company)
        if management_company and prop.status != derived_status:
            prop.status = derived_status
            changed = True
    changed |= _assign_if_present(prop, "bedrooms", bedrooms)
    changed |= _assign_if_present(prop, "bathrooms", bathrooms)
    changed |= _assign_if_present(prop, "projected_adr", projected_adr)
    changed |= _assign_if_present(prop, "projected_annual_revenue", projected_annual_revenue)
    for key, value in identifiers.items():
        if value:
            changed |= _assign_if_present(prop, key, value)
    if changed:
        summary["properties_updated"] += 1
    return prop


async def _ensure_pipeline(
    db: AsyncSession,
    *,
    prop: AcquisitionProperty,
    stage: FunnelStage | None,
    llm_viability_score: Decimal | None,
    next_action_date: date | None,
    rejection_reason: str | None,
    summary: dict[str, int],
) -> AcquisitionPipeline:
    stmt = select(AcquisitionPipeline).where(AcquisitionPipeline.property_id == prop.id).limit(1)
    pipeline = (await db.execute(stmt)).scalar_one_or_none()
    if pipeline is None:
        pipeline = AcquisitionPipeline(
            property_id=prop.id,
            stage=stage or FunnelStage.RADAR,
            llm_viability_score=llm_viability_score,
            next_action_date=next_action_date,
            rejection_reason=rejection_reason,
        )
        db.add(pipeline)
        await db.flush()
        summary["pipelines_created"] += 1
        return pipeline

    _assign_if_present(pipeline, "stage", stage)
    _assign_if_present(pipeline, "llm_viability_score", llm_viability_score)
    _assign_if_present(pipeline, "next_action_date", next_action_date)
    _assign_if_present(pipeline, "rejection_reason", rejection_reason)
    return pipeline


async def _append_intel_event(
    db: AsyncSession,
    *,
    prop: AcquisitionProperty,
    event_type: str,
    event_description: str,
    raw_source_data: dict[str, Any],
    summary: dict[str, int],
) -> None:
    db.add(
        AcquisitionIntelEvent(
            property_id=prop.id,
            event_type=event_type,
            event_description=event_description,
            raw_source_data=raw_source_data or {},
        )
    )
    await db.flush()
    summary["intel_events_created"] += 1


async def run_acquisition_ingestion_cycle(
    db: AsyncSession,
    request: AcquisitionIngestionRequest,
) -> dict[str, Any]:
    dry_run_savepoint = await db.begin_nested() if request.dry_run else None
    parcel_records = await _load_parcel_records(request)
    permit_records = await _load_permit_records(request)
    ota_records = await _load_ota_records(request)
    summary: dict[str, int] = {
        "parcel_source_count": len(parcel_records),
        "permit_source_count": len(permit_records),
        "ota_source_count": len(ota_records),
        "parcels_created": 0,
        "parcels_updated": 0,
        "owners_created": 0,
        "owners_updated": 0,
        "properties_created": 0,
        "properties_updated": 0,
        "pipelines_created": 0,
        "intel_events_created": 0,
        "ota_signals_created": 0,
        "warnings_count": 0,
    }
    warnings: list[str] = []

    try:
        for record in parcel_records:
            parcel = await _upsert_parcel(db, record=record, summary=summary)
            owner = await _upsert_owner(
                db,
                legal_name=record.owner_legal_name,
                tax_mailing_address=record.tax_mailing_address,
                primary_residence_state=record.primary_residence_state,
                psychological_profile=record.psychological_profile,
                contacts=record.owner_contacts,
                summary=summary,
            )
            prop = await _ensure_property(
                db,
                parcel=parcel,
                owner=owner,
                identifiers={},
                management_company=record.management_company,
                status=record.status,
                bedrooms=record.bedrooms,
                bathrooms=record.bathrooms,
                projected_adr=record.projected_adr,
                projected_annual_revenue=record.projected_annual_revenue,
                summary=summary,
            )
            await _ensure_pipeline(
                db,
                prop=prop,
                stage=FunnelStage.RADAR,
                llm_viability_score=record.llm_viability_score,
                next_action_date=record.next_action_date,
                rejection_reason=record.rejection_reason,
                summary=summary,
            )
            await _append_intel_event(
                db,
                prop=prop,
                event_type="QPUBLIC_SYNC",
                event_description=f"Parcel baseline synchronized for {record.parcel_id}.",
                raw_source_data=record.raw_source_data,
                summary=summary,
            )

        for record in permit_records:
            parcel = await _get_parcel(db, parcel_id=record.parcel_id)
            if parcel is None:
                warning = f"STR permit record skipped because parcel {record.parcel_id} has not been ingested yet."
                warnings.append(warning)
                logger.warning("acquisition_ingestion_missing_parcel", parcel_id=record.parcel_id)
                continue
            owner = await _upsert_owner(
                db,
                legal_name=record.owner_legal_name,
                tax_mailing_address=record.tax_mailing_address,
                primary_residence_state=record.primary_residence_state,
                psychological_profile=record.psychological_profile,
                contacts=record.owner_contacts,
                summary=summary,
            )
            prop = await _ensure_property(
                db,
                parcel=parcel,
                owner=owner,
                identifiers={
                    "fannin_str_cert_id": record.fannin_str_cert_id,
                    "blue_ridge_str_permit": record.blue_ridge_str_permit,
                    "zillow_zpid": record.zillow_zpid,
                    "google_place_id": record.google_place_id,
                    "airbnb_listing_id": record.airbnb_listing_id,
                    "vrbo_listing_id": record.vrbo_listing_id,
                },
                management_company=record.management_company,
                status=record.status,
                bedrooms=record.bedrooms,
                bathrooms=record.bathrooms,
                projected_adr=record.projected_adr,
                projected_annual_revenue=record.projected_annual_revenue,
                summary=summary,
            )
            await _ensure_pipeline(
                db,
                prop=prop,
                stage=record.stage or FunnelStage.TARGET_LOCKED,
                llm_viability_score=record.llm_viability_score,
                next_action_date=record.next_action_date,
                rejection_reason=record.rejection_reason,
                summary=summary,
            )
            await _append_intel_event(
                db,
                prop=prop,
                event_type="STR_REGISTRY_SYNC",
                event_description=f"STR registry intelligence synchronized for parcel {record.parcel_id}.",
                raw_source_data=record.raw_source_data,
                summary=summary,
            )

        for record in ota_records:
            prop, inside_match = await resolve_property_by_coordinates(
                db,
                latitude=record.latitude,
                longitude=record.longitude,
                radius_meters=int(settings.acquisition_ota_radius_meters or 75),
            )
            if prop is None:
                warning = (
                    "OTA listing could not be spatially matched: "
                    f"{record.listing_url or record.external_listing_id or record.title or '<unknown>'}"
                )
                warnings.append(warning)
                logger.warning(
                    "acquisition_ingestion_unmatched_ota_signal",
                    listing_source=record.listing_source,
                    listing_url=record.listing_url,
                )
                continue

            if record.airbnb_listing_id and not prop.airbnb_listing_id:
                prop.airbnb_listing_id = record.airbnb_listing_id
            if record.vrbo_listing_id and not prop.vrbo_listing_id:
                prop.vrbo_listing_id = record.vrbo_listing_id
            if record.projected_adr is not None:
                prop.projected_adr = record.projected_adr
            if record.projected_annual_revenue is not None:
                prop.projected_annual_revenue = record.projected_annual_revenue

            confidence = Decimal("0.80") if inside_match else Decimal("0.60")
            await create_str_signal(
                db,
                property_id=prop.id,
                signal_source=SignalSource.OTA_FIRECRAWL_HEURISTIC,
                confidence_score=confidence,
                raw_payload={
                    "listing_source": record.listing_source,
                    "title": record.title,
                    "listing_url": record.listing_url,
                    "external_listing_id": record.external_listing_id,
                    "airbnb_listing_id": record.airbnb_listing_id,
                    "vrbo_listing_id": record.vrbo_listing_id,
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "projected_adr": record.projected_adr,
                    "projected_annual_revenue": record.projected_annual_revenue,
                    "matched_by": "st_contains" if inside_match else "st_dwithin",
                    "raw_source_data": record.raw_source_data,
                },
            )
            summary["ota_signals_created"] += 1
            await _append_intel_event(
                db,
                prop=prop,
                event_type="OTA_SPATIAL_MATCH",
                event_description="OTA listing spatially matched to parcel geometry.",
                raw_source_data={
                    "listing_source": record.listing_source,
                    "listing_url": record.listing_url,
                    "matched_by": "st_contains" if inside_match else "st_dwithin",
                    "external_listing_id": record.external_listing_id,
                },
                summary=summary,
            )

        summary["warnings_count"] = len(warnings)
        if request.dry_run:
            if dry_run_savepoint is not None:
                await dry_run_savepoint.rollback()
        else:
            await db.commit()
        result = {
            **summary,
            "county_name": request.county_name,
            "dry_run": request.dry_run,
            "warnings": warnings,
        }
        logger.info("acquisition_ingestion_completed", **result)
        return result
    except Exception:
        if dry_run_savepoint is not None:
            await dry_run_savepoint.rollback()
        await db.rollback()
        logger.exception("acquisition_ingestion_failed")
        raise
