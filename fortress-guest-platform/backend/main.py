"""
Fortress Guest Platform - Main FastAPI Application
Enterprise guest communication system
"""
import asyncio
import os
import time
import uuid
import traceback
import structlog
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import settings
from backend.core.database import init_db, close_db, get_db, async_engine
from backend.api import guests, messages, reservations, properties, workorders, analytics, webhooks, guestbook
from backend.api import integrations as integrations_api
from backend.api import booking, housekeeping, channels, agent
from backend.api import portal as portal_api
from backend.api import review_queue, email_bridge, damage_claims
from backend.api import tenants as tenants_api
from backend.api import owner_portal
from backend.api import direct_booking as direct_booking_api
from backend.api import guest_portal_api
from backend.api import channel_mgr
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
from backend.api import quotes as quotes_api
from backend.api import vrs_quotes as vrs_quotes_api
from backend.api import leads as leads_api
from backend.api import vrs_operations as vrs_operations_api
from backend.api import checkout as checkout_api
from backend.api import templates as templates_api
from backend.api import copilot_queue as copilot_queue_api
from backend.api import admin as admin_api
from backend.api import rule_engine as rule_engine_api
from backend.api import intelligence as intelligence_api
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
from backend.api import verses as verses_api
from backend.api import seo_patches as seo_patches_api
from backend.api import wealth as wealth_api
from backend.api import reservation_webhooks
from backend.api import contracts as contracts_api
from backend.api import dispute_webhooks
from backend.api import disputes as disputes_api
from backend.api import system_sensors as system_sensors_api
from backend.api import system_health as system_health_api
from backend.api import vrs_health as vrs_health_api
from backend.api import vrs_treasury as vrs_treasury_api
from backend.api import hunter as hunter_api
from backend.api import concierge as concierge_api
from backend.api import dispatch as dispatch_api
from backend.api import internal_deck as internal_deck_api
from backend.api import disagg_admin as disagg_admin_api
from backend.core.tenant import TenantMiddleware

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


# ---------------------------------------------------------------------------
# Global Auth Middleware — protects ALL /api/* routes by default
# ---------------------------------------------------------------------------
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/ws",
    "/webhooks/",
    "/dashboard",
    "/guestbook",
    "/portal/",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/sso",
    "/api/auth/command-center-url",
    "/api/auth/owner/request-magic-link",
    "/api/auth/owner/verify-magic-link",
    "/api/auth/owner/logout",
    "/api/guest-portal/",
    "/api/guestbook/",
    "/api/agreements/public/",
    "/api/direct-booking/availability",
    "/api/direct-booking/properties",
    "/api/seo-patches/live/",
    "/api/quotes/",
    "/api/seo-patches/proposals",
    "/api/seo-patches/bulk-proposals",
    "/api/checkout/",
    "/api/copilot-queue/",
    "/api/vrs/automations/",
    "/api/system/health/",
    "/api/vrs/system-pulse",
    "/api/vrs/leads/",
    "/api/webhooks/",
    "/api/dispatch/",
    "/api/internal/deck-key",
)


