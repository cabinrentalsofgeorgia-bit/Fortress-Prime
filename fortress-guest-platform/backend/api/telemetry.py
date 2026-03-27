"""Telemetry aggregation API for the Fortress Prime command dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.openshell_audit import (
    HistoricalRecoverySummaryOut,
    ShadowAuditSummaryOut,
    ShadowSeoSummaryOut,
    summarize_historical_recovery,
    summarize_shadow_audits,
)
from backend.api.command_c2 import build_pulse_response
from backend.api.system_health import build_system_health_payload
from backend.core.config import settings
from backend.core.database import get_db, get_session_factory
from backend.core.security import (
    RoleChecker,
    load_staff_user_from_token_string,
    staff_allowed_for_system_health_stream,
)
from backend.models.async_job import AsyncJobRun
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.recovery_parity_comparison import RecoveryParityComparison
from backend.models.message import Message
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.reservation_hold import ReservationHold
from backend.models.seo_patch import SEOPatch
from backend.models.staff import StaffRole, StaffUser
from backend.services.agentic_orchestrator import AgenticOrchestrator
from backend.services.async_jobs import count_jobs_by_status
from backend.services.funnel_analytics_service import DROP_OFF_POINT_LABELS
from backend.services.intelligence_projection import (
    build_intelligence_feed_snapshot,
    load_scout_alpha_metrics,
)
from backend.services.seo_shadow_observer import observe_semrush_parity

logger = structlog.get_logger()

router = APIRouter()
orchestrator = AgenticOrchestrator()


class AgentStatusPayload(BaseModel):
    concierge: str
    seo_swarm: str
    yield_engine: str


class RecentCommunicationPayload(BaseModel):
    id: str
    direction: str
    phone_number: str
    snippet: str
    timestamp: datetime


class TelemetryDashboardPayload(BaseModel):
    seo_queue_depth: int
    seo_deploy_queue_depth: int
    seo_failed_deploys: int
    seo_last_deploy_success_at: datetime | None = None
    seo_last_deploy_failure_at: datetime | None = None
    recent_comms: list[RecentCommunicationPayload]
    active_holds: int
    agent_status: AgentStatusPayload


class ShadowModePayload(BaseModel):
    active: bool
    status: str
    legacy_authority: str
    message: str


class LegacyTargetScorecardPayload(BaseModel):
    target_id: str
    label: str
    legacy_system: str
    status: str
    legacy_authority: bool
    observed_count: int
    score_pct: float | None = None
    last_observed_at: datetime | None = None
    proof: str


class AgenticObservationPayload(BaseModel):
    system_active: bool
    orchestrator_status: str
    automation_rate_pct: float
    total_messages: int
    escalated_to_human: int
    avg_ai_confidence: float
    lanes: AgentStatusPayload
    generated_at: str


class SeoObserverStatusPayload(BaseModel):
    enabled: bool
    agentic_system_active: bool
    interval_seconds: int
    queue_depth: int
    running_jobs: int
    last_job_status: str
    last_job_created_at: datetime | None = None
    last_job_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_audit_at: datetime | None = None


class QuoteObserverStatusPayload(BaseModel):
    agentic_system_active: bool
    queue_depth: int
    running_jobs: int
    last_job_status: str
    last_job_created_at: datetime | None = None
    last_job_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_audit_at: datetime | None = None
    last_drift_status: str | None = None
    last_quote_id: str | None = None


class SeoObserverRunPayload(BaseModel):
    job_id: str
    trigger_mode: str
    status: str
    requested_by: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    observed_count: int | None = None
    superior_count: int | None = None
    error: str | None = None
    async_job_href: str
    audit_log_href: str


class ScoutObserverStatusPayload(BaseModel):
    enabled: bool
    agentic_system_active: bool
    interval_seconds: int
    queue_depth: int
    running_jobs: int
    last_job_status: str
    last_job_created_at: datetime | None = None
    last_job_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_discovery_at: datetime | None = None
    last_inserted_count: int = 0
    last_duplicate_count: int = 0
    last_seo_draft_count: int = 0
    last_pricing_signal_count: int = 0


class ConciergeAlphaObserverStatusPayload(BaseModel):
    enabled: bool
    agentic_system_active: bool
    interval_seconds: int
    queue_depth: int
    running_jobs: int
    last_job_status: str
    last_job_created_at: datetime | None = None
    last_job_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_candidates_considered: int = 0
    last_inserted_count: int = 0
    last_skipped_duplicate_count: int = 0
    last_skipped_no_template_count: int = 0


class RecoveryDraftComparisonPayload(BaseModel):
    id: str
    dedupe_hash: str
    session_fp: str
    session_fp_suffix: str | None = None
    property_slug: str | None = None
    drop_off_point: str
    drop_off_point_label: str | None = None
    intent_score_estimate: float
    legacy_template_key: str
    legacy_body: str
    sovereign_body: str
    parity_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IntelligenceFeedItemPayload(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    market: str
    locality: str | None = None
    confidence_score: float | None = None
    query_topic: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    target_tags: list[str] = Field(default_factory=list)
    targeted_properties: list[dict[str, str]] = Field(default_factory=list)
    dedupe_hash: str
    seo_patch_ids: list[str] = Field(default_factory=list)
    seo_patch_statuses: list[str] = Field(default_factory=list)
    pricing_signal_ids: list[str] = Field(default_factory=list)
    pricing_signal_statuses: list[str] = Field(default_factory=list)
    discovered_at: datetime


class ScoutAlphaCategoryPayload(BaseModel):
    category: str
    patch_count: int
    deployed_count: int
    avg_godhead_score: float


class ScoutAlphaConversionPayload(BaseModel):
    window_days: int
    scout_patch_count: int
    manual_patch_count: int
    scout_deployed_count: int
    manual_deployed_count: int
    scout_pending_human_count: int
    manual_pending_human_count: int
    scout_avg_godhead_score: float
    manual_avg_godhead_score: float
    scout_intent_event_count: int
    manual_intent_event_count: int
    scout_hold_started_count: int
    manual_hold_started_count: int
    scout_insight_impression_count: int
    category_breakdown: list[ScoutAlphaCategoryPayload] = Field(default_factory=list)


class QuoteObserverRunPayload(BaseModel):
    job_id: str
    status: str
    requested_by: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    quote_id: str | None = None
    drift_status: str | None = None
    trace_id: str | None = None
    error: str | None = None
    async_job_href: str
    audit_log_href: str


class ParityDashboardPayload(BaseModel):
    shadow_mode: ShadowModePayload
    quote_parity: ShadowAuditSummaryOut
    quote_observer: QuoteObserverStatusPayload
    quote_observer_recent_runs: list[QuoteObserverRunPayload]
    seo_parity: ShadowSeoSummaryOut
    seo_observer: SeoObserverStatusPayload
    seo_observer_recent_runs: list[SeoObserverRunPayload]
    scout_observer: ScoutObserverStatusPayload
    concierge_observer: ConciergeAlphaObserverStatusPayload
    market_intelligence_feed: list[IntelligenceFeedItemPayload]
    scout_alpha_conversion: ScoutAlphaConversionPayload
    recovery_ghosts: HistoricalRecoverySummaryOut
    recovery_comparisons: list[RecoveryDraftComparisonPayload]
    legacy_targets: list[LegacyTargetScorecardPayload]
    agentic_observation: AgenticObservationPayload
    generated_at: str


async def _load_seo_stats(db: AsyncSession) -> dict[str, Any]:
    seo_queue_depth = int(
        (
            await db.execute(
                select(func.count()).select_from(SEOPatch).where(SEOPatch.status == "pending_human")
            )
        ).scalar_one()
        or 0
    )
    seo_deploy_queue_depth = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SEOPatch)
                .where(SEOPatch.deploy_status.in_(("queued", "processing")))
            )
        ).scalar_one()
        or 0
    )
    seo_failed_deploys = int(
        (
            await db.execute(
                select(func.count()).select_from(SEOPatch).where(SEOPatch.deploy_status == "failed")
            )
        ).scalar_one()
        or 0
    )
    seo_last_deploy_success_at = (
        await db.execute(
            select(func.max(SEOPatch.deploy_acknowledged_at)).where(SEOPatch.deploy_status == "succeeded")
        )
    ).scalar_one_or_none()
    seo_last_deploy_failure_at = (
        await db.execute(
            select(func.max(SEOPatch.deploy_acknowledged_at)).where(SEOPatch.deploy_status == "failed")
        )
    ).scalar_one_or_none()

    return {
        "seo_queue_depth": seo_queue_depth,
        "seo_deploy_queue_depth": seo_deploy_queue_depth,
        "seo_failed_deploys": seo_failed_deploys,
        "seo_last_deploy_success_at": seo_last_deploy_success_at,
        "seo_last_deploy_failure_at": seo_last_deploy_failure_at,
    }


async def _load_active_holds(db: AsyncSession, *, now: datetime) -> int:
    hold_window_start = now - timedelta(hours=24)
    active_holds_result = await db.execute(
        select(func.count())
        .select_from(ReservationHold)
        .where(
            ReservationHold.created_at >= hold_window_start,
            ReservationHold.status != "converted",
        )
    )
    return int(active_holds_result.scalar_one() or 0)


def _derive_agent_status(
    *,
    system_active: bool,
    agent_stats: dict[str, Any],
    seo_stats: dict[str, Any],
    active_holds: int,
    now: datetime,
) -> AgentStatusPayload:
    if not system_active:
        return AgentStatusPayload(
            concierge="inactive",
            seo_swarm="inactive",
            yield_engine="inactive",
        )

    total_messages = int(agent_stats.get("total_messages") or 0)
    avg_ai_confidence = float(agent_stats.get("avg_ai_confidence") or 0.0)
    if total_messages > 0 and avg_ai_confidence > 0:
        concierge = "observing"
    elif total_messages > 0:
        concierge = "warming"
    else:
        concierge = "idle"

    seo_failed_deploys = int(seo_stats["seo_failed_deploys"])
    seo_deploy_queue_depth = int(seo_stats["seo_deploy_queue_depth"])
    seo_last_deploy_success_at = seo_stats["seo_last_deploy_success_at"]
    if seo_failed_deploys > 0:
        seo_swarm = "degraded"
    elif seo_deploy_queue_depth > 0 or int(seo_stats["seo_queue_depth"]) > 0:
        seo_swarm = "observing"
    elif seo_last_deploy_success_at and seo_last_deploy_success_at >= now - timedelta(hours=1):
        seo_swarm = "online"
    else:
        seo_swarm = "idle"

    yield_engine = "observing" if active_holds > 0 else "idle"

    return AgentStatusPayload(
        concierge=concierge,
        seo_swarm=seo_swarm,
        yield_engine=yield_engine,
    )


def _derive_orchestrator_status(*, system_active: bool, agent_stats: dict[str, Any]) -> str:
    if not system_active:
        return "inactive"
    total_messages = int(agent_stats.get("total_messages") or 0)
    automation_rate_pct = float(agent_stats.get("automation_rate_pct") or 0.0)
    if total_messages > 0 and automation_rate_pct > 0:
        return "observing"
    if total_messages > 0:
        return "warming"
    return "idle"


def _build_shadow_mode_payload() -> ShadowModePayload:
    if settings.agentic_system_active:
        return ShadowModePayload(
            active=True,
            status="observation",
            legacy_authority="Drupal / Streamline / Rue Ba Rue remain primary",
            message="Shadow Parallel is active. Fortress Prime is observing live authority without switching control.",
        )
    return ShadowModePayload(
        active=False,
        status="inactive",
        legacy_authority="Drupal / Streamline / Rue Ba Rue remain primary",
        message="Shadow Parallel is disabled by AGENTIC_SYSTEM_ACTIVE. No observation swarm is armed.",
    )


def _empty_agentic_observation() -> AgenticObservationPayload:
    generated_at = datetime.now(timezone.utc).isoformat()
    return AgenticObservationPayload(
        system_active=False,
        orchestrator_status="inactive",
        automation_rate_pct=0.0,
        total_messages=0,
        escalated_to_human=0,
        avg_ai_confidence=0.0,
        lanes=AgentStatusPayload(
            concierge="inactive",
            seo_swarm="inactive",
            yield_engine="inactive",
        ),
        generated_at=generated_at,
    )


def _empty_seo_observer_status() -> SeoObserverStatusPayload:
    return SeoObserverStatusPayload(
        enabled=settings.semrush_shadow_observer_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(60, int(settings.semrush_shadow_observer_interval_seconds)),
        queue_depth=0,
        running_jobs=0,
        last_job_status="inactive" if not settings.semrush_shadow_observer_enabled else "idle",
        last_job_created_at=None,
        last_job_finished_at=None,
        last_success_at=None,
        last_audit_at=None,
    )


def _empty_scout_observer_status() -> ScoutObserverStatusPayload:
    return ScoutObserverStatusPayload(
        enabled=settings.research_scout_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(3600, int(settings.research_scout_interval_seconds)),
        queue_depth=0,
        running_jobs=0,
        last_job_status="inactive" if not settings.research_scout_enabled else "idle",
        last_job_created_at=None,
        last_job_finished_at=None,
        last_success_at=None,
        last_discovery_at=None,
        last_inserted_count=0,
        last_duplicate_count=0,
        last_seo_draft_count=0,
        last_pricing_signal_count=0,
    )


def _empty_concierge_observer_status() -> ConciergeAlphaObserverStatusPayload:
    return ConciergeAlphaObserverStatusPayload(
        enabled=settings.concierge_shadow_draft_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(300, int(settings.concierge_shadow_draft_interval_seconds)),
        queue_depth=0,
        running_jobs=0,
        last_job_status="inactive" if not settings.concierge_shadow_draft_enabled else "idle",
        last_job_created_at=None,
        last_job_finished_at=None,
        last_success_at=None,
        last_candidates_considered=0,
        last_inserted_count=0,
        last_skipped_duplicate_count=0,
        last_skipped_no_template_count=0,
    )


def _empty_scout_alpha_conversion() -> ScoutAlphaConversionPayload:
    return ScoutAlphaConversionPayload(
        window_days=30,
        scout_patch_count=0,
        manual_patch_count=0,
        scout_deployed_count=0,
        manual_deployed_count=0,
        scout_pending_human_count=0,
        manual_pending_human_count=0,
        scout_avg_godhead_score=0.0,
        manual_avg_godhead_score=0.0,
        scout_intent_event_count=0,
        manual_intent_event_count=0,
        scout_hold_started_count=0,
        manual_hold_started_count=0,
        scout_insight_impression_count=0,
        category_breakdown=[],
    )


def _empty_quote_observer_status() -> QuoteObserverStatusPayload:
    return QuoteObserverStatusPayload(
        agentic_system_active=settings.agentic_system_active,
        queue_depth=0,
        running_jobs=0,
        last_job_status="inactive" if not settings.agentic_system_active else "idle",
        last_job_created_at=None,
        last_job_finished_at=None,
        last_success_at=None,
        last_audit_at=None,
        last_drift_status=None,
        last_quote_id=None,
    )


def _trigger_mode_for_job(job: AsyncJobRun) -> str:
    if (job.request_id or "").strip() == "semrush-shadow-observer":
        return "scheduled"
    return "manual"


def _empty_legacy_targets() -> list[LegacyTargetScorecardPayload]:
    return [
        LegacyTargetScorecardPayload(
            target_id="streamline",
            label="Streamline Parity",
            legacy_system="Streamline",
            status="inactive",
            legacy_authority=True,
            observed_count=0,
            score_pct=None,
            last_observed_at=None,
            proof="Observation gated by AGENTIC_SYSTEM_ACTIVE.",
        ),
        LegacyTargetScorecardPayload(
            target_id="semrush",
            label="SEMRush SEO Parity",
            legacy_system="SEMRush",
            status="inactive",
            legacy_authority=True,
            observed_count=0,
            score_pct=None,
            last_observed_at=None,
            proof="Observation gated by AGENTIC_SYSTEM_ACTIVE.",
        ),
        LegacyTargetScorecardPayload(
            target_id="rue-bar-rue",
            label="Rue Ba Rue Recovery Parity",
            legacy_system="Rue Ba Rue",
            status="inactive",
            legacy_authority=True,
            observed_count=0,
            score_pct=None,
            last_observed_at=None,
            proof="Observation gated by AGENTIC_SYSTEM_ACTIVE.",
        ),
    ]


def _build_legacy_targets(
    *,
    shadow_summary: ShadowAuditSummaryOut,
    seo_summary: ShadowSeoSummaryOut,
    recovery_summary: HistoricalRecoverySummaryOut,
    recovery_draft_parity_rows: int = 0,
    recovery_draft_parity_last_at: datetime | None = None,
) -> list[LegacyTargetScorecardPayload]:
    latest_shadow_observation = None
    if shadow_summary.recent_traces:
        latest_shadow_observation = datetime.fromisoformat(
            shadow_summary.recent_traces[0].created_at.replace("Z", "+00:00")
        )

    return [
        LegacyTargetScorecardPayload(
            target_id="streamline",
            label="Streamline Parity",
            legacy_system="Streamline",
            status=shadow_summary.status,
            legacy_authority=True,
            observed_count=shadow_summary.gate_completed,
            score_pct=round(shadow_summary.accuracy_rate * 100.0, 2),
            last_observed_at=latest_shadow_observation,
            proof=(
                f"{shadow_summary.gate_progress} shadow traces observed with "
                f"{round(shadow_summary.tax_accuracy_rate * 100.0, 2):.2f}% tax accuracy."
            ),
        ),
        LegacyTargetScorecardPayload(
            target_id="semrush",
            label="SEMRush SEO Parity",
            legacy_system="SEMRush",
            status=seo_summary.status,
            legacy_authority=True,
            observed_count=seo_summary.observed_count,
            score_pct=round(seo_summary.avg_uplift_pct_points, 2) if seo_summary.observed_count else None,
            last_observed_at=seo_summary.last_observed_at,
            proof=(
                f"{seo_summary.superior_count} superior, {seo_summary.parity_count} parity, "
                f"{seo_summary.trailing_count} trailing against legacy SEMRush observations."
                if seo_summary.observed_count
                else (
                    "Awaiting SEMRush snapshot on sovereign storage."
                    if seo_summary.status == "no_snapshot"
                    else "SEMRush observation lane is inactive."
                )
            ),
        ),
        LegacyTargetScorecardPayload(
            target_id="rue-bar-rue",
            label="Rue Ba Rue Recovery Parity",
            legacy_system="Rue Ba Rue",
            status="observing" if recovery_summary.total_events > 0 else "cold_start",
            legacy_authority=True,
            observed_count=recovery_summary.total_events,
            score_pct=round(recovery_summary.signature_health_pct, 2),
            last_observed_at=recovery_draft_parity_last_at,
            proof=(
                f"{recovery_summary.total_resurrections} recovered events and "
                f"{recovery_summary.soft_landed_losses} soft-landed misses in the last "
                f"{recovery_summary.window_hours}h. "
                + (
                    f"Concierge draft parity ledger: {recovery_draft_parity_rows} comparison row(s)."
                    if recovery_draft_parity_rows
                    else "Concierge draft parity ledger is empty."
                )
            ),
        ),
    ]


async def _load_seo_observer_status(db: AsyncSession) -> SeoObserverStatusPayload:
    queue_depth = await count_jobs_by_status(
        db,
        status="queued",
        job_name="seo_parity_observation",
    )
    running_jobs = await count_jobs_by_status(
        db,
        status="running",
        job_name="seo_parity_observation",
    )
    latest_job = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "seo_parity_observation")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_success_at = (
        await db.execute(
            select(func.max(AsyncJobRun.finished_at))
            .where(
                AsyncJobRun.job_name == "seo_parity_observation",
                AsyncJobRun.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    last_audit_at = (
        await db.execute(
            select(func.max(OpenShellAuditLog.created_at)).where(
                OpenShellAuditLog.resource_type == "shadow_seo_audit"
            )
        )
    ).scalar_one_or_none()

    return SeoObserverStatusPayload(
        enabled=settings.semrush_shadow_observer_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(60, int(settings.semrush_shadow_observer_interval_seconds)),
        queue_depth=int(queue_depth),
        running_jobs=int(running_jobs),
        last_job_status=str(latest_job.status) if latest_job is not None else (
            "inactive" if not settings.semrush_shadow_observer_enabled else "idle"
        ),
        last_job_created_at=latest_job.created_at if latest_job is not None else None,
        last_job_finished_at=latest_job.finished_at if latest_job is not None else None,
        last_success_at=last_success_at,
        last_audit_at=last_audit_at,
    )


async def _load_quote_observer_status(db: AsyncSession) -> QuoteObserverStatusPayload:
    queue_depth = await count_jobs_by_status(
        db,
        status="queued",
        job_name="run_shadow_audit",
    )
    running_jobs = await count_jobs_by_status(
        db,
        status="running",
        job_name="run_shadow_audit",
    )
    latest_job = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "run_shadow_audit")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_success_at = (
        await db.execute(
            select(func.max(AsyncJobRun.finished_at))
            .where(
                AsyncJobRun.job_name == "run_shadow_audit",
                AsyncJobRun.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    last_audit_at = (
        await db.execute(
            select(func.max(OpenShellAuditLog.created_at)).where(
                OpenShellAuditLog.resource_type == "shadow_quote_audit"
            )
        )
    ).scalar_one_or_none()

    latest_result = latest_job.result_json if latest_job and isinstance(latest_job.result_json, dict) else {}
    shadow_audit = latest_result.get("shadow_audit") if isinstance(latest_result.get("shadow_audit"), dict) else {}
    latest_payload = latest_job.payload_json if latest_job and isinstance(latest_job.payload_json, dict) else {}
    metadata = latest_payload.get("metadata") if isinstance(latest_payload.get("metadata"), dict) else {}

    return QuoteObserverStatusPayload(
        agentic_system_active=settings.agentic_system_active,
        queue_depth=int(queue_depth),
        running_jobs=int(running_jobs),
        last_job_status=str(latest_job.status) if latest_job is not None else "idle",
        last_job_created_at=latest_job.created_at if latest_job is not None else None,
        last_job_finished_at=latest_job.finished_at if latest_job is not None else None,
        last_success_at=last_success_at,
        last_audit_at=last_audit_at,
        last_drift_status=(
            str(shadow_audit.get("drift_status")) if shadow_audit.get("drift_status") else None
        ),
        last_quote_id=str(metadata.get("quote_id")) if metadata.get("quote_id") else None,
    )


async def _load_recent_seo_observer_runs(
    db: AsyncSession,
    *,
    limit: int = 6,
) -> list[SeoObserverRunPayload]:
    rows = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "seo_parity_observation")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    recent_runs: list[SeoObserverRunPayload] = []
    for job in rows:
        result = job.result_json if isinstance(job.result_json, dict) else {}
        seo_parity = result.get("seo_parity") if isinstance(result.get("seo_parity"), dict) else {}
        recent_runs.append(
            SeoObserverRunPayload(
                job_id=str(job.id),
                trigger_mode=_trigger_mode_for_job(job),
                status=str(job.status),
                requested_by=job.requested_by,
                created_at=job.created_at,
                finished_at=job.finished_at,
                observed_count=int(seo_parity.get("observed_count")) if seo_parity.get("observed_count") is not None else None,
                superior_count=int(seo_parity.get("superior_count")) if seo_parity.get("superior_count") is not None else None,
                error=job.error_text,
                async_job_href=f"/api/async/jobs/{job.id}",
                audit_log_href=(
                    f"/api/openshell/audit/log?resource_type=shadow_seo_audit&request_id={job.id}"
                ),
            )
        )
    return recent_runs


async def _load_recent_quote_observer_runs(
    db: AsyncSession,
    *,
    limit: int = 6,
) -> list[QuoteObserverRunPayload]:
    rows = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "run_shadow_audit")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    recent_runs: list[QuoteObserverRunPayload] = []
    for job in rows:
        result = job.result_json if isinstance(job.result_json, dict) else {}
        shadow_audit = result.get("shadow_audit") if isinstance(result.get("shadow_audit"), dict) else {}
        payload = job.payload_json if isinstance(job.payload_json, dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        trace_id = str(shadow_audit.get("trace_id")) if shadow_audit.get("trace_id") else None
        quote_id = str(metadata.get("quote_id")) if metadata.get("quote_id") else None
        recent_runs.append(
            QuoteObserverRunPayload(
                job_id=str(job.id),
                status=str(job.status),
                requested_by=job.requested_by,
                created_at=job.created_at,
                finished_at=job.finished_at,
                quote_id=quote_id,
                drift_status=(
                    str(shadow_audit.get("drift_status")) if shadow_audit.get("drift_status") else None
                ),
                trace_id=trace_id,
                error=job.error_text,
                async_job_href=f"/api/async/jobs/{job.id}",
                audit_log_href=(
                    f"/api/openshell/audit/log?resource_type=shadow_quote_audit&request_id={job.id}"
                    if trace_id
                    else f"/api/openshell/audit/log?resource_type=shadow_quote_audit&request_id={job.id}"
                ),
            )
        )
    return recent_runs


async def _load_scout_observer_status(db: AsyncSession) -> ScoutObserverStatusPayload:
    queue_depth = await count_jobs_by_status(
        db,
        status="queued",
        job_name="research_scout_cycle",
    )
    running_jobs = await count_jobs_by_status(
        db,
        status="running",
        job_name="research_scout_cycle",
    )
    latest_job = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "research_scout_cycle")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_success_at = (
        await db.execute(
            select(func.max(AsyncJobRun.finished_at))
            .where(
                AsyncJobRun.job_name == "research_scout_cycle",
                AsyncJobRun.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    last_discovery_at = (
        await db.execute(select(func.max(IntelligenceLedgerEntry.discovered_at)))
    ).scalar_one_or_none()
    latest_result = latest_job.result_json if latest_job and isinstance(latest_job.result_json, dict) else {}
    scout_result = (
        latest_result.get("research_scout")
        if isinstance(latest_result.get("research_scout"), dict)
        else {}
    )
    action_result = scout_result.get("actions") if isinstance(scout_result.get("actions"), dict) else {}
    return ScoutObserverStatusPayload(
        enabled=settings.research_scout_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(3600, int(settings.research_scout_interval_seconds)),
        queue_depth=int(queue_depth),
        running_jobs=int(running_jobs),
        last_job_status=str(latest_job.status) if latest_job is not None else (
            "inactive" if not settings.research_scout_enabled else "idle"
        ),
        last_job_created_at=latest_job.created_at if latest_job is not None else None,
        last_job_finished_at=latest_job.finished_at if latest_job is not None else None,
        last_success_at=last_success_at,
        last_discovery_at=last_discovery_at,
        last_inserted_count=int(scout_result.get("inserted_count") or 0),
        last_duplicate_count=int(scout_result.get("duplicate_count") or 0),
        last_seo_draft_count=int(action_result.get("seo_draft_count") or 0),
        last_pricing_signal_count=int(action_result.get("pricing_signal_count") or 0),
    )


async def _recovery_parity_ledger_stats(db: AsyncSession) -> tuple[int, datetime | None]:
    total = int(
        (await db.execute(select(func.count()).select_from(RecoveryParityComparison))).scalar_one()
        or 0
    )
    last_at = (
        await db.execute(select(func.max(RecoveryParityComparison.created_at)))
    ).scalar_one_or_none()
    return total, last_at


async def _load_recovery_comparisons(
    db: AsyncSession,
    *,
    limit: int = 40,
) -> list[RecoveryDraftComparisonPayload]:
    rows = (
        await db.execute(
            select(RecoveryParityComparison)
            .order_by(desc(RecoveryParityComparison.created_at))
            .limit(limit)
        )
    ).scalars().all()
    out: list[RecoveryDraftComparisonPayload] = []
    for row in rows:
        snap = row.candidate_snapshot if isinstance(row.candidate_snapshot, dict) else {}
        suffix = snap.get("session_fp_suffix")
        if suffix is None and row.session_fp:
            suffix = row.session_fp[-8:] if len(row.session_fp) >= 8 else row.session_fp
        drop_label: str | None
        if isinstance(snap.get("drop_off_point_label"), str):
            drop_label = snap["drop_off_point_label"]
        else:
            drop_label = DROP_OFF_POINT_LABELS.get(row.drop_off_point, row.drop_off_point)
        out.append(
            RecoveryDraftComparisonPayload(
                id=str(row.id),
                dedupe_hash=row.dedupe_hash,
                session_fp=row.session_fp,
                session_fp_suffix=str(suffix) if suffix is not None else None,
                property_slug=row.property_slug,
                drop_off_point=row.drop_off_point,
                drop_off_point_label=drop_label,
                intent_score_estimate=float(row.intent_score_estimate),
                legacy_template_key=row.legacy_template_key,
                legacy_body=row.legacy_body,
                sovereign_body=row.sovereign_body,
                parity_summary=dict(row.parity_summary) if row.parity_summary else {},
                candidate_snapshot=dict(row.candidate_snapshot) if row.candidate_snapshot else {},
                created_at=row.created_at,
            )
        )
    return out


async def _load_concierge_observer_status(db: AsyncSession) -> ConciergeAlphaObserverStatusPayload:
    queue_depth = await count_jobs_by_status(
        db,
        status="queued",
        job_name="concierge_shadow_draft_cycle",
    )
    running_jobs = await count_jobs_by_status(
        db,
        status="running",
        job_name="concierge_shadow_draft_cycle",
    )
    latest_job = (
        await db.execute(
            select(AsyncJobRun)
            .where(AsyncJobRun.job_name == "concierge_shadow_draft_cycle")
            .order_by(AsyncJobRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_success_at = (
        await db.execute(
            select(func.max(AsyncJobRun.finished_at))
            .where(
                AsyncJobRun.job_name == "concierge_shadow_draft_cycle",
                AsyncJobRun.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    latest_result = latest_job.result_json if latest_job and isinstance(latest_job.result_json, dict) else {}
    crp = (
        latest_result.get("concierge_recovery_parity")
        if isinstance(latest_result.get("concierge_recovery_parity"), dict)
        else {}
    )
    return ConciergeAlphaObserverStatusPayload(
        enabled=settings.concierge_shadow_draft_enabled,
        agentic_system_active=settings.agentic_system_active,
        interval_seconds=max(300, int(settings.concierge_shadow_draft_interval_seconds)),
        queue_depth=int(queue_depth),
        running_jobs=int(running_jobs),
        last_job_status=str(latest_job.status) if latest_job is not None else (
            "inactive" if not settings.concierge_shadow_draft_enabled else "idle"
        ),
        last_job_created_at=latest_job.created_at if latest_job is not None else None,
        last_job_finished_at=latest_job.finished_at if latest_job is not None else None,
        last_success_at=last_success_at,
        last_candidates_considered=int(crp.get("candidates_considered") or 0),
        last_inserted_count=int(crp.get("inserted_count") or 0),
        last_skipped_duplicate_count=int(crp.get("skipped_duplicate_count") or 0),
        last_skipped_no_template_count=int(crp.get("skipped_no_template") or 0),
    )


async def _load_recent_market_intelligence_feed(
    db: AsyncSession,
    *,
    limit: int = 6,
) -> list[IntelligenceFeedItemPayload]:
    rows = await build_intelligence_feed_snapshot(db, limit=limit)
    return [IntelligenceFeedItemPayload.model_validate(row) for row in rows]


@router.get(
    "/dashboard",
    response_model=TelemetryDashboardPayload,
)
async def get_telemetry_dashboard(
    _: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])),
    db: AsyncSession = Depends(get_db),
) -> TelemetryDashboardPayload:
    now = datetime.now(timezone.utc)
    seo_stats = await _load_seo_stats(db)

    recent_comms_result = await db.execute(select(Message).order_by(Message.created_at.desc()).limit(5))
    recent_messages = list(recent_comms_result.scalars().all())
    active_holds = await _load_active_holds(db, now=now)
    agent_stats = await orchestrator.get_agent_stats(db)
    agent_status = _derive_agent_status(
        system_active=settings.agentic_system_active,
        agent_stats=agent_stats,
        seo_stats=seo_stats,
        active_holds=active_holds,
        now=now,
    )

    return TelemetryDashboardPayload(
        seo_queue_depth=int(seo_stats["seo_queue_depth"]),
        seo_deploy_queue_depth=int(seo_stats["seo_deploy_queue_depth"]),
        seo_failed_deploys=int(seo_stats["seo_failed_deploys"]),
        seo_last_deploy_success_at=seo_stats["seo_last_deploy_success_at"],
        seo_last_deploy_failure_at=seo_stats["seo_last_deploy_failure_at"],
        recent_comms=[
            RecentCommunicationPayload(
                id=str(message.id),
                direction=message.direction,
                phone_number=message.phone_from if message.direction == "inbound" else message.phone_to,
                snippet=(message.body or "").strip()[:140],
                timestamp=message.created_at,
            )
            for message in recent_messages
        ],
        active_holds=active_holds,
        agent_status=agent_status,
    )


@router.get(
    "/parity-dashboard",
    response_model=ParityDashboardPayload,
)
async def get_parity_dashboard(
    _: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])),
    db: AsyncSession = Depends(get_db),
) -> ParityDashboardPayload:
    now = datetime.now(timezone.utc)
    audit_now = now.replace(tzinfo=None)
    shadow_mode = _build_shadow_mode_payload()

    if not settings.agentic_system_active:
        generated_at = now.isoformat()
        return ParityDashboardPayload(
            shadow_mode=shadow_mode,
            quote_parity=summarize_shadow_audits([], now=now),
            quote_observer=_empty_quote_observer_status(),
            quote_observer_recent_runs=[],
            seo_parity=ShadowSeoSummaryOut(
                status="inactive",
                source="semrush",
                snapshot_path=settings.semrush_shadow_snapshot_path,
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
            ),
            seo_observer=_empty_seo_observer_status(),
            seo_observer_recent_runs=[],
            scout_observer=_empty_scout_observer_status(),
            concierge_observer=_empty_concierge_observer_status(),
            market_intelligence_feed=[],
            scout_alpha_conversion=_empty_scout_alpha_conversion(),
            recovery_ghosts=summarize_historical_recovery([], window_hours=24),
            recovery_comparisons=[],
            legacy_targets=_empty_legacy_targets(),
            agentic_observation=_empty_agentic_observation(),
            generated_at=generated_at,
        )

    shadow_rows = (
        await db.execute(
            select(OpenShellAuditLog)
            .where(OpenShellAuditLog.resource_type == "shadow_quote_audit")
            .order_by(desc(OpenShellAuditLog.created_at))
            .limit(100)
        )
    ).scalars().all()
    recovery_window_start = audit_now - timedelta(hours=24)
    recovery_rows = (
        await db.execute(
            select(OpenShellAuditLog)
            .where(OpenShellAuditLog.resource_type == "historical_archive")
            .where(OpenShellAuditLog.created_at >= recovery_window_start)
            .order_by(desc(OpenShellAuditLog.created_at))
        )
    ).scalars().all()

    shadow_summary = summarize_shadow_audits(list(shadow_rows), now=now)
    quote_observer = await _load_quote_observer_status(db)
    quote_observer_recent_runs = await _load_recent_quote_observer_runs(db)
    seo_summary = ShadowSeoSummaryOut.model_validate(
        (await observe_semrush_parity(db, persist_audit=False)).model_dump(mode="json")
    )
    seo_observer = await _load_seo_observer_status(db)
    seo_observer_recent_runs = await _load_recent_seo_observer_runs(db)
    scout_observer = await _load_scout_observer_status(db)
    concierge_observer = await _load_concierge_observer_status(db)
    market_intelligence_feed = await _load_recent_market_intelligence_feed(db)
    scout_alpha_conversion = ScoutAlphaConversionPayload.model_validate(
        await load_scout_alpha_metrics(db)
    )
    recovery_summary = summarize_historical_recovery(list(recovery_rows), window_hours=24)
    recovery_comparisons = await _load_recovery_comparisons(db)
    parity_total, parity_last = await _recovery_parity_ledger_stats(db)
    seo_stats = await _load_seo_stats(db)
    active_holds = await _load_active_holds(db, now=now)
    agent_stats = await orchestrator.get_agent_stats(db)
    lanes = _derive_agent_status(
        system_active=True,
        agent_stats=agent_stats,
        seo_stats=seo_stats,
        active_holds=active_holds,
        now=now,
    )
    agentic_observation = AgenticObservationPayload(
        system_active=True,
        orchestrator_status=_derive_orchestrator_status(system_active=True, agent_stats=agent_stats),
        automation_rate_pct=float(agent_stats.get("automation_rate_pct") or 0.0),
        total_messages=int(agent_stats.get("total_messages") or 0),
        escalated_to_human=int(agent_stats.get("escalated_to_human") or 0),
        avg_ai_confidence=float(agent_stats.get("avg_ai_confidence") or 0.0),
        lanes=lanes,
        generated_at=str(agent_stats.get("generated_at") or now.isoformat()),
    )

    return ParityDashboardPayload(
        shadow_mode=shadow_mode,
        quote_parity=shadow_summary,
        quote_observer=quote_observer,
        quote_observer_recent_runs=quote_observer_recent_runs,
        seo_parity=seo_summary,
        seo_observer=seo_observer,
        seo_observer_recent_runs=seo_observer_recent_runs,
        scout_observer=scout_observer,
        concierge_observer=concierge_observer,
        market_intelligence_feed=market_intelligence_feed,
        scout_alpha_conversion=scout_alpha_conversion,
        recovery_ghosts=recovery_summary,
        recovery_comparisons=recovery_comparisons,
        legacy_targets=_build_legacy_targets(
            shadow_summary=shadow_summary,
            seo_summary=seo_summary,
            recovery_summary=recovery_summary,
            recovery_draft_parity_rows=parity_total,
            recovery_draft_parity_last_at=parity_last,
        ),
        agentic_observation=agentic_observation,
        generated_at=now.isoformat(),
    )


@router.post(
    "/seo-parity/observe",
    response_model=ShadowSeoSummaryOut,
)
async def trigger_semrush_parity_observation(
    _: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])),
    db: AsyncSession = Depends(get_db),
) -> ShadowSeoSummaryOut:
    return await observe_semrush_parity(db, persist_audit=True)


# ---------------------------------------------------------------------------
# WebSocket: 1 Hz system health stream for Command Center (same payload as REST)
# ---------------------------------------------------------------------------
_SYSTEM_HEALTH_WS_INTERVAL_SEC = 1.0


@router.websocket("/ws/system-health")
async def system_health_telemetry_websocket(websocket: WebSocket) -> None:
    """Stream `build_system_health_payload` JSON at 1 Hz; requires `?token=<JWT>`."""
    token = (websocket.query_params.get("token") or "").strip()
    await websocket.accept()

    factory = get_session_factory()
    async with factory() as db:
        user = await load_staff_user_from_token_string(db, token)
        allowed = user is not None and staff_allowed_for_system_health_stream(user)

    if not allowed or user is None:
        logger.warning("system_health_ws_rejected", reason="auth_or_role")
        await websocket.close(code=1008)
        return

    logger.info("system_health_ws_connected", user_id=str(user.id))
    try:
        while True:
            async with factory() as db:
                payload = await build_system_health_payload(db)
            pulse = await build_pulse_response()
            payload = {
                **payload,
                "pulse": pulse.model_dump(mode="json"),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(_SYSTEM_HEALTH_WS_INTERVAL_SEC)
    except WebSocketDisconnect:
        logger.info("system_health_ws_disconnected")
    except Exception as exc:
        logger.error("system_health_ws_error", error=str(exc))
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
