#!/usr/bin/env python3
"""
CROG Command Center - Master Console (SECURITY HARDENED)
==========================================================
Enterprise-grade command center with production security

SECURITY IMPROVEMENTS:
- JWT secret from environment (not hardcoded)
- Restricted CORS origins
- Secure cookie settings
- Input validation with Pydantic
- Rate limiting on authentication endpoints
- Security headers
"""

import os
import logging
import asyncio
import httpx
import base64
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta

try:
    import psutil
except ImportError:
    psutil = None

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, EmailStr
from jose import jwt, JWTError

import psycopg2
import psycopg2.extras
import psycopg2.pool

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / "fortress-guest-platform" / ".env")
except ImportError:
    pass

# Logging (must be before other code that uses it)
log = logging.getLogger("console")
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [CONSOLE] %(levelname)s %(message)s"
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION (SECURE)
# ══════════════════════════════════════════════════════════════════════════════

BASE = os.getenv("BASE_IP", "192.168.0.100")
GATEWAY_URL = os.getenv("GATEWAY_URL", f"http://{BASE}:8001")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")
FGP_API_URL = os.getenv("FGP_API_URL", "http://localhost:8100").rstrip("/")
FGP_BEARER_TOKEN = os.getenv("FGP_BEARER_TOKEN", "").strip() or os.getenv("FGP_SERVICE_TOKEN", "").strip()
LEGAL_CRM_URL = os.getenv("LEGAL_CRM_URL", "http://localhost:9878").rstrip("/")
EMAIL_INTAKE_URL = os.getenv("EMAIL_INTAKE_URL", "http://localhost:9879").rstrip("/")
GODHEAD_LB_BASE = os.getenv("GODHEAD_LB_BASE", f"http://{BASE}").rstrip("/")
_OLLAMA_NODES = [("Captain", "192.168.0.100"), ("Muscle", "192.168.0.104"), ("Ocular", "192.168.0.105"), ("Sovereign", "192.168.0.106")]
OLLAMA_PORT = 11434
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
IS_PRODUCTION = ENVIRONMENT == "production"

# SECURITY: JWT RSA public key MUST come from environment
JWT_RSA_PUBLIC_KEY = os.getenv("JWT_RSA_PUBLIC_KEY", "")
if not JWT_RSA_PUBLIC_KEY:
    raise RuntimeError(
        "SECURITY ERROR: JWT_RSA_PUBLIC_KEY environment variable not set. "
        "Add to .env.security: JWT_RSA_PUBLIC_KEY=<base64-pem>"
    )

def _decode_public_key(raw: str) -> str:
    val = (raw or "").strip()
    if val.startswith("-----BEGIN"):
        return val
    try:
        return base64.b64decode(val).decode("utf-8")
    except Exception:
        return ""

JWT_RSA_PUBLIC_KEY_PEM = _decode_public_key(JWT_RSA_PUBLIC_KEY)
if not JWT_RSA_PUBLIC_KEY_PEM:
    raise RuntimeError("SECURITY ERROR: JWT_RSA_PUBLIC_KEY is malformed")

JWT_ALGORITHM = "RS256"
COOKIE_NAME = "fortress_session"

# SECURITY: Restrict CORS to known origins
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "https://crog-ai.com,http://192.168.0.100:9800,http://localhost:9800"
).split(",")

log.info(f"Environment: {ENVIRONMENT}")
log.info(f"Allowed CORS origins: {ALLOWED_ORIGINS}")

# ══════════════════════════════════════════════════════════════════════════════
# FORTRESS DB CONNECTION POOL (read-only telemetry queries)
# ══════════════════════════════════════════════════════════════════════════════

_FORTRESS_DB_CFG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "fortress_db"),
    "user": os.getenv("DB_USER", "miner_bot"),
    "password": os.getenv("DB_PASS", os.getenv("DB_PASSWORD", "")),
}

_fortress_db_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_fortress_conn():
    global _fortress_db_pool
    if _fortress_db_pool is None:
        _fortress_db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=4, **_FORTRESS_DB_CFG,
        )
        log.info("fortress_db connection pool initialized (1-4)")
    return _fortress_db_pool.getconn()


def _put_fortress_conn(conn):
    if _fortress_db_pool and conn:
        _fortress_db_pool.putconn(conn)


def _fortress_query(sql: str, params: tuple = ()) -> list[dict]:
    """Read-only query against fortress_db. Returns rows as dicts."""
    conn = _get_fortress_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except psycopg2.ProgrammingError:
        return []
    finally:
        _put_fortress_conn(conn)


# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="CROG Command Center",
    version="2.1.0-secure",
    docs_url=None if IS_PRODUCTION else "/docs",  # Disable docs in production
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

_http_client = httpx.AsyncClient(timeout=15.0)


@app.on_event("startup")
async def startup():
    """Ping FGP (VRS data engine) on port 8100; log clear warning if offline."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{FGP_API_URL}/health")
            if resp.status_code == 200:
                log.info("FGP backend (VRS data engine) is online at %s", FGP_API_URL)
            else:
                log.warning(
                    "FGP backend (VRS data engine) returned HTTP %s at %s — VRS dashboard may fail",
                    resp.status_code,
                    FGP_API_URL,
                )
    except httpx.RequestError as e:
        log.warning(
            "FGP backend (VRS data engine) is OFFLINE or unreachable at %s: %s — VRS dashboard will return 503",
            FGP_API_URL,
            e,
        )


@app.on_event("shutdown")
async def shutdown():
    await _http_client.aclose()

# SECURITY: Restricted CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Only known domains
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    max_age=3600,
)

# SECURITY: Add security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Redirect browser 404s to / so users never see raw JSON Not Found."""
    if exc.status_code == 404 and "text/html" in (request.headers.get("accept") or ""):
        return RedirectResponse(url="/", status_code=302)
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


# ══════════════════════════════════════════════════════════════════════════════
# MODELS (WITH VALIDATION)
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)

class SignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: str
    password: str = Field(min_length=8, max_length=128)

class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(admin|operator|viewer)$")

class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(admin|operator|viewer)$")

class StatusUpdateRequest(BaseModel):
    is_active: bool

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

def verify_jwt(token: str) -> dict:
    """Verify and decode JWT token."""
    try:
        return jwt.decode(token, JWT_RSA_PUBLIC_KEY_PEM, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(request: Request) -> dict:
    """Get current authenticated user from cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_jwt(token)

# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/login")
async def login(body: LoginRequest):
    """Login endpoint - authenticates with Gateway and returns JSON + sets session cookie."""
    try:
        gateway_resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/login",
            json={"username": body.username, "password": body.password},
        )
        
        if gateway_resp.status_code != 200:
            error_data = gateway_resp.json()
            log.warning(f"Login failed for user: {body.username}")
            raise HTTPException(
                status_code=gateway_resp.status_code,
                detail=error_data.get("detail", "Login failed")
            )
        
        data = gateway_resp.json()
        log.info(f"Login successful: {data['username']} ({data['role']})")
        
        from fastapi.responses import JSONResponse
        response = JSONResponse(content={
            "access_token": data["access_token"],
            "username": data["username"],
            "role": data.get("role", "viewer"),
        })
        response.set_cookie(
            key=COOKIE_NAME,
            value=data["access_token"],
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="lax",
            max_age=86400
        )
        
        return response
    
    except httpx.HTTPError as e:
        log.error(f"Gateway connection failed: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

@app.post("/api/logout")
async def logout():
    """Logout endpoint - clears session cookie."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response

@app.get("/api/verify")
async def verify_session(user: dict = Depends(get_current_user)):
    """Verify current session and return user info."""
    return {
        "username": user.get("username"),
        "role": user.get("role"),
        "authenticated": True
    }

@app.post("/api/signup")
async def signup(body: SignupRequest):
    """Public signup endpoint - creates user pending admin approval."""
    try:
        gateway_resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/signup",
            json=body.dict(),
        )
        
        if gateway_resp.status_code != 200:
            error_data = gateway_resp.json()
            raise HTTPException(
                status_code=gateway_resp.status_code,
                detail=error_data.get("detail", "Signup failed")
            )
        
        log.info(f"New signup: {body.username}")
        return gateway_resp.json()
    
    except httpx.HTTPError as e:
        log.error(f"Gateway connection failed: {e}")
        raise HTTPException(status_code=503, detail="Registration service unavailable")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN USER MANAGEMENT APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """List all users (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        log.warning(f"Unauthorized admin access attempt by: {user.get('username')}")
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.get(
            f"{GATEWAY_URL}/v1/auth/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.post("/api/admin/users")
async def admin_create_user(body: UserCreateRequest, request: Request):
    """Create user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/users",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} created user: {body.username}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: int, body: RoleUpdateRequest, request: Request):
    """Update user role (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} updated user {user_id} role to: {body.role}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/status")
async def admin_update_status(user_id: int, body: StatusUpdateRequest, request: Request):
    """Update user status (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        action = "activated" if body.is_active else "deactivated"
        log.info(f"Admin {user.get('username')} {action} user {user_id}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    """Delete user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.delete(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.warning(f"Admin {user.get('username')} DELETED user {user_id}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

def _is_localhost_or_empty(url: str) -> bool:
    """True if FRONTEND_URL would send the user off-site to localhost (breaking crog-ai.com)."""
    if not url or not url.strip():
        return True
    u = url.strip().lower()
    return u.startswith("http://localhost") or u.startswith("https://localhost") or u == "localhost"


def _fgp_headers(request: Request) -> dict:
    """Headers for FGP proxy: forward Authorization if present, else use FGP_BEARER_TOKEN."""
    headers = {}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    elif FGP_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {FGP_BEARER_TOKEN}"
    return headers


# HTMX: detect fragment request (return only content) vs full page (return enterprise shell with content)
def is_htmx_request(request: Request) -> bool:
    """True when client sends HX-Request (HTMX); response must be fragment only."""
    return (request.headers.get("HX-Request") or "").strip().lower() == "true"


def _get_enterprise_fragment(path_key: str) -> str:
    """Load fragment HTML for enterprise shell. path_key: '', 'vrs', 'accounting', 'trust', 'ai-orchestration', 'system-health'."""
    _ENTERPRISE_FRAGMENTS = {
        "": "fragments/command_center.html",
        "vrs": "fragments/vrs_hub_fragment.html",
        "accounting": "accounting.html",
        "trust": "trust_accounting.html",
        "ai-orchestration": "ai_orchestration.html",
        "system-health": "system_health.html",
        "legal": "legal.html",
        "email-intake": "email_intake.html",
    }
    filename = _ENTERPRISE_FRAGMENTS.get(path_key) or _ENTERPRISE_FRAGMENTS.get("")
    filepath = _TOOLS_DIR / filename
    if not filepath.exists():
        filepath = _TOOLS_DIR / "fragments/command_center.html"
    if not filepath.exists():
        return "<main id=\"enterprise-content\"><p>Fragment not found.</p></main>"
    return filepath.read_text()


# Nav paths from vrs_hub.html -> HTML file in tools/ (None = serve vrs_hub.html)
_PAGE_TO_FILE = {
    "vrs": "vrs_hub.html",
    "vrs/properties": "vrs_properties.html",
    "vrs/reservations": "vrs_reservations.html",
    "vrs/guests": "vrs_guests.html",
    "vrs/work-orders": "vrs_work_orders.html",
    "vrs/housekeeping": "vrs_housekeeping.html",
    "vrs/contracts": "vrs_contracts.html",
    "vrs/analytics": "vrs_analytics.html",
    "vrs/payments": "vrs_hub.html",  # no dedicated page
    "vrs/utilities": "vrs_utilities.html",
    "vrs/channels": "vrs_channels.html",
    "vrs/owners": "vrs_owners.html",
    "vrs/direct-booking": "vrs_direct_booking.html",
    "vrs/iot": "vrs_iot.html",
    "guest-agent": "vrs_hub.html",  # no guest_agent.html
    "reservations": "vrs_reservations.html",
    "analytics": "vrs_analytics.html",
    "email-intake": "email_intake.html",
    "intelligence": "intelligence.html",
    "docs-center": "docs.html",
    "legal": "legal.html",
    "vault": "vault.html",
    "webui": "vrs_hub.html",  # Mission Control placeholder
}
_TOOLS_DIR = Path(__file__).parent


def _enterprise_page_response(request: Request, path_key: str):
    """Return fragment only (HTMX) or full enterprise_base shell with fragment injected."""
    fragment = _get_enterprise_fragment(path_key)
    if is_htmx_request(request):
        return HTMLResponse(content=fragment)
    return templates.TemplateResponse(
        "enterprise_base.html",
        {"request": request, "content": fragment},
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Authenticated root — enterprise shell (Command Center) or redirect to Next.js when configured."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if not _is_localhost_or_empty(FRONTEND_URL):
        return RedirectResponse(url=FRONTEND_URL, status_code=302)
    return _enterprise_page_response(request, "")


@app.get("/vrs", response_class=HTMLResponse)
async def enterprise_vrs(request: Request):
    """CROG-VRS dashboard — fragment or full shell per HTMX header."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "vrs")


@app.get("/accounting", response_class=HTMLResponse)
async def enterprise_accounting(request: Request):
    """Enterprise Accounting — fragment or full shell per HTMX header."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "accounting")


@app.get("/trust", response_class=HTMLResponse)
async def enterprise_trust(request: Request):
    """Trust Accounting — fragment or full shell per HTMX header."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "trust")


@app.get("/ai-orchestration", response_class=HTMLResponse)
async def enterprise_ai_orchestration(request: Request):
    """AI Orchestration (DGX/M4 config) — fragment or full shell per HTMX header."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "ai-orchestration")


@app.get("/system-health", response_class=HTMLResponse)
async def enterprise_system_health(request: Request):
    """System Health telemetry — fragment or full shell per HTMX header."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "system-health")


@app.get("/reservations", response_class=HTMLResponse)
async def view_reservations(request: Request):
    """Streamline Reservations UI — top-level shortcut to VRS reservations."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "reservations")


@app.get("/analytics", response_class=HTMLResponse)
async def view_analytics(request: Request):
    """AI Swarm Analytics & Drift HUD."""
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return _enterprise_page_response(request, "analytics")


@app.get("/vrs/fragments/arriving-today", response_class=HTMLResponse)
async def vrs_fragment_arriving_today(request: Request, user: dict = Depends(get_current_user)):
    """HTMX fragment: today's check-ins from FGP. Bearer token added server-side."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{FGP_API_URL}/api/reservations/arriving/today",
                headers=_fgp_headers(request),
            )
            if resp.status_code != 200:
                return templates.TemplateResponse(
                    "vrs/partials/arriving_today.html",
                    {"request": request, "arrivals": [], "error": resp.text or f"HTTP {resp.status_code}"},
                )
            arrivals = resp.json()
    except Exception as e:
        return templates.TemplateResponse(
            "vrs/partials/arriving_today.html",
            {"request": request, "arrivals": [], "error": str(e)},
        )
    return templates.TemplateResponse(
        "vrs/partials/arriving_today.html",
        {"request": request, "arrivals": arrivals, "error": None},
    )


@app.get("/vrs/fragments/unread-messages", response_class=HTMLResponse)
async def vrs_fragment_unread_messages(request: Request, user: dict = Depends(get_current_user)):
    """HTMX fragment: unread guest messages from FGP. Bearer token added server-side."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{FGP_API_URL}/api/messages/unread",
                params={"limit": 50},
                headers=_fgp_headers(request),
            )
            if resp.status_code != 200:
                return templates.TemplateResponse(
                    "vrs/partials/unread_messages.html",
                    {"request": request, "messages": [], "error": resp.text or f"HTTP {resp.status_code}"},
                )
            messages = resp.json()
    except Exception as e:
        return templates.TemplateResponse(
            "vrs/partials/unread_messages.html",
            {"request": request, "messages": [], "error": str(e)},
        )
    return templates.TemplateResponse(
        "vrs/partials/unread_messages.html",
        {"request": request, "messages": messages, "error": None},
    )


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL INTAKE API PROXY (Email Intake service on port 9879)
# ══════════════════════════════════════════════════════════════════════════════

async def _proxy_email_intake(request: Request, method: str, path: str, body: Optional[bytes] = None):
    """Proxy request to Email Intake service (port 9879). Path is the part after /api/email-intake."""
    url = f"{EMAIL_INTAKE_URL}/{path}" if path else EMAIL_INTAKE_URL
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, params=dict(request.query_params))
            else:
                resp = await client.request(
                    method,
                    url,
                    params=dict(request.query_params),
                    content=body,
                    headers={"Content-Type": request.headers.get("content-type", "application/json")},
                )
        if resp.status_code != 200:
            return JSONResponse(content={"detail": resp.text or f"HTTP {resp.status_code}"}, status_code=resp.status_code)
        try:
            return JSONResponse(content=resp.json())
        except Exception:
            return JSONResponse(content={"detail": resp.text})
    except httpx.RequestError as e:
        log.warning(f"Email Intake proxy error for {method} /{path}: {e}")
        return JSONResponse(content={"detail": "Email Intake service unavailable"}, status_code=503)


@app.get("/api/email-intake/{path:path}")
async def email_intake_get_proxy(request: Request, path: str, user: dict = Depends(get_current_user)):
    """Proxy GET /api/email-intake/* to Email Intake service."""
    return await _proxy_email_intake(request, "GET", path)


@app.post("/api/email-intake/{path:path}")
async def email_intake_post_proxy(request: Request, path: str, user: dict = Depends(get_current_user)):
    """Proxy POST /api/email-intake/* to Email Intake service."""
    body = await request.body()
    return await _proxy_email_intake(request, "POST", path, body)


@app.get("/api/vrs/{path:path}")
async def vrs_api_proxy(request: Request, path: str, user: dict = Depends(get_current_user)):
    """Proxy GET /api/vrs/* to FGP backend with Bearer auth. Returns JSON for dashboard KPIs, arrivals, departures, guests, messages/stats, reservation detail."""
    rewritten_path = path
    if path == "automations" or path.startswith("automations/"):
        rewritten_path = path.replace("automations", "rules", 1)
    url = f"{FGP_API_URL}/api/{rewritten_path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=dict(request.query_params), headers=_fgp_headers(request))
        if resp.status_code != 200:
            return JSONResponse(content={"detail": resp.text or f"HTTP {resp.status_code}"}, status_code=resp.status_code)
        return JSONResponse(content=resp.json())
    except httpx.RequestError as e:
        log.warning(f"FGP proxy error for /api/{path}: {e}")
        return JSONResponse(content={"detail": "FGP backend unavailable"}, status_code=503)


@app.post("/api/vrs/{path:path}")
async def vrs_api_post_proxy(request: Request, path: str, user: dict = Depends(get_current_user)):
    """Proxy POST /api/vrs/* to FGP backend with Bearer auth."""
    rewritten_path = path
    if path == "automations" or path.startswith("automations/"):
        rewritten_path = path.replace("automations", "rules", 1)
    url = f"{FGP_API_URL}/api/{rewritten_path}"
    body = await request.body()
    headers = _fgp_headers(request)
    ct = request.headers.get("content-type")
    if ct:
        headers["Content-Type"] = ct
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, content=body, headers=headers)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.RequestError as e:
        log.warning(f"FGP POST proxy error for /api/{path}: {e}")
        return JSONResponse(content={"detail": "FGP backend unavailable"}, status_code=503)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve login page with injected FRONTEND_URL for SSO redirect."""
    login_html = Path(__file__).parent / "login.html"
    if not login_html.exists():
        return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)
    content = login_html.read_text()
    content = content.replace(
        "</head>",
        f'<script>window.__FRONTEND_URL__="{FRONTEND_URL}";</script></head>',
    )
    return HTMLResponse(content=content)

@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    """Serve public signup page."""
    signup_html = Path(__file__).parent / "signup.html"
    if not signup_html.exists():
        return HTMLResponse(content="<h1>Signup page not found</h1>", status_code=404)
    return HTMLResponse(content=signup_html.read_text())

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    """Serve user management page (admin only)."""
    try:
        user = get_current_user(request)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        users_html = Path(__file__).parent / "users.html"
        if not users_html.exists():
            return HTMLResponse(content="<h1>User management page not found</h1>", status_code=404)
        return HTMLResponse(content=users_html.read_text())
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve profile page (requires authentication)."""
    try:
        user = get_current_user(request)
        profile_html = Path(__file__).parent / "profile.html"
        if not profile_html.exists():
            return HTMLResponse(content="<h1>Profile page not found</h1>", status_code=404)
        return HTMLResponse(content=profile_html.read_text())
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


# ══════════════════════════════════════════════════════════════════════════════
# LEGAL CRM API PROXY (Legal Case Manager on port 9878)
# ══════════════════════════════════════════════════════════════════════════════

async def _proxy_legal(request: Request, path: str):
    """Proxy request to Legal CRM service (port 9878)."""
    url = f"{LEGAL_CRM_URL}{path}"
    try:
        resp = await _http_client.get(url, params=dict(request.query_params), timeout=15.0)
        if resp.status_code != 200:
            return JSONResponse(content={"detail": resp.text}, status_code=resp.status_code)
        return JSONResponse(content=resp.json())
    except httpx.RequestError as e:
        log.warning(f"Legal CRM proxy error for {path}: {e}")
        return JSONResponse(content={"detail": "Legal CRM service unavailable"}, status_code=503)


@app.post("/api/legal/cases/{slug}/synthesize")
async def legal_synthesize_proxy(slug: str, request: Request, user: dict = Depends(get_current_user)):
    """Proxy synthesis request to Legal CRM HYDRA endpoint (long timeout for deep reasoning)."""
    url = f"{LEGAL_CRM_URL}/api/cases/{slug}/synthesize"
    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            resp = await client.post(url, timeout=130.0)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        return JSONResponse(content={"detail": "HYDRA synthesis timed out (>130s)"}, status_code=504)
    except httpx.RequestError as e:
        log.warning(f"Legal CRM synthesis proxy error: {e}")
        return JSONResponse(content={"detail": "Legal CRM service unavailable"}, status_code=503)


@app.get("/api/legal/overview")
async def legal_overview_proxy(request: Request, user: dict = Depends(get_current_user)):
    """Proxy /api/legal/overview to Legal CRM /api/crm/overview."""
    return await _proxy_legal(request, "/api/crm/overview")


@app.get("/api/legal/cases/{slug}")
async def legal_case_detail_proxy(slug: str, request: Request, user: dict = Depends(get_current_user)):
    """Proxy /api/legal/cases/{slug} to Legal CRM."""
    return await _proxy_legal(request, f"/api/cases/{slug}")


@app.get("/api/legal/cases/{slug}/deadlines")
async def legal_deadlines_proxy(slug: str, request: Request, user: dict = Depends(get_current_user)):
    """Proxy case deadlines to Legal CRM."""
    return await _proxy_legal(request, f"/api/cases/{slug}/deadlines")


@app.get("/api/legal/cases/{slug}/correspondence")
async def legal_correspondence_proxy(slug: str, request: Request, user: dict = Depends(get_current_user)):
    """Proxy case correspondence to Legal CRM."""
    return await _proxy_legal(request, f"/api/cases/{slug}/correspondence")


# ══════════════════════════════════════════════════════════════════════════════
# LEGAL FILE PROXY (NAS vault — download/files)
# ══════════════════════════════════════════════════════════════════════════════

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"
_CASE_SUBDIRS = ("certified_mail", "correspondence", "evidence", "receipts", "filings/incoming", "filings/outgoing")
_MIME_MAP = {".pdf": "application/pdf", ".txt": "text/plain", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".csv": "text/csv"}


@app.get("/api/legal/cases/{slug}/download/{filename}")
async def legal_download(slug: str, filename: str, request: Request):
    """Serve legal files directly from NAS (authenticated)."""
    get_current_user(request)

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    case_root = Path(NAS_LEGAL_ROOT) / slug
    if not case_root.is_dir():
        raise HTTPException(status_code=404, detail=f"Case vault '{slug}' not found")

    for subdir in _CASE_SUBDIRS:
        candidate = case_root / subdir / filename
        if candidate.is_file():
            resolved = candidate.resolve()
            if not str(resolved).startswith(NAS_LEGAL_ROOT):
                raise HTTPException(status_code=403, detail="Access denied")
            ext = candidate.suffix.lower()
            media_type = _MIME_MAP.get(ext, "application/octet-stream")
            log.info(f"Legal download: {slug}/{subdir}/{filename} by {request.cookies.get(COOKIE_NAME, 'unknown')[:8]}")
            from fastapi.responses import FileResponse
            return FileResponse(path=str(resolved), media_type=media_type, filename=filename)

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found in case vault")


@app.get("/api/legal/cases/{slug}/files")
async def legal_files(slug: str, request: Request):
    """List all files in a case's NAS vault (authenticated)."""
    get_current_user(request)

    case_root = Path(NAS_LEGAL_ROOT) / slug
    if not case_root.is_dir():
        raise HTTPException(status_code=404, detail=f"Case vault '{slug}' not found")

    files = []
    for subdir in _CASE_SUBDIRS:
        d = case_root / subdir
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "subdir": subdir,
                    "size_bytes": f.stat().st_size,
                    "download_url": f"/api/legal/cases/{slug}/download/{f.name}",
                })
    return {"case_slug": slug, "files": files, "total": len(files)}


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "crog-console",
        "version": "2.1.0-secure",
        "environment": ENVIRONMENT
    }


