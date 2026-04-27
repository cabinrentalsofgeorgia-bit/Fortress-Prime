"""
legal_dispatcher_health.py — programmatic health endpoint for legal_dispatcher.

Phase 1-4 implementation per:
  docs/architecture/cross-division/FLOS-phase-1-4-cli-health-implementation.md
  §10 (health endpoint)

GET /api/internal/legal/dispatcher/health
  Returns dispatcher state as JSON, same data as
  `legal_dispatcher_cli dispatcher status` but machine-parseable. Used by
  ops dashboards, alertmanager probes, and automation.

Auth pattern: matches backend/api/legal_mail_health.py (PR #247) verbatim
  - Authorization: Bearer <internal_api_bearer_token>
  - X-Fortress-Ingress: command_center
  - X-Fortress-Tunnel-Signature: <internal_api_bearer_token>

All three required. Internal-only endpoint, never exposed via the public
storefront tunnel.

Status semantics (LOCKED v1.1 §10.3):
  disabled — settings.legal_dispatcher_enabled is False
  lagging  — flag True + oldest_unprocessed_age_sec > LAG_THRESHOLD_SEC (60s)
  degraded — flag True + (failed_last_hour > 0 OR dead_lettered_last_hour > 0)
  ok       — flag True + lag within threshold + no recent failures

Pause state is reflected in pause.paused + summary.paused; does NOT change
overall_status (paused is a deliberate operator state, not a degradation
signal).

Design decision: overall_status computation is duplicated between this
endpoint and legal_dispatcher_cli.py status subcommand. Per Phase 1-4A
review — don't extract to shared helper at 2 consumers; defer extraction
to Phase 2+ at 3+ consumers.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from backend.core.config import settings
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_dispatcher import (
    BATCH_SIZE,
    DISPATCHER_VERSIONED,
    POLL_INTERVAL_SEC,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Status thresholds (LOCKED v1.1 §10.3)
# ─────────────────────────────────────────────────────────────────────────────


# Queue lag threshold beyond which overall_status flips to "lagging".
# 60 seconds = 12× POLL_INTERVAL_SEC at the LOCKED v1.1 cadence; represents
# genuine queue backup, not transient lag. Operator may override via
# environment if Phase 1-6 24h soak data reveals a different cadence.
LAG_THRESHOLD_SEC: float = 60.0


# ─────────────────────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────────────────────


OverallStatus = Literal["ok", "degraded", "disabled", "lagging"]


class QueueStats(BaseModel):
    """Queue depth + last-hour aggregates from dispatcher_event_attempts."""
    model_config = ConfigDict(extra="forbid")

    unprocessed_total: int
    oldest_unprocessed_age_sec: Optional[float] = None
    processed_last_hour: int
    failed_last_hour: int
    dead_lettered_last_hour: int
    mean_handler_ms: Optional[float] = None
    p99_handler_ms: Optional[float] = None


class RouteSummary(BaseModel):
    """Per-route summary from dispatcher_routes."""
    model_config = ConfigDict(extra="forbid")

    event_type: str
    handler: str  # composite "<module>.<function>"
    enabled: bool
    max_retries: int


class PauseStatus(BaseModel):
    """Singleton pause state from dispatcher_pause."""
    model_config = ConfigDict(extra="forbid")

    paused: bool
    paused_at: Optional[datetime] = None
    paused_by: Optional[str] = None
    reason: Optional[str] = None


class HealthSummary(BaseModel):
    """Aggregate counts."""
    model_config = ConfigDict(extra="forbid")

    total_routes: int
    enabled_routes: int
    paused: bool
    overall_status: OverallStatus


class LegalDispatcherHealthResponse(BaseModel):
    """Top-level response for GET /api/internal/legal/dispatcher/health."""
    model_config = ConfigDict(extra="forbid")

    service: Literal["legal_dispatcher"] = "legal_dispatcher"
    version: Literal["v1"] = "v1"
    dispatcher_versioned: str = Field(min_length=1)
    dispatcher_enabled: bool
    poll_interval_sec: int
    batch_size: int
    checked_at: datetime
    overall_status: OverallStatus
    queue: QueueStats
    routes: list[RouteSummary]
    pause: PauseStatus
    summary: HealthSummary


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers (mirror legal_mail_health.py from PR #247 verbatim)
# ─────────────────────────────────────────────────────────────────────────────


def _secure_equals(presented: str | None, expected: str) -> bool:
    if not presented or not expected:
        return False
    return secrets.compare_digest(presented.strip(), expected.strip())


def _enforce_internal_auth(
    authorization: str | None,
    x_fortress_ingress: str | None,
    x_fortress_tunnel_signature: str | None,
) -> None:
    """
    Bearer + ingress + tunnel-signature gate. Same triple-check as
    legal_mail_health.py — any failure raises HTTPException with the same
    status codes / details so monitoring tools see consistent error shape
    across both health endpoints.
    """
    expected_secret = settings.internal_api_bearer_token

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    bearer_token = authorization[7:].strip()
    if not _secure_equals(bearer_token, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
    if x_fortress_ingress != "command_center":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid ingress boundary.",
        )
    if not _secure_equals(x_fortress_tunnel_signature, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid tunnel signature.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Status computation
# ─────────────────────────────────────────────────────────────────────────────


def _compute_overall_status(
    flag_enabled: bool,
    queue: QueueStats,
) -> OverallStatus:
    """
    Per spec §10.3 LOCKED:
      disabled — flag is False
      degraded — flag True + (failed_last_hour > 0 OR dead_lettered_last_hour > 0)
      lagging  — flag True + oldest_unprocessed_age_sec > LAG_THRESHOLD_SEC
      ok       — otherwise

    Pause does NOT trigger degraded; pause is a deliberate operator state
    and is surfaced via pause.paused / summary.paused. A monitoring tool
    that wants to alert on long pauses can read those fields directly.

    Failure precedence over lag: a degraded handler is more actionable
    than a backed-up queue; surface degraded first.
    """
    if not flag_enabled:
        return "disabled"
    if queue.failed_last_hour > 0 or queue.dead_lettered_last_hour > 0:
        return "degraded"
    if (
        queue.oldest_unprocessed_age_sec is not None
        and queue.oldest_unprocessed_age_sec > LAG_THRESHOLD_SEC
    ):
        return "lagging"
    return "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────────────────────


async def _fetch_routes() -> list[RouteSummary]:
    """Read dispatcher_routes ordered by event_type."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT event_type, handler_module, handler_function, enabled, max_retries
            FROM legal.dispatcher_routes
            ORDER BY event_type
        """))
        return [
            RouteSummary(
                event_type=row.event_type,
                handler=f"{row.handler_module}.{row.handler_function}",
                enabled=bool(row.enabled),
                max_retries=int(row.max_retries),
            )
            for row in result.fetchall()
        ]


async def _fetch_pause() -> PauseStatus:
    """Read dispatcher_pause singleton row."""
    async with LegacySession() as db:
        result = await db.execute(text("""
            SELECT paused_at, paused_by, reason
            FROM legal.dispatcher_pause
            WHERE singleton_id = 1
            LIMIT 1
        """))
        row = result.fetchone()
        if row is None:
            return PauseStatus(paused=False)
        return PauseStatus(
            paused=True,
            paused_at=row.paused_at,
            paused_by=row.paused_by,
            reason=row.reason,
        )


async def _fetch_queue_stats() -> QueueStats:
    """Read queue depth + last-hour aggregates in two queries."""
    async with LegacySession() as db:
        # Queue depth + oldest unprocessed age
        result = await db.execute(text("""
            SELECT
                COUNT(*) AS unprocessed_total,
                EXTRACT(EPOCH FROM (NOW() - MIN(emitted_at))) AS oldest_unprocessed_age_sec
            FROM legal.event_log
            WHERE processed_at IS NULL
        """))
        queue_row = result.fetchone()
        unprocessed_total = int(queue_row.unprocessed_total or 0) if queue_row else 0
        oldest_age_raw = queue_row.oldest_unprocessed_age_sec if queue_row else None
        oldest_age_sec: Optional[float] = (
            float(oldest_age_raw) if oldest_age_raw is not None else None
        )

        # Last-hour aggregates from dispatcher_event_attempts
        result = await db.execute(text("""
            SELECT
                SUM(CASE WHEN outcome = 'success'     THEN 1 ELSE 0 END) AS processed_last_hour,
                SUM(CASE WHEN outcome = 'error'       THEN 1 ELSE 0 END) AS failed_last_hour,
                SUM(CASE WHEN outcome = 'dead_letter' THEN 1 ELSE 0 END) AS dead_lettered_last_hour,
                AVG(duration_ms)                                          AS mean_handler_ms,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_handler_ms
            FROM legal.dispatcher_event_attempts
            WHERE attempted_at >= NOW() - INTERVAL '1 hour'
        """))
        agg_row = result.fetchone()
        if agg_row is None:
            return QueueStats(
                unprocessed_total=unprocessed_total,
                oldest_unprocessed_age_sec=oldest_age_sec,
                processed_last_hour=0,
                failed_last_hour=0,
                dead_lettered_last_hour=0,
                mean_handler_ms=None,
                p99_handler_ms=None,
            )

        return QueueStats(
            unprocessed_total=unprocessed_total,
            oldest_unprocessed_age_sec=oldest_age_sec,
            processed_last_hour=int(agg_row.processed_last_hour or 0),
            failed_last_hour=int(agg_row.failed_last_hour or 0),
            dead_lettered_last_hour=int(agg_row.dead_lettered_last_hour or 0),
            mean_handler_ms=float(agg_row.mean_handler_ms) if agg_row.mean_handler_ms is not None else None,
            p99_handler_ms=float(agg_row.p99_handler_ms) if agg_row.p99_handler_ms is not None else None,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/legal/dispatcher/health",
    response_model=LegalDispatcherHealthResponse,
    include_in_schema=False,
)
async def legal_dispatcher_health(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_fortress_ingress: Annotated[
        str | None, Header(alias="X-Fortress-Ingress")
    ] = None,
    x_fortress_tunnel_signature: Annotated[
        str | None, Header(alias="X-Fortress-Tunnel-Signature")
    ] = None,
) -> LegalDispatcherHealthResponse:
    """
    Programmatic health surface for legal_dispatcher.

    Returns the same data as `legal_dispatcher_cli dispatcher status` —
    routes + queue depth + last-hour metrics + pause state + computed
    overall_status — JSON-shaped and JWT-protected. Designed for ops
    dashboards and alertmanager probes.

    HTTP semantics:
      200 — successful response (overall_status in body indicates health)
      401 — missing or bad bearer token
      403 — wrong ingress boundary or tunnel signature
      503 — DB connection failure (service can't evaluate itself)
    """
    _enforce_internal_auth(
        authorization=authorization,
        x_fortress_ingress=x_fortress_ingress,
        x_fortress_tunnel_signature=x_fortress_tunnel_signature,
    )

    try:
        routes = await _fetch_routes()
        pause = await _fetch_pause()
        queue = await _fetch_queue_stats()
    except Exception as exc:
        # DB-level failure means the service can't evaluate its own
        # health. 503 is the correct HTTP signal — not 200 with a
        # "broken" status field that would obscure the underlying issue.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Dispatcher health DB query failed: {exc}",
        )

    flag_enabled = bool(settings.legal_dispatcher_enabled)
    overall_status = _compute_overall_status(
        flag_enabled=flag_enabled,
        queue=queue,
    )

    enabled_route_count = sum(1 for r in routes if r.enabled)
    summary = HealthSummary(
        total_routes=len(routes),
        enabled_routes=enabled_route_count,
        paused=pause.paused,
        overall_status=overall_status,
    )

    return LegalDispatcherHealthResponse(
        dispatcher_versioned=DISPATCHER_VERSIONED,
        dispatcher_enabled=flag_enabled,
        poll_interval_sec=POLL_INTERVAL_SEC,
        batch_size=BATCH_SIZE,
        checked_at=datetime.now(timezone.utc),
        overall_status=overall_status,
        queue=queue,
        routes=routes,
        pause=pause,
        summary=summary,
    )
