"""
Privacy router for local-first AI requests.

If a request needs cloud fallback, payloads are redacted first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_SENSITIVE_KEYS = {
    "guest_name",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "guest_email",
    "phone",
    "guest_phone",
    "ssn",
    "tax_id",
    "reservation_id",
    "confirmation_code",
}

_NAME_KEYS = {"guest_name", "full_name", "first_name", "last_name", "name"}


@dataclass
class PrivacyRouteDecision:
    redacted_payload: Any
    redaction_status: str
    redaction_count: int
    removed_fields: list[str]


def _redact_text(value: str) -> tuple[str, int]:
    redactions = 0
    out, n = EMAIL_RE.subn("[REDACTED_EMAIL]", value)
    redactions += n
    out, n = PHONE_RE.subn("[REDACTED_PHONE]", out)
    redactions += n
    out, n = CREDIT_CARD_RE.subn("[REDACTED_CARD]", out)
    redactions += n
    return out, redactions


def _walk(payload: Any, removed_fields: list[str]) -> tuple[Any, int]:
    if isinstance(payload, dict):
        redactions = 0
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_l = key.lower()
            if key_l in _NAME_KEYS and isinstance(value, str) and value.strip():
                redacted[key] = "GUEST_ALPHA"
                removed_fields.append(key)
                redactions += 1
                continue

            if key_l in _SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
                removed_fields.append(key)
                redactions += 1
                continue
            new_value, nested = _walk(value, removed_fields)
            redacted[key] = new_value
            redactions += nested
        return redacted, redactions

    if isinstance(payload, list):
        redactions = 0
        out_list = []
        for item in payload:
            new_item, nested = _walk(item, removed_fields)
            out_list.append(new_item)
            redactions += nested
        return out_list, redactions

    if isinstance(payload, str):
        redacted_text, count = _redact_text(payload)
        return redacted_text, count

    return payload, 0


def _collect_known_names(payload: Any, names: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in _NAME_KEYS and isinstance(value, str) and value.strip():
                names.add(value.strip())
            _collect_known_names(value, names)
    elif isinstance(payload, list):
        for item in payload:
            _collect_known_names(item, names)


def _replace_known_names(payload: Any, names: set[str]) -> Any:
    if isinstance(payload, dict):
        return {k: _replace_known_names(v, names) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_replace_known_names(v, names) for v in payload]
    if isinstance(payload, str):
        out = payload
        for name in names:
            out = out.replace(name, "GUEST_ALPHA")
        return out
    return payload


def sanitize_for_cloud(payload: Any) -> PrivacyRouteDecision:
    known_names: set[str] = set()
    _collect_known_names(payload, known_names)
    removed_fields: list[str] = []
    redacted_payload, redaction_count = _walk(payload, removed_fields)
    if known_names:
        redacted_payload = _replace_known_names(redacted_payload, known_names)
    status = "redacted" if redaction_count > 0 or removed_fields else "clean"
    return PrivacyRouteDecision(
        redacted_payload=redacted_payload,
        redaction_status=status,
        redaction_count=redaction_count,
        removed_fields=sorted(set(removed_fields)),
    )