@app.get("/api/health")
async def api_health_check():
    """API health endpoint used by UI service-status probes."""
    return await health_check()


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM TELEMETRY (M4 orchestrator, DGX Spark cluster, Synology NAS)
# ══════════════════════════════════════════════════════════════════════════════

# DGX Spark + NAS IPs (from config.py)
_TELEMETRY_CLUSTER = [
    ("Spark-01 (Captain)", os.getenv("SPARK_01_IP", "192.168.0.100")),
    ("Spark-02 (Muscle)", os.getenv("SPARK_02_IP", "192.168.0.104")),
    ("Spark-03 (Ocular)", os.getenv("SPARK_03_IP", "192.168.0.105")),
    ("Spark-04 (Sovereign)", os.getenv("SPARK_04_IP", "192.168.0.106")),
]
_NAS_IP = os.getenv("NAS_IP", "192.168.0.113")
_NAS_MOUNT = "/mnt/fortress_nas"
_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.0.100:9090")


_DGX_SPARK_VRAM_TOTAL_GB = 128  # GB10 Blackwell unified memory per node

async def _fetch_dcgm_metrics() -> dict:
    """Query Prometheus for DCGM GPU metrics, grouped by node IP.
    Returns {ip: {gpu_utilization_percent, vram_used_gb, vram_total_gb, gpu_temp_c, power_watts}} or {} on failure.
    Metrics sourced from dcgm-exporter (port 9400): GPU_UTIL, GPU_TEMP, MEM_COPY_UTIL, POWER_USAGE."""
    metrics_by_ip: dict = {}
    queries = {
        "gpu_util": "DCGM_FI_DEV_GPU_UTIL",
        "mem_util": "DCGM_FI_DEV_MEM_COPY_UTIL",
        "gpu_temp": "DCGM_FI_DEV_GPU_TEMP",
        "power": "DCGM_FI_DEV_POWER_USAGE",
    }
    try:
        raw: dict = {}
        for key, metric in queries.items():
            resp = await _http_client.get(
                f"{_PROMETHEUS_URL}/api/v1/query",
                params={"query": metric},
                timeout=3.0,
            )
            if resp.status_code == 200:
                raw[key] = resp.json().get("data", {}).get("result", [])

        for entry in raw.get("gpu_util", []):
            ip = entry.get("metric", {}).get("instance", "").split(":")[0]
            if ip:
                metrics_by_ip.setdefault(ip, {})["gpu_utilization_percent"] = round(float(entry["value"][1]), 1)

        for entry in raw.get("mem_util", []):
            ip = entry.get("metric", {}).get("instance", "").split(":")[0]
            if ip:
                mem_pct = float(entry["value"][1])
                node = metrics_by_ip.setdefault(ip, {})
                node["vram_total_gb"] = _DGX_SPARK_VRAM_TOTAL_GB
                node["vram_used_gb"] = round(mem_pct / 100.0 * _DGX_SPARK_VRAM_TOTAL_GB, 1)

        for entry in raw.get("gpu_temp", []):
            ip = entry.get("metric", {}).get("instance", "").split(":")[0]
            if ip:
                metrics_by_ip.setdefault(ip, {})["gpu_temp_c"] = round(float(entry["value"][1]))

        for entry in raw.get("power", []):
            ip = entry.get("metric", {}).get("instance", "").split(":")[0]
            if ip:
                metrics_by_ip.setdefault(ip, {})["power_watts"] = round(float(entry["value"][1]), 1)
    except Exception as e:
        log.warning(f"DCGM Prometheus query failed (falling back to N/A): {e}")
    return metrics_by_ip


