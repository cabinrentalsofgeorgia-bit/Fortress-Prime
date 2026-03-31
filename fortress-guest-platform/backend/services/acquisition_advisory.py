"""
Advisory and mutation helpers for CROG acquisition Paperclip tools.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import settings
from backend.models.acquisition import (
    AcquisitionIntelEvent,
    AcquisitionOwner,
    AcquisitionOwnerContact,
    AcquisitionParcel,
    AcquisitionPipeline,
    AcquisitionProperty,
    AcquisitionSTRSignal,
    FunnelStage,
    MarketState,
)
from backend.services.acquisition_matching import normalize_name
from backend.services.vendors import B2CContactProvider, StrictMockB2CProvider


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_PATTERN = re.compile(r"(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})")


class AcquisitionCandidateContactSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    contact_type: str | None = None
    contact_value: str
    source: str | None = None
    confidence_score: float | None = None
    is_dnc: bool


class AcquisitionCandidateIntelEventSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    event_type: str
    event_description: str
    raw_source_data: dict[str, Any]
    detected_at: str | None = None


class AcquisitionCandidateSTRSignalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    signal_source: str
    confidence_score: float
    raw_payload: dict[str, Any]
    detected_at: str | None = None


class AcquisitionCandidateParcelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    parcel_id: str | None = None
    county_name: str | None = None
    assessed_value: float | None = None
    zoning_code: str | None = None
    is_waterfront: bool
    is_ridgeline: bool


class AcquisitionCandidateOwnerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    legal_name: str | None = None
    tax_mailing_address: str | None = None
    primary_residence_state: str | None = None
    psychological_profile: dict[str, Any] | None = None
    contacts: list[AcquisitionCandidateContactSchema]


class AcquisitionCandidatePipelineSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    stage: str | None = None
    llm_viability_score: float | None = None
    next_action_date: str | None = None
    rejection_reason: str | None = None


class AcquisitionCandidateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: str
    status: str
    management_company: str | None = None
    bedrooms: int | None = None
    bathrooms: float | None = None
    projected_adr: float | None = None
    projected_annual_revenue: float | None = None
    parcel: AcquisitionCandidateParcelSchema
    owner: AcquisitionCandidateOwnerSchema
    pipeline: AcquisitionCandidatePipelineSchema
    recent_intel_events: list[AcquisitionCandidateIntelEventSchema]
    recent_str_signals: list[AcquisitionCandidateSTRSignalSchema]
    score_viability_input: dict[str, str]


def _serialize_contact(contact: AcquisitionOwnerContact) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "contact_type": contact.contact_type,
        "contact_value": contact.contact_value,
        "source": contact.source,
        "confidence_score": float(contact.confidence_score) if contact.confidence_score is not None else None,
        "is_dnc": bool(contact.is_dnc),
    }


def _serialize_event(event: AcquisitionIntelEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "event_description": event.event_description,
        "raw_source_data": event.raw_source_data or {},
        "detected_at": event.detected_at.isoformat() if event.detected_at else None,
    }


def _serialize_signal(signal: AcquisitionSTRSignal) -> dict[str, Any]:
    return {
        "id": str(signal.id),
        "signal_source": signal.signal_source.value if hasattr(signal.signal_source, "value") else str(signal.signal_source),
        "confidence_score": float(signal.confidence_score),
        "raw_payload": signal.raw_payload or {},
        "detected_at": signal.detected_at.isoformat() if signal.detected_at else None,
    }


def _safe_recent_str_signals(prop: AcquisitionProperty) -> list[AcquisitionSTRSignal]:
    signals = prop.__dict__.get("str_signals") or []
    return sorted(signals, key=lambda signal: signal.detected_at or _utcnow(), reverse=True)[:5]


def _serialize_property_context(prop: AcquisitionProperty) -> dict[str, Any]:
    parcel = prop.parcel
    owner = prop.owner
    pipeline = prop.pipeline
    recent_events = sorted(prop.intel_events or [], key=lambda event: event.detected_at or _utcnow(), reverse=True)[:5]
    recent_signals = _safe_recent_str_signals(prop)
    return {
        "property_id": str(prop.id),
        "status": prop.status.value if isinstance(prop.status, MarketState) else str(prop.status),
        "management_company": prop.management_company,
        "bedrooms": prop.bedrooms,
        "bathrooms": float(prop.bathrooms) if prop.bathrooms is not None else None,
        "projected_adr": float(prop.projected_adr) if prop.projected_adr is not None else None,
        "projected_annual_revenue": float(prop.projected_annual_revenue) if prop.projected_annual_revenue is not None else None,
        "parcel": {
            "id": str(parcel.id) if parcel else None,
            "parcel_id": parcel.parcel_id if parcel else None,
            "county_name": parcel.county_name if parcel else None,
            "assessed_value": float(parcel.assessed_value) if parcel and parcel.assessed_value is not None else None,
            "zoning_code": parcel.zoning_code if parcel else None,
            "is_waterfront": bool(parcel.is_waterfront) if parcel else False,
            "is_ridgeline": bool(parcel.is_ridgeline) if parcel else False,
        },
        "owner": {
            "id": str(owner.id) if owner else None,
            "legal_name": owner.legal_name if owner else None,
            "tax_mailing_address": owner.tax_mailing_address if owner else None,
            "primary_residence_state": owner.primary_residence_state if owner else None,
            "psychological_profile": owner.psychological_profile if owner else None,
            "contacts": [_serialize_contact(contact) for contact in owner.contacts] if owner else [],
        },
        "pipeline": {
            "id": str(pipeline.id) if pipeline else None,
            "stage": pipeline.stage.value if pipeline and isinstance(pipeline.stage, FunnelStage) else (str(pipeline.stage) if pipeline else None),
            "llm_viability_score": float(pipeline.llm_viability_score) if pipeline and pipeline.llm_viability_score is not None else None,
            "next_action_date": pipeline.next_action_date.isoformat() if pipeline and pipeline.next_action_date else None,
            "rejection_reason": pipeline.rejection_reason if pipeline else None,
        },
        "recent_intel_events": [_serialize_event(event) for event in recent_events],
        "recent_str_signals": [_serialize_signal(signal) for signal in recent_signals],
    }


def _property_select() -> Select[tuple[AcquisitionProperty]]:
    return (
        select(AcquisitionProperty)
        .options(
            selectinload(AcquisitionProperty.parcel),
            selectinload(AcquisitionProperty.owner).selectinload(AcquisitionOwner.contacts),
            selectinload(AcquisitionProperty.pipeline),
            selectinload(AcquisitionProperty.intel_events),
        )
    )


async def load_acquisition_property(db: AsyncSession, property_id: UUID) -> AcquisitionProperty:
    stmt = _property_select().where(AcquisitionProperty.id == property_id).limit(1)
    prop = (await db.execute(stmt)).scalar_one_or_none()
    if prop is None:
        raise ValueError(f"Acquisition property {property_id} not found.")
    return prop


async def load_acquisition_owner(db: AsyncSession, owner_id: UUID) -> AcquisitionOwner:
    stmt = (
        select(AcquisitionOwner)
        .options(selectinload(AcquisitionOwner.contacts), selectinload(AcquisitionOwner.properties))
        .where(AcquisitionOwner.id == owner_id)
        .limit(1)
    )
    owner = (await db.execute(stmt)).scalar_one_or_none()
    if owner is None:
        raise ValueError(f"Acquisition owner {owner_id} not found.")
    return owner


def _candidate_schema_from_property(prop: AcquisitionProperty) -> AcquisitionCandidateSchema:
    payload = _serialize_property_context(prop)
    payload["score_viability_input"] = {"property_id": payload["property_id"]}
    return AcquisitionCandidateSchema.model_validate(payload)


async def list_acquisition_candidates(
    db: AsyncSession,
    *,
    limit: int = 5,
) -> list[AcquisitionCandidateSchema]:
    stmt = (
        _property_select()
        .outerjoin(AcquisitionPipeline, AcquisitionPipeline.property_id == AcquisitionProperty.id)
        .where(
            or_(
                AcquisitionPipeline.id.is_(None),
                AcquisitionPipeline.llm_viability_score.is_(None),
            )
        )
        .order_by(AcquisitionProperty.created_at.asc())
        .limit(limit)
    )
    properties = (await db.execute(stmt)).scalars().unique().all()
    return [_candidate_schema_from_property(prop) for prop in properties]


def _normalize_contact_phone(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def _normalize_contact_candidates(
    contacts: list[dict[str, str]],
    *,
    source: str,
    email_confidence: Decimal,
    phone_confidence: Decimal,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for contact in contacts:
        contact_type = str(contact.get("contact_type") or "").upper()
        contact_value = str(contact.get("contact_value") or "").strip()
        if contact_type == "EMAIL":
            contact_value = contact_value.lower()
            if not contact_value or "@" not in contact_value:
                continue
            confidence = email_confidence
        elif contact_type in {"CELL", "LANDLINE"}:
            contact_value = _normalize_contact_phone(contact_value) or ""
            if not contact_value:
                continue
            confidence = phone_confidence
        else:
            continue
        dedupe_key = (contact_type, contact_value.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "contact_type": contact_type,
                "contact_value": contact_value,
                "source": source,
                "confidence_score": confidence,
            }
        )
    return normalized


def _resolve_b2c_contact_provider() -> B2CContactProvider | None:
    provider_name = str(settings.acquisition_b2c_contact_provider or "").strip().lower()
    if provider_name in {"", "none"}:
        return None
    if provider_name == "mock":
        return StrictMockB2CProvider()
    return None


def _owner_apn(linked_property: AcquisitionProperty | None) -> str | None:
    if linked_property is None or linked_property.parcel is None:
        return None
    return linked_property.parcel.parcel_id


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


def _apollo_headers() -> dict[str, str]:
    api_key = str(settings.apollo_api_key or "").strip()
    if not api_key:
        raise RuntimeError("APOLLO_API_KEY is not configured")
    return {
        "x-api-key": api_key,
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
    }


def _apollo_base_url() -> str:
    return str(settings.apollo_base_url or "https://api.apollo.io/api/v1").strip().rstrip("/")


def _owner_name_parts(owner: AcquisitionOwner) -> tuple[str, str, str]:
    full_name = str(owner.legal_name or "").strip()
    cleaned = [token for token in normalize_name(full_name).split() if token and token != "AND"]
    first_name = cleaned[0] if cleaned else ""
    last_name = cleaned[-1] if len(cleaned) >= 2 else ""
    return full_name, first_name, last_name


async def _apollo_enrich_owner_contacts(owner: AcquisitionOwner) -> tuple[list[dict[str, str]], dict[str, Any]]:
    full_name, first_name, last_name = _owner_name_parts(owner)
    params = {
        "name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "reveal_personal_emails": "true",
        "reveal_phone_number": "false",
    }
    async with httpx.AsyncClient(timeout=_firecrawl_timeout()) as client:
        response = await client.post(
            f"{_apollo_base_url()}/people/match",
            params=params,
            headers=_apollo_headers(),
        )
        response.raise_for_status()
        body = response.json()

    person = body.get("person") if isinstance(body, dict) and isinstance(body.get("person"), dict) else body
    if not isinstance(person, dict):
        return [], {"matched": False, "name": full_name}

    contacts: list[dict[str, str]] = []
    for key in ("email", "personal_email"):
        value = str(person.get(key) or "").strip().lower()
        if value and "@" in value:
            contacts.append({"contact_type": "EMAIL", "contact_value": value})

    for email in person.get("personal_emails") or []:
        value = str(email or "").strip().lower()
        if value and "@" in value:
            contacts.append({"contact_type": "EMAIL", "contact_value": value})

    phone_candidates = []
    for key in ("phone", "phone_number", "mobile_phone", "sanitized_phone", "direct_dial"):
        phone_candidates.append(person.get(key))
    phone_candidates.extend(person.get("phone_numbers") or [])

    for phone in phone_candidates:
        normalized_phone = _normalize_contact_phone(str(phone or ""))
        if normalized_phone:
            contacts.append({"contact_type": "LANDLINE", "contact_value": normalized_phone})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for contact in contacts:
        key = (contact["contact_type"], contact["contact_value"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(contact)

    metadata = {
        "matched": bool(person.get("id")),
        "person_id": person.get("id"),
        "name": person.get("name") or full_name,
        "title": person.get("title"),
        "organization_id": person.get("organization_id"),
        "has_email": bool(person.get("email") or person.get("personal_email") or person.get("personal_emails")),
        "has_phone": bool(any(phone_candidates)),
    }
    return deduped, metadata


def _owner_contact_search_queries(owner: AcquisitionOwner) -> list[str]:
    name = str(owner.legal_name or "").strip()
    address = str(owner.tax_mailing_address or "").strip()
    return [
        f"\"{name}\" \"{address}\" email phone contact",
        f"site:fastpeoplesearch.com \"{name}\" \"{address}\"",
        f"site:truepeoplesearch.com \"{name}\" \"{address}\"",
        f"site:clustrmaps.com \"{name}\" \"{address}\"",
    ]


async def _firecrawl_search_owner_contacts(query: str) -> list[dict[str, Any]]:
    payload = {"query": query, "limit": 3, "scrapeOptions": {"formats": ["markdown"]}}
    endpoint = f"{_firecrawl_base_url()}/v1/search"
    async with httpx.AsyncClient(timeout=_firecrawl_timeout()) as client:
        response = await client.post(endpoint, json=payload, headers=_firecrawl_headers())
        response.raise_for_status()
        body = response.json()

    results = (body or {}).get("data") or []
    if not isinstance(results, list):
        return []
    return [row for row in results if isinstance(row, dict)]


def _extract_public_contact_candidates(owner: AcquisitionOwner, result: dict[str, Any]) -> list[dict[str, str]]:
    owner_tokens = [token for token in normalize_name(owner.legal_name).split() if token]
    address_digits = "".join(ch for ch in str(owner.tax_mailing_address or "") if ch.isdigit())
    text_blob = " ".join(
        [
            str(result.get("title") or ""),
            str(result.get("description") or ""),
            str(result.get("markdown") or ""),
        ]
    )
    upper_blob = text_blob.upper()

    if owner_tokens and not any(token in upper_blob for token in owner_tokens[-2:]):
        return []
    if address_digits and address_digits not in upper_blob:
        return []

    candidates: list[dict[str, str]] = []
    for email in EMAIL_PATTERN.findall(text_blob):
        candidates.append({"contact_type": "EMAIL", "contact_value": email.strip().lower()})
    for phone_match in PHONE_PATTERN.findall(text_blob):
        normalized_phone = _normalize_contact_phone(phone_match)
        if normalized_phone:
            candidates.append({"contact_type": "LANDLINE", "contact_value": normalized_phone})
    return candidates


async def enrich_owner_contacts_from_internal_registry(
    db: AsyncSession,
    *,
    owner_id: UUID,
    property_id: UUID | None = None,
) -> dict[str, Any]:
    owner = await load_acquisition_owner(db, owner_id)

    linked_property: AcquisitionProperty | None = None
    if property_id is not None:
        linked_property = await load_acquisition_property(db, property_id)
        if linked_property.owner_id not in {None, owner.id}:
            raise ValueError("property_id does not belong to the supplied owner.")
    elif owner.properties:
        linked_property = owner.properties[0]

    normalized_owner_name = normalize_name(owner.legal_name)
    if not normalized_owner_name:
        raise ValueError("Owner legal_name is required for internal contact enrichment.")

    registry_rows = (
        await db.execute(
            text(
                """
                SELECT owner_name, email, phone, unit_id, property_name
                FROM owner_property_map
                WHERE owner_name IS NOT NULL
                """
            )
        )
    ).mappings().all()

    matches = [row for row in registry_rows if normalize_name(row.get("owner_name")) == normalized_owner_name]
    existing_values = {str(contact.contact_value or "").strip().lower() for contact in owner.contacts}
    added_contacts: list[dict[str, Any]] = []
    apollo_matches: list[dict[str, str]] = []
    apollo_lookup_error: str | None = None
    apollo_metadata: dict[str, Any] | None = None
    b2c_provider_name: str | None = None
    b2c_provider_match_count = 0
    b2c_provider_error: str | None = None
    b2c_provider_metadata: dict[str, Any] | None = None
    external_results_considered = 0
    external_lookup_error: str | None = None
    firecrawl_query: str | None = None
    firecrawl_queries: list[str] = []

    for row in matches:
        email = str(row.get("email") or "").strip().lower()
        if email and "@" in email and email not in existing_values:
            contact = AcquisitionOwnerContact(
                id=uuid4(),
                owner_id=owner.id,
                contact_type="EMAIL",
                contact_value=email,
                source="owner_property_map",
                confidence_score=Decimal("0.95"),
                is_dnc=False,
            )
            db.add(contact)
            existing_values.add(email)
            added_contacts.append(_serialize_contact(contact))

        phone = _normalize_contact_phone(row.get("phone"))
        phone_key = (phone or "").lower()
        if phone and phone_key not in existing_values:
            contact = AcquisitionOwnerContact(
                id=uuid4(),
                owner_id=owner.id,
                contact_type="LANDLINE",
                contact_value=phone,
                source="owner_property_map",
                confidence_score=Decimal("0.80"),
                is_dnc=False,
            )
            db.add(contact)
            existing_values.add(phone_key)
            added_contacts.append(_serialize_contact(contact))

    if not added_contacts:
        try:
            apollo_matches, apollo_metadata = await _apollo_enrich_owner_contacts(owner)
            for candidate in _normalize_contact_candidates(
                apollo_matches,
                source="apollo_people_match",
                email_confidence=Decimal("0.85"),
                phone_confidence=Decimal("0.75"),
            ):
                candidate_value = candidate["contact_value"].lower()
                if candidate_value in existing_values:
                    continue
                contact = AcquisitionOwnerContact(
                    id=uuid4(),
                    owner_id=owner.id,
                    contact_type=candidate["contact_type"],
                    contact_value=candidate["contact_value"],
                    source=candidate["source"],
                    confidence_score=candidate["confidence_score"],
                    is_dnc=False,
                )
                db.add(contact)
                existing_values.add(candidate_value)
                added_contacts.append(_serialize_contact(contact))
        except Exception as exc:  # noqa: BLE001
            apollo_lookup_error = str(exc)[:300]

    if not added_contacts:
        provider = _resolve_b2c_contact_provider()
        if provider is not None:
            b2c_provider_name = provider.provider_name
            try:
                result = await provider.resolve_contact(_owner_apn(linked_property) or "", owner.legal_name)
                b2c_provider_metadata = result.metadata
                normalized_provider_contacts = _normalize_contact_candidates(
                    [contact.model_dump() for contact in result.contacts],
                    source=result.provider_name,
                    email_confidence=Decimal("0.99"),
                    phone_confidence=Decimal("0.99"),
                )
                b2c_provider_match_count = len(normalized_provider_contacts)
                for candidate in normalized_provider_contacts:
                    candidate_value = candidate["contact_value"].lower()
                    if candidate_value in existing_values:
                        continue
                    contact = AcquisitionOwnerContact(
                        id=uuid4(),
                        owner_id=owner.id,
                        contact_type=candidate["contact_type"],
                        contact_value=candidate["contact_value"],
                        source=candidate["source"],
                        confidence_score=candidate["confidence_score"],
                        is_dnc=False,
                    )
                    db.add(contact)
                    existing_values.add(candidate_value)
                    added_contacts.append(_serialize_contact(contact))
            except Exception as exc:  # noqa: BLE001
                b2c_provider_error = str(exc)[:300]

    if not added_contacts:
        external_lookup_error = None
        for query in _owner_contact_search_queries(owner):
            firecrawl_query = query
            firecrawl_queries.append(query)
            try:
                search_results = await _firecrawl_search_owner_contacts(query)
            except Exception as exc:  # noqa: BLE001
                external_lookup_error = str(exc)[:300]
                continue

            external_results_considered += len(search_results)
            for result in search_results:
                for candidate in _extract_public_contact_candidates(owner, result):
                    candidate_value = candidate["contact_value"].lower()
                    if candidate_value in existing_values:
                        continue
                    confidence = Decimal("0.65") if candidate["contact_type"] == "EMAIL" else Decimal("0.45")
                    contact = AcquisitionOwnerContact(
                        id=uuid4(),
                        owner_id=owner.id,
                        contact_type=candidate["contact_type"],
                        contact_value=candidate["contact_value"],
                        source="firecrawl_search",
                        confidence_score=confidence,
                        is_dnc=False,
                    )
                    db.add(contact)
                    existing_values.add(candidate_value)
                    added_contacts.append(_serialize_contact(contact))
            if added_contacts:
                break

    event_payload = {
        "owner_id": str(owner.id),
        "owner_name": owner.legal_name,
        "registry_match_count": len(matches),
        "added_contact_count": len(added_contacts),
        "apollo_match_count": len(apollo_matches),
        "apollo_lookup_error": apollo_lookup_error,
        "apollo_metadata": apollo_metadata,
        "b2c_provider_name": b2c_provider_name,
        "b2c_provider_match_count": b2c_provider_match_count,
        "b2c_provider_error": b2c_provider_error,
        "b2c_provider_metadata": b2c_provider_metadata,
        "external_results_considered": external_results_considered,
        "external_lookup_error": external_lookup_error,
        "firecrawl_query": firecrawl_query,
        "firecrawl_queries": firecrawl_queries,
        "property_id": str(linked_property.id) if linked_property is not None else None,
        "match_unit_ids": [str(row.get("unit_id") or "") for row in matches],
    }

    if linked_property is not None:
        db.add(
            AcquisitionIntelEvent(
                property_id=linked_property.id,
                event_type=(
                    "HERMES_OWNER_CONTACT_ENRICHMENT"
                    if added_contacts
                    else "HERMES_OWNER_CONTACT_ENRICHMENT_MISS"
                ),
                event_description=(
                    f"Hermes enriched {len(added_contacts)} owner contacts from internal registry."
                    if added_contacts
                    else "Hermes found no trusted internal owner contact matches."
                ),
                raw_source_data=event_payload,
            )
        )

    return {
        "owner_id": str(owner.id),
        "legal_name": owner.legal_name,
        "matched_registry_rows": len(matches),
        "apollo_match_count": len(apollo_matches),
        "apollo_lookup_error": apollo_lookup_error,
        "b2c_provider_name": b2c_provider_name,
        "b2c_provider_match_count": b2c_provider_match_count,
        "b2c_provider_error": b2c_provider_error,
        "external_results_considered": external_results_considered,
        "external_lookup_error": external_lookup_error,
        "added_contacts": added_contacts,
        "linked_property_id": str(linked_property.id) if linked_property is not None else None,
    }


def _merge_profile(existing: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_profile(merged.get(key), value)
        else:
            merged[key] = value
    return merged


def _candidate_contacts(owner: AcquisitionOwner | None) -> list[AcquisitionOwnerContact]:
    if owner is None:
        return []
    return sorted(
        owner.contacts,
        key=lambda contact: (
            bool(contact.is_dnc),
            -(float(contact.confidence_score) if contact.confidence_score is not None else 0.0),
            contact.contact_type or "",
        ),
    )


def _recommended_channel(contacts: Sequence[AcquisitionOwnerContact]) -> str:
    for contact in contacts:
        if contact.is_dnc:
            continue
        if contact.contact_type == "EMAIL":
            return "EMAIL"
    for contact in contacts:
        if contact.is_dnc:
            continue
        if contact.contact_type in {"CELL", "LANDLINE"}:
            return contact.contact_type
    return "DIRECT_MAIL"


def _profile_angle(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict) or not profile:
        return "asset stewardship"
    explicit_angle = str(profile.get("angle") or "").strip()
    if explicit_angle:
        return explicit_angle
    interests = profile.get("interests")
    if isinstance(interests, list) and interests:
        return f"{interests[0]} alignment"
    return "owner legacy"


def _score_components(prop: AcquisitionProperty) -> tuple[float, dict[str, float]]:
    parcel: AcquisitionParcel | None = prop.parcel
    owner = prop.owner
    contacts = _candidate_contacts(owner)
    recent_events = sorted(prop.intel_events or [], key=lambda event: event.detected_at or _utcnow(), reverse=True)
    recent_signals = _safe_recent_str_signals(prop)
    thirty_days_ago = _utcnow() - timedelta(days=30)
    recent_signal_count = sum(1 for event in recent_events if event.detected_at and event.detected_at >= thirty_days_ago)
    recent_str_signal_strength = sum(
        float(signal.confidence_score)
        for signal in recent_signals
        if signal.detected_at and signal.detected_at >= thirty_days_ago
    )

    assessed_value = float(parcel.assessed_value) if parcel and parcel.assessed_value is not None else 0.0
    projected_revenue = float(prop.projected_annual_revenue) if prop.projected_annual_revenue is not None else 0.0
    adr = float(prop.projected_adr) if prop.projected_adr is not None else 0.0

    components = {
        "ownership_resolution": 0.18 if owner is not None else 0.04,
        "contactability": min(0.16, 0.06 + 0.05 * len([c for c in contacts if not c.is_dnc])),
        "terrain_premium": (
            (0.07 if parcel and parcel.is_waterfront else 0.0)
            + (0.05 if parcel and parcel.is_ridgeline else 0.0)
        ),
        "market_control": {
            MarketState.UNMANAGED: 0.22,
            MarketState.FOR_SALE: 0.24,
            MarketState.CROG_MANAGED: 0.05,
            MarketState.COMPETITOR_MANAGED: 0.11,
        }.get(prop.status, 0.08),
        "underwriting_signal": min(0.18, (projected_revenue / 500000.0) * 0.18) if projected_revenue > 0 else min(0.08, (adr / 450.0) * 0.08),
        "parcel_value_signal": min(0.12, (assessed_value / 1000000.0) * 0.12) if assessed_value > 0 else 0.0,
        "recent_intel_signal": min(0.10, recent_signal_count * 0.02),
        "recent_str_signal": min(0.12, recent_str_signal_strength * 0.06),
    }
    raw_score = sum(components.values())
    bounded_score = max(0.01, min(0.99, round(raw_score, 2)))
    return bounded_score, {key: round(value, 4) for key, value in components.items()}


async def score_acquisition_property(db: AsyncSession, property_id: UUID) -> dict[str, Any]:
    prop = await load_acquisition_property(db, property_id)
    score, components = _score_components(prop)

    if prop.pipeline is None:
        pipeline = AcquisitionPipeline(property_id=prop.id, stage=FunnelStage.RADAR)
        db.add(pipeline)
        await db.flush()
        prop.pipeline = pipeline

    prop.pipeline.llm_viability_score = Decimal(str(score))
    if prop.pipeline.next_action_date is None and score >= 0.7:
        prop.pipeline.next_action_date = date.today() + timedelta(days=3)

    return {
        "property": _serialize_property_context(prop),
        "viability_score": score,
        "score_components": components,
        "recommended_action": (
            "advance_to_target_locked"
            if score >= 0.75
            else "continue_signal_collection"
            if score >= 0.45
            else "monitor_only"
        ),
    }


async def enrich_owner_psychology(
    db: AsyncSession,
    *,
    owner_id: UUID,
    profile_patch: dict[str, Any],
    source_note: str | None = None,
    property_id: UUID | None = None,
) -> dict[str, Any]:
    owner = await load_acquisition_owner(db, owner_id)
    owner.psychological_profile = _merge_profile(owner.psychological_profile, profile_patch)

    linked_property: AcquisitionProperty | None = None
    if property_id is not None:
        linked_property = await load_acquisition_property(db, property_id)
        if linked_property.owner_id not in {None, owner.id}:
            raise ValueError("property_id does not belong to the supplied owner.")

    if linked_property is None and owner.properties:
        linked_property = owner.properties[0]

    if linked_property is not None:
        db.add(
            AcquisitionIntelEvent(
                property_id=linked_property.id,
                event_type="PAPERCLIP_PSYCHOLOGY_ENRICHED",
                event_description=source_note or f"Paperclip enriched owner psychology for {owner.legal_name}.",
                raw_source_data={
                    "owner_id": str(owner.id),
                    "profile_patch": profile_patch,
                    "source_note": source_note,
                },
            )
        )
        await db.flush()

    return {
        "owner_id": str(owner.id),
        "legal_name": owner.legal_name,
        "psychological_profile": owner.psychological_profile,
        "linked_property_id": str(linked_property.id) if linked_property is not None else None,
    }


async def append_acquisition_intel_event(
    db: AsyncSession,
    *,
    property_id: UUID,
    event_type: str,
    event_description: str,
    raw_source_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prop = await load_acquisition_property(db, property_id)
    event = AcquisitionIntelEvent(
        property_id=prop.id,
        event_type=event_type,
        event_description=event_description,
        raw_source_data=raw_source_data or {},
    )
    db.add(event)
    await db.flush()
    return _serialize_event(event)


async def advance_acquisition_pipeline(
    db: AsyncSession,
    *,
    property_id: UUID,
    stage: FunnelStage,
    next_action_date: date | None = None,
    rejection_reason: str | None = None,
    llm_viability_score: Decimal | None = None,
) -> dict[str, Any]:
    prop = await load_acquisition_property(db, property_id)
    if prop.pipeline is None:
        pipeline = AcquisitionPipeline(property_id=prop.id, stage=stage)
        db.add(pipeline)
        await db.flush()
        prop.pipeline = pipeline

    prop.pipeline.stage = stage
    prop.pipeline.next_action_date = next_action_date
    prop.pipeline.rejection_reason = rejection_reason
    if llm_viability_score is not None:
        prop.pipeline.llm_viability_score = llm_viability_score

    db.add(
        AcquisitionIntelEvent(
            property_id=prop.id,
            event_type="PIPELINE_STAGE_UPDATED",
            event_description=f"Pipeline stage updated to {stage.value}.",
            raw_source_data={
                "stage": stage.value,
                "next_action_date": next_action_date.isoformat() if next_action_date else None,
                "rejection_reason": rejection_reason,
                "llm_viability_score": float(llm_viability_score) if llm_viability_score is not None else None,
            },
        )
    )
    await db.flush()
    return _serialize_property_context(prop)["pipeline"]


async def draft_acquisition_outreach_sequence(
    db: AsyncSession,
    *,
    property_id: UUID,
) -> dict[str, Any]:
    prop = await load_acquisition_property(db, property_id)
    owner = prop.owner
    if owner is None:
        raise ValueError("Property has no linked owner; enrich ownership before drafting outreach.")

    contacts = _candidate_contacts(owner)
    recommended_channel = _recommended_channel(contacts)
    angle = _profile_angle(owner.psychological_profile)
    first_name = owner.legal_name.split()[0].strip(",") if owner.legal_name else "there"
    property_reference = prop.parcel.parcel_id if prop.parcel else str(prop.id)
    competitor_line = (
        f"We noticed {prop.management_company} appears to be involved."
        if prop.management_company and prop.status == MarketState.COMPETITOR_MANAGED
        else "We noticed this parcel may be under-managed or ready for repositioning."
    )

    email_subject = f"Idea for {property_reference}: a higher-conviction owner strategy"
    email_body = (
        f"Hi {first_name},\n\n"
        f"I'm reaching out because {competitor_line} We believe there is a strong {angle} story for this asset, "
        "with a management approach that protects owner intent while improving revenue quality.\n\n"
        "If useful, we can share a short upside memo with market comps, positioning ideas, and a low-friction transition path."
    )
    sms_body = (
        f"Hi {first_name}, this is CROG. We have a quick idea for improving the upside on parcel {property_reference} "
        f"through a {angle} angle. If you'd like, we can send a short summary."
    )

    return {
        "property": _serialize_property_context(prop),
        "recommended_channel": recommended_channel,
        "candidate_contacts": [_serialize_contact(contact) for contact in contacts[:3]],
        "angle": angle,
        "sequence": [
            {"step": 1, "channel": recommended_channel, "goal": "initial_contact"},
            {"step": 2, "channel": "DIRECT_MAIL" if recommended_channel != "DIRECT_MAIL" else "EMAIL", "goal": "leave_behind_brief"},
            {"step": 3, "channel": "CALL" if recommended_channel == "EMAIL" else "EMAIL", "goal": "follow_up_with_upside_memo"},
        ],
        "drafts": {
            "email_subject": email_subject,
            "email_body": email_body,
            "sms_body": sms_body,
        },
    }
