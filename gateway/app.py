"""
Fortress Prime — Enterprise API Gateway
==========================================
Single entry point for ALL Fortress services.

Consolidates 6+ standalone FastAPI apps behind unified auth,
rate limiting, and CORS.

Run:
    uvicorn gateway.app:app --host 0.0.0.0 --port 8000 --workers 4

Route Map:
    /v1/auth/*          Authentication (login, keys, users)
    /v1/ops/*           Division 3 Operations Engine
    /v1/legal/*         Division 1 Legal OS (Fortress JD)
    /v1/finance/*       CF-04 Audit Ledger
    /v1/boardroom/*     Holding Company Executive Orders
    /v1/webhook/*       Plaid + External Webhooks
    /v1/sovereign/*     Sovereign Orchestrator
    /v1/guardian/*      CF-01 Vision Inspection
    /v1/quant/*         CF-02 Dynamic Pricing
    /health             System health (public)
    /static/*           Static files
    /ui/*               HTML interfaces
"""

import os
import sys
import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from gateway.db import get_pool, close_pool, ping as db_ping
from gateway.schema import init_schema
from gateway.auth import require_auth
from gateway.middleware import RequestLoggingMiddleware, RateLimitMiddleware
from gateway.users import router as auth_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# CORS origins — from config.py or env override
# ---------------------------------------------------------------------------

try:
    from config import CORS_ORIGINS
except ImportError:
    CORS_ORIGINS = []

_env_origins = os.getenv("GATEWAY_CORS_ORIGINS", "")
if _env_origins:
    CORS_ORIGINS = list(set(CORS_ORIGINS + [o.strip() for o in _env_origins.split(",") if o.strip()]))

# Always allow localhost for development
for origin in [
    "http://localhost:8501",
    "http://localhost:3000",
    "http://localhost:8000",
]:
    if origin not in CORS_ORIGINS:
        CORS_ORIGINS.append(origin)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB pool + auth schema on startup, cleanup on shutdown."""
    logger.info("=" * 60)
    logger.info("  FORTRESS PRIME — API GATEWAY STARTING")
    logger.info("=" * 60)

    # Init gateway DB pool
    pool = get_pool()
    logger.info(f"  DB pool initialized")

    # Ensure auth tables exist
    conn = pool.getconn()
    try:
        init_schema(conn)
    finally:
        pool.putconn(conn)

    # Initialize service-specific pools that would normally start via on_event
    try:
        from src.ops_api import init_pool as ops_init_pool
        ops_init_pool()
        logger.info("  Ops Engine DB pool initialized")
    except Exception as e:
        logger.error(f"  Ops Engine pool init failed: {e}")

    logger.info("  Auth schema ready")
    logger.info(f"  CORS origins: {CORS_ORIGINS}")
    logger.info("  Gateway ONLINE")
    logger.info("=" * 60)

    yield

    # Shutdown
    try:
        from src.ops_api import pool as ops_pool
        if ops_pool:
            ops_pool.closeall()
    except Exception:
        pass

    close_pool()
    logger.info("Gateway shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Fortress Prime API Gateway",
    description="Unified Enterprise API — Cabin Rentals of Georgia",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Middleware (order matters: first added = outermost) ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware, auth_limit=200, anon_limit=30)
app.add_middleware(RequestLoggingMiddleware)

# --- Static files ---
STATIC_DIR = PROJECT_ROOT / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- Auth router (always available, no prefix beyond /v1/auth) ---
app.include_router(auth_router)


# ---------------------------------------------------------------------------
# Import and mount service routers
# ---------------------------------------------------------------------------
# Each import is wrapped in try/except so the gateway starts even if
# a single service has import errors.

def _mount_router(prefix: str, module_path: str, attr: str = "router",
                  tags: list = None):
    """Safely import and mount a router (standard importlib)."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        rtr = getattr(mod, attr)
        app.include_router(rtr, prefix=prefix, tags=tags or [])
        logger.info(f"  Mounted {prefix} <- {module_path}.{attr}")
    except Exception as e:
        logger.error(f"  FAILED to mount {prefix} <- {module_path}: {e}")


def _mount_router_from_file(prefix: str, file_path: str, module_name: str,
                            attr: str = "router", tags: list = None):
    """Safely import from a file path (for hyphenated directories) and mount."""
    import importlib.util
    fp = PROJECT_ROOT / file_path
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(fp))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rtr = getattr(mod, attr)
        app.include_router(rtr, prefix=prefix, tags=tags or [])
        logger.info(f"  Mounted {prefix} <- {file_path} ({attr})")
    except Exception as e:
        logger.error(f"  FAILED to mount {prefix} <- {file_path}: {e}")


# Ops Engine (Division 3)
_mount_router("/v1/ops", "src.ops_api", "router", ["Operations"])

# Legal OS (Division 1)
_mount_router("/v1/legal", "src.legal_api", "router", ["Legal"])

