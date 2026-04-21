"""
Fortress Guest Platform - Main FastAPI Application
Enterprise guest communication system
"""
import asyncio
import logging
import os
import secrets
import sys
import time
import uuid
import traceback
import structlog
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import settings
from backend.core.database import init_db, close_db, get_db, async_engine
from backend.core.public_api_paths import is_public_api_path
from backend.core.queue import create_arq_pool
from backend.api import guests, messages, reservations, properties, workorders, analytics, webhooks, webhooks_channex, guestbook
from backend.api import integrations as integrations_api
from backend.api import booking, housekeeping, channels, agent
from backend.api import portal as portal_api
from backend.api import review_queue, email_bridge, damage_claims
from backend.api import email_outbound_drafts as email_outbound_drafts_api
from backend.api import tenants as tenants_api
from backend.api import owner_portal
from backend.api import paperclip_bridge as paperclip_bridge_api
from backend.api import direct_booking as direct_booking_api
from backend.api import guest_portal_api
from backend.api import channel_mgr
from backend.api import channel_mappings as channel_mappings_api
from backend.api import cleaners as cleaners_api
from backend.api import vendors as vendors_api
from backend.api import acquisition_pipeline as acquisition_pipeline_api
from backend.api import admin_charges as admin_charges_api
from backend.api import admin_statements_workflow as admin_stmts_workflow_api
from backend.api import ai_superpowers
from backend.api import stripe_webhooks
from backend.api import stripe_connect_webhooks
from backend.api import iot as iot_api
from backend.api import search as search_api
from backend.api import inspections as inspections_api
from backend.api import utilities as utilities_api
from backend.api import auth as auth_api
from backend.api import invites as invites_api
from backend.api import agreements as agreements_api
from backend.api import payments as payments_api
from backend.api import fast_quote as fast_quote_api
from backend.api import quotes as quotes_api
from backend.api import vrs_quotes as vrs_quotes_api
from backend.api import leads as leads_api
from backend.api import vrs as vrs_api
from backend.api import vrs_operations as vrs_operations_api
from backend.api import checkout as checkout_api
from backend.api import templates as templates_api
from backend.api import copilot_queue as copilot_queue_api
from backend.api import admin as admin_api
from backend.api import admin_acquisition as admin_acquisition_api
from backend.api import admin_acquisition_foia as admin_acquisition_foia_api
from backend.api import admin_channex as admin_channex_api
from backend.api import admin_insights as admin_insights_api
from backend.api import admin_statements as admin_statements_api
from backend.api import rule_engine as rule_engine_api
from backend.api import intelligence as intelligence_api
from backend.api import intelligence_feed as intelligence_feed_api
from backend.api import intelligence_projection as intelligence_projection_api
from backend.api import vault as vault_api
from backend.api import legal_council as legal_council_api
from backend.api import ediscovery as ediscovery_api
from backend.api import legal_docgen as legal_docgen_api
from backend.api import legal_graph as legal_graph_api
from backend.api import legal_discovery as legal_discovery_api
from backend.api import legal_cases as legal_cases_api
from backend.api import legal_strategy as legal_strategy_api
from backend.api import legal_counsel_dispatch as legal_counsel_dispatch_api
from backend.api import legal_hold as legal_hold_api
from backend.api import legal_tactical as legal_tactical_api
from backend.api import legal_sanctions as legal_sanctions_api
from backend.api import legal_deposition as legal_deposition_api
from backend.api import legal_agent as legal_agent_api
from backend.api import legal_email_intake_api
from backend.api import admin_payouts as admin_payouts_api
from backend.api import verses as verses_api
from backend.api import seo_patches as seo_patches_api
from backend.api import wealth as wealth_api
from backend.api import reservation_webhooks
from backend.api import contracts as contracts_api
from backend.api import dispute_webhooks
from backend.api import disputes as disputes_api
from backend.api import system_sensors as system_sensors_api
from backend.api import system_health as system_health_api
from backend.api import system_nodes as system_nodes_api
from backend.api import system_dashboard as system_dashboard_api
from backend.api import internal_health as internal_health_api
from backend.api import ops as ops_api
from backend.api import vrs_health as vrs_health_api
from backend.api import vrs_treasury as vrs_treasury_api
from backend.api import hunter as hunter_api
from backend.api import concierge as concierge_api
from backend.api import dispatch as contact_form
from backend.api import internal_deck as internal_deck_api
from backend.api import redirect_vanguard_admin as redirect_vanguard_admin_api
from backend.api import storefront_calendar as storefront_calendar_api
from backend.api import storefront_catalog as storefront_catalog_api
from backend.api import tax_reports as tax_reports_api
from backend.api import storefront_demand as storefront_demand_api
from backend.api import storefront_concierge as storefront_concierge_api
from backend.api import storefront_intent as storefront_intent_api
from backend.api import disagg_admin as disagg_admin_api
from backend.api import telemetry as telemetry_api
from backend.api import command_c2 as command_c2_api
from backend.api import sovereign_pulse as sovereign_pulse_api
from backend.api import funnel_hq as funnel_hq_api
from backend.api import openshell_audit as openshell_audit_api
from backend.api import legacy_pages as legacy_pages_api
from backend.api import activities as activities_api
from backend.api import blogs as blogs_api
from backend.api import financial_approvals as financial_approvals_api
from backend.api import storefront_checkout as storefront_checkout_api
from backend.api import trust_ledger_command_center as trust_ledger_command_center_api
from backend.api import shadow_router as shadow_router_api
from backend.core.tenant import TenantMiddleware

