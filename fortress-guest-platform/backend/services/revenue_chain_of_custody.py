"""
Revenue-first deterministic services for the V1 quote pipeline.

These helpers keep pricing math and signing out of the model loop so the
orchestrator can delegate judgment to AI without delegating arithmetic or
integrity guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
from typing import Any

from backend.core.config import settings

TWO_PLACES = Decimal("0.01")
FANNIN_PERCENT_RATE = Decimal("0.06")
FANNIN_NIGHTLY_FEE = Decimal("5.00")
UTC_ISO_Z_SUFFIX = "Z"


def _to_decimal(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, ROUND_HALF_UP)


def _money(value: Decimal | str | int | float) -> str:
    return format(_to_decimal(value), ".2f")


def _normalize_timestamp(timestamp: str | datetime | None) -> str:
    if timestamp is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", UTC_ISO_Z_SUFFIX)
    if isinstance(timestamp, datetime):
        dt = timestamp.astimezone(timezone.utc).replace(microsecond=0)
        return dt.isoformat().replace("+00:00", UTC_ISO_Z_SUFFIX)
    text = timestamp.strip()
    if not text:
        raise ValueError("timestamp cannot be blank")
    if text.endswith(UTC_ISO_Z_SUFFIX):
        return text
    return text


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signing_secret(explicit_secret: str | None = None) -> str:
    return (
        explicit_secret
        or getattr(settings, "revenue_hmac_secret", "")
        or settings.audit_log_signing_key
        or settings.jwt_secret_key
        or "fortress-revenue-fallback-key"
    )


@dataclass(frozen=True)
class DeterministicTaxResult:
    raw_total: str
    percentage_tax: str
    nightly_fee_total: str
    tax_total: str
    quoted_total: str
    nights: int
    tax_rule: str = "fannin_county_v1"
    percentage_rate: str = "0.06"
    nightly_fee_rate: str = "5.00"

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_total": self.raw_total,
            "percentage_tax": self.percentage_tax,
            "nightly_fee_total": self.nightly_fee_total,
            "tax_total": self.tax_total,
            "quoted_total": self.quoted_total,
            "nights": self.nights,
            "tax_rule": self.tax_rule,
            "percentage_rate": self.percentage_rate,
            "nightly_fee_rate": self.nightly_fee_rate,
        }


def calculate_fannin_county_tax(
    *,
    raw_total: Decimal | str | int | float,
    nights: int,
) -> DeterministicTaxResult:
    """
    Apply the V1 hard gate rule: 6% of the raw total plus $5.00 per night.
    """
    if nights < 1:
        raise ValueError("nights must be >= 1")

    raw_total_decimal = _to_decimal(raw_total)
    if raw_total_decimal < Decimal("0.00"):
        raise ValueError("raw_total must be >= 0")

    percentage_tax = (raw_total_decimal * FANNIN_PERCENT_RATE).quantize(TWO_PLACES, ROUND_HALF_UP)
    nightly_fee_total = (FANNIN_NIGHTLY_FEE * Decimal(nights)).quantize(TWO_PLACES, ROUND_HALF_UP)
    tax_total = (percentage_tax + nightly_fee_total).quantize(TWO_PLACES, ROUND_HALF_UP)
    quoted_total = (raw_total_decimal + tax_total).quantize(TWO_PLACES, ROUND_HALF_UP)

    return DeterministicTaxResult(
        raw_total=_money(raw_total_decimal),
        percentage_tax=_money(percentage_tax),
        nightly_fee_total=_money(nightly_fee_total),
        tax_total=_money(tax_total),
        quoted_total=_money(quoted_total),
        nights=nights,
    )


def build_canonical_quote_payload(
    *,
    quote_id: str,
    raw_total: Decimal | str | int | float,
    tax_total: Decimal | str | int | float,
    timestamp: str | datetime | None = None,
) -> dict[str, str]:
    """
    Build the canonical payload shape for HMAC signing.

    The signed shape intentionally stays narrow so future agents can verify the
    chain of custody without needing internal pricing metadata.
    """
    quote_identifier = str(quote_id).strip()
    if not quote_identifier:
        raise ValueError("quote_id is required")

    return {
        "quote_id": quote_identifier,
        "raw_total": _money(raw_total),
        "tax_total": _money(tax_total),
        "timestamp": _normalize_timestamp(timestamp),
    }


def sign_quote_payload(payload: dict[str, str], *, secret: str | None = None) -> str:
    canonical = _canonical_json(payload)
    key = _signing_secret(secret).encode("utf-8")
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def build_signed_quote_record(
    *,
    quote_id: str,
    raw_total: Decimal | str | int | float,
    tax_total: Decimal | str | int | float,
    timestamp: str | datetime | None = None,
    secret: str | None = None,
) -> dict[str, str]:
    payload = build_canonical_quote_payload(
        quote_id=quote_id,
        raw_total=raw_total,
        tax_total=tax_total,
        timestamp=timestamp,
    )
    return {
        **payload,
        "hmac_sig": sign_quote_payload(payload, secret=secret),
    }