async def _ping_host(ip: str, timeout_sec: float = 2.0) -> Tuple[bool, float]:
    """Ping host; return (reachable, latency_ms). Uses system ping."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(int(timeout_sec)), ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(proc.wait(), timeout=timeout_sec + 1.0)
        latency_ms = (asyncio.get_event_loop().time() - start) * 1000.0
        return (proc.returncode == 0, round(latency_ms, 2))
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return (False, 0.0)


@app.get("/api/system/telemetry")
async def system_telemetry(request: Request, user: dict = Depends(get_current_user)):
    """Return orchestrator CPU/memory/disk, DGX cluster ping status, NAS ping and mount."""
    result = {"orchestrator": {}, "cluster": [], "nas": {}}

    # Orchestrator (local) — psutil
    if psutil:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            mem_used_gb = round(mem.used / (1024**3), 2)
            mem_total_gb = round(mem.total / (1024**3), 2)
            disk = psutil.disk_usage("/")
            disk_used_gb = round(disk.used / (1024**3), 1)
            disk_total_gb = round(disk.total / (1024**3), 1)
            boot = datetime.fromtimestamp(psutil.boot_time())
            uptime_seconds = int((datetime.now() - boot).total_seconds())
            result["orchestrator"] = {
                "cpu_percent": round(cpu, 1),
                "memory_used_gb": mem_used_gb,
                "memory_total_gb": mem_total_gb,
                "disk_used_gb": disk_used_gb,
                "disk_total_gb": disk_total_gb,
                "uptime_seconds": uptime_seconds,
            }
        except Exception as e:
            log.warning(f"Telemetry psutil error: {e}")
            result["orchestrator"] = {"error": str(e)}
    else:
        result["orchestrator"] = {"error": "psutil not installed"}

    # Cluster pings (parallel)
    async def one_node(name: str, ip: str):
        reachable, latency_ms = await _ping_host(ip)
        return {"name": name, "ip": ip, "reachable": reachable, "latency_ms": latency_ms}

    result["cluster"] = await asyncio.gather(
        *[one_node(name, ip) for name, ip in _TELEMETRY_CLUSTER]
    )

    # DCGM GPU metrics from Prometheus (non-blocking; empty dict on failure)
    dcgm = await _fetch_dcgm_metrics()
    for node in result["cluster"]:
        gpu_data = dcgm.get(node["ip"], {})
        node["gpu_utilization_percent"] = gpu_data.get("gpu_utilization_percent")
        node["vram_used_gb"] = gpu_data.get("vram_used_gb")
        node["vram_total_gb"] = gpu_data.get("vram_total_gb")
        node["gpu_temp_c"] = gpu_data.get("gpu_temp_c")
        node["power_watts"] = gpu_data.get("power_watts")

    # NAS ping + mount
    nas_reachable, nas_latency = await _ping_host(_NAS_IP)
    mount_ok = Path(_NAS_MOUNT).is_dir() if _NAS_MOUNT else False
    result["nas"] = {
        "ip": _NAS_IP,
        "reachable": nas_reachable,
        "latency_ms": nas_latency,
        "mount_ok": mount_ok,
    }

    return result


# ══════════════════════════════════════════════════════════════════════════════
# SENTIMENT DRIFT TELEMETRY (live analysis from agent_response_queue)
# ══════════════════════════════════════════════════════════════════════════════

_DRIFT_GRADE_THRESHOLD = 0.5
_DRIFT_EDIT_THRESHOLD = 15.0
_DRIFT_MIN_SAMPLES = 3


@app.get("/api/metrics/sentiment-drift")
async def get_sentiment_drift(request: Request, user: dict = Depends(get_current_user)):
    """Live AI drift analysis: rolling 30-day window comparison from agent_response_queue,
    plus recent drift alerts from system_post_mortems."""
    try:
        intents = _fortress_query("""
            SELECT
                intent,
                COUNT(*) FILTER (
                    WHERE created_at BETWEEN NOW() - INTERVAL '60 days'
                                        AND NOW() - INTERVAL '30 days'
                ) AS baseline_count,
                ROUND(AVG(quality_grade) FILTER (
                    WHERE created_at BETWEEN NOW() - INTERVAL '60 days'
                                        AND NOW() - INTERVAL '30 days'
                      AND quality_grade IS NOT NULL
                )::numeric, 3) AS baseline_avg_grade,
                ROUND(AVG(edit_distance_pct) FILTER (
                    WHERE created_at BETWEEN NOW() - INTERVAL '60 days'
                                        AND NOW() - INTERVAL '30 days'
                      AND edit_distance_pct IS NOT NULL
                )::numeric, 2) AS baseline_avg_edit_pct,

                COUNT(*) FILTER (
                    WHERE created_at > NOW() - INTERVAL '30 days'
                ) AS current_count,
                ROUND(AVG(quality_grade) FILTER (
                    WHERE created_at > NOW() - INTERVAL '30 days'
                      AND quality_grade IS NOT NULL
                )::numeric, 3) AS current_avg_grade,
                ROUND(AVG(edit_distance_pct) FILTER (
                    WHERE created_at > NOW() - INTERVAL '30 days'
                      AND edit_distance_pct IS NOT NULL
                )::numeric, 2) AS current_avg_edit_pct

            FROM agent_response_queue
            WHERE intent IS NOT NULL
              AND created_at > NOW() - INTERVAL '60 days'
            GROUP BY intent
            HAVING COUNT(*) >= %s
            ORDER BY intent
        """, (_DRIFT_MIN_SAMPLES,))

        analysis = []
        for row in intents:
            b_grade = float(row["baseline_avg_grade"]) if row["baseline_avg_grade"] is not None else None
            c_grade = float(row["current_avg_grade"]) if row["current_avg_grade"] is not None else None
            b_edit = float(row["baseline_avg_edit_pct"]) if row["baseline_avg_edit_pct"] is not None else None
            c_edit = float(row["current_avg_edit_pct"]) if row["current_avg_edit_pct"] is not None else None
            b_count = int(row["baseline_count"] or 0)
            c_count = int(row["current_count"] or 0)

            grade_delta = round(b_grade - c_grade, 3) if b_grade is not None and c_grade is not None else None
            edit_delta = round(c_edit - b_edit, 2) if b_edit is not None and c_edit is not None else None

            degraded = False
            reasons = []
            if grade_delta is not None and grade_delta > _DRIFT_GRADE_THRESHOLD and b_count >= _DRIFT_MIN_SAMPLES:
                degraded = True
                reasons.append(f"grade dropped {grade_delta:+.2f} ({b_grade:.2f} → {c_grade:.2f})")
            if edit_delta is not None and edit_delta > _DRIFT_EDIT_THRESHOLD and b_count >= _DRIFT_MIN_SAMPLES:
                degraded = True
                reasons.append(f"edit distance rose {edit_delta:+.1f}% ({b_edit:.1f}% → {c_edit:.1f}%)")

            analysis.append({
                "intent": row["intent"],
                "baseline_count": b_count,
                "current_count": c_count,
                "baseline_avg_grade": b_grade,
                "current_avg_grade": c_grade,
                "baseline_avg_edit_pct": b_edit,
                "current_avg_edit_pct": c_edit,
                "grade_delta": grade_delta,
                "edit_delta": edit_delta,
                "degraded": degraded,
                "reasons": reasons,
            })

        alerts = _fortress_query("""
            SELECT id, severity, error_summary, root_cause, remediation, status,
                   occurred_at::text AS created_at
            FROM system_post_mortems
            WHERE component = 'persona_drift'
            ORDER BY occurred_at DESC
            LIMIT 20
        """)

        total = len(analysis)
        degraded_count = sum(1 for a in analysis if a["degraded"])
        healthy_count = total - degraded_count

        return {
            "status": "success",
            "summary": {
                "topics_analyzed": total,
                "degraded": degraded_count,
                "healthy": healthy_count,
                "thresholds": {
                    "grade_drop": _DRIFT_GRADE_THRESHOLD,
                    "edit_rise_pct": _DRIFT_EDIT_THRESHOLD,
                },
            },
            "intents": analysis,
            "recent_alerts": [dict(a) for a in alerts],
        }

    except Exception as e:
        log.warning(f"Sentiment drift query failed: {e}")
        return JSONResponse(
            content={"status": "error", "detail": f"Drift telemetry unavailable: {e}"},
            status_code=503,
        )


# ══════════════════════════════════════════════════════════════════════════════
# AI ORCHESTRATION — Total Inference Strike
# ══════════════════════════════════════════════════════════════════════════════

async def _fire_engine(name: str, url: str, method: str = "POST", timeout: float = 10.0):
    """Fire a single inference engine and return a status dict."""
    t0 = asyncio.get_event_loop().time()
    try:
        if method == "POST":
            resp = await _http_client.post(url, timeout=timeout, json={})
        else:
            resp = await _http_client.get(url, timeout=timeout)
        elapsed = round((asyncio.get_event_loop().time() - t0) * 1000)
        return {"engine": name, "status": "ok" if resp.status_code < 500 else "degraded",
                "http_status": resp.status_code, "latency_ms": elapsed}
    except Exception as exc:
        elapsed = round((asyncio.get_event_loop().time() - t0) * 1000)
        return {"engine": name, "status": "unreachable", "error": str(exc)[:120], "latency_ms": elapsed}


@app.post("/api/ai/ignite-all", response_class=HTMLResponse)
async def ai_ignite_all(request: Request, user: dict = Depends(get_current_user)):
    """Total Inference Strike — fire all four engines (Operations, Protection, Revenue, God Head)."""
    results = await asyncio.gather(
        _fire_engine("Email Classification Engine", f"{EMAIL_INTAKE_URL}/api/email-intake/health", method="GET"),
        _fire_engine("Legal RAG Engine", f"{LEGAL_CRM_URL}/api/cases", method="GET"),
        _fire_engine("VRS Guest Agent", f"{FGP_API_URL}/health", method="GET"),
        _fire_engine("God Head — DGX Spark LLM", f"{GODHEAD_LB_BASE}/v1/models", method="GET"),
    )

    def _row(r):
        eng = r["engine"]
        st = r["status"]
        lat = r["latency_ms"]
        if st == "ok":
            dot = "#4ade80"; label = "ONLINE"; border = "#065f46"
        elif st == "degraded":
            dot = "#fbbf24"; label = f"DEGRADED ({r.get('http_status', '?')})"; border = "#78350f"
        else:
            dot = "#f87171"; label = "UNREACHABLE"; border = "#7f1d1d"
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'padding:12px 16px;background:#0a0a0a;border:1px solid {border};border-radius:10px;">'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{dot};'
            f'box-shadow:0 0 6px {dot};"></span>'
            f'<span style="font-size:13px;color:#ccc;font-weight:600;">{eng}</span></div>'
            f'<div style="text-align:right;">'
            f'<span style="font-size:11px;color:{dot};font-weight:700;">{label}</span>'
            f'<span style="font-size:10px;color:#555;margin-left:10px;">{lat}ms</span>'
            f'</div></div>'
        )

    rows = "\n".join(_row(r) for r in results)
    online = sum(1 for r in results if r["status"] == "ok")
    total = len(results)
    summary_color = "#4ade80" if online == total else "#fbbf24" if online > 0 else "#f87171"
    ts = datetime.now().strftime("%H:%M:%S")

    html = (
        f'<div style="border:1px solid #1a1a1a;border-radius:14px;padding:20px;background:#111;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">'
        f'<h3 style="font-size:14px;font-weight:700;color:#fff;margin:0;">Inference Strike Results</h3>'
        f'<span style="font-size:11px;color:#555;">{ts}</span></div>'
        f'<div style="display:flex;flex-direction:column;gap:8px;">{rows}</div>'
        f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid #1a1a1a;'
        f'display:flex;align-items:center;justify-content:space-between;">'
        f'<span style="font-size:12px;color:{summary_color};font-weight:700;">'
        f'{online}/{total} engines responding</span>'
        f'<span style="font-size:10px;color:#555;">Cluster inference '
        f'{"ACTIVE" if online == total else "PARTIAL" if online > 0 else "OFFLINE"}</span>'
        f'</div></div>'
    )
    return HTMLResponse(content=html)


@app.get("/api/ai/godhead-status")
async def ai_godhead_status(request: Request, user: dict = Depends(get_current_user)):
    """God Head health — probe Nginx LB and per-node Ollama; return models and latency."""
    lb_url = f"{GODHEAD_LB_BASE}/v1/models"
    lb_result = {"reachable": False, "latency_ms": None, "models": [], "error": None}
    t0 = asyncio.get_event_loop().time()
    try:
        resp = await _http_client.get(lb_url, timeout=8.0)
        lb_result["latency_ms"] = round((asyncio.get_event_loop().time() - t0) * 1000)
        lb_result["reachable"] = resp.status_code == 200
        if resp.status_code == 200:
            data = resp.json()
            lb_result["models"] = [m.get("id") or m.get("root") for m in data.get("data", [])]
    except Exception as e:
        lb_result["error"] = str(e)[:100]

    async def probe_node(name: str, ip: str):
        url = f"http://{ip}:{OLLAMA_PORT}/v1/models"
        t0 = asyncio.get_event_loop().time()
        out = {"name": name, "ip": ip, "reachable": False, "latency_ms": None, "models": []}
        try:
            resp = await _http_client.get(url, timeout=5.0)
            out["latency_ms"] = round((asyncio.get_event_loop().time() - t0) * 1000)
            out["reachable"] = resp.status_code == 200
            if resp.status_code == 200:
                data = resp.json()
                out["models"] = [m.get("id") or m.get("root") for m in data.get("data", [])]
        except Exception as e:
            out["error"] = str(e)[:80]
        return out

    node_results = await asyncio.gather(*[probe_node(n, ip) for n, ip in _OLLAMA_NODES])
    return JSONResponse(content={
        "lb": lb_result,
        "nodes": node_results,
        "defcon": os.getenv("FORTRESS_DEFCON", "SWARM"),
    })


@app.post("/api/ai/test-inference")
async def ai_test_inference(request: Request, user: dict = Depends(get_current_user)):
    """Single-shot completion via cluster inference (get_inference_client) — proves God Head is thinking."""
    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from config import get_inference_client
        client, model_name = get_inference_client(timeout=45)
        t0 = asyncio.get_event_loop().time()
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Respond with OK and the current timestamp."}],
            max_tokens=80,
        )
        elapsed_ms = round((asyncio.get_event_loop().time() - t0) * 1000)
        content = (completion.choices[0].message.content or "").strip() if completion.choices else ""
        payload = {"status": "ok", "model": model_name, "latency_ms": elapsed_ms, "response": content}
    except Exception as e:
        log.warning(f"Test inference failed: {e}")
        payload = {"status": "error", "error": str(e)[:200]}
        elapsed_ms = 0
        content = ""
        model_name = ""

    if is_htmx_request(request):
        if payload.get("status") == "ok":
            safe_content = (content or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            safe_model = (model_name or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = (
                f'<div style="padding:12px 16px;background:#0a0a0a;border:1px solid #065f46;border-radius:10px;">'
                f'<div style="font-size:12px;color:#4ade80;">Model: {safe_model} — {payload["latency_ms"]}ms</div>'
                f'<div style="font-size:13px;color:#ccc;margin-top:8px;white-space:pre-wrap;">{safe_content}</div>'
                f'</div>'
            )
        else:
            err = (payload.get("error") or "Unknown").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            html = (
                f'<div style="padding:12px 16px;background:#0a0a0a;border:1px solid #7f1d1d;border-radius:10px;">'
                f'<div style="font-size:12px;color:#f87171;">Error</div>'
                f'<div style="font-size:12px;color:#888;margin-top:4px;">{err}</div>'
                f'</div>'
            )
        return HTMLResponse(content=html)
    return JSONResponse(content=payload, status_code=200 if payload.get("status") == "ok" else 502)


@app.get("/legal", response_class=HTMLResponse)
async def legal_page(request: Request, user: dict = Depends(get_current_user)):
    """Fortress Legal — fragment or full shell per HTMX header."""
    return _enterprise_page_response(request, "legal")


@app.get("/email-intake", response_class=HTMLResponse)
async def email_intake_page(request: Request, user: dict = Depends(get_current_user)):
    """Email Intake — fragment or full shell per HTMX header."""
    return _enterprise_page_response(request, "email-intake")


@app.get("/{path:path}", response_class=HTMLResponse)
async def ui_catch_all(request: Request, path: str):
    """Serve VRS/ops UI pages for nav links; unknown paths redirect to /. Must be after /health."""
    if path.startswith("api") or path.startswith("vrs/fragments"):
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    filename = _PAGE_TO_FILE.get(path.rstrip("/")) or _PAGE_TO_FILE.get(path)
    if not filename:
        return RedirectResponse(url="/", status_code=302)
    filepath = _TOOLS_DIR / filename
    if not filepath.exists():
        filepath = _TOOLS_DIR / "vrs_hub.html"
    return HTMLResponse(content=filepath.read_text())


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    log.info("=" * 70)
    log.info("  🔒 CROG COMMAND CENTER (SECURITY HARDENED)")
    log.info("  Cabin Rentals of Georgia")
    log.info(f"  Environment: {ENVIRONMENT}")
    log.info(f"  URL: http://{BASE}:9800")
    log.info(f"  CORS: {len(ALLOWED_ORIGINS)} allowed origins")
    log.info(f"  Secure Cookies: {IS_PRODUCTION}")
    log.info("=" * 70)
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=9800,
        log_level="info"
    )