# ---------------------------------------------------------------------------
# Root logger — must be configured before structlog so that stdlib-backed
# structlog loggers (LoggerFactory) have a handler to write to.  Without
# this, every logger.info() call is silently discarded by Python's
# lastResort handler (WARNING-only, no formatter, no journald output).
#
# force=True overrides any implicit basicConfig that libraries may have
# called before us (e.g. uvicorn's own startup).  Uvicorn's named loggers
# (uvicorn, uvicorn.access, uvicorn.error) have their own handlers and are
# unaffected — they propagate=False so they never reach the root handler.
# ---------------------------------------------------------------------------
_log_level_name: str = getattr(settings, "log_level", "INFO") or "INFO"
logging.basicConfig(
    level=getattr(logging, _log_level_name, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
    force=True,
)
logging.getLogger(__name__).info("Logging initialized at level %s", _log_level_name)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Background task tracking (for watchdog)
# ---------------------------------------------------------------------------
_bg_task_heartbeats: dict[str, float] = {}
INTERNAL_LEGAL_API_PREFIX = "/api/internal/legal"
INTERNAL_INGRESS_HEADER = "x-fortress-ingress"
INTERNAL_INGRESS_SIGNATURE_HEADER = "x-fortress-tunnel-signature"
COMMAND_CENTER_INGRESS = "command_center"
PUBLIC_STOREFRONT_INGRESS = "public_storefront"


def _normalize_host(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or raw.split("/")[0].split(":")[0]).strip().lower()
    return host


def _expand_host_variants(value: str | None) -> set[str]:
    host = _normalize_host(value)
    if not host:
        return set()
    variants = {host}
    if host in {"localhost", "127.0.0.1", "::1"}:
        return variants

    base = host[4:] if host.startswith("www.") else host
    variants.add(base)
    variants.add(f"www.{base}")
    variants.add(f"api.{base}")
    return variants


def _extra_command_center_ingress_hosts() -> set[str]:
    raw = (settings.command_center_ingress_hosts or "").strip()
    if not raw:
        return set()
    out: set[str] = set()
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        out.add(_normalize_host(p))
    return out


def _command_center_hosts() -> set[str]:
    return (
        _expand_host_variants(settings.frontend_url)
        | _expand_host_variants(settings.command_center_url)
        | _extra_command_center_ingress_hosts()
    )


def _storefront_hosts() -> set[str]:
    return _expand_host_variants(settings.storefront_base_url)


def _request_effective_host(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        first = forwarded_host.split(",")[0].strip()
        if first:
            return _normalize_host(first)
    return _normalize_host(request.headers.get("host"))


def _request_origin_host(request: Request) -> str:
    for header_name in ("origin", "referer"):
        header_value = request.headers.get(header_name)
        if header_value:
            return _normalize_host(header_value)
    return ""


def _has_valid_internal_tunnel_signature(request: Request) -> bool:
    expected = settings.internal_api_bearer_token
    presented = (request.headers.get(INTERNAL_INGRESS_SIGNATURE_HEADER) or "").strip()
    ingress = (request.headers.get(INTERNAL_INGRESS_HEADER) or "").strip().lower()
    if not expected or not presented or ingress != COMMAND_CENTER_INGRESS:
        return False
    return secrets.compare_digest(presented, expected)


def _requires_internal_ingress(request: Request) -> bool:
    path = request.url.path
    return path.startswith("/api/") and not is_public_api_path(path, request.method)


_TRUSTED_CF_ACCESS_CLIENT_ID = "9046745d856ea018e6a8d9d8bd1eea7f.access"


def _has_trusted_cf_access_token(request: Request) -> bool:
    client_id = (request.headers.get("cf-access-client-id") or "").strip()
    return client_id == _TRUSTED_CF_ACCESS_CLIENT_ID


def _is_allowed_internal_request(request: Request) -> bool:
    if not _requires_internal_ingress(request):
        return True

    request_host = _request_effective_host(request)
    if request_host and request_host in _storefront_hosts():
        return False

    if _has_valid_internal_tunnel_signature(request):
        return True

    if _has_trusted_cf_access_token(request):
        return True

    origin_host = _request_origin_host(request)
    return origin_host in _command_center_hosts()


class GlobalAuthMiddleware(BaseHTTPMiddleware):
    """Enforces JWT authentication on all /api/* routes except whitelisted public paths."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not path.startswith("/api/"):
            return await call_next(request)

        if not _is_allowed_internal_request(request):
            return JSONResponse(
                status_code=403,
                content={
                    "type": "https://fortress/errors/ingress-boundary",
                    "title": "Ingress Boundary Violation",
                    "status": 403,
                    "detail": "Internal routes are restricted to crog-ai.com or signed command-center ingress.",
                    "instance": path,
                },
            )

        if is_public_api_path(path, request.method):
            return await call_next(request)

        if "/download/" in path and path.startswith(f"{INTERNAL_LEGAL_API_PREFIX}/cases/"):
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "type": "https://fortress/errors/auth",
                    "title": "Authentication Required",
                    "status": 401,
                    "detail": "Missing or invalid Bearer token",
                    "instance": path,
                },
            )

        token = auth_header[7:]
        try:
            from backend.core.security import decode_token
            payload = decode_token(token)
            if not payload.get("sub"):
                raise ValueError("Missing sub claim")
        except Exception:
            return JSONResponse(
                status_code=401,
                content={
                    "type": "https://fortress/errors/auth",
                    "title": "Invalid Token",
                    "status": 401,
                    "detail": "Token is invalid or expired",
                    "instance": path,
                },
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Request Logging Middleware
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(
                "request_error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=str(exc)[:500],
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "request_complete",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-duration-ms"] = str(duration_ms)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    app.state.arq_pool = None
    logger.info(
        "starting_fortress_guest_platform",
        environment=settings.environment,
        version="1.0.0",
    )

    # Phase 2.5: initialise model registry (non-fatal if atlas missing)
    try:
        from backend.services.model_registry import initialise as _init_registry
        _init_registry()
        logger.info("model_registry_initialized")
    except Exception as _mr_exc:
        logger.warning("model_registry_init_skipped", error=str(_mr_exc))

    try:
        await init_db()
        logger.info("database_initialized")

        from backend.core.schema_audit import run_schema_audit
        from backend.core.database import get_async_engine
        await run_schema_audit(get_async_engine())
    except RuntimeError as e:
        if "SCHEMA AUDIT FAILED" in str(e):
            logger.critical("startup_aborted_schema_mismatch", error=str(e))
            raise
        logger.warning("database_init_skipped", error=str(e), note="App will run without DB - configure DATABASE_URL")
    except Exception as e:
        logger.warning("database_init_skipped", error=str(e), note="App will run without DB - configure DATABASE_URL")

    try:
        app.state.arq_pool = await create_arq_pool()
        logger.info("arq_pool_initialized", queue_name=settings.arq_queue_name)
    except Exception as e:
        logger.warning("arq_pool_init_skipped", error=str(e), queue_name=settings.arq_queue_name)

    async def _deferred_kb_sync_enqueue():
        await asyncio.sleep(5)
        try:
            from backend.core.qdrant import ensure_collection
            qdrant_ready = await ensure_collection()
            if qdrant_ready:
                logger.info("qdrant_fgp_knowledge_ready")
                from backend.services.qdrant_dual_writer import log_read_endpoint_at_startup
                log_read_endpoint_at_startup()
                from backend.core.database import AsyncSessionLocal
                from backend.services.async_jobs import enqueue_async_job

                if app.state.arq_pool is None:
                    logger.warning("kb_vectorization_enqueue_skipped", error="ARQ pool unavailable")
                    return
                async with AsyncSessionLocal() as kb_session:
                    job = await enqueue_async_job(
                        kb_session,
                        worker_name="sync_knowledge_base_job",
                        job_name="sync_knowledge_base",
                        payload={"reason": "startup_bootstrap"},
                        requested_by="system_startup",
                        tenant_id=None,
                        request_id="startup-bootstrap",
                        redis=app.state.arq_pool,
                    )
                    logger.info("kb_vectorization_enqueued", job_id=str(job.id))
            else:
                logger.warning("qdrant_fgp_knowledge_unavailable")
        except Exception as e:
            logger.warning("qdrant_init_skipped", error=str(e))

    kb_sync_task = asyncio.create_task(_deferred_kb_sync_enqueue())

    from backend.workers.hermes_daily_auditor import hermes_daily_auditor_loop
    auditor_task = asyncio.create_task(hermes_daily_auditor_loop())

    # Streamline full sync (sync_all) runs in a dedicated process:
    # systemd fortress-sync-worker → python -m backend.sync
    logger.info("streamline_full_sync_delegated_to_sync_worker")

    yield

    kb_sync_task.cancel()
    auditor_task.cancel()
    if app.state.arq_pool is not None:
        await app.state.arq_pool.aclose()
    from backend.core.http_client import close_shared_client
    await close_shared_client()
    from backend.core.event_publisher import close_event_publisher
    await close_event_publisher()
    await close_db()
    logger.info("fortress_guest_platform_shutdown")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Fortress Guest Platform",
    description="Enterprise Guest Communication System",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware (order matters — last added = first executed)
app.add_middleware(TenantMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(GlobalAuthMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://crog-ai.com",
        "https://www.crog-ai.com",
        "https://api.cabin-rentals-of-georgia.com",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://192.168.0.100:3001",
        "http://192.168.0.114:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Health Check (public)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Fortress Guest Platform",
        "version": "1.0.0",
        "environment": settings.environment,
    }


# ---------------------------------------------------------------------------
# Register API Routers
# ---------------------------------------------------------------------------
app.include_router(auth_api.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(internal_health_api.router, tags=["Internal Health"])
app.include_router(properties.router, prefix="/api/properties", tags=["Properties"])
app.include_router(reservations.router, prefix="/api/reservations", tags=["Reservations"])
app.include_router(guests.router, prefix="/api/guests", tags=["Guests"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(workorders.router, prefix="/api/work-orders", tags=["Work Orders"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(webhooks_channex.router, prefix="/api/webhooks/channex", tags=["Channex Webhooks"])
app.include_router(
    webhooks_channex.router,
    prefix="/webhooks/channex",
    tags=["Channex Webhooks Legacy Compatibility"],
    include_in_schema=False,
)
app.include_router(guestbook.router, prefix="/api/guestbook", tags=["Guestbook"])
app.include_router(integrations_api.router, prefix="/api/integrations", tags=["Integrations"])
app.include_router(booking.router, prefix="/api/booking", tags=["Booking"])
app.include_router(housekeeping.router, prefix="/api/housekeeping", tags=["Housekeeping"])
app.include_router(channels.router, prefix="/api/channels", tags=["Channels"])
app.include_router(agent.router, prefix="/api/agent", tags=["AI Agent"])
app.include_router(paperclip_bridge_api.router, prefix="/api/agent", tags=["Paperclip Bridge"])
app.include_router(paperclip_bridge_api.router, prefix="/api/paperclip", tags=["Paperclip Bridge"])
app.include_router(portal_api.router, prefix="/api/portal", tags=["Portal"])
app.include_router(review_queue.router, prefix="/api/review-queue", tags=["Review Queue"])
app.include_router(email_bridge.router, prefix="/api/email-bridge", tags=["Email Bridge"])
app.include_router(email_outbound_drafts_api.router)
app.include_router(damage_claims.router, prefix="/api/damage-claims", tags=["Damage Claims"])
app.include_router(tenants_api.router, prefix="/api/tenants", tags=["Tenants"])
app.include_router(owner_portal.router, prefix="/api/owner", tags=["Owner Portal"])
app.include_router(direct_booking_api.router, prefix="/api/direct-booking", tags=["Direct Booking"])
app.include_router(guest_portal_api.router, prefix="/api/guest-portal", tags=["Guest Portal"])
app.include_router(channel_mgr.router, prefix="/api/channel-manager", tags=["Channel Manager"])
app.include_router(channel_mappings_api.router, prefix="/api/channel-mappings", tags=["Channel Mappings"])
app.include_router(cleaners_api.router, prefix="/api/cleaners", tags=["Cleaners"])
app.include_router(vendors_api.router, prefix="/api/vendors", tags=["Vendors"])
app.include_router(acquisition_pipeline_api.router, prefix="/api/acquisition", tags=["Acquisition Pipeline"])
app.include_router(ai_superpowers.router, prefix="/api/ai", tags=["AI Superpowers"])
app.include_router(iot_api.router, prefix="/api/iot", tags=["IoT"])
app.include_router(search_api.router, prefix="/api/search", tags=["Search"])
app.include_router(inspections_api.router, prefix="/api/inspections", tags=["Inspections"])
app.include_router(utilities_api.router, prefix="/api/utilities", tags=["Utilities"])
app.include_router(invites_api.router, prefix="/api/invites", tags=["Invites"])
app.include_router(agreements_api.router, prefix="/api/agreements", tags=["Agreements"])
app.include_router(payments_api.router, prefix="/api/payments", tags=["Payments"])
# Before /api/quotes/{quote_id} so POST /api/quotes/calculate is not swallowed as a UUID path.
app.include_router(fast_quote_api.router, tags=["Fast Quote"])
app.include_router(quotes_api.router, prefix="/api/quotes", tags=["Quotes"])
app.include_router(vrs_quotes_api.router, prefix="/api/quotes", tags=["Sovereign Quotes"])
app.include_router(leads_api.router, prefix="/api/leads", tags=["Leads"])
app.include_router(vrs_api.router, prefix="/api/vrs", tags=["VRS Command Center"])
app.include_router(vrs_operations_api.router, prefix="/api/vrs", tags=["VRS Operations"])
app.include_router(checkout_api.router, prefix="/api/checkout", tags=["Checkout Gateway"])
app.include_router(templates_api.router, prefix="/api/templates", tags=["Templates"])
app.include_router(copilot_queue_api.router, prefix="/api/copilot-queue", tags=["Copilot Queue"])
app.include_router(stripe_webhooks.router, prefix="/api/webhooks", tags=["Stripe Webhooks"])
app.include_router(stripe_connect_webhooks.router, prefix="/api/webhooks", tags=["Stripe Connect Webhooks"])
app.include_router(admin_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_acquisition_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_acquisition_foia_api.router, tags=["Admin"])
app.include_router(admin_channex_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_insights_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_statements_api.router, prefix="/api/v1/admin", tags=["Owner Statements"])
app.include_router(admin_payouts_api.router, prefix="/api/admin/payouts", tags=["Admin Payouts"])
app.include_router(admin_charges_api.router, prefix="/api/admin/payouts", tags=["Admin Owner Charges"])
app.include_router(admin_stmts_workflow_api.router, prefix="/api/admin/payouts", tags=["Admin Statement Workflow"])
app.include_router(rule_engine_api.router, prefix="/api/rules", tags=["Rule Engine"])
app.include_router(intelligence_api.router, prefix="/api/intelligence", tags=["Intelligence"])
app.include_router(intelligence_feed_api.router, prefix="/api/intelligence/feed", tags=["Intelligence Feed"])
app.include_router(
    intelligence_projection_api.router,
    prefix="/api/intelligence/projection",
    tags=["Intelligence Projection"],
)
app.include_router(vault_api.router, prefix="/api/vault", tags=["E-Discovery Vault"])
app.include_router(legal_council_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Council"])
app.include_router(ediscovery_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["E-Discovery"])
app.include_router(legal_docgen_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal DocGen"])
app.include_router(legal_graph_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Graph"])
app.include_router(legal_discovery_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Discovery"])
app.include_router(legal_cases_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Cases"])
app.include_router(legal_strategy_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Strategy"])
app.include_router(legal_counsel_dispatch_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Outside Counsel Dispatch"])
app.include_router(legal_hold_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Hold"])
app.include_router(legal_tactical_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Tactical"])
app.include_router(legal_sanctions_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Sanctions"])
app.include_router(legal_deposition_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Deposition"])
app.include_router(legal_agent_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Agent"])
app.include_router(legal_email_intake_api.router, prefix=INTERNAL_LEGAL_API_PREFIX, tags=["Legal Email Intake"])
app.include_router(verses_api.router, prefix="/api/verses", tags=["Verses In Bloom"])
app.include_router(seo_patches_api.router, prefix="/api/seo", tags=["SEO"])
app.include_router(
    seo_patches_api.router,
    prefix="/api/seo-patches",
    tags=["SEO Compatibility"],
    include_in_schema=False,
)
app.include_router(wealth_api.router, prefix="/api/wealth", tags=["Wealth & Development"])
app.include_router(reservation_webhooks.router, prefix="/api/webhooks", tags=["Reservation Webhooks"])
app.include_router(dispute_webhooks.router, prefix="/api/webhooks", tags=["Dispute Webhooks"])
app.include_router(contracts_api.router, prefix="/api/admin/contracts", tags=["Management Contracts"])
app.include_router(disputes_api.router, prefix="/api/admin/disputes", tags=["Dispute Exception Desk"])
app.include_router(system_sensors_api.router, prefix="/api/system/sensors", tags=["System Sensors"])
app.include_router(system_health_api.router, prefix="/api/system/health", tags=["System Health Hardware"])
app.include_router(system_nodes_api.router, prefix="/api/system/nodes", tags=["System Nodes"])
app.include_router(system_dashboard_api.router, prefix="/api/system", tags=["Staff Dashboard Aggregate"])
app.include_router(ops_api.router, prefix="/api")
app.include_router(vrs_health_api.router, tags=["VRS Health"])
app.include_router(vrs_treasury_api.router, prefix="/api/vrs/treasury", tags=["OTA Warfare"])
app.include_router(hunter_api.router, prefix="/api", tags=["Reactivation Hunter"])
app.include_router(concierge_api.router, tags=["Concierge"])
app.include_router(contact_form.router, prefix="/api/dispatch", tags=["Autonomous Dispatch"])
app.include_router(internal_deck_api.router, prefix="/api/internal", tags=["Internal Deck"])
app.include_router(redirect_vanguard_admin_api.router, prefix="/api/internal", tags=["Redirect Vanguard"])
app.include_router(storefront_calendar_api.router, prefix="/api/v1/calendar", tags=["Storefront Calendar"])
app.include_router(storefront_catalog_api.router, prefix="/api/storefront/catalog", tags=["Storefront Catalog"])
app.include_router(tax_reports_api.router, prefix="/api/v1/tax-reports", tags=["Tax Reports"])
app.include_router(storefront_intent_api.router, prefix="/api/storefront/intent", tags=["Storefront Intent"])
app.include_router(storefront_demand_api.router, prefix="/api/storefront/demand", tags=["Storefront Demand"])
app.include_router(storefront_concierge_api.router, prefix="/api/storefront/concierge", tags=["Storefront Concierge"])
app.include_router(disagg_admin_api.router, prefix="/api/disagg/admin", tags=["Disagg Admin"])
app.include_router(telemetry_api.router, prefix="/api/telemetry", tags=["Telemetry"])
app.include_router(command_c2_api.router, prefix="/api/telemetry", tags=["Command C2"])
app.include_router(sovereign_pulse_api.router, prefix="/api/telemetry", tags=["Sovereign Pulse"])
app.include_router(funnel_hq_api.router, prefix="/api/telemetry", tags=["Sovereign Pulse"])
app.include_router(openshell_audit_api.router, prefix="/api/openshell/audit", tags=["OpenShell Audit"])
app.include_router(legacy_pages_api.router, prefix="/api/v1/pages", tags=["Legacy Pages"])
app.include_router(activities_api.router, prefix="/api/v1/activities", tags=["Activities"])
app.include_router(blogs_api.router, prefix="/api/v1/blogs", tags=["Blogs"])
app.include_router(financial_approvals_api.router, prefix="/api/v1/financial-approvals", tags=["Financial Approvals"])
app.include_router(storefront_checkout_api.router, prefix="/api/v1/checkout", tags=["Storefront Checkout"])
app.include_router(shadow_router_api.router, prefix="/api/v1/shadow", tags=["Shadow Router"])
app.include_router(
    trust_ledger_command_center_api.router,
    prefix="/api/trust-ledger/command-center",
    tags=["Trust Ledger Command Center"],
)


# ---------------------------------------------------------------------------
# Static files / Frontend fallback
# ---------------------------------------------------------------------------
_frontend_dist = Path(__file__).resolve().parent.parent / "apps" / "storefront" / "out"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


# ---------------------------------------------------------------------------
# WebSocket for real-time updates — delegates to core.websocket.manager
# ---------------------------------------------------------------------------
from backend.core.websocket import manager as ws_manager


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            _bg_task_heartbeats["ws_client"] = time.time()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
