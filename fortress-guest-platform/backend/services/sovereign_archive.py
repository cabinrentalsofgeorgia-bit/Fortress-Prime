"""
Deterministic helpers for signed sovereign archive records.

These records represent historical content snapshots that can be rendered by
the frontend without invoking generative systems at request time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any

from backend.core.config import settings

UTC_ISO_Z_SUFFIX = "Z"


def _normalize_timestamp(timestamp: str | datetime | None = None) -> str:
    if timestamp is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", UTC_ISO_Z_SUFFIX)
    if isinstance(timestamp, datetime):
        dt = timestamp.astimezone(timezone.utc).replace(microsecond=0)
        return dt.isoformat().replace("+00:00", UTC_ISO_Z_SUFFIX)
    text = timestamp.strip()
    if not text:
        raise ValueError("timestamp cannot be blank")
    return text if text.endswith(UTC_ISO_Z_SUFFIX) else text


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signing_secret(explicit_secret: str | None = None) -> str:
    return (
        explicit_secret
        or getattr(settings, "audit_log_signing_key", "")
        or settings.jwt_secret_key
        or settings.secret_key
        or "fortress-sovereign-archive-fallback-key"
    )


def build_canonical_archive_payload(
    *,
    legacy_node_id: str | int,
    original_slug: str,
    content_body: str,
    category_tags: list[str],
    title: str | None = None,
    archive_slug: str | None = None,
    archive_path: str | None = None,
    source_ref: str | None = None,
    node_type: str = "testimonial",
    legacy_type: str | None = None,
    legacy_created_at: int | None = None,
    legacy_updated_at: int | None = None,
    legacy_author_id: str | int | None = None,
    legacy_language: str | None = None,
    related_property_slug: str | None = None,
    related_property_path: str | None = None,
    related_property_title: str | None = None,
    body_status: str = "verified",
    signed_at: str | datetime | None = None,
) -> dict[str, Any]:
    node_id = str(legacy_node_id).strip()
    slug = original_slug.strip()
    if not node_id:
        raise ValueError("legacy_node_id is required")
    if not slug:
        raise ValueError("original_slug is required")

    normalized_tags = sorted({str(tag).strip() for tag in category_tags if str(tag).strip()})
    payload: dict[str, Any] = {
        "legacy_node_id": node_id,
        "original_slug": slug,
        "content_body": content_body.strip(),
        "category_tags": normalized_tags,
        "node_type": node_type.strip() or "testimonial",
        "body_status": body_status.strip() or "verified",
        "signed_at": _normalize_timestamp(signed_at),
    }
    if legacy_type and legacy_type.strip():
        payload["legacy_type"] = legacy_type.strip()
    if title and title.strip():
        payload["title"] = title.strip()
    if archive_slug and archive_slug.strip():
        payload["archive_slug"] = archive_slug.strip()
    if archive_path and archive_path.strip():
        payload["archive_path"] = archive_path.strip()
    if source_ref and source_ref.strip():
        payload["source_ref"] = source_ref.strip()
    if legacy_created_at is not None:
        payload["legacy_created_at"] = int(legacy_created_at)
    if legacy_updated_at is not None:
        payload["legacy_updated_at"] = int(legacy_updated_at)
    if legacy_author_id is not None and str(legacy_author_id).strip():
        payload["legacy_author_id"] = str(legacy_author_id).strip()
    if legacy_language and legacy_language.strip():
        payload["legacy_language"] = legacy_language.strip()
    if related_property_slug and related_property_slug.strip():
        payload["related_property_slug"] = related_property_slug.strip()
    if related_property_path and related_property_path.strip():
        payload["related_property_path"] = related_property_path.strip()
    if related_property_title and related_property_title.strip():
        payload["related_property_title"] = related_property_title.strip()
    return payload


def sign_archive_payload(payload: dict[str, Any], *, secret: str | None = None) -> str:
    canonical = _canonical_json(payload)
    key = _signing_secret(secret).encode("utf-8")
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def build_signed_archive_record(
    *,
    legacy_node_id: str | int,
    original_slug: str,
    content_body: str,
    category_tags: list[str],
    title: str | None = None,
    archive_slug: str | None = None,
    archive_path: str | None = None,
    source_ref: str | None = None,
    node_type: str = "testimonial",
    legacy_type: str | None = None,
    legacy_created_at: int | None = None,
    legacy_updated_at: int | None = None,
    legacy_author_id: str | int | None = None,
    legacy_language: str | None = None,
    related_property_slug: str | None = None,
    related_property_path: str | None = None,
    related_property_title: str | None = None,
    body_status: str = "verified",
    signed_at: str | datetime | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    payload = build_canonical_archive_payload(
        legacy_node_id=legacy_node_id,
        original_slug=original_slug,
        content_body=content_body,
        category_tags=category_tags,
        title=title,
        archive_slug=archive_slug,
        archive_path=archive_path,
        source_ref=source_ref,
        node_type=node_type,
        legacy_type=legacy_type,
        legacy_created_at=legacy_created_at,
        legacy_updated_at=legacy_updated_at,
        legacy_author_id=legacy_author_id,
        legacy_language=legacy_language,
        related_property_slug=related_property_slug,
        related_property_path=related_property_path,
        related_property_title=related_property_title,
        body_status=body_status,
        signed_at=signed_at,
    )
    return {
        **payload,
        "hmac_signature": sign_archive_payload(payload, secret=secret),
    }
