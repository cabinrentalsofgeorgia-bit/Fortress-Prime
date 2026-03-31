"""
Emit deduplicated backend-side Channex attention signals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.event_publisher import EventPublisher
from backend.integrations.twilio_client import TwilioClient
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.staff import StaffUser
from backend.services.email_service import send_email
from backend.services.channex_health import ChannexHealthResponse
from backend.services.openshell_audit import record_audit_event

ATTENTION_ACTION = "admin.channex.attention_signal"
ATTENTION_RESOURCE_ID = "fleet"


class ChannexAttentionSummary(BaseModel):
    recent: bool
    last_alert_at: str | None = None
    request_id: str | None = None
    property_count: int | None = None
    healthy_count: int | None = None
    catalog_ready_count: int | None = None
    ari_ready_count: int | None = None
    duplicate_rate_plan_count: int | None = None
    reasons: list[str]


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return None


def build_attention_reasons(snapshot: ChannexHealthResponse) -> list[str]:
    reasons: list[str] = []
    if snapshot.healthy_count < snapshot.property_count:
        reasons.append(f"{snapshot.property_count - snapshot.healthy_count} properties are not healthy")
    if snapshot.duplicate_rate_plan_count > 0:
        reasons.append(f"{snapshot.duplicate_rate_plan_count} duplicate rate plans detected")
    if snapshot.ari_ready_count < snapshot.property_count:
        reasons.append(f"{snapshot.property_count - snapshot.ari_ready_count} properties are missing ARI coverage")
    return reasons


def build_attention_fingerprint(snapshot: ChannexHealthResponse) -> str:
    return "|".join(
        [
            str(snapshot.property_count),
            str(snapshot.healthy_count),
            str(snapshot.catalog_ready_count),
            str(snapshot.ari_ready_count),
            str(snapshot.duplicate_rate_plan_count),
        ]
    )


async def emit_channex_attention_signal_if_needed(
    db: AsyncSession,
    *,
    actor_id: str | None,
    actor_email: str | None,
    request_id: str | None,
    snapshot: ChannexHealthResponse,
) -> bool:
    reasons = build_attention_reasons(snapshot)
    if not reasons:
        return False

    fingerprint = build_attention_fingerprint(snapshot)
    window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
    stmt = (
        select(OpenShellAuditLog)
        .where(OpenShellAuditLog.action == ATTENTION_ACTION)
        .where(OpenShellAuditLog.resource_id == ATTENTION_RESOURCE_ID)
        .where(OpenShellAuditLog.created_at >= window_start)
        .order_by(desc(OpenShellAuditLog.created_at))
        .limit(5)
    )
    rows = (await db.execute(stmt)).scalars().all()
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if str(meta.get("fingerprint") or "") == fingerprint:
            return False

    payload = {
        "resource_id": ATTENTION_RESOURCE_ID,
        "fingerprint": fingerprint,
        "property_count": snapshot.property_count,
        "healthy_count": snapshot.healthy_count,
        "catalog_ready_count": snapshot.catalog_ready_count,
        "ari_ready_count": snapshot.ari_ready_count,
        "duplicate_rate_plan_count": snapshot.duplicate_rate_plan_count,
        "reasons": reasons,
    }
    await EventPublisher.publish("ops.channex.attention_required", payload, key=ATTENTION_RESOURCE_ID)
    await record_audit_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action=ATTENTION_ACTION,
        resource_type="channex_inventory",
        resource_id=ATTENTION_RESOURCE_ID,
        purpose="emit backend channex attention signal",
        outcome="attention_required",
        request_id=request_id,
        metadata_json=payload,
        db=db,
    )
    await _notify_urgent_staff_of_channex_attention(db, payload)
    return True


async def get_latest_channex_attention_summary(
    db: AsyncSession,
    *,
    recent_hours: int = 24,
) -> ChannexAttentionSummary | None:
    stmt = (
        select(OpenShellAuditLog)
        .where(OpenShellAuditLog.action == ATTENTION_ACTION)
        .where(OpenShellAuditLog.resource_id == ATTENTION_RESOURCE_ID)
        .order_by(desc(OpenShellAuditLog.created_at))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recent = row.created_at >= (now - timedelta(hours=recent_hours))
    return ChannexAttentionSummary(
        recent=recent,
        last_alert_at=row.created_at.isoformat(),
        request_id=row.request_id,
        property_count=_int(metadata.get("property_count")),
        healthy_count=_int(metadata.get("healthy_count")),
        catalog_ready_count=_int(metadata.get("catalog_ready_count")),
        ari_ready_count=_int(metadata.get("ari_ready_count")),
        duplicate_rate_plan_count=_int(metadata.get("duplicate_rate_plan_count")),
        reasons=[str(item) for item in metadata.get("reasons", []) if str(item).strip()],
    )


async def _notify_urgent_staff_of_channex_attention(db: AsyncSession, payload: dict[str, object]) -> None:
    reasons = [str(item) for item in payload.get("reasons", []) if str(item).strip()]
    summary = " • ".join(reasons) if reasons else "Channex fleet health requires review."
    subject = "Channex Attention Required"
    html_body = (
        "<p><strong>Channex Attention Required</strong></p>"
        f"<p>{summary}</p>"
        f"<p>Healthy properties: {payload.get('healthy_count')} / {payload.get('property_count')}</p>"
        f"<p>Catalog ready: {payload.get('catalog_ready_count')} | "
        f"ARI ready: {payload.get('ari_ready_count')} | "
        f"Duplicate rate plans: {payload.get('duplicate_rate_plan_count')}</p>"
    )
    text_body = (
        "Channex Attention Required\n\n"
        f"{summary}\n\n"
        f"Healthy properties: {payload.get('healthy_count')} / {payload.get('property_count')}\n"
        f"Catalog ready: {payload.get('catalog_ready_count')}\n"
        f"ARI ready: {payload.get('ari_ready_count')}\n"
        f"Duplicate rate plans: {payload.get('duplicate_rate_plan_count')}\n"
    )

    staff_result = await db.execute(
        select(StaffUser).where(
            and_(
                StaffUser.is_active == True,  # noqa: E712
                StaffUser.notify_urgent == True,  # noqa: E712
            )
        )
    )
    staff_members = list(staff_result.scalars().all())

    emails = [staff.notification_email for staff in staff_members if staff.notification_email]
    phones = [staff.notification_phone for staff in staff_members if staff.notification_phone]

    if not emails and settings.staff_notification_email:
        emails.append(settings.staff_notification_email)
    if not phones and settings.staff_notification_phone:
        phones.append(settings.staff_notification_phone)

    for email in sorted(set(emails)):
        send_email(
            to=email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    if phones:
        twilio = TwilioClient()
        sms_body = (
            "ALERT [CHANNEX] Fleet attention required.\n"
            f"{summary}\n"
            f"Healthy {payload.get('healthy_count')}/{payload.get('property_count')} | "
            f"ARI {payload.get('ari_ready_count')} | "
            f"Duplicates {payload.get('duplicate_rate_plan_count')}"
        )
        for phone in sorted(set(phones)):
            try:
                await twilio.send_sms(to=phone, body=sms_body)
            except Exception:
                continue
