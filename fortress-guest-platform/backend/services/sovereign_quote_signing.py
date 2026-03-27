"""
HMAC-SHA256 sealing for sovereign checkout quotes.

The message is the canonical JSON of all fields except ``signature``, sorted keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_signing_bytes(payload_without_signature: dict[str, Any]) -> bytes:
    """Stable UTF-8 JSON for HMAC input."""
    return json.dumps(
        payload_without_signature,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def compute_quote_hmac(payload_without_signature: dict[str, Any], secret: str) -> str:
    if not secret.strip():
        return ""
    digest = hmac.new(
        secret.encode("utf-8"),
        canonical_signing_bytes(payload_without_signature),
        hashlib.sha256,
    ).hexdigest()
    return digest


def build_signed_quote(
    payload_without_signature: dict[str, Any],
    secret: str,
) -> dict[str, Any]:
    """Return payload with ``signature`` field (empty digest when secret unset)."""
    sig = compute_quote_hmac(payload_without_signature, secret)
    return {**payload_without_signature, "signature": sig}


def verify_signed_quote(full_payload: dict[str, Any], secret: str) -> bool:
    if not secret.strip():
        return False
    sig = full_payload.get("signature")
    if not sig or not isinstance(sig, str):
        return False
    body = {k: v for k, v in full_payload.items() if k != "signature"}
    expected = compute_quote_hmac(body, secret)
    return hmac.compare_digest(expected, sig)
