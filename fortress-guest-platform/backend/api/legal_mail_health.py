"""
legal_mail_health.py — programmatic health endpoint for legal_mail_ingester.

Phase 0a-3 implementation per:
  docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md
  §6 (operator surface) + §7 (observability)

GET /api/internal/legal/mail/health
  Returns per-mailbox status as JSON, same data as
  `fgp legal mail status` but machine-parseable. Used by ops dashboards,
  alertmanager probes, and automation.

Auth pattern: matches backend/api/internal_health.py
  - Authorization: Bearer <internal_api_bearer_token>
  - X-Fortress-Ingress: command_center
  - X-Fortress-Tunnel-Signature: <internal_api_bearer_token>

All three required. Internal-only endpoint, never exposed via the public
storefront tunnel.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Sequence, cast

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from backend.core.config import settings
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_mail_ingester import (
    INGESTER_VERSIONED,
    LegalMailboxConfigError,
    load_legal_mailbox_configs,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────────────────────


MailboxStatus = Literal["ok", "stale", "errored", "paused", "unconfigured"]
OverallStatus = Literal["ok", "degraded", "disabled"]


class MailboxHealth(BaseModel):
    """Per-mailbox health record."""
    model_config = ConfigDict(extra="forbid")

    alias: str
    host: str
    folder: str
    routing_tag: str
    poll_interval_sec: int

    # State row from legal.mail_ingester_state
    last_patrol_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error: Optional[str] = None
    messages_ingested_total: int = 0
    messages_errored_total: int = 0

    # Today's counters from legal.event_log
    messages_ingested_today: int = 0
    watchdog_matches_today: int = 0

    # Pause row from legal.mail_ingester_pause
    paused: bool = False
    paused_by: Optional[str] = None
    pause_reason: Optional[str] = None
    paused_at: Optional[datetime] = None

    # Computed per-mailbox rollup
    status: MailboxStatus


class HealthSummary(BaseModel):
    """Aggregate counts across all mailboxes."""
    model_config = ConfigDict(extra="forbid")

    total_mailboxes: int
    healthy: int
    paused: int
    errored: int
    stale: int


class LegalMailHealthResponse(BaseModel):
    """Top-level response for GET /api/internal/legal/mail/health."""
    model_config = ConfigDict(extra="forbid")

    service: Literal["legal_mail_ingester"] = "legal_mail_ingester"
    ingester_versioned: str = Field(min_length=1)
    ingester_enabled: bool
    checked_at: datetime
    overall_status: OverallStatus
    mailboxes: list[MailboxHealth]
    summary: HealthSummary


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers (mirror internal_health.py)
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
    internal_health.py — any failure raises HTTPException with the same
    status codes / details so monitoring tools see consistent error shape.
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


# A mailbox is "stale" if its last successful patrol was longer than this many
# poll intervals ago. 3× provides slack for transient connectivity blips
# without flagging a healthy mailbox as stale during a single retry.
STALE_MULTIPLIER = 3

# Errors older than this are considered resolved (the patrol has succeeded
# since); stop surfacing them as the per-mailbox status.
ERROR_FRESHNESS_WINDOW = timedelta(hours=1)


def _compute_mailbox_status(
    *,
    paused: bool,
    last_success_at: Optional[datetime],
    last_error_at: Optional[datetime],
    poll_interval_sec: int,
    now: datetime,
) -> MailboxStatus:
    """
    Per-mailbox rollup. Order matters — pause is sticky (operator-explicit
    signal); errored takes precedence over stale (errored is more actionable);
    stale only if no recent success.
    """
    if paused:
        return "paused"

    # Errored: there was an error AND the last successful patrol was either
    # missing or older than the error. Once the patrol succeeds AFTER an
    # error, the mailbox is no longer "errored" from a monitoring view.
    if last_error_at is not None:
        recent_error = (now - last_error_at) < ERROR_FRESHNESS_WINDOW
        unrecovered = (
            last_success_at is None
            or last_success_at < last_error_at
        )
        if recent_error and unrecovered:
            return "errored"

    # Stale: no successful patrol ever, or the last one is much older than
    # the configured poll interval would expect.
    if last_success_at is None:
        return "stale"
    elapsed = (now - last_success_at).total_seconds()
    if elapsed > (poll_interval_sec * STALE_MULTIPLIER):
        return "stale"

    return "ok"


def _overall_status(
    ingester_enabled: bool,
    mailbox_statuses: Sequence[MailboxStatus],
) -> OverallStatus:
    """
    Top-level rollup. If the flag is off, status is 'disabled' regardless
    of mailbox state — that lets monitors distinguish "code is inert by
    design" from "code is running but degraded".
    """
    if not ingester_enabled:
        return "disabled"
    if any(s in ("errored", "stale") for s in mailbox_statuses):
        return "degraded"
    return "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────────────────────


async def _build_mailbox_health(
    *,
    alias: str,
    host: str,
    folder: str,
    routing_tag: str,
    poll_interval_sec: int,
    today_start_utc: datetime,
    now: datetime,
) -> MailboxHealth:
    """
    Three queries against fortress_db (same shape the CLI uses):
      1. legal.mail_ingester_state  — counters + last_patrol/success/error
      2. legal.mail_ingester_pause  — pause row if present
      3. legal.event_log            — today's email.received events emitted by us
    """
    async with LegacySession() as db:
        r = await db.execute(
            text("""
                SELECT last_patrol_at, last_success_at, last_error_at, last_error,
                       messages_ingested_total, messages_errored_total
                FROM legal.mail_ingester_state
                WHERE mailbox_alias = :alias
            """),
            {"alias": alias},
        )
        state_row = r.fetchone()

        r = await db.execute(
            text("""
                SELECT paused_at, paused_by, reason
                FROM legal.mail_ingester_pause
                WHERE mailbox_alias = :alias
            """),
            {"alias": alias},
        )
        pause_row = r.fetchone()

        r = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS events_today,
                    COALESCE(SUM(jsonb_array_length(event_payload->'watchdog_matches')), 0)
                        AS watchdog_matches_today
                FROM legal.event_log
                WHERE event_type = 'email.received'
                  AND emitted_by = :v
                  AND emitted_at >= :today_start
                  AND event_payload->>'mailbox' = :alias
            """),
            {
                "v": INGESTER_VERSIONED,
                "today_start": today_start_utc,
                "alias": alias,
            },
        )
        counters_row = r.fetchone()

    paused = pause_row is not None
    last_patrol_at = state_row.last_patrol_at if state_row else None
    last_success_at = state_row.last_success_at if state_row else None
    last_error_at = state_row.last_error_at if state_row else None
    last_error = state_row.last_error if state_row else None
    messages_ingested_total = int(state_row.messages_ingested_total or 0) if state_row else 0
    messages_errored_total = int(state_row.messages_errored_total or 0) if state_row else 0

    # COUNT(*) always returns one row, so counters_row is non-None.
    assert counters_row is not None
    messages_ingested_today = int(counters_row.events_today or 0)
    watchdog_matches_today = int(counters_row.watchdog_matches_today or 0)

    mailbox_status = _compute_mailbox_status(
        paused=paused,
        last_success_at=last_success_at,
        last_error_at=last_error_at,
        poll_interval_sec=poll_interval_sec,
        now=now,
    )

    return MailboxHealth(
        alias=alias,
        host=host,
        folder=folder,
        routing_tag=routing_tag,
        poll_interval_sec=poll_interval_sec,
        last_patrol_at=last_patrol_at,
        last_success_at=last_success_at,
        last_error_at=last_error_at,
        last_error=last_error,
        messages_ingested_total=messages_ingested_total,
        messages_errored_total=messages_errored_total,
        messages_ingested_today=messages_ingested_today,
        watchdog_matches_today=watchdog_matches_today,
        paused=paused,
        paused_by=pause_row.paused_by if pause_row else None,
        pause_reason=pause_row.reason if pause_row else None,
        paused_at=pause_row.paused_at if pause_row else None,
        status=mailbox_status,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/legal/mail/health",
    response_model=LegalMailHealthResponse,
    include_in_schema=False,
)
async def legal_mail_health(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_fortress_ingress: Annotated[str | None, Header(alias="X-Fortress-Ingress")] = None,
    x_fortress_tunnel_signature: Annotated[
        str | None, Header(alias="X-Fortress-Tunnel-Signature")
    ] = None,
) -> LegalMailHealthResponse:
    """
    Programmatic health surface for legal_mail_ingester.

    Returns per-mailbox status + aggregate rollup. Designed for ops
    dashboards and alertmanager probes — same data as
    `fgp legal mail status`, but JSON-shaped and JWT-protected.

    HTTP semantics:
      200 — successful response (overall_status in body indicates health)
      401 — missing or bad bearer token
      403 — wrong ingress boundary or tunnel signature
      503 — MAILBOXES_CONFIG malformed (the ingester can't be evaluated)
    """
    _enforce_internal_auth(
        authorization=authorization,
        x_fortress_ingress=x_fortress_ingress,
        x_fortress_tunnel_signature=x_fortress_tunnel_signature,
    )

    try:
        configs = load_legal_mailbox_configs()
    except LegalMailboxConfigError as exc:
        # Configuration error is a service-unavailable signal: the
        # ingester literally cannot evaluate its own health because
        # the input it would patrol is malformed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MAILBOXES_CONFIG malformed: {exc}",
        )

    now = datetime.now(timezone.utc)
    today_start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)

    mailboxes: list[MailboxHealth] = []
    for cfg in configs:
        mh = await _build_mailbox_health(
            alias=cfg.name,
            host=cfg.host,
            folder=cfg.folder,
            routing_tag=cfg.routing_tag,
            poll_interval_sec=cfg.poll_interval_sec,
            today_start_utc=today_start_utc,
            now=now,
        )
        mailboxes.append(mh)

    statuses: list[MailboxStatus] = cast(
        "list[MailboxStatus]", [m.status for m in mailboxes]
    )
    summary = HealthSummary(
        total_mailboxes=len(mailboxes),
        healthy=sum(1 for s in statuses if s == "ok"),
        paused=sum(1 for s in statuses if s == "paused"),
        errored=sum(1 for s in statuses if s == "errored"),
        stale=sum(1 for s in statuses if s == "stale"),
    )

    return LegalMailHealthResponse(
        ingester_versioned=INGESTER_VERSIONED,
        ingester_enabled=settings.legal_mail_ingester_enabled,
        checked_at=now,
        overall_status=_overall_status(
            ingester_enabled=settings.legal_mail_ingester_enabled,
            mailbox_statuses=statuses,
        ),
        mailboxes=mailboxes,
        summary=summary,
    )
