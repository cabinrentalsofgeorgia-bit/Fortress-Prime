"""
OpenShell audit helpers.

Provides an append-only signed audit chain for AI/tool/data operations.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.openshell_audit import OpenShellAuditLog

logger = structlog.get_logger(service="openshell_audit")


def _utcnow_db_naive() -> datetime:
    """
    Store UTC timestamps as naive datetimes for compatibility with the current
    Postgres audit column definition (`TIMESTAMP` without timezone).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat(timespec="seconds") + "Z"
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_metadata(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, dict):
        return {str(key): _normalize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_metadata(item) for item in value]
    return value


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sign(entry_hash: str) -> str:
    key = (
        getattr(settings, "audit_log_signing_key", "")
        or settings.jwt_secret_key
        or "fortress-audit-fallback-key"
    ).encode("utf-8")
    return hmac.new(key, entry_hash.encode("utf-8"), hashlib.sha256).hexdigest()


async def _latest_entry_hash(db: AsyncSession) -> Optional[str]:
    result = await db.execute(
        select(OpenShellAuditLog.entry_hash).order_by(desc(OpenShellAuditLog.created_at)).limit(1)
    )
    return result.scalar_one_or_none()


async def _write_audit_row(
    db: AsyncSession,
    *,
    actor_id: Optional[str],
    actor_email: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    purpose: Optional[str],
    tool_name: Optional[str],
    redaction_status: str,
    model_route: Optional[str],
    outcome: str,
    request_id: Optional[str],
    metadata_json: dict[str, Any],
) -> OpenShellAuditLog:
    created_at = _utcnow_db_naive()
    normalized_metadata = _normalize_metadata(metadata_json)
    payload = {
        "actor_id": actor_id,
        "actor_email": actor_email,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "purpose": purpose,
        "tool_name": tool_name,
        "redaction_status": redaction_status,
        "model_route": model_route,
        "outcome": outcome,
        "request_id": request_id,
        "metadata_json": normalized_metadata,
        "created_at": _iso_utc(created_at),
    }
    payload_hash = _sha256(_canonical_json(payload))
    prev_hash = await _latest_entry_hash(db)
    entry_hash = _sha256(f"{payload_hash}:{prev_hash or ''}:{_iso_utc(created_at)}")
    signature = _sign(entry_hash)

    row = OpenShellAuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        purpose=purpose,
        tool_name=tool_name,
        redaction_status=redaction_status,
        model_route=model_route,
        outcome=outcome,
        request_id=request_id,
        metadata_json=normalized_metadata,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        signature=signature,
        created_at=created_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def record_audit_event(
    *,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    purpose: Optional[str] = None,
    tool_name: Optional[str] = None,
    redaction_status: str = "not_applicable",
    model_route: Optional[str] = None,
    outcome: str = "success",
    request_id: Optional[str] = None,
    metadata_json: Optional[dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
) -> Optional[OpenShellAuditLog]:
    metadata_json = metadata_json or {}
    try:
        if db is not None:
            return await _write_audit_row(
                db,
                actor_id=actor_id,
                actor_email=actor_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                purpose=purpose,
                tool_name=tool_name,
                redaction_status=redaction_status,
                model_route=model_route,
                outcome=outcome,
                request_id=request_id,
                metadata_json=metadata_json,
            )

        async with AsyncSessionLocal() as session:
            return await _write_audit_row(
                session,
                actor_id=actor_id,
                actor_email=actor_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                purpose=purpose,
                tool_name=tool_name,
                redaction_status=redaction_status,
                model_route=model_route,
                outcome=outcome,
                request_id=request_id,
                metadata_json=metadata_json,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("openshell_audit_write_failed", error=str(exc)[:400], action=action, resource_type=resource_type)
        return None
