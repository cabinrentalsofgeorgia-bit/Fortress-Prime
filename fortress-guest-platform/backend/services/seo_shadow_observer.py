"""
SEMRush Shadow Parallel observer for sovereign-vs-legacy SEO parity.

Reads a local SEMRush-style snapshot from sovereign storage, compares it against
the latest sovereign SEO patch scores, and can persist observation traces into
OpenShell audit logs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger(service="seo_shadow_observer")


class SEMRushSnapshotEntry(BaseModel):
    page_path: str
    property_slug: str | None = None
    legacy_score: float = Field(ge=0.0, le=100.0)
    legacy_rank: int | None = None
    legacy_traffic: float | None = None
    keyword: str | None = None
    observed_at: datetime | None = None


class SEMRushSnapshot(BaseModel):
    source: str = "semrush"
    observed_at: datetime | None = None
    pages: list[SEMRushSnapshotEntry]
    snapshot_path: str | None = None


@dataclass
class SEOParityTrace:
    trace_id: str
    page_path: str
    property_slug: str | None
    legacy_score: float
    sovereign_score: float
    uplift_pct_points: float
    legacy_rank: int | None
    legacy_traffic: float | None
    keyword: str | None
    status: str
    observed_at: datetime


class ShadowSeoTracePayload(BaseModel):
    trace_id: str
    page_path: str
    property_slug: str | None = None
    observed_at: str
    status: str
    legacy_score: float
    sovereign_score: float
    uplift_pct_points: float
    legacy_rank: int | None = None
    legacy_traffic: float | None = None
    keyword: str | None = None


class ShadowSeoSummaryPayload(BaseModel):
    status: str
    source: str
    snapshot_path: str | None = None
    observed_count: int
    superior_count: int
    parity_count: int
    trailing_count: int
    missing_sovereign_count: int
    avg_legacy_score: float
    avg_sovereign_score: float
    avg_uplift_pct_points: float
    last_observed_at: str | None = None
    recent_traces: list[ShadowSeoTracePayload]


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any, *, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_page_path(raw_path: str | None, raw_slug: str | None) -> str:
    if raw_path:
        path = raw_path.strip()
        if path.startswith("http://") or path.startswith("https://"):
            suffix = path.split("/", 3)[-1] if "/" in path[8:] else ""
            path = f"/{suffix}" if suffix else "/"
        if not path.startswith("/"):
            path = f"/{path}"
        return path.rstrip("/") or "/"
    if raw_slug:
        slug = raw_slug.strip().strip("/")
        return f"/cabins/{slug}" if slug else "/"
    raise ValueError("Snapshot row requires page_path or property_slug.")


def load_semrush_snapshot(snapshot_path: str | Path | None = None) -> SEMRushSnapshot | None:
    resolved_path = Path(snapshot_path or settings.semrush_shadow_snapshot_path).expanduser()
    if not resolved_path.exists():
        return None

    raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw_pages = raw.get("pages") or raw.get("entries") or []
        if not isinstance(raw_pages, list):
            raise ValueError("SEMRush snapshot pages must be a list.")
        observed_at = _parse_datetime(raw.get("observed_at"))
        entries: list[SEMRushSnapshotEntry] = []
        for item in raw_pages:
            if not isinstance(item, dict):
                continue
            property_slug = str(item.get("property_slug") or item.get("slug") or "").strip() or None
            page_path = _normalize_page_path(
                str(item.get("page_path") or item.get("path") or "").strip() or None,
                property_slug,
            )
            legacy_score = _coerce_float(
                item.get("legacy_score", item.get("semrush_score", item.get("score"))),
                default=None,
            )
            if legacy_score is None:
                continue
            item_observed_at = _parse_datetime(item.get("observed_at")) or observed_at
            entries.append(
                SEMRushSnapshotEntry(
                    page_path=page_path,
                    property_slug=property_slug,
                    legacy_score=max(0.0, min(float(legacy_score), 100.0)),
                    legacy_rank=_coerce_int(item.get("legacy_rank", item.get("rank"))),
                    legacy_traffic=_coerce_float(item.get("legacy_traffic", item.get("traffic"))),
                    keyword=str(item.get("keyword")).strip() if item.get("keyword") else None,
                    observed_at=item_observed_at,
                )
            )
        return SEMRushSnapshot(
            source=str(raw.get("source") or "semrush"),
            observed_at=observed_at,
            pages=entries,
            snapshot_path=str(resolved_path),
        )

    raise ValueError("SEMRush snapshot must decode to an object.")


def _derive_trace_status(legacy_score: float, sovereign_score: float) -> str:
    uplift = sovereign_score - legacy_score
    if sovereign_score <= 0:
        return "missing_sovereign"
    if uplift >= 5.0:
        return "superior"
    if uplift <= -5.0:
        return "trailing"
    return "parity"


async def _latest_patch_by_path(db: AsyncSession) -> dict[str, tuple[SEOPatch, Property | None]]:
    rows = (
        await db.execute(
            select(SEOPatch, Property)
            .outerjoin(Property, SEOPatch.property_id == Property.id)
            .order_by(SEOPatch.page_path.asc(), SEOPatch.updated_at.desc())
        )
    ).all()
    latest: dict[str, tuple[SEOPatch, Property | None]] = {}
    for patch, property_record in rows:
        latest.setdefault(patch.page_path.rstrip("/") or "/", (patch, property_record))
    return latest


def _sovereign_score_for_patch(patch: SEOPatch | None) -> float:
    if patch is None:
        return 0.0
    if patch.godhead_score is not None:
        return round(float(patch.godhead_score) * 100.0, 2)
    if patch.status == "deployed":
        return 100.0
    if patch.status == "pending_human":
        return round(float(settings.seo_godhead_min_score) * 100.0, 2)
    return 0.0


def summarize_seo_parity_traces(
    traces: list[SEOParityTrace],
    *,
    source: str = "semrush",
    snapshot_path: str | None = None,
) -> ShadowSeoSummaryPayload:
    total = len(traces)
    superior = sum(1 for trace in traces if trace.status == "superior")
    parity = sum(1 for trace in traces if trace.status == "parity")
    trailing = sum(1 for trace in traces if trace.status == "trailing")
    missing = sum(1 for trace in traces if trace.status == "missing_sovereign")
    avg_legacy = round(sum(trace.legacy_score for trace in traces) / total, 2) if total else 0.0
    avg_sovereign = round(sum(trace.sovereign_score for trace in traces) / total, 2) if total else 0.0
    avg_uplift = round(sum(trace.uplift_pct_points for trace in traces) / total, 2) if total else 0.0
    last_observed = max((trace.observed_at for trace in traces), default=None)

    if total == 0:
        status = "cold_start"
    elif missing == total:
        status = "no_sovereign"
    elif trailing > 0:
        status = "trailing"
    elif superior > 0:
        status = "observing"
    else:
        status = "parity"

    recent_traces = [
        ShadowSeoTracePayload(
            trace_id=trace.trace_id,
            page_path=trace.page_path,
            property_slug=trace.property_slug,
            observed_at=trace.observed_at.isoformat(),
            status=trace.status,
            legacy_score=trace.legacy_score,
            sovereign_score=trace.sovereign_score,
            uplift_pct_points=trace.uplift_pct_points,
            legacy_rank=trace.legacy_rank,
            legacy_traffic=trace.legacy_traffic,
            keyword=trace.keyword,
        )
        for trace in sorted(traces, key=lambda item: item.observed_at, reverse=True)[:10]
    ]

    return ShadowSeoSummaryPayload(
        status=status,
        source=source,
        snapshot_path=snapshot_path,
        observed_count=total,
        superior_count=superior,
        parity_count=parity,
        trailing_count=trailing,
        missing_sovereign_count=missing,
        avg_legacy_score=avg_legacy,
        avg_sovereign_score=avg_sovereign,
        avg_uplift_pct_points=avg_uplift,
        last_observed_at=last_observed.isoformat() if last_observed else None,
        recent_traces=recent_traces,
    )


async def observe_semrush_parity(
    db: AsyncSession,
    *,
    snapshot_path: str | Path | None = None,
    persist_audit: bool = False,
    request_id: str | None = None,
) -> ShadowSeoSummaryPayload:
    if not settings.agentic_system_active:
        return ShadowSeoSummaryPayload(
            status="inactive",
            source="semrush",
            snapshot_path=str(snapshot_path or settings.semrush_shadow_snapshot_path),
            observed_count=0,
            superior_count=0,
            parity_count=0,
            trailing_count=0,
            missing_sovereign_count=0,
            avg_legacy_score=0.0,
            avg_sovereign_score=0.0,
            avg_uplift_pct_points=0.0,
            last_observed_at=None,
            recent_traces=[],
        )

    snapshot = load_semrush_snapshot(snapshot_path)
    if snapshot is None:
        return ShadowSeoSummaryPayload(
            status="no_snapshot",
            source="semrush",
            snapshot_path=str(snapshot_path or settings.semrush_shadow_snapshot_path),
            observed_count=0,
            superior_count=0,
            parity_count=0,
            trailing_count=0,
            missing_sovereign_count=0,
            avg_legacy_score=0.0,
            avg_sovereign_score=0.0,
            avg_uplift_pct_points=0.0,
            last_observed_at=None,
            recent_traces=[],
        )

    latest_patches = await _latest_patch_by_path(db)
    traces: list[SEOParityTrace] = []
    snapshot_observed_at = snapshot.observed_at or datetime.now(timezone.utc)

    for entry in snapshot.pages:
        patch_pair = latest_patches.get(entry.page_path.rstrip("/") or "/")
        patch = patch_pair[0] if patch_pair else None
        property_record = patch_pair[1] if patch_pair else None
        sovereign_score = _sovereign_score_for_patch(patch)
        observed_at = entry.observed_at or snapshot_observed_at
        status = _derive_trace_status(entry.legacy_score, sovereign_score)
        trace = SEOParityTrace(
            trace_id=str(uuid4()),
            page_path=entry.page_path,
            property_slug=entry.property_slug or (property_record.slug if property_record else None),
            legacy_score=round(entry.legacy_score, 2),
            sovereign_score=round(sovereign_score, 2),
            uplift_pct_points=round(sovereign_score - entry.legacy_score, 2),
            legacy_rank=entry.legacy_rank,
            legacy_traffic=entry.legacy_traffic,
            keyword=entry.keyword,
            status=status,
            observed_at=observed_at,
        )
        traces.append(trace)

        if persist_audit:
            await record_audit_event(
                action="shadow.seo.audit.write",
                resource_type="shadow_seo_audit",
                resource_id=trace.trace_id,
                purpose="shadow_mode_validation",
                tool_name="observe_semrush_parity",
                model_route="local_cluster",
                outcome="success" if status in {"superior", "parity"} else "warning",
                request_id=request_id,
                metadata_json={
                    "trace_id": trace.trace_id,
                    "legacy_system": "semrush",
                    "page_path": trace.page_path,
                    "property_slug": trace.property_slug,
                    "legacy_score": trace.legacy_score,
                    "sovereign_score": trace.sovereign_score,
                    "uplift_pct_points": trace.uplift_pct_points,
                    "legacy_rank": trace.legacy_rank,
                    "legacy_traffic": trace.legacy_traffic,
                    "keyword": trace.keyword,
                    "status": trace.status,
                    "observed_at": trace.observed_at.isoformat(),
                    "snapshot_path": snapshot.snapshot_path,
                    "patch_status": patch.status if patch else None,
                    "patch_id": str(patch.id) if patch else None,
                },
                db=db,
            )

    summary = summarize_seo_parity_traces(
        traces,
        source=snapshot.source,
        snapshot_path=snapshot.snapshot_path,
    )
    logger.info(
        "semrush_shadow_observation_completed",
        observed_count=summary.observed_count,
        superior_count=summary.superior_count,
        parity_count=summary.parity_count,
        trailing_count=summary.trailing_count,
        missing_sovereign_count=summary.missing_sovereign_count,
        persist_audit=persist_audit,
    )
    return summary