class GlobalAuthMiddleware(BaseHTTPMiddleware):
    """Enforces JWT authentication on all /api/* routes except whitelisted public paths."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not path.startswith("/api/"):
            return await call_next(request)

        if any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        if (
            path.startswith("/api/quotes/")
            and path not in ("/api/quotes", "/api/quotes/")
            and not path.endswith("/generate")
        ):
            if request.method == "GET" or path.endswith("/checkout"):
                return await call_next(request)

        if "/download/" in path and path.startswith("/api/legal/cases/"):
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
    logger.info(
        "starting_fortress_guest_platform",
        environment=settings.environment,
        version="1.0.0",
    )

    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.warning("database_init_skipped", error=str(e), note="App will run without DB - configure DATABASE_URL")

    async def _deferred_kb_sync():
        await asyncio.sleep(5)
        try:
            from backend.core.qdrant import ensure_collection
            qdrant_ready = await ensure_collection()
            if qdrant_ready:
                logger.info("qdrant_fgp_knowledge_ready")
                try:
                    from backend.services.knowledge_retriever import sync_knowledge_base_to_qdrant
                    from backend.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as kb_session:
                        synced = await sync_knowledge_base_to_qdrant(kb_session)
                        logger.info("kb_vectorization_complete", synced=synced)
                except Exception as kb_err:
                    logger.warning("kb_vectorization_failed", error=str(kb_err)[:200])
            else:
                logger.warning("qdrant_fgp_knowledge_unavailable")
        except Exception as e:
            logger.warning("qdrant_init_skipped", error=str(e))

    kb_sync_task = asyncio.create_task(_deferred_kb_sync())

    from backend.integrations.streamline_vrs import StreamlineVRS
    from backend.core.database import AsyncSessionLocal
    vrs = StreamlineVRS()
    sync_task = None
    if vrs.is_configured:
        async def _run_sync():
            while True:
                try:
                    async with AsyncSessionLocal() as db:
                        await vrs.sync_all(db)
                except Exception as e:
                    logger.error("streamline_sync_error", error=str(e)[:500])
                await asyncio.sleep(settings.streamline_sync_interval)
        sync_task = asyncio.create_task(_run_sync())
        logger.info("streamline_background_sync_started", interval=settings.streamline_sync_interval)
    else:
        logger.warning("streamline_not_configured")

    # --- VRS Event Consumer (Priority #2 from Forensic Audit) ---
    event_consumer_task = None
    try:
        from backend.vrs.application.event_consumer import process_automation_queue
        event_consumer_task = asyncio.create_task(process_automation_queue())
        logger.info("vrs_event_consumer_started")
    except Exception as e:
        logger.warning("vrs_event_consumer_start_failed", error=str(e)[:200])

    yield

    if event_consumer_task:
        event_consumer_task.cancel()
        try:
            await event_consumer_task
        except asyncio.CancelledError:
            pass
    if sync_task:
        sync_task.cancel()
    kb_sync_task.cancel()
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
app.include_router(properties.router, prefix="/api/properties", tags=["Properties"])
app.include_router(reservations.router, prefix="/api/reservations", tags=["Reservations"])
app.include_router(guests.router, prefix="/api/guests", tags=["Guests"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(workorders.router, prefix="/api/work-orders", tags=["Work Orders"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(guestbook.router, prefix="/api/guestbook", tags=["Guestbook"])
app.include_router(integrations_api.router, prefix="/api/integrations", tags=["Integrations"])
app.include_router(booking.router, prefix="/api/booking", tags=["Booking"])
app.include_router(housekeeping.router, prefix="/api/housekeeping", tags=["Housekeeping"])
app.include_router(channels.router, prefix="/api/channels", tags=["Channels"])
app.include_router(agent.router, prefix="/api/agent", tags=["AI Agent"])
app.include_router(portal_api.router, prefix="/api/portal", tags=["Portal"])
app.include_router(review_queue.router, prefix="/api/review-queue", tags=["Review Queue"])
app.include_router(email_bridge.router, prefix="/api/email-bridge", tags=["Email Bridge"])
app.include_router(damage_claims.router, prefix="/api/damage-claims", tags=["Damage Claims"])
app.include_router(tenants_api.router, prefix="/api/tenants", tags=["Tenants"])
app.include_router(owner_portal.router, prefix="/api/owner", tags=["Owner Portal"])
app.include_router(direct_booking_api.router, prefix="/api/direct-booking", tags=["Direct Booking"])
app.include_router(guest_portal_api.router, prefix="/api/guest-portal", tags=["Guest Portal"])
app.include_router(channel_mgr.router, prefix="/api/channel-manager", tags=["Channel Manager"])
app.include_router(ai_superpowers.router, prefix="/api/ai", tags=["AI Superpowers"])
app.include_router(iot_api.router, prefix="/api/iot", tags=["IoT"])
app.include_router(search_api.router, prefix="/api/search", tags=["Search"])
app.include_router(inspections_api.router, prefix="/api/inspections", tags=["Inspections"])
app.include_router(utilities_api.router, prefix="/api/utilities", tags=["Utilities"])
app.include_router(invites_api.router, prefix="/api/invites", tags=["Invites"])
app.include_router(agreements_api.router, prefix="/api/agreements", tags=["Agreements"])
app.include_router(payments_api.router, prefix="/api/payments", tags=["Payments"])
app.include_router(quotes_api.router, prefix="/api/quotes", tags=["Quotes"])
app.include_router(vrs_quotes_api.router, prefix="/api/quotes", tags=["Sovereign Quotes"])
app.include_router(leads_api.router, prefix="/api/leads", tags=["Leads"])
app.include_router(vrs_operations_api.router, prefix="/api/vrs", tags=["VRS Operations"])
app.include_router(checkout_api.router, prefix="/api/checkout", tags=["Checkout Gateway"])
app.include_router(templates_api.router, prefix="/api/templates", tags=["Templates"])
app.include_router(copilot_queue_api.router, prefix="/api/copilot-queue", tags=["Copilot Queue"])
app.include_router(stripe_webhooks.router, prefix="/api/webhooks", tags=["Stripe Webhooks"])
app.include_router(stripe_connect_webhooks.router, prefix="/api/webhooks", tags=["Stripe Connect Webhooks"])
app.include_router(admin_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(rule_engine_api.router, prefix="/api/rules", tags=["Rule Engine"])
app.include_router(intelligence_api.router, prefix="/api/intelligence", tags=["Intelligence"])
app.include_router(vault_api.router, prefix="/api/vault", tags=["E-Discovery Vault"])
app.include_router(legal_council_api.router, prefix="/api/legal", tags=["Legal Council"])
app.include_router(ediscovery_api.router, prefix="/api/legal", tags=["E-Discovery"])
app.include_router(legal_docgen_api.router, prefix="/api/legal", tags=["Legal DocGen"])
app.include_router(legal_graph_api.router, prefix="/api/legal", tags=["Legal Graph"])
app.include_router(legal_discovery_api.router, prefix="/api/legal", tags=["Legal Discovery"])
app.include_router(legal_cases_api.router, prefix="/api/legal", tags=["Legal Cases"])
app.include_router(legal_strategy_api.router, prefix="/api/legal", tags=["Legal Strategy"])
app.include_router(legal_counsel_dispatch_api.router, prefix="/api/legal", tags=["Outside Counsel Dispatch"])
app.include_router(legal_hold_api.router, prefix="/api/legal", tags=["Legal Hold"])
app.include_router(legal_tactical_api.router, prefix="/api/legal", tags=["Legal Tactical"])
app.include_router(legal_sanctions_api.router, prefix="/api/legal", tags=["Legal Sanctions"])
app.include_router(legal_deposition_api.router, prefix="/api/legal", tags=["Legal Deposition"])
app.include_router(legal_agent_api.router, prefix="/api/legal", tags=["Legal Agent"])
app.include_router(verses_api.router, prefix="/api/verses", tags=["Verses In Bloom"])
app.include_router(seo_patches_api.router, prefix="/api/seo-patches", tags=["SEO Patches"])
app.include_router(wealth_api.router, prefix="/api/wealth", tags=["Wealth & Development"])
app.include_router(reservation_webhooks.router, prefix="/api/webhooks", tags=["Reservation Webhooks"])
app.include_router(dispute_webhooks.router, prefix="/api/webhooks", tags=["Dispute Webhooks"])
app.include_router(contracts_api.router, prefix="/api/admin/contracts", tags=["Management Contracts"])
app.include_router(disputes_api.router, prefix="/api/admin/disputes", tags=["Dispute Exception Desk"])
app.include_router(system_sensors_api.router, prefix="/api/system/sensors", tags=["System Sensors"])
app.include_router(system_health_api.router, prefix="/api/system/health", tags=["System Health Hardware"])
app.include_router(vrs_health_api.router, tags=["VRS Health"])
app.include_router(vrs_treasury_api.router, prefix="/api/vrs/treasury", tags=["OTA Warfare"])
app.include_router(hunter_api.router, prefix="/api", tags=["Reactivation Hunter"])
app.include_router(concierge_api.router, tags=["Concierge"])
app.include_router(dispatch_api.router, prefix="/api/dispatch", tags=["Autonomous Dispatch"])
app.include_router(internal_deck_api.router, prefix="/api/internal", tags=["Internal Deck"])
app.include_router(disagg_admin_api.router, prefix="/api/disagg/admin", tags=["Disagg Admin"])


# ---------------------------------------------------------------------------
# Static files / Frontend fallback
# ---------------------------------------------------------------------------
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend-next" / "out"
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
