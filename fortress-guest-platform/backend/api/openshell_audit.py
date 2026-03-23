"""
OpenShell audit log inspection endpoints.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.openshell_audit import OpenShellAuditLog

router = APIRouter()


class OpenShellAuditOut(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: Optional[str]
    tool_name: Optional[str]
    redaction_status: str
    model_route: Optional[str]
    outcome: str
    request_id: Optional[str]
    created_at: str
    entry_hash: str
    prev_hash: Optional[str]
    signature: str
    metadata_json: dict


class ShadowAuditTraceOut(BaseModel):
    trace_id: str
    quote_id: Optional[str]
    created_at: str
    drift_status: str
    legacy_total: float
    sovereign_total: float
    total_drift_pct: float
    tax_delta: float
    base_rate_drift_pct: float
    hmac_signature: Optional[str]


class ShadowAuditSummaryOut(BaseModel):
    status: str
    gate_target: int
    gate_completed: int
    gate_progress: str
    accuracy_rate: float
    tax_accuracy_rate: float
    avg_base_drift_pct: float
    critical_mismatch_count: int
    kill_switch_armed: bool
    spark_node_2_status: str
    recent_traces: list[ShadowAuditTraceOut]


class HistoricalRecoverySlugOut(BaseModel):
    slug: str
    count: int


class HistoricalRecoverySummaryOut(BaseModel):
    window_hours: int
    total_events: int
    total_resurrections: int
    soft_landed_losses: int
    valid_signature_count: int
    signature_health_pct: float
    top_recovered_slugs: list[HistoricalRecoverySlugOut]
    top_soft_landed_slugs: list[HistoricalRecoverySlugOut]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _total_drift_pct(legacy_total: float, sovereign_total: float) -> float:
    if legacy_total <= 0:
        return 0.0
    return abs(((sovereign_total - legacy_total) / legacy_total) * 100.0)


def summarize_shadow_audits(
    rows: list[OpenShellAuditLog],
    *,
    now: datetime | None = None,
) -> ShadowAuditSummaryOut:
    total = len(rows)
    gate_target = 100
    now = now or datetime.now(timezone.utc)

    traces: list[ShadowAuditTraceOut] = []
    exact_matches = 0
    tax_matches = 0
    critical_mismatches = 0
    drift_values: list[float] = []
    kill_switch_armed = False

    for row in rows[:10]:
        meta = row.metadata_json or {}
        legacy_total = _to_float(meta.get("legacy_total"))
        sovereign_total = _to_float(meta.get("sovereign_total"))
        total_drift_pct = _total_drift_pct(legacy_total, sovereign_total)
        trace = ShadowAuditTraceOut(
            trace_id=str(meta.get("trace_id") or row.resource_id or row.id),
            quote_id=str(meta.get("quote_id")) if meta.get("quote_id") else None,
            created_at=row.created_at.isoformat(),
            drift_status=str(meta.get("drift_status") or "UNKNOWN"),
            legacy_total=legacy_total,
            sovereign_total=sovereign_total,
            total_drift_pct=round(total_drift_pct, 4),
            tax_delta=round(_to_float(meta.get("tax_delta")), 4),
            base_rate_drift_pct=round(_to_float(meta.get("base_rate_drift_pct")), 4),
            hmac_signature=str(meta.get("hmac_signature")) if meta.get("hmac_signature") else None,
        )
        traces.append(trace)

    for row in rows:
        meta = row.metadata_json or {}
        drift_status = str(meta.get("drift_status") or "UNKNOWN")
        tax_delta = abs(_to_float(meta.get("tax_delta")))
        base_rate_drift_pct = abs(_to_float(meta.get("base_rate_drift_pct")))
        legacy_total = _to_float(meta.get("legacy_total"))
        sovereign_total = _to_float(meta.get("sovereign_total"))
        total_drift_pct = _total_drift_pct(legacy_total, sovereign_total)

        drift_values.append(base_rate_drift_pct)
        if drift_status == "MATCH":
            exact_matches += 1
        if tax_delta == 0.0:
            tax_matches += 1
        if drift_status == "CRITICAL_MISMATCH":
            critical_mismatches += 1
        if drift_status == "CRITICAL_MISMATCH" or total_drift_pct > 5.0:
            kill_switch_armed = True

    avg_base_drift_pct = round(sum(drift_values) / total, 4) if total else 0.0

    if rows and rows[0].created_at >= now - timedelta(minutes=10):
        spark_node_2_status = "online"
    elif rows:
        spark_node_2_status = "idle"
    else:
        spark_node_2_status = "unknown"

    status = "alert" if kill_switch_armed else "active" if total else "cold_start"

    return ShadowAuditSummaryOut(
        status=status,
        gate_target=gate_target,
        gate_completed=min(total, gate_target),
        gate_progress=f"{min(total, gate_target)}/{gate_target}",
        accuracy_rate=round(exact_matches / total, 4) if total else 0.0,
        tax_accuracy_rate=round(tax_matches / total, 4) if total else 0.0,
        avg_base_drift_pct=avg_base_drift_pct,
        critical_mismatch_count=critical_mismatches,
        kill_switch_armed=kill_switch_armed,
        spark_node_2_status=spark_node_2_status,
        recent_traces=traces,
    )


def _leaderboard(counter: Counter[str], *, limit: int = 5) -> list[HistoricalRecoverySlugOut]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [HistoricalRecoverySlugOut(slug=slug, count=count) for slug, count in ranked[:limit] if slug]


def summarize_historical_recovery(
    rows: list[OpenShellAuditLog],
    *,
    window_hours: int = 24,
) -> HistoricalRecoverySummaryOut:
    relevant_rows = [
        row
        for row in rows
        if str(getattr(row, "outcome", "") or "").lower() in {"restored", "cache_hit", "soft_landed"}
    ]

    recovered_counter: Counter[str] = Counter()
    soft_landed_counter: Counter[str] = Counter()
    total_resurrections = 0
    soft_landed_losses = 0
    valid_signature_count = 0

    for row in relevant_rows:
        meta = row.metadata_json or {}
        outcome = str(row.outcome or "").lower()
        slug = str(meta.get("slug") or row.resource_id or "").strip()
        signature_valid = bool(meta.get("signature_valid"))

        if outcome in {"restored", "cache_hit"}:
            total_resurrections += 1
            if slug:
                recovered_counter[slug] += 1
        elif outcome == "soft_landed":
            soft_landed_losses += 1
            if slug:
                soft_landed_counter[slug] += 1

        if signature_valid:
            valid_signature_count += 1

    total_events = len(relevant_rows)
    signature_health_pct = round((valid_signature_count / total_events) * 100.0, 2) if total_events else 0.0

    return HistoricalRecoverySummaryOut(
        window_hours=window_hours,
        total_events=total_events,
        total_resurrections=total_resurrections,
        soft_landed_losses=soft_landed_losses,
        valid_signature_count=valid_signature_count,
        signature_health_pct=signature_health_pct,
        top_recovered_slugs=_leaderboard(recovered_counter),
        top_soft_landed_slugs=_leaderboard(soft_landed_counter),
    )


@router.get("/log", response_model=list[OpenShellAuditOut])
async def list_openshell_audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OpenShellAuditLog).order_by(desc(OpenShellAuditLog.created_at)).limit(limit)
    if resource_type:
        stmt = stmt.where(OpenShellAuditLog.resource_type == resource_type.strip())
    if resource_id:
        stmt = stmt.where(OpenShellAuditLog.resource_id == resource_id.strip())
    if action:
        stmt = stmt.where(OpenShellAuditLog.action == action.strip())
    rows = (await db.execute(stmt)).scalars().all()

    return [
        OpenShellAuditOut(
            id=str(row.id),
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            tool_name=row.tool_name,
            redaction_status=row.redaction_status,
            model_route=row.model_route,
            outcome=row.outcome,
            request_id=row.request_id,
            created_at=row.created_at.isoformat(),
            entry_hash=row.entry_hash,
            prev_hash=row.prev_hash,
            signature=row.signature,
            metadata_json=row.metadata_json or {},
        )
        for row in rows
    ]


@router.get("/shadow-summary", response_model=ShadowAuditSummaryOut)
async def get_shadow_summary(
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(OpenShellAuditLog)
            .where(OpenShellAuditLog.resource_type == "shadow_quote_audit")
            .order_by(desc(OpenShellAuditLog.created_at))
            .limit(100)
        )
    ).scalars().all()

    return summarize_shadow_audits(rows)


@router.get("/historical-recovery-summary", response_model=HistoricalRecoverySummaryOut)
async def get_historical_recovery_summary(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
):
    window_start = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(OpenShellAuditLog)
            .where(OpenShellAuditLog.resource_type == "historical_archive")
            .where(OpenShellAuditLog.created_at >= window_start)
            .order_by(desc(OpenShellAuditLog.created_at))
        )
    ).scalars().all()

    return summarize_historical_recovery(rows, window_hours=hours)