# Audit Ledger (CF-04) — needs special handling for relative import
try:
    import importlib
    import importlib.util

    # First, load ledger_engine so the relative import works
    _le_path = PROJECT_ROOT / "Modules" / "CF-04_AuditLedger" / "ledger_engine.py"
    _le_spec = importlib.util.spec_from_file_location(
        "Modules.CF_04_AuditLedger.ledger_engine", str(_le_path)
    )
    _le_mod = importlib.util.module_from_spec(_le_spec)
    import sys as _sys
    _sys.modules["Modules.CF_04_AuditLedger.ledger_engine"] = _le_mod
    _le_spec.loader.exec_module(_le_mod)

    # Now load the api module with the parent package set
    _api_path = PROJECT_ROOT / "Modules" / "CF-04_AuditLedger" / "api.py"
    _api_spec = importlib.util.spec_from_file_location(
        "Modules.CF_04_AuditLedger.api", str(_api_path),
        submodule_search_locations=[],
    )
    _api_mod = importlib.util.module_from_spec(_api_spec)
    _api_mod.__package__ = "Modules.CF_04_AuditLedger"
    _sys.modules["Modules.CF_04_AuditLedger"] = type(_sys)("Modules.CF_04_AuditLedger")
    _sys.modules["Modules.CF_04_AuditLedger"].ledger_engine = _le_mod
    _sys.modules["Modules.CF_04_AuditLedger.api"] = _api_mod
    _api_spec.loader.exec_module(_api_mod)

    app.include_router(_api_mod.router, prefix="/v1/finance", tags=["Finance"])
    logger.info("  Mounted /v1/finance <- CF-04_AuditLedger/api.py (router)")
except Exception as e:
    logger.error(f"  FAILED to mount /v1/finance <- CF-04_AuditLedger: {e}")

# Holding Company (Boardroom)
_mount_router("/v1/boardroom", "holding_company_api", "router", ["Boardroom"])

# Webhooks (Plaid + test)
_mount_router("/v1/webhook", "webhook_server", "webhook_router", ["Webhooks"])

# Sovereign (orchestrator, health, escalations)
_mount_router("/v1/sovereign", "webhook_server", "sovereign_router", ["Sovereign"])

# Guardian Ops (CF-01 Vision) — hyphenated directory
_mount_router_from_file(
    "/v1/guardian",
    "Modules/CF-01_GuardianOps/api.py",
    "cf01_api", "router", ["Guardian"],
)

# QuantRevenue (CF-02 Pricing) — hyphenated directory
_mount_router_from_file(
    "/v1/quant",
    "Modules/CF-02_QuantRevenue/api.py",
    "cf02_api", "router", ["QuantRevenue"],
)

# CROG — Flagship API for Next.js developer (properties + calendar)
try:
    from gateway.crog_api import router as crog_router
    app.include_router(crog_router, prefix="/v1/crog", tags=["CROG"])
    logger.info("  Mounted /v1/crog <- gateway.crog_api (CROG)")
except Exception as e:
    logger.error(f"  FAILED to mount /v1/crog: {e}")

# Legal CRM (Case Manager + Correspondence + Deadlines + Document Gen)
try:
    import importlib.util as _ilu
    _lcm_path = PROJECT_ROOT / "tools" / "legal_case_manager.py"
    _lcm_spec = _ilu.spec_from_file_location("legal_case_manager", str(_lcm_path))
    _lcm_mod = _ilu.module_from_spec(_lcm_spec)
    _lcm_spec.loader.exec_module(_lcm_mod)
    app.mount("/v1/legal-crm", _lcm_mod.app)
    logger.info("  Mounted /v1/legal-crm <- tools/legal_case_manager.py (sub-app)")
except Exception as e:
    logger.error(f"  FAILED to mount /v1/legal-crm <- tools/legal_case_manager.py: {e}")


# ---------------------------------------------------------------------------
# Gateway-level endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    """Aggregated system health (public, no auth required)."""
    db_ok = db_ping()
    return {
        "status": "OPERATIONAL" if db_ok else "DEGRADED",
        "service": "Fortress Prime API Gateway",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected" if db_ok else "unreachable",
    }


@app.get("/", tags=["System"])
def root():
    """Gateway root — redirect to docs."""
    return {
        "service": "Fortress Prime API Gateway",
        "docs": "/docs",
        "health": "/health",
        "version": "1.0.0",
    }


# --- HTML UI routes ---

@app.get("/ui/ops", include_in_schema=False)
def ui_field_ops():
    """Mobile Field Operations interface."""
    html_path = STATIC_DIR / "field_ops.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "field_ops.html not found"}, status_code=404)


@app.get("/ui/legal", include_in_schema=False)
def ui_legal_enterprise():
    """Enterprise Legal Dashboard."""
    html_path = STATIC_DIR / "firm_enterprise.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "firm_enterprise.html not found"}, status_code=404)


@app.get("/ui/legal/search", include_in_schema=False)
def ui_legal_search():
    """Legal Precedent Library search."""
    html_path = STATIC_DIR / "legal_search.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "legal_search.html not found"}, status_code=404)


@app.get("/ui/legal/war-room/{matter_id}", include_in_schema=False)
def ui_war_room(matter_id: str):
    """Legal War Room for specific matter."""
    html_path = STATIC_DIR / "war_room.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "war_room.html not found"}, status_code=404)
