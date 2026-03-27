"""
Backend shadow-mode observer for guest quote generation.

This service is designed to run behind FastAPI BackgroundTasks so the live guest
path remains unchanged while the sovereign quote lane is evaluated in parallel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.services.openshell_audit import record_audit_event
from backend.services.quote_builder import calculate_property_quote
from backend.services.revenue_chain_of_custody import calculate_fannin_county_tax

logger = structlog.get_logger(service="shadow_mode_observer")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_PATH = REPO_ROOT / "docs" / "fortress_prime_shadow_audit.md"
TWO_PLACES = Decimal("0.01")
LEGACY_PROPERTY_MAP = {
    "14": "f66def25-6b88-4a72-a023-efa575281a59",
}


class ShadowQuoteRequest(BaseModel):
    property_id: str | UUID | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int = 2
    children: int = 0
    pets: int = 0
    base_rent: Decimal = Field(default=Decimal("0.00"))
    taxes: Decimal = Field(default=Decimal("0.00"))
    fees: Decimal = Field(default=Decimal("0.00"))
    campaign: str = "direct"
    target_keyword: str | None = None


@dataclass
class QuoteSnapshot:
    property_id: str
    property_name: str
    requested_property_id: str
    pricing_source: str
    check_in: str | None
    check_out: str | None
    nights: int
    base_rent: Decimal
    fees: Decimal
    taxes: Decimal
    total_amount: Decimal
    raw_total: Decimal
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "property_name": self.property_name,
            "requested_property_id": self.requested_property_id,
            "pricing_source": self.pricing_source,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "nights": self.nights,
            "base_rent": money(self.base_rent),
            "fees": money(self.fees),
            "taxes": money(self.taxes),
            "total_amount": money(self.total_amount),
            "raw_total": money(self.raw_total),
            "metadata": self.metadata,
        }


@dataclass
class ComparisonResult:
    trace_id: str
    timestamp: str
    drift_status: str
    legacy_total: Decimal
    sovereign_total: Decimal
    total_delta: Decimal
    legacy_taxes: Decimal
    sovereign_taxes: Decimal
    tax_delta: Decimal
    legacy_base_rent: Decimal
    sovereign_base_rent: Decimal
    base_rate_delta: Decimal
    base_rate_drift_pct: Decimal
    notes: list[str]

    def as_signature_payload(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "drift_status": self.drift_status,
            "legacy_total": money(self.legacy_total),
            "sovereign_total": money(self.sovereign_total),
            "total_delta": money(self.total_delta),
            "tax_delta": money(self.tax_delta),
            "base_rate_drift_pct": format(self.base_rate_drift_pct, ".4f"),
        }


def money(value: Decimal | str | int | float) -> str:
    return format(Decimal(str(value)).quantize(TWO_PLACES), ".2f")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signing_key() -> bytes:
    secret = (
        getattr(settings, "revenue_hmac_secret", "")
        or settings.audit_log_signing_key
        or settings.jwt_secret_key
        or "fortress-shadow-fallback-key"
    )
    return secret.encode("utf-8")


def sign_audit_payload(payload: dict[str, Any]) -> str:
    canonical = _canonical_json(payload)
    return hmac.new(_signing_key(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_request(payload: dict[str, Any]) -> ShadowQuoteRequest:
    return ShadowQuoteRequest.model_validate(payload)


def should_calculate_quote(request: ShadowQuoteRequest) -> bool:
    return (
        request.check_in is not None
        and request.check_out is not None
        and request.base_rent == Decimal("0.00")
        and request.taxes == Decimal("0.00")
        and request.fees == Decimal("0.00")
    )


def derive_nights(request: ShadowQuoteRequest) -> int:
    if request.check_in is None or request.check_out is None:
        return 1
    nights = (request.check_out - request.check_in).days
    if nights < 1:
        raise ValueError("check_out must be after check_in")
    return nights


async def resolve_quote_property(
    requested_property_id: str | UUID | None,
) -> tuple[Property, str]:
    if requested_property_id is None:
        raise ValueError("property_id is required")

    raw_property_id = str(requested_property_id).strip()
    if not raw_property_id:
        raise ValueError("property_id is required")

    resolved_identifier = LEGACY_PROPERTY_MAP.get(raw_property_id, raw_property_id)

    property_uuid: UUID | None = None
    try:
        property_uuid = UUID(resolved_identifier)
    except ValueError:
        property_uuid = None

    async with AsyncSessionLocal() as db:
        property_record = None
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
            f"Property '{raw_property_id}' not found. "
            "Expected a mapped legacy ID, property UUID, or Streamline property ID."
        )

    return property_record, raw_property_id


async def calculate_legacy_quote_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    request = normalize_request(payload)
    property_record, _requested_property_id = await resolve_quote_property(request.property_id)
    nights = derive_nights(request)

    pricing_source = "manual_payload"
    base_rent = request.base_rent
    taxes = request.taxes
    fees = request.fees

    if should_calculate_quote(request):
        async with AsyncSessionLocal() as db:
            pricing = await calculate_property_quote(
                property_id=property_record.id,
                check_in=request.check_in,
                check_out=request.check_out,
                db=db,
            )
        pricing_source = pricing["pricing_source"]
        base_rent = Decimal(pricing["base_rent"])
        taxes = Decimal(pricing["taxes"])
        fees = Decimal(pricing["fees"])

    total_amount = (base_rent + taxes + fees).quantize(TWO_PLACES)
    return {
        "property_id": str(property_record.id),
        "property_name": property_record.name,
        "base_rent": money(base_rent),
        "taxes": money(taxes),
        "fees": money(fees),
        "total_amount": money(total_amount),
        "pricing_source": pricing_source,
        "nights": nights,
    }


async def build_legacy_snapshot(
    request: ShadowQuoteRequest,
    legacy_result: dict[str, Any],
) -> QuoteSnapshot:
    property_record, requested_property_id = await resolve_quote_property(request.property_id)
    base_rent = Decimal(str(legacy_result["base_rent"]))
    fees = Decimal(str(legacy_result["fees"]))
    taxes = Decimal(str(legacy_result["taxes"]))
    total_amount = Decimal(str(legacy_result["total_amount"]))
    nights = int(legacy_result.get("nights") or derive_nights(request))

    return QuoteSnapshot(
        property_id=str(legacy_result.get("property_id") or property_record.id),
        property_name=str(legacy_result.get("property_name") or property_record.name),
        requested_property_id=requested_property_id,
        pricing_source=str(legacy_result.get("pricing_source") or "manual_payload"),
        check_in=request.check_in.isoformat() if request.check_in else None,
        check_out=request.check_out.isoformat() if request.check_out else None,
        nights=nights,
        base_rent=base_rent,
        fees=fees,
        taxes=taxes,
        total_amount=total_amount,
        raw_total=(base_rent + fees).quantize(TWO_PLACES),
        metadata={
            "guest_email_present": bool(request.guest_email),
            "campaign": request.campaign,
            "target_keyword": request.target_keyword,
        },
    )


async def build_shadow_snapshot(
    request: ShadowQuoteRequest,
    legacy: QuoteSnapshot,
    *,
    remote_closer_url: str | None = None,
    timeout_seconds: float = 20.0,
    metadata: dict[str, Any] | None = None,
) -> QuoteSnapshot:
    metadata = metadata or {}
    notes: list[str] = []
    remote_result: dict[str, Any] | None = None

    if remote_closer_url:
        remote_result, remote_note = await try_remote_closer(
            remote_closer_url=remote_closer_url,
            request=request,
            legacy=legacy,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        )
        if remote_note:
            notes.append(remote_note)

    if remote_result:
        taxes = Decimal(str(remote_result["tax_total"]))
        total_amount = Decimal(str(remote_result.get("quoted_total", legacy.raw_total + taxes)))
        shadow_metadata = {
            "closer_mode": "remote",
            "orchestrator": metadata.get("orchestrator") or settings.orchestrator_source,
            "signed_record": remote_result,
            "notes": notes,
        }
    else:
        tax_result = calculate_fannin_county_tax(raw_total=legacy.raw_total, nights=legacy.nights)
        signed_record = {
            "trace_id": metadata.get("trace_id") or str(uuid4()),
            "quote_id": metadata.get("quote_id", ""),
            "raw_total": money(legacy.raw_total),
            "tax_total": tax_result.tax_total,
            "quoted_total": tax_result.quoted_total,
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        signed_record["hmac_sig"] = sign_audit_payload(signed_record)
        taxes = Decimal(tax_result.tax_total)
        total_amount = Decimal(tax_result.quoted_total)
        shadow_metadata = {
            "closer_mode": "local_contract",
            "orchestrator": metadata.get("orchestrator") or settings.orchestrator_source,
            "signed_record": signed_record,
            "tax_rule": tax_result.tax_rule,
            "notes": notes,
        }

    return QuoteSnapshot(
        property_id=legacy.property_id,
        property_name=legacy.property_name,
        requested_property_id=legacy.requested_property_id,
        pricing_source=legacy.pricing_source,
        check_in=legacy.check_in,
        check_out=legacy.check_out,
        nights=legacy.nights,
        base_rent=legacy.base_rent,
        fees=legacy.fees,
        taxes=taxes,
        total_amount=total_amount,
        raw_total=legacy.raw_total,
        metadata=shadow_metadata,
    )


async def try_remote_closer(
    *,
    remote_closer_url: str,
    request: ShadowQuoteRequest,
    legacy: QuoteSnapshot,
    timeout_seconds: float,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    payload = {
        "mode": "shadow",
        "trace_id": metadata.get("trace_id") or str(uuid4()),
        "quote_request": {
            "property_id": legacy.property_id,
            "requested_property_id": legacy.requested_property_id,
            "property_name": legacy.property_name,
            "check_in": request.check_in.isoformat() if request.check_in else None,
            "check_out": request.check_out.isoformat() if request.check_out else None,
            "adults": request.adults,
            "children": request.children,
            "pets": request.pets,
            "campaign": request.campaign,
            "target_keyword": request.target_keyword,
            "pricing_source": legacy.pricing_source,
            "raw_total": money(legacy.raw_total),
            "nights": legacy.nights,
            "metadata": metadata,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(remote_closer_url, json=payload)
            response.raise_for_status()
        return response.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"Remote closer unavailable; fell back to local contract: {str(exc)[:180]}"


def compare_snapshots(
    legacy: QuoteSnapshot,
    sovereign: QuoteSnapshot,
    *,
    tolerance: Decimal,
) -> ComparisonResult:
    total_delta = (sovereign.total_amount - legacy.total_amount).quantize(TWO_PLACES)
    tax_delta = (sovereign.taxes - legacy.taxes).quantize(TWO_PLACES)
    base_rate_delta = (sovereign.base_rent - legacy.base_rent).quantize(TWO_PLACES)

    if legacy.base_rent == Decimal("0.00"):
        base_rate_drift_pct = Decimal("0.0000")
    else:
        base_rate_drift_pct = (
            (abs(base_rate_delta) / legacy.base_rent) * Decimal("100")
        ).quantize(Decimal("0.0001"))

    notes: list[str] = []
    if abs(tax_delta) == Decimal("0.00") and abs(total_delta) <= tolerance and base_rate_drift_pct == Decimal("0.0000"):
        drift_status = "MATCH"
    elif abs(tax_delta) == Decimal("0.00") and base_rate_drift_pct < Decimal("1.0000"):
        drift_status = "MINOR_DRIFT"
        notes.append("Base-rate drift is below 1% and deterministic tax still matches.")
    else:
        drift_status = "CRITICAL_MISMATCH"
        notes.append("Shadow quote diverged beyond the accepted no-harm guardrail.")

    shadow_notes = sovereign.metadata.get("notes")
    if isinstance(shadow_notes, list):
        notes.extend(str(note) for note in shadow_notes if note)

    return ComparisonResult(
        trace_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        drift_status=drift_status,
        legacy_total=legacy.total_amount,
        sovereign_total=sovereign.total_amount,
        total_delta=total_delta,
        legacy_taxes=legacy.taxes,
        sovereign_taxes=sovereign.taxes,
        tax_delta=tax_delta,
        legacy_base_rent=legacy.base_rent,
        sovereign_base_rent=sovereign.base_rent,
        base_rate_delta=base_rate_delta,
        base_rate_drift_pct=base_rate_drift_pct,
        notes=notes,
    )


def render_report(
    *,
    request_payload: dict[str, Any],
    legacy: QuoteSnapshot,
    sovereign: QuoteSnapshot,
    comparison: ComparisonResult,
    hmac_signature: str,
) -> str:
    payload_json = json.dumps(request_payload, indent=2, sort_keys=True, default=str)
    legacy_json = json.dumps(legacy.as_dict(), indent=2, sort_keys=True)
    sovereign_json = json.dumps(sovereign.as_dict(), indent=2, sort_keys=True)
    notes_block = "\n".join(f"- {note}" for note in comparison.notes) if comparison.notes else "- None"

    return (
        f"\n## Comparison Report {comparison.timestamp}\n"
        f"\n"
        f"- Trace ID: `{comparison.trace_id}`\n"
        f"- Legacy Total: `${money(comparison.legacy_total)}`\n"
        f"- Sovereign Total: `${money(comparison.sovereign_total)}`\n"
        f"- Drift Status: `{comparison.drift_status}`\n"
        f"- HMAC Signature: `{hmac_signature}`\n"
        f"- Legacy Taxes: `${money(comparison.legacy_taxes)}`\n"
        f"- Sovereign Taxes: `${money(comparison.sovereign_taxes)}`\n"
        f"- Tax Delta: `${money(comparison.tax_delta)}`\n"
        f"- Base Rate Drift: `{format(comparison.base_rate_drift_pct, '.4f')}%`\n"
        f"\n"
        f"### Notes\n"
        f"{notes_block}\n"
        f"\n"
        f"### Request Payload\n"
        f"```json\n{payload_json}\n```\n"
        f"\n"
        f"### Legacy Snapshot\n"
        f"```json\n{legacy_json}\n```\n"
        f"\n"
        f"### Sovereign Snapshot\n"
        f"```json\n{sovereign_json}\n```\n"
    )


def append_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Fortress Prime Shadow Audit\n\n"
            "Append-only comparison reports from `backend.services.shadow_mode_observer`.\n"
            "Each entry compares the live legacy quote path against the sovereign shadow lane.\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(report)


async def run_shadow_audit(
    *,
    payload: dict[str, Any],
    legacy_result: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    audit_path: str | Path | None = None,
    remote_closer_url: str | None = None,
    timeout_seconds: float = 20.0,
    tolerance: str | Decimal = Decimal("0.01"),
    request_id: str | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    target_audit_path = Path(audit_path) if audit_path else DEFAULT_AUDIT_PATH
    tolerance_decimal = Decimal(str(tolerance)).quantize(TWO_PLACES)

    if not settings.agentic_system_active:
        return {
            "status": "inactive",
            "detail": "Shadow Parallel observation is disabled by AGENTIC_SYSTEM_ACTIVE.",
            "audit_path": str(target_audit_path),
        }

    try:
        request = normalize_request(payload)
        if legacy_result is None:
            legacy_result = await calculate_legacy_quote_from_request(payload)
        legacy = await build_legacy_snapshot(request, legacy_result)
        sovereign = await build_shadow_snapshot(
            request,
            legacy,
            remote_closer_url=remote_closer_url or metadata.get("remote_closer_url"),
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        )
        comparison = compare_snapshots(legacy, sovereign, tolerance=tolerance_decimal)
        signature_payload = {
            **comparison.as_signature_payload(),
            "quote_id": str(metadata.get("quote_id", "")),
        }
        hmac_signature = sign_audit_payload(signature_payload)
        report = render_report(
            request_payload=payload,
            legacy=legacy,
            sovereign=sovereign,
            comparison=comparison,
            hmac_signature=hmac_signature,
        )
        append_report(target_audit_path, report)

        await record_audit_event(
            action="shadow.quote.audit.write",
            resource_type="shadow_quote_audit",
            resource_id=comparison.trace_id,
            purpose="shadow_mode_validation",
            tool_name="run_shadow_audit",
            model_route="local_cluster",
            outcome="success" if comparison.drift_status != "CRITICAL_MISMATCH" else "error",
            request_id=request_id,
            metadata_json={
                "trace_id": comparison.trace_id,
                "quote_id": str(metadata.get("quote_id", "")),
                "drift_status": comparison.drift_status,
                "legacy_total": money(comparison.legacy_total),
                "sovereign_total": money(comparison.sovereign_total),
                "base_rate_drift_pct": format(comparison.base_rate_drift_pct, ".4f"),
                "tax_delta": money(comparison.tax_delta),
                "hmac_signature": hmac_signature,
                "audit_path": str(target_audit_path),
            },
        )

        return {
            "trace_id": comparison.trace_id,
            "drift_status": comparison.drift_status,
            "audit_path": str(target_audit_path),
            "legacy_total": money(comparison.legacy_total),
            "sovereign_total": money(comparison.sovereign_total),
            "tax_delta": money(comparison.tax_delta),
            "base_rate_drift_pct": format(comparison.base_rate_drift_pct, ".4f"),
            "hmac_signature": hmac_signature,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("shadow_audit_failed", error=str(exc)[:400], metadata=metadata)
        return {
            "status": "error",
            "error": str(exc)[:400],
            "audit_path": str(target_audit_path),
        }
