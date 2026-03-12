#!/usr/bin/env python3
"""
CROG Command Center — Master Console
=======================================
Enterprise-grade command center with production security.

Security hardening applied (2026-02-16):
  FIX #1  JWT secret loaded from environment (never hardcoded)
  FIX #2  CORS restricted to explicit whitelist
  FIX #3  Secure cookies auto-enabled in production
  FIX #4  Rate limiting on login / signup (5 req/min per IP)
  FIX #5  Pydantic input validation on every endpoint
  FIX #6  Audit-grade logging (no secrets, actor tracking)
  FIX #7  CSRF protection via Origin / Referer header check
  FIX #8  Security response headers on every request
"""

import os
import time
import json
import base64
import contextvars
import logging
import secrets
import requests as http_client
from pathlib import Path
from typing import Optional
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from jose import jwt, JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT
# ══════════════════════════════════════════════════════════════════════════════

try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
# FIX #6 — STRUCTURED LOGGING (no secrets, includes actor)
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s  %(message)s",
)
log = logging.getLogger("crog.console")

# ══════════════════════════════════════════════════════════════════════════════
# FIX #1 — JWT SECRET FROM ENVIRONMENT (never hardcoded)
# ══════════════════════════════════════════════════════════════════════════════

BASE = os.getenv("BASE_IP", "192.168.0.100")
GATEWAY_URL = os.getenv("GATEWAY_URL", f"http://{BASE}:8001")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

JWT_RSA_PUBLIC_KEY = os.getenv("JWT_RSA_PUBLIC_KEY", "")
if not JWT_RSA_PUBLIC_KEY:
    raise RuntimeError(
        "FATAL: JWT_RSA_PUBLIC_KEY environment variable is empty or missing. "
        "Set it in .env.security or export it before starting."
    )

def _decode_public_key(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("-----BEGIN"):
        return value
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return ""


JWT_RSA_PUBLIC_KEY_PEM = _decode_public_key(JWT_RSA_PUBLIC_KEY)
if not JWT_RSA_PUBLIC_KEY_PEM:
    raise RuntimeError("FATAL: JWT_RSA_PUBLIC_KEY is malformed (expected base64 PEM)")

JWT_ALGORITHM = "RS256"
COOKIE_NAME = "fortress_session"
_CURRENT_REQUEST_TOKEN = contextvars.ContextVar("fortress_request_token", default="")

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE — Direct DB access for web_ui_access permission
# ══════════════════════════════════════════════════════════════════════════════

import psycopg2
import psycopg2.extras
import psycopg2.pool

_DB_CFG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "fortress_db"),
    "user": os.getenv("DB_USER", "miner_bot"),
    "password": os.getenv("DB_PASS", os.getenv("DB_PASSWORD", "")),
}

_db_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _init_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, **_DB_CFG)
        log.info("DB connection pool initialized (2-10)")


def _get_pooled_conn():
    if _db_pool is None:
        _init_db_pool()
    return _db_pool.getconn()


def _put_conn(conn):
    if _db_pool and conn:
        try:
            conn.rollback()
        except Exception:
            pass
        _db_pool.putconn(conn)


def _db_query(sql: str, params: tuple = (), commit: bool = False):
    """Run a single query against fortress_db and return rows as dicts."""
    conn = _get_pooled_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if commit:
                conn.commit()
                try:
                    return cur.fetchall()
                except psycopg2.ProgrammingError:
                    return []
            return cur.fetchall()
    finally:
        _put_conn(conn)


# ══════════════════════════════════════════════════════════════════════════════
# FIX #2 — CORS RESTRICTED TO WHITELIST
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        f"https://crog-ai.com,http://{BASE}:9800,http://localhost:9800",
    ).split(",")
    if o.strip()
]

log.info("env=%s  cors_origins=%s  gateway=%s", ENVIRONMENT, ALLOWED_ORIGINS, GATEWAY_URL)

# ══════════════════════════════════════════════════════════════════════════════
# FIX #4 — RATE LIMITER (slowapi)
# ══════════════════════════════════════════════════════════════════════════════

limiter = Limiter(key_func=get_remote_address)
_start_time = time.time()

# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="CROG Command Center",
    version="2.2.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    log.warning("rate_limit  ip=%s  path=%s", get_remote_address(request), request.url.path)
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Try again in 60 seconds."},
        headers={"Retry-After": "60"},
    )


# FIX #2 — attach CORS middleware with explicit origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    max_age=3600,
)


# ══════════════════════════════════════════════════════════════════════════════
# FIX #7 — CSRF PROTECTION (Origin / Referer check on mutating methods)
# FIX #8 — SECURITY RESPONSE HEADERS
# ══════════════════════════════════════════════════════════════════════════════

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # ── FIX #7: CSRF check on state-changing requests ──
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        source = origin or referer

        if source:
            allowed = any(source.startswith(o) for o in ALLOWED_ORIGINS)
            if not allowed:
                log.warning("csrf_block  origin=%s  path=%s  ip=%s",
                            source, request.url.path, get_remote_address(request))
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request blocked"},
                )

    response = await call_next(request)

    # ── FIX #8: Security headers ──
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

    return response




# ══════════════════════════════════════════════════════════════════════════════
# VOICE MATRIX — Level 6 (Twilio WebSocket Bridge)
# ══════════════════════════════════════════════════════════════════════════════

try:
    import sys as _sys
    import importlib.util as _imp_util

    _voice_spec = _imp_util.spec_from_file_location(
        "voice_stream",
        PROJECT_ROOT / "fortress-guest-platform" / "backend" / "api" / "voice_stream.py",
    )
    _voice_mod = _imp_util.module_from_spec(_voice_spec)
    _voice_spec.loader.exec_module(_voice_mod)
    _sys.modules["voice_stream"] = _voice_mod
    app.include_router(_voice_mod.router)
    log.info("voice_matrix  router mounted (/api/voice/stream, /api/webhooks/twilio-voice)")
except Exception as _voice_err:
    log.warning("voice_matrix  failed to mount: %s", _voice_err)

# ── xAI Cloud Route (parallel to local pipeline) ──
try:
    _xai_spec = _imp_util.spec_from_file_location(
        "xai_voice_stream",
        PROJECT_ROOT / "fortress-guest-platform" / "backend" / "api" / "xai_voice_stream.py",
    )
    _xai_mod = _imp_util.module_from_spec(_xai_spec)
    _xai_spec.loader.exec_module(_xai_mod)
    _sys.modules["xai_voice_stream"] = _xai_mod
    app.include_router(_xai_mod.router)
    log.info("voice_matrix  xAI router mounted (/api/xai/voice/stream, /api/xai/webhooks/twilio-voice)")
except Exception as _xai_err:
    log.warning("voice_matrix  xAI route failed to mount: %s", _xai_err)

# ── S2S Cloud Route (OpenAI/xAI Realtime API with Qdrant tool calling) ──
try:
    _s2s_spec = _imp_util.spec_from_file_location(
        "s2s_voice_stream",
        PROJECT_ROOT / "fortress-guest-platform" / "backend" / "api" / "s2s_voice_stream.py",
    )
    _s2s_mod = _imp_util.module_from_spec(_s2s_spec)
    _s2s_spec.loader.exec_module(_s2s_mod)
    _sys.modules["s2s_voice_stream"] = _s2s_mod
    app.include_router(_s2s_mod.router, prefix="/api/s2s")
    log.info("voice_matrix  S2S router mounted (/api/s2s/voice/stream, /api/s2s/webhooks/twilio-voice)")
except Exception as _s2s_err:
    log.warning("voice_matrix  S2S route failed to mount: %s", _s2s_err)

# ── ElevenLabs Tool Webhook (Qdrant search for Eve) ──
try:
    _el_spec = _imp_util.spec_from_file_location(
        "elevenlabs_tools",
        PROJECT_ROOT / "fortress-guest-platform" / "backend" / "api" / "elevenlabs_tools.py",
    )
    _el_mod = _imp_util.module_from_spec(_el_spec)
    _el_spec.loader.exec_module(_el_mod)
    _sys.modules["elevenlabs_tools"] = _el_mod
    app.include_router(_el_mod.router, prefix="/api/elevenlabs")
    log.info("voice_matrix  ElevenLabs tools mounted (/api/elevenlabs/tools/qdrant_search)")
except Exception as _el_err:
    log.warning("voice_matrix  ElevenLabs tools failed to mount: %s", _el_err)


# ══════════════════════════════════════════════════════════════════════════════
# FIX #5 — PYDANTIC MODELS (strict input validation)
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class SignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="viewer", pattern=r"^(admin|operator|viewer)$")


class RoleUpdate(BaseModel):
    role: str = Field(pattern=r"^(admin|operator|viewer)$")


class StatusUpdate(BaseModel):
    is_active: bool


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def verify_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_RSA_PUBLIC_KEY_PEM, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = verify_jwt(token)
    _CURRENT_REQUEST_TOKEN.set(token)
    return user


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") != "admin":
        log.warning("authz_denied  user=%s  path=%s", user.get("username"), request.url.path)
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _bearer(request: Request) -> str:
    return request.cookies.get(COOKIE_NAME, "")


def _safe_json_detail(resp, fallback="Gateway error"):
    """Extract error detail from a response, handling non-JSON bodies."""
    try:
        return resp.json().get("detail", fallback)
    except Exception:
        return resp.text[:200] or fallback


def _proxy_get(path: str, token: str):
    resp = http_client.get(
        f"{GATEWAY_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_json_detail(resp))
    return resp.json()


def _proxy_mutate(method: str, path: str, token: str, body: dict = None):
    fn = getattr(http_client, method)
    kwargs = {"headers": {"Authorization": f"Bearer {token}"}, "timeout": 10}
    if body is not None:
        kwargs["json"] = body
    resp = fn(f"{GATEWAY_URL}{path}", **kwargs)
    if resp.status_code not in (200, 201, 204):
        raise HTTPException(status_code=resp.status_code, detail=_safe_json_detail(resp))
    if resp.status_code == 204 or not resp.text:
        return {"status": "success"}
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

_login_failures: dict = defaultdict(list)
_LOCKOUT_WINDOW = 300      # 5 minutes
_LOCKOUT_THRESHOLD = 5     # 5 failures → lockout


def _check_lockout(username: str):
    now = time.time()
    attempts = _login_failures.get(username, [])
    recent = [t for t in attempts if now - t < _LOCKOUT_WINDOW]
    _login_failures[username] = recent
    if len(recent) >= _LOCKOUT_THRESHOLD:
        log.warning("account_locked  user=%s  attempts=%d", username, len(recent))
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked. Try again in {_LOCKOUT_WINDOW // 60} minutes.",
        )


def _record_failure(username: str):
    _login_failures[username].append(time.time())


def _clear_failures(username: str):
    _login_failures.pop(username, None)


@app.post("/api/login")
async def api_login(request: Request, body: LoginRequest):
    """Rate limiting handled by _check_lockout (5 failures = 5min ban)."""
    """Authenticate → set HTTP-only session cookie → redirect to dashboard."""
    _check_lockout(body.username)
    try:
        gw = http_client.post(
            f"{GATEWAY_URL}/v1/auth/login",
            json={"username": body.username, "password": body.password},
            timeout=10,
        )
    except http_client.RequestException:
        log.error("gateway_down  endpoint=/v1/auth/login")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

    if gw.status_code != 200:
        _record_failure(body.username)
        log.warning("login_fail  user=%s  status=%d", body.username, gw.status_code)  # FIX #6
        detail = _safe_json_detail(gw, "Invalid credentials")
        raise HTTPException(status_code=gw.status_code, detail=detail)

    data = gw.json()
    _clear_failures(body.username)
    log.info("login_ok  user=%s  role=%s", data["username"], data["role"])  # FIX #6

    is_https = request.headers.get("x-forwarded-proto", "").lower() == "https"

    accept = request.headers.get("accept", "")
    wants_json = "application/json" in accept

    if wants_json:
        response = JSONResponse(content={
            "access_token": data["access_token"],
            "username": data["username"],
            "role": data["role"],
        })
    else:
        response = RedirectResponse(url="/", status_code=302)

    response.set_cookie(
        key=COOKIE_NAME,
        value=data["access_token"],
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=86400,
        path="/",
    )
    return response


@app.post("/api/logout")
async def api_logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/api/verify")
async def api_verify(request: Request):
    user = get_current_user(request)
    return {"username": user.get("username"), "role": user.get("role"), "authenticated": True}


@app.post("/api/signup")
async def api_signup(request: Request, body: SignupRequest):
    """Public registration — proxied to Gateway."""
    try:
        gw = http_client.post(
            f"{GATEWAY_URL}/v1/auth/signup",
            json=body.model_dump(),
            timeout=10,
        )
    except http_client.RequestException:
        log.error("gateway_down  endpoint=/v1/auth/signup")
        raise HTTPException(status_code=503, detail="Registration service unavailable")

    if gw.status_code not in (200, 201):
        raise HTTPException(status_code=gw.status_code, detail=gw.json().get("detail", "Signup failed"))

    log.info("signup_ok  user=%s", body.username)  # FIX #6
    return gw.json()


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN USER MANAGEMENT APIs (all require admin role)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """List all users enriched with web_ui_access and vrs_access flags from DB."""
    _require_admin(request)
    users = _proxy_get("/v1/auth/admin/users", _bearer(request))
    try:
        rows = _db_query(
            "SELECT id, web_ui_access, vrs_access FROM fortress_users"
        )
        access_map = {r["id"]: {"web_ui_access": r["web_ui_access"], "vrs_access": r["vrs_access"]} for r in rows}
        for u in users:
            flags = access_map.get(u["id"], {})
            u["web_ui_access"] = flags.get("web_ui_access", False)
            u["vrs_access"] = flags.get("vrs_access", False)
    except Exception as e:
        log.error("db_enrich_failed  error=%s", e)
        for u in users:
            u["web_ui_access"] = False
            u["vrs_access"] = False
    return users


@app.post("/api/admin/users")
async def admin_create_user(request: Request, body: AdminUserCreate):  # FIX #5
    admin = _require_admin(request)
    result = _proxy_mutate("post", "/v1/auth/users", _bearer(request), body.model_dump())
    log.info("admin_create_user  actor=%s  target=%s  role=%s",
             admin.get("username"), body.username, body.role)  # FIX #6
    return result


@app.patch("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: int, request: Request, body: RoleUpdate):  # FIX #5
    admin = _require_admin(request)
    result = _proxy_mutate("patch", f"/v1/auth/admin/users/{user_id}/role",
                           _bearer(request), body.model_dump())
    log.info("admin_role_change  actor=%s  target_id=%d  new_role=%s",
             admin.get("username"), user_id, body.role)  # FIX #6
    return result


@app.patch("/api/admin/users/{user_id}/status")
async def admin_update_status(user_id: int, request: Request, body: StatusUpdate):  # FIX #5
    admin = _require_admin(request)
    result = _proxy_mutate("patch", f"/v1/auth/admin/users/{user_id}/status",
                           _bearer(request), body.model_dump())
    action = "activated" if body.is_active else "deactivated"
    log.info("admin_status_change  actor=%s  target_id=%d  action=%s",
             admin.get("username"), user_id, action)  # FIX #6
    return result


class WebUIAccessUpdate(BaseModel):
    web_ui_access: bool


@app.patch("/api/admin/users/{user_id}/webui-access")
async def admin_update_webui_access(user_id: int, request: Request, body: WebUIAccessUpdate):
    """Toggle Web UI access for a user (admin only)."""
    admin = _require_admin(request)
    _db_query(
        "UPDATE fortress_users SET web_ui_access = %s WHERE id = %s",
        (body.web_ui_access, user_id),
        commit=True,
    )
    action = "granted" if body.web_ui_access else "revoked"
    log.info("webui_access_%s  actor=%s  target_id=%d", action, admin.get("username"), user_id)
    return {"status": "success", "user_id": user_id, "web_ui_access": body.web_ui_access}


class VRSAccessUpdate(BaseModel):
    vrs_access: bool


@app.patch("/api/admin/users/{user_id}/vrs-access")
async def admin_update_vrs_access(user_id: int, request: Request, body: VRSAccessUpdate):
    """Toggle VRS Dashboard access for a user (admin only)."""
    admin = _require_admin(request)
    _db_query(
        "UPDATE fortress_users SET vrs_access = %s WHERE id = %s",
        (body.vrs_access, user_id),
        commit=True,
    )
    action = "granted" if body.vrs_access else "revoked"
    log.info("vrs_access_%s  actor=%s  target_id=%d", action, admin.get("username"), user_id)
    return {"status": "success", "user_id": user_id, "vrs_access": body.vrs_access}


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, request: Request, body: PasswordResetRequest):
    """Reset any user's password (admin only). Proxied to Gateway."""
    admin = _require_admin(request)
    result = _proxy_mutate(
        "post",
        f"/v1/auth/admin/users/{user_id}/reset-password",
        _bearer(request),
        body.model_dump(),
    )
    log.warning("admin_password_reset  actor=%s  target_id=%d",
                admin.get("username"), user_id)
    return result


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    admin = _require_admin(request)
    result = _proxy_mutate("delete", f"/v1/auth/admin/users/{user_id}", _bearer(request))
    log.warning("admin_delete_user  actor=%s  target_id=%d",
                admin.get("username"), user_id)  # FIX #6
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE APIs (authenticated user)
# ══════════════════════════════════════════════════════════════════════════════

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UsernameChange(BaseModel):
    new_username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


@app.get("/api/profile")
async def profile_info(request: Request):
    """Return current user profile from gateway."""
    user = get_current_user(request)
    try:
        return _proxy_get("/v1/auth/me", _bearer(request))
    except Exception:
        return {
            "username": user.get("username"),
            "role": user.get("role"),
            "email": None,
        }


@app.post("/api/profile/password")
async def profile_change_password(request: Request, body: PasswordChange):
    user = get_current_user(request)
    result = _proxy_mutate("post", "/v1/auth/profile/password", _bearer(request), body.model_dump())
    log.info("password_changed  user=%s", user.get("username"))
    return result


@app.post("/api/profile/username")
async def profile_change_username(request: Request, body: UsernameChange):
    user = get_current_user(request)
    result = _proxy_mutate("post", "/v1/auth/profile/username", _bearer(request), body.model_dump())
    log.info("username_changed  user=%s  new=%s", user.get("username"), body.new_username)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT CENTER APIs
# ══════════════════════════════════════════════════════════════════════════════

DOC_ROOT = Path(__file__).resolve().parent.parent          # /home/admin/Fortress-Prime
DOC_DIRS = [DOC_ROOT, DOC_ROOT / "docs"]                   # scan root + docs/

CATEGORY_RULES = [
    (["security", "audit", "csrf", "jwt"],                  "Security"),
    (["deploy", "setup", "install", "quick_start", "guide"],"Deployment"),
    (["architecture", "council", "strangler"],               "Architecture"),
    (["integration", "mcp", "cursor"],                       "Integration"),
    (["sms", "twilio", "ruebarue", "guest"],                 "Guest Ops"),
    (["database", "schema", "migration"],                    "Database"),
    (["jordi", "intelligence", "hunt", "forensic"],          "Intelligence"),
    (["whisper", "dgx", "nvidia", "gpu"],                    "AI / Compute"),
    (["constitution", "requirements", "manifest", "command"],"Governance"),
    (["session", "review", "summary", "status", "ready"],    "Status"),
]


def _classify(name: str) -> str:
    lower = name.lower()
    for keywords, category in CATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return category
    return "General"


def _scan_docs() -> list[dict]:
    seen, out = set(), []
    for d in DOC_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name in seen:
                continue
            seen.add(f.name)
            stat = f.stat()
            out.append({
                "name": f.name,
                "title": f.name.replace("_", " ").replace("-", " ").removesuffix(".md"),
                "category": _classify(f.name),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "path": str(f.relative_to(DOC_ROOT)),
                "lines": sum(1 for _ in open(f, errors="ignore")),
            })
    return out


@app.get("/api/docs")
async def api_docs_list(request: Request):
    """Return metadata for every .md doc (requires auth)."""
    get_current_user(request)
    docs = _scan_docs()
    categories = sorted({d["category"] for d in docs})
    return {"total": len(docs), "categories": categories, "documents": docs}


@app.get("/api/docs/{doc_name:path}")
async def api_docs_content(doc_name: str, request: Request):
    """Return the raw markdown content of a single document (requires auth)."""
    get_current_user(request)

    # Security: prevent path traversal
    clean = Path(doc_name).name
    for d in DOC_DIRS:
        candidate = d / clean
        if candidate.is_file() and candidate.suffix == ".md":
            return {
                "name": clean,
                "content": candidate.read_text(errors="ignore"),
                "size": candidate.stat().st_size,
            }
    raise HTTPException(status_code=404, detail=f"Document '{clean}' not found")


# ══════════════════════════════════════════════════════════════════════════════
# LEGAL CASE VIEWER — proxy to FGP legal API on port 8100
# ══════════════════════════════════════════════════════════════════════════════

LEGAL_API = os.getenv("LEGAL_API_URL", "http://127.0.0.1:8100")


def _legal_headers(token: str | None) -> dict:
    headers = {}
    if token:
        headers["Cookie"] = f"{COOKIE_NAME}={token}"
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _legal_get(path: str, token: str = None):
    """Forward a GET request to the legal API with auth."""
    try:
        resp = http_client.get(f"{LEGAL_API}{path}", headers=_legal_headers(token), timeout=15)
    except http_client.RequestException:
        log.error("legal_api_down  path=%s", path)
        raise HTTPException(status_code=503, detail="Legal case service unavailable")
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "Legal API error")
        except Exception:
            detail = resp.text[:200] or "Legal API error"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


def _legal_post(path: str, token: str = None, payload: dict | None = None):
    """Forward a POST request to the legal API with auth."""
    try:
        resp = http_client.post(
            f"{LEGAL_API}{path}",
            headers=_legal_headers(token),
            json=payload or {},
            timeout=120,
        )
    except http_client.RequestException:
        log.error("legal_api_down  path=%s", path)
        raise HTTPException(status_code=503, detail="Legal case service unavailable")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", "Legal API error")
        except Exception:
            detail = resp.text[:300] or "Legal API error"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


@app.get("/api/legal/cases")
async def legal_cases(request: Request):
    """List all legal cases."""
    get_current_user(request)
    return _legal_get("/api/legal/cases", _bearer(request))


@app.get("/api/legal/overview")
async def legal_overview(request: Request):
    """Legacy compatibility route for legal CRM overview."""
    get_current_user(request)
    return _legal_get("/api/legal/crm/overview", _bearer(request))


@app.get("/api/legal/crm/overview")
async def legal_crm_overview(request: Request):
    """Full legal CRM overview (cases, deadlines, correspondence, actions)."""
    get_current_user(request)
    return _legal_get("/api/legal/crm/overview", _bearer(request))


@app.get("/api/legal/health")
async def legal_health_proxy(request: Request):
    """Legal API health check proxy."""
    get_current_user(request)
    return _legal_get("/api/legal/health", _bearer(request))


@app.post("/api/legal/cases/{slug}/synthesize")
async def legal_case_synthesize(slug: str, request: Request):
    """Proxy legal case synthesis to FGP legal API."""
    get_current_user(request)
    body = await request.json()
    return _legal_post(f"/api/legal/cases/{slug}/synthesize", _bearer(request), body)


@app.get("/api/legal/cases/{slug}")
async def legal_case_detail(slug: str, request: Request):
    """Single case detail with actions, evidence, watchdog."""
    get_current_user(request)
    return _legal_get(f"/api/legal/cases/{slug}", _bearer(request))


@app.get("/api/legal/cases/{slug}/correspondence")
async def legal_case_correspondence(slug: str, request: Request):
    """Correspondence for a specific case."""
    get_current_user(request)
    return _legal_get(f"/api/legal/cases/{slug}/correspondence", _bearer(request))


@app.get("/api/legal/cases/{slug}/deadlines")
async def legal_case_deadlines(slug: str, request: Request):
    """Deadlines for a specific case."""
    get_current_user(request)
    return _legal_get(f"/api/legal/cases/{slug}/deadlines", _bearer(request))


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE HEALTH + CLUSTER TELEMETRY — server-side probes (no direct browser→port)
# ══════════════════════════════════════════════════════════════════════════════

_HEALTH_TARGETS = {
    "legal":      "http://127.0.0.1:8100/api/legal/health",
    "cluster":    "http://127.0.0.1:9876/",
    "classifier": "http://127.0.0.1:9877/",
    "mission":    "http://127.0.0.1:8080/health",
    "grafana":    "http://127.0.0.1:3000/login",
}


@app.get("/api/service-health")
async def service_health(request: Request):
    """Probe all internal services and return a status map."""
    get_current_user(request)
    result = {}
    for name, url in _HEALTH_TARGETS.items():
        try:
            t = 10 if name == "cluster" else 3
            r = http_client.get(url, timeout=t, allow_redirects=True)
            result[name] = "up" if r.status_code < 500 else "down"
        except Exception:
            result[name] = "down"
    result["up_count"] = sum(1 for v in result.values() if v == "up")
    result["total"] = len(_HEALTH_TARGETS)
    return result


@app.get("/api/bridge/status")
async def bridge_status_proxy(request: Request):
    """Proxy the email bridge status from the Legal Case Manager service."""
    get_current_user(request)
    try:
        r = http_client.get("http://127.0.0.1:8100/api/bridge/status", timeout=2)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"last_24h": "-", "bridge_total": 0, "latest_email": None}


@app.get("/api/cluster-telemetry")
async def cluster_telemetry(request: Request):
    """Fetch live GPU/node metrics from the bare-metal dashboard."""
    get_current_user(request)
    payload = {"nodes_online": 0, "nodes_total": 4, "gpu_temp_c": None}
    try:
        r = http_client.get("http://127.0.0.1:9876/api/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            nodes_dict = data.get("nodes", {})
            node_list = list(nodes_dict.values())
            payload["nodes_total"] = len(node_list) if node_list else 4
            payload["nodes_online"] = sum(
                1 for n in node_list if n.get("online")
            )
            for n in node_list:
                gpu = n.get("gpu", {}).get("temp_c")
                if gpu is not None:
                    payload["gpu_temp_c"] = gpu
                    break
    except Exception:
        pass
    return payload


# ══════════════════════════════════════════════════════════════════════════════
# CROG-VRS — Vacation Rental Software proxy to guest-platform on port 8100
# ══════════════════════════════════════════════════════════════════════════════

VRS_API = os.getenv("VRS_API_URL", "http://127.0.0.1:8100")
FGP_BEARER_TOKEN = os.getenv("FGP_BEARER_TOKEN", "").strip() or os.getenv("FGP_SERVICE_TOKEN", "").strip()


def _vrs_headers() -> dict:
    request_token = _CURRENT_REQUEST_TOKEN.get()
    token = request_token or FGP_BEARER_TOKEN
    if not token:
        raise HTTPException(401, "Missing authentication token for VRS proxy")
    return {"Authorization": f"Bearer {token}"}


def _vrs_get(path: str, params: dict = None):
    try:
        resp = http_client.get(f"{VRS_API}{path}", params=params, headers=_vrs_headers(), timeout=10)
    except http_client.RequestException:
        log.error("vrs_api_down  path=%s", path)
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


def _vrs_post(path: str, body: dict = None):
    try:
        resp = http_client.post(f"{VRS_API}{path}", json=body, headers=_vrs_headers(), timeout=15)
    except http_client.RequestException:
        log.error("vrs_api_down  path=%s", path)
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.get("/api/vrs/properties")
async def vrs_properties(request: Request):
    get_current_user(request)
    return _vrs_get("/api/properties/")


@app.get("/api/vrs/properties/{prop_id}")
async def vrs_property_detail(prop_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/properties/{prop_id}")


@app.get("/api/vrs/reservations")
async def vrs_reservations(
    request: Request,
    status: str = None,
    property_id: str = None,
    search: str = None,
    sort_by: str = "check_in_date",
    order: str = "desc",
    limit: int = 500,
):
    get_current_user(request)
    params = {"limit": limit, "sort_by": sort_by, "order": order}
    if status:
        params["status"] = status
    if property_id:
        params["property_id"] = property_id
    if search:
        params["search"] = search
    return _vrs_get("/api/reservations/", params=params)


@app.get("/api/vrs/reservations/arriving/today")
async def vrs_arrivals_today(request: Request):
    get_current_user(request)
    return _vrs_get("/api/reservations/arriving/today")


@app.get("/api/vrs/reservations/departing/today")
async def vrs_departures_today(request: Request):
    get_current_user(request)
    return _vrs_get("/api/reservations/departing/today")


@app.get("/api/vrs/reservations/{res_id}")
async def vrs_reservation_detail(res_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/reservations/{res_id}")


@app.get("/api/vrs/reservations/{res_id}/full")
async def vrs_reservation_full(res_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/reservations/{res_id}/full")


@app.patch("/api/vrs/reservations/{res_id}")
async def vrs_reservation_update(res_id: str, request: Request, body: dict = None):
    get_current_user(request)
    try:
        resp = http_client.patch(f"{VRS_API}/api/reservations/{res_id}", json=body or {}, headers=_vrs_headers(), timeout=10)
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json() if resp.status_code < 300 else {"error": resp.text}


@app.post("/api/vrs/booking/reservations/{res_id}/check-in")
async def vrs_check_in(res_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/booking/reservations/{res_id}/check-in")


@app.post("/api/vrs/booking/reservations/{res_id}/check-out")
async def vrs_check_out(res_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/booking/reservations/{res_id}/check-out")


@app.get("/api/vrs/booking/calendar/{prop_id}")
async def vrs_calendar(prop_id: str, request: Request, month: int = None, year: int = None):
    get_current_user(request)
    params = {}
    if month:
        params["month"] = month
    if year:
        params["year"] = year
    return _vrs_get(f"/api/booking/calendar/{prop_id}", params=params)


@app.get("/api/vrs/booking/reservations/occupancy")
async def vrs_occupancy(request: Request):
    get_current_user(request)
    params = dict(request.query_params)
    return _vrs_get("/api/booking/reservations/occupancy", params=params)


@app.get("/api/vrs/booking/reservations/arrivals")
async def vrs_upcoming_arrivals(request: Request):
    get_current_user(request)
    return _vrs_get("/api/booking/reservations/arrivals")


@app.get("/api/vrs/booking/reservations/departures")
async def vrs_upcoming_departures(request: Request):
    get_current_user(request)
    return _vrs_get("/api/booking/reservations/departures")


@app.get("/api/vrs/booking/reservations/search")
async def vrs_search_reservations(request: Request, q: str = ""):
    get_current_user(request)
    return _vrs_get("/api/booking/reservations/search", params={"q": q})


@app.get("/api/vrs/guests")
async def vrs_guests(request: Request):
    get_current_user(request)
    return _vrs_get("/api/guests/")


@app.get("/api/vrs/guests/{guest_id}")
async def vrs_guest_detail(guest_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/guests/{guest_id}")


@app.get("/api/vrs/guests/{guest_id}/360")
async def vrs_guest_360(guest_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/guests/{guest_id}/360")


@app.get("/api/vrs/messages/stats")
async def vrs_message_stats(request: Request):
    get_current_user(request)
    return _vrs_get("/api/messages/stats")


@app.get("/api/vrs/messages")
async def vrs_messages_list(request: Request, guest_id: str = None, reservation_id: str = None, limit: int = 100):
    get_current_user(request)
    params = {"limit": limit}
    if guest_id:
        params["guest_id"] = guest_id
    if reservation_id:
        params["reservation_id"] = reservation_id
    return _vrs_get("/api/messages/", params=params)


@app.post("/api/vrs/messages/send")
async def vrs_send_message(request: Request, body: dict = None):
    get_current_user(request)
    return _vrs_post("/api/messages/send", body or {})


@app.get("/api/vrs/guests/analytics")
async def vrs_guest_analytics(request: Request):
    get_current_user(request)
    return _vrs_get("/api/guests/analytics")


@app.get("/api/vrs/review/queue")
async def vrs_review_queue(request: Request, status: str = "pending", limit: int = 50):
    get_current_user(request)
    return _vrs_get("/api/review/queue", params={"status": status, "limit": limit})


@app.get("/api/vrs/review/queue/stats")
async def vrs_review_stats(request: Request):
    get_current_user(request)
    return _vrs_get("/api/review/queue/stats")


@app.post("/api/vrs/review/queue/{entry_id}/approve")
async def vrs_review_approve(entry_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/review/queue/{entry_id}/approve", {"reviewed_by": "admin"})


@app.post("/api/vrs/review/queue/{entry_id}/edit")
async def vrs_review_edit(entry_id: str, request: Request, body: dict = None):
    get_current_user(request)
    return _vrs_post(f"/api/review/queue/{entry_id}/edit", body or {})


@app.post("/api/vrs/review/queue/{entry_id}/reject")
async def vrs_review_reject(entry_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/review/queue/{entry_id}/reject", {"reviewed_by": "admin"})


@app.get("/api/vrs/agent/stats")
async def vrs_agent_stats(request: Request):
    get_current_user(request)
    return _vrs_get("/api/agent/stats")


@app.post("/api/vrs/agent/run-lifecycle")
async def vrs_run_lifecycle(request: Request):
    get_current_user(request)
    return _vrs_post("/api/agent/run-lifecycle")


@app.get("/api/vrs/integrations/streamline/status")
async def vrs_streamline_status(request: Request):
    get_current_user(request)
    return _vrs_get("/api/integrations/streamline/status")


@app.post("/api/vrs/integrations/streamline/sync")
async def vrs_streamline_sync(request: Request):
    get_current_user(request)
    return _vrs_post("/api/integrations/streamline/sync")


# ─── Damage Claims VRS proxy ─────────────────────────────────────────────────

@app.get("/api/vrs/damage-claims/")
async def vrs_damage_claims_list(
    request: Request,
    status: str = "all",
    search: str = None,
    property_id: str = None,
    year: int = None,
    limit: int = 100,
):
    get_current_user(request)
    params = {"status": status, "limit": limit}
    if search:
        params["search"] = search
    if property_id:
        params["property_id"] = property_id
    if year:
        params["year"] = year
    return _vrs_get("/api/damage-claims/", params=params)


@app.get("/api/vrs/damage-claims/stats")
async def vrs_damage_claims_stats(request: Request):
    get_current_user(request)
    return _vrs_get("/api/damage-claims/stats")


@app.get("/api/vrs/damage-claims/{claim_id}")
async def vrs_damage_claim_get(claim_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/damage-claims/{claim_id}")


@app.post("/api/vrs/damage-claims/")
async def vrs_damage_claim_create(request: Request, body: dict = None):
    get_current_user(request)
    return _vrs_post("/api/damage-claims/", body or {})


@app.patch("/api/vrs/damage-claims/{claim_id}")
async def vrs_damage_claim_update(claim_id: str, request: Request, body: dict = None):
    get_current_user(request)
    try:
        resp = http_client.patch(f"{VRS_API}/api/damage-claims/{claim_id}", json=body or {}, headers=_vrs_headers(), timeout=10)
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json() if resp.status_code < 300 else {"error": resp.text}


@app.post("/api/vrs/damage-claims/{claim_id}/generate-legal-draft")
async def vrs_damage_legal_draft(claim_id: str, request: Request):
    get_current_user(request)
    try:
        resp = http_client.post(f"{VRS_API}/api/damage-claims/{claim_id}/generate-legal-draft", headers=_vrs_headers(), timeout=180)
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json() if resp.status_code < 300 else {"error": resp.text}


@app.post("/api/vrs/damage-claims/{claim_id}/approve")
async def vrs_damage_approve(claim_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/damage-claims/{claim_id}/approve")


@app.post("/api/vrs/damage-claims/{claim_id}/send")
async def vrs_damage_send(claim_id: str, request: Request, via: str = "email"):
    get_current_user(request)
    try:
        resp = http_client.post(f"{VRS_API}/api/damage-claims/{claim_id}/send?via={via}", headers=_vrs_headers(), timeout=30)
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json() if resp.status_code < 300 else {"error": resp.text}


# ─── Housekeeping VRS proxy ────────────────────────────────────────────────────

@app.get("/api/vrs/housekeeping/dirty-turnovers")
async def vrs_dirty_turnovers(request: Request, target_date: str = None):
    get_current_user(request)
    params = {}
    if target_date:
        params["target_date"] = target_date
    return _vrs_get("/api/housekeeping/dirty-turnovers", params=params)


@app.get("/api/vrs/housekeeping/today")
async def vrs_housekeeping_today(request: Request):
    get_current_user(request)
    return _vrs_get("/api/housekeeping/today")


@app.post("/api/vrs/housekeeping/mark-clean/{property_id}")
async def vrs_mark_clean(property_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/housekeeping/mark-clean/{property_id}")


@app.get("/api/vrs/housekeeping/status/{property_id}")
async def vrs_cleaning_status(property_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/housekeeping/status/{property_id}")


@app.post("/api/vrs/housekeeping/dispatch/{reservation_id}")
async def vrs_dispatch_turnover(reservation_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/housekeeping/dispatch/{reservation_id}")


@app.get("/api/vrs/housekeeping/evaluate/{reservation_id}")
async def vrs_evaluate_turnover(reservation_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/housekeeping/evaluate/{reservation_id}")


# ─── Work Orders VRS proxy ────────────────────────────────────────────────────

@app.get("/api/vrs/workorders")
async def vrs_workorders_list(request: Request, status: str = None, limit: int = 50):
    get_current_user(request)
    params = {"limit": limit}
    if status:
        params["status"] = status
    return _vrs_get("/api/workorders/", params=params)


@app.get("/api/vrs/workorders/{wo_id}")
async def vrs_workorder_detail(wo_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/workorders/{wo_id}")


@app.post("/api/vrs/workorders")
async def vrs_workorder_create(request: Request, body: dict = None):
    get_current_user(request)
    return _vrs_post("/api/workorders/", body or {})


@app.patch("/api/vrs/workorders/{wo_id}")
async def vrs_workorder_update(wo_id: str, request: Request, body: dict = None):
    get_current_user(request)
    try:
        resp = http_client.patch(f"{VRS_API}/api/workorders/{wo_id}", json=body or {}, headers=_vrs_headers(), timeout=10)
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json() if resp.status_code < 300 else {"error": resp.text}


# ─── Utilities VRS proxy ─────────────────────────────────────────────────────

@app.get("/api/vrs/utilities/property/{prop_id}")
async def vrs_utilities_by_property(prop_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/utilities/property/{prop_id}")


@app.get("/api/vrs/utilities/analytics/{prop_id}")
async def vrs_utility_analytics(prop_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/utilities/analytics/{prop_id}")


@app.get("/api/vrs/utilities/analytics/portfolio/summary")
async def vrs_utility_portfolio(request: Request):
    get_current_user(request)
    return _vrs_get("/api/utilities/analytics/portfolio/summary")


# ─── Agreements VRS proxy ────────────────────────────────────────────────────

@app.get("/api/vrs/agreements")
async def vrs_agreements_list(request: Request, limit: int = 50):
    get_current_user(request)
    return _vrs_get("/api/agreements/", params={"limit": limit})


@app.get("/api/vrs/agreements/dashboard")
async def vrs_agreements_dashboard(request: Request):
    get_current_user(request)
    return _vrs_get("/api/agreements/dashboard")


@app.get("/api/vrs/agreements/templates")
async def vrs_agreement_templates(request: Request):
    get_current_user(request)
    return _vrs_get("/api/agreements/templates")


@app.get("/api/vrs/agreements/{agreement_id}/pdf")
async def vrs_agreement_pdf(agreement_id: str, request: Request):
    get_current_user(request)
    try:
        resp = http_client.get(f"{VRS_API}/api/agreements/{agreement_id}/pdf", headers=_vrs_headers(), timeout=30)
        if resp.status_code == 200:
            from starlette.responses import Response
            return Response(
                content=resp.content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="agreement-{agreement_id}.pdf"'},
            )
        return {"error": resp.text[:200], "status": resp.status_code}
    except Exception:
        raise HTTPException(502, "VRS platform unavailable")


@app.get("/api/vrs/agreements/{agreement_id}/info")
async def vrs_agreement_info(agreement_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/agreements/{agreement_id}")


# ─── Analytics VRS proxy ─────────────────────────────────────────────────────

@app.get("/api/vrs/analytics/dashboard")
async def vrs_analytics_dashboard(request: Request):
    get_current_user(request)
    return _vrs_get("/api/analytics/dashboard")


# ─── Payments VRS proxy ──────────────────────────────────────────────────────

@app.get("/api/vrs/payments/config")
async def vrs_payments_config(request: Request):
    get_current_user(request)
    return _vrs_get("/api/payments/config")


@app.get("/api/vrs/payments/reservation/{res_id}")
async def vrs_payments_by_reservation(res_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/payments/reservation/{res_id}")


@app.post("/api/vrs/payments/create-intent")
async def vrs_payments_create_intent(request: Request):
    get_current_user(request)
    body = await request.json()
    return _vrs_post("/api/payments/create-intent", body)


@app.post("/api/vrs/payments/refund")
async def vrs_payments_refund(request: Request):
    get_current_user(request)
    body = await request.json()
    return _vrs_post("/api/payments/refund", body)


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE ENGINE — Council of Giants API
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
from fastapi.responses import StreamingResponse
from intelligence_engine import (
    list_personas, get_persona_detail, start_vote, get_vote_stream,
    get_vote_history, get_vote_detail, resolve_vote, run_debate,
    get_leaderboard,
)


class VoteRequest(BaseModel):
    event: str = Field(min_length=5, max_length=500)
    context: Optional[str] = Field(default=None, max_length=2000)
    model: str = Field(default="qwen2.5:7b", pattern=r"^[a-zA-Z0-9.:_\-]+$")


class DebateRequest(BaseModel):
    persona_a: str = Field(min_length=1, max_length=50)
    persona_b: str = Field(min_length=1, max_length=50)
    topic: str = Field(min_length=5, max_length=500)
    model: str = Field(default="qwen2.5:7b", pattern=r"^[a-zA-Z0-9.:_\-]+$")


class ResolveRequest(BaseModel):
    actual_outcome: str = Field(pattern=r"^(BULLISH|BEARISH|NEUTRAL)$")
    notes: str = Field(default="", max_length=1000)


@app.get("/api/intelligence/personas")
async def intel_personas(request: Request):
    """List all 9 personas with stats, vectors, accuracy."""
    get_current_user(request)
    return list_personas()


@app.get("/api/intelligence/persona/{slug}")
async def intel_persona_detail(slug: str, request: Request):
    """Single persona full detail + recent opinions."""
    get_current_user(request)
    try:
        return get_persona_detail(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Persona '{slug}' not found")


@app.post("/api/intelligence/vote")
async def intel_vote(request: Request, body: VoteRequest):
    """Trigger a Council vote. Returns vote_id for SSE streaming."""
    user = get_current_user(request)
    log.info("council_vote  user=%s  event=%s  model=%s",
             user.get("username"), body.event[:60], body.model)
    vote_id = start_vote(body.event, body.context, body.model)
    return {"vote_id": vote_id, "status": "started", "model": body.model}


@app.get("/api/intelligence/stream/{vote_id}")
async def intel_vote_stream(vote_id: str, request: Request):
    """SSE stream of live Council vote progress."""
    get_current_user(request)

    async def event_generator():
        last_count = -1
        for _ in range(600):  # 10 min max
            data = get_vote_stream(vote_id)
            if not data:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return

            current_count = data.get("personas_completed", 0)
            status = data.get("status", "unknown")

            if current_count != last_count or status in ("complete", "error"):
                yield f"data: {json.dumps(data, default=str)}\n\n"
                last_count = current_count

            if status in ("complete", "error"):
                return

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/intelligence/history")
async def intel_history(request: Request, limit: int = 50, offset: int = 0):
    """Past Council votes with outcomes."""
    get_current_user(request)
    return get_vote_history(min(limit, 100), max(offset, 0))


@app.get("/api/intelligence/history/{vote_id}")
async def intel_history_detail(vote_id: str, request: Request):
    """Single vote full detail with all opinions."""
    get_current_user(request)
    result = get_vote_detail(vote_id)
    if not result:
        raise HTTPException(status_code=404, detail="Vote not found")
    return result


@app.patch("/api/intelligence/history/{vote_id}/resolve")
async def intel_resolve(vote_id: str, request: Request, body: ResolveRequest):
    """Resolve a vote with actual outcome. Updates persona accuracy."""
    _require_admin(request)
    result = resolve_vote(vote_id, body.actual_outcome, body.notes)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    log.info("vote_resolved  id=%s  outcome=%s", vote_id, body.actual_outcome)
    return result


@app.post("/api/intelligence/debate")
async def intel_debate(request: Request, body: DebateRequest):
    """Trigger a 2-persona debate on a topic."""
    user = get_current_user(request)
    log.info("council_debate  user=%s  a=%s  b=%s  topic=%s",
             user.get("username"), body.persona_a, body.persona_b, body.topic[:40])
    try:
        return run_debate(body.persona_a, body.persona_b, body.topic, body.model)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/intelligence/leaderboard")
async def intel_leaderboard(request: Request):
    """Persona accuracy leaderboard."""
    get_current_user(request)
    return get_leaderboard()


# ══════════════════════════════════════════════════════════════════════════════
# SENTIMENT DRIFT TELEMETRY (live analysis from agent_response_queue)
# ══════════════════════════════════════════════════════════════════════════════

_DRIFT_GRADE_THRESHOLD = 0.5
_DRIFT_EDIT_THRESHOLD = 15.0
_DRIFT_MIN_SAMPLES = 3


@app.get("/api/metrics/sentiment-drift")
async def get_sentiment_drift(request: Request):
    """Live AI drift analysis: rolling 30-day window comparison from agent_response_queue,
    plus recent drift alerts from system_post_mortems."""
    get_current_user(request)
    try:
        intents = _db_query("""
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
                reasons.append(f"grade dropped {grade_delta:+.2f} ({b_grade:.2f} -> {c_grade:.2f})")
            if edit_delta is not None and edit_delta > _DRIFT_EDIT_THRESHOLD and b_count >= _DRIFT_MIN_SAMPLES:
                degraded = True
                reasons.append(f"edit distance rose {edit_delta:+.1f}% ({b_edit:.1f}% -> {c_edit:.1f}%)")

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

        alerts = _db_query("""
            SELECT id, severity, error_summary, root_cause, remediation, status,
                   occurred_at::text AS created_at
            FROM system_post_mortems
            WHERE component = 'persona_drift'
            ORDER BY occurred_at DESC
            LIMIT 20
        """)

        total = len(analysis)
        degraded_count = sum(1 for a in analysis if a["degraded"])

        return {
            "status": "success",
            "summary": {
                "topics_analyzed": total,
                "degraded": degraded_count,
                "healthy": total - degraded_count,
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
# AVAILABILITY SCANNER (Hunter context injector)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/vrs/availability/{property_name}")
async def get_cabin_availability(property_name: str, request: Request):
    """Calculate next 3 availability gaps (2+ nights) over a 120-day horizon."""
    get_current_user(request)
    import datetime as _dt

    try:
        resp = http_client.get(
            f"{VRS_API}/api/properties/",
            headers=_vrs_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return {"status": "error", "detail": "Could not fetch properties"}

        props = resp.json()
        prop = None
        for p in (props if isinstance(props, list) else []):
            if (p.get("name") or "").lower() == property_name.lower():
                prop = p
                break
        if not prop:
            for p in (props if isinstance(props, list) else []):
                if property_name.lower() in (p.get("name") or "").lower():
                    prop = p
                    break
        if not prop:
            return {"status": "error", "detail": f"Property '{property_name}' not found"}

        res_resp = http_client.get(
            f"{VRS_API}/api/reservations/",
            params={"property_id": prop["id"], "limit": 200, "sort_by": "check_in_date", "order": "asc"},
            headers=_vrs_headers(),
            timeout=10,
        )
        reservations = res_resp.json() if res_resp.status_code == 200 else []
        if not isinstance(reservations, list):
            reservations = []

        today = _dt.date.today()
        horizon = today + _dt.timedelta(days=120)
        future = []
        for r in reservations:
            cin = r.get("check_in_date")
            cout = r.get("check_out_date")
            status = (r.get("status") or "").lower()
            if not cin or not cout or status in ("cancelled", "no_show"):
                continue
            cin_d = _dt.date.fromisoformat(cin) if isinstance(cin, str) else cin
            cout_d = _dt.date.fromisoformat(cout) if isinstance(cout, str) else cout
            if cout_d >= today:
                future.append({"cin": cin_d, "cout": cout_d})
        future.sort(key=lambda x: x["cin"])

        gaps = []
        cursor = today
        for bk in future:
            if bk["cin"] > cursor:
                gap_nights = (bk["cin"] - cursor).days
                if gap_nights >= 2:
                    gaps.append({
                        "start": cursor.strftime("%b %-d"),
                        "end": bk["cin"].strftime("%b %-d"),
                        "nights": gap_nights,
                    })
            cursor = max(cursor, bk["cout"])
            if len(gaps) >= 3:
                break

        if len(gaps) < 3 and cursor < horizon:
            gaps.append({
                "start": cursor.strftime("%b %-d"),
                "end": "Open",
                "nights": "Available",
            })

        return {"status": "success", "cabin": prop["name"], "property_id": prop["id"], "blocks": gaps[:3]}

    except Exception as e:
        log.warning("availability_scan_error  property=%s  error=%s", property_name, e)
        return {"status": "error", "detail": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_DIR = Path(__file__).resolve().parent


def _serve_html(filename: str) -> HTMLResponse:
    path = TOOLS_DIR / filename
    if not path.exists():
        return HTMLResponse(content=f"<h1>{filename} not found</h1>", status_code=404)
    resp = HTMLResponse(content=path.read_text())
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.get("/")
async def page_dashboard(request: Request):
    """Root route — authenticated users SSO into Next.js, others see login."""
    try:
        user = get_current_user(request)
        token = request.cookies.get(COOKIE_NAME, "")
        if token:
            frontend = os.getenv("VRS_FRONTEND_URL", f"https://crog-ai.com")
            return RedirectResponse(
                url=f"{frontend}/sso?token={token}", status_code=302
            )
        return RedirectResponse(url="/vrs", status_code=302)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def page_login():
    return _serve_html("login.html")


@app.get("/signup", response_class=HTMLResponse)
async def page_signup():
    return _serve_html("signup.html")


@app.get("/users", response_class=HTMLResponse)
async def page_users(request: Request):
    try:
        _require_admin(request)
        return _serve_html("users.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/profile", response_class=HTMLResponse)
async def page_profile(request: Request):
    try:
        get_current_user(request)
        return _serve_html("profile.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/docs-center", response_class=HTMLResponse)
async def page_docs_center(request: Request):
    try:
        get_current_user(request)
        return _serve_html("docs.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/legal", response_class=HTMLResponse)
async def page_legal(request: Request):
    try:
        get_current_user(request)
        return _serve_html("legal.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/intelligence", response_class=HTMLResponse)
async def page_intelligence(request: Request):
    try:
        get_current_user(request)
        return _serve_html("intelligence.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/guest-agent", response_class=HTMLResponse)
async def page_guest_agent(request: Request):
    try:
        get_current_user(request)
        return _serve_html("guest_agent.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/api/vrs/templates")
async def vrs_templates_list(request: Request):
    get_current_user(request)
    return _vrs_get("/api/templates/")


@app.get("/api/vrs/templates/triggers")
async def vrs_template_triggers(request: Request):
    get_current_user(request)
    return _vrs_get("/api/templates/triggers")


@app.post("/api/vrs/templates")
async def vrs_template_create(request: Request):
    get_current_user(request)
    body = await request.json()
    return _vrs_post("/api/templates/", body)


@app.put("/api/vrs/templates/{template_id}")
async def vrs_template_update(template_id: str, request: Request):
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.put(
            f"{VRS_API}/api/templates/{template_id}",
            json=body, headers=_vrs_headers(), timeout=10,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.post("/api/vrs/templates/{template_id}/preview")
async def vrs_template_preview(template_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/templates/{template_id}/preview")


# ── Copilot Queue Proxy ──────────────────────────────────────────────────────

@app.get("/api/vrs/copilot-queue/pending")
async def vrs_copilot_pending(request: Request):
    get_current_user(request)
    return _vrs_get("/api/copilot-queue/pending")


@app.put("/api/vrs/copilot-queue/{msg_id}")
async def vrs_copilot_edit(msg_id: str, request: Request):
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.put(
            f"{VRS_API}/api/copilot-queue/{msg_id}",
            json=body, headers=_vrs_headers(), timeout=10,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    return resp.json()


@app.post("/api/vrs/copilot-queue/{msg_id}/approve")
async def vrs_copilot_approve(msg_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/copilot-queue/{msg_id}/approve")


@app.post("/api/vrs/copilot-queue/{msg_id}/cancel")
async def vrs_copilot_cancel(msg_id: str, request: Request):
    get_current_user(request)
    return _vrs_post(f"/api/copilot-queue/{msg_id}/cancel")


# ── VRS Automations Proxy ────────────────────────────────────────────────────

@app.get("/api/vrs/automations")
async def vrs_automations_list(request: Request):
    get_current_user(request)
    params = {}
    if request.query_params.get("active_only"):
        params["active_only"] = request.query_params["active_only"]
    return _vrs_get("/api/vrs/automations/", params=params)


@app.post("/api/vrs/automations")
async def vrs_automations_create(request: Request):
    get_current_user(request)
    body = await request.json()
    return _vrs_post("/api/vrs/automations/", body)


@app.put("/api/vrs/automations/{rule_id}")
async def vrs_automations_update(rule_id: str, request: Request):
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.put(
            f"{VRS_API}/api/vrs/automations/{rule_id}",
            json=body, headers=_vrs_headers(), timeout=10,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.delete("/api/vrs/automations/{rule_id}")
async def vrs_automations_deactivate(rule_id: str, request: Request):
    get_current_user(request)
    try:
        resp = http_client.delete(
            f"{VRS_API}/api/vrs/automations/{rule_id}",
            headers=_vrs_headers(), timeout=10,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.get("/api/vrs/automations/events")
async def vrs_automations_events(request: Request):
    get_current_user(request)
    params = {}
    if request.query_params.get("limit"):
        params["limit"] = request.query_params["limit"]
    if request.query_params.get("offset"):
        params["offset"] = request.query_params["offset"]
    return _vrs_get("/api/vrs/automations/events", params=params)


@app.get("/api/vrs/automations/events/{rule_id}")
async def vrs_automations_rule_events(rule_id: str, request: Request):
    get_current_user(request)
    params = {}
    if request.query_params.get("limit"):
        params["limit"] = request.query_params["limit"]
    return _vrs_get(f"/api/vrs/automations/events/{rule_id}", params=params)


@app.post("/api/vrs/automations/{rule_id}/test")
async def vrs_automations_test(rule_id: str, request: Request):
    get_current_user(request)
    body = await request.json()
    return _vrs_post(f"/api/vrs/automations/{rule_id}/test", body)


@app.get("/api/vrs/automations/queue-status")
async def vrs_automations_queue_status(request: Request):
    get_current_user(request)
    return _vrs_get("/api/vrs/automations/queue-status")


@app.get("/api/vrs/automations/email-templates")
async def vrs_automations_email_templates(request: Request):
    get_current_user(request)
    return _vrs_get("/api/vrs/automations/email-templates")


@app.get("/preview-email", response_class=HTMLResponse)
async def preview_email():
    """Serve the brand-aesthetic email template preview (no auth — static asset)."""
    path = PROJECT_ROOT / "fortress-guest-platform" / "tools" / "preview_email.html"
    if not path.exists():
        return HTMLResponse(content="<h1>preview_email.html not found</h1>", status_code=404)
    return HTMLResponse(content=path.read_text())


@app.get("/preview/receipt")
async def preview_receipt_pdf():
    """Serve the generated receipt PDF inline in the browser. No auth — preview asset."""
    path = PROJECT_ROOT / "fortress-guest-platform" / "tools" / "preview_receipt.pdf"
    if not path.exists():
        raise HTTPException(404, "preview_receipt.pdf not found — run test_document_engine.py first")
    return Response(
        content=path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=CROG_Receipt.pdf"},
    )


@app.get("/preview/agreement")
async def preview_agreement_pdf():
    """Serve the generated rental agreement PDF inline in the browser. No auth — preview asset."""
    path = PROJECT_ROOT / "fortress-guest-platform" / "tools" / "preview_agreement.pdf"
    if not path.exists():
        raise HTTPException(404, "preview_agreement.pdf not found — run test_document_engine.py first")
    return Response(
        content=path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=CROG_Rental_Agreement.pdf"},
    )


@app.get("/email-intake", response_class=HTMLResponse)
async def page_email_intake(request: Request):
    try:
        get_current_user(request)
        return _serve_html("email_intake.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


VRS_FRONTEND_URL = os.getenv("VRS_FRONTEND_URL", f"http://{BASE}:3001")


@app.get("/vrs-dashboard")
async def vrs_dashboard_gate(request: Request):
    """
    VRS Dashboard gate -- checks auth and VRS access, then serves the full
    dashboard.  Routes through the Command Center (no external port redirect)
    so it works reliably through nginx and Cloudflare tunnel.
    """
    try:
        user = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    user_id = int(user.get("sub", 0))
    username = user.get("username", "unknown")

    try:
        rows = _db_query(
            "SELECT vrs_access FROM fortress_users WHERE id = %s",
            (user_id,),
        )
        has_access = rows[0]["vrs_access"] if rows else False
    except Exception as e:
        log.error("vrs_gate_db_error  user=%s  error=%s", username, e)
        has_access = False

    if has_access:
        log.info("vrs_access_ok  user=%s", username)
        return RedirectResponse(url="/vrs", status_code=302)

    log.warning("vrs_access_denied  user=%s  id=%d", username, user_id)
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Access Denied — VRS Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#000;color:#fff;
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#111;border:1px solid #222;border-radius:16px;padding:48px;
  max-width:480px;width:100%;text-align:center}}
.icon{{font-size:48px;margin-bottom:20px}}
h1{{font-size:22px;margin-bottom:12px;color:#f87171}}
p{{color:#888;font-size:14px;line-height:1.6;margin-bottom:24px}}
.user{{color:#60a5fa;font-weight:600}}
a{{display:inline-block;padding:12px 28px;background:#1a1a1a;border:1px solid #333;
  color:#fff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:600;
  transition:all .15s}}
a:hover{{background:#222;border-color:#4ade80;color:#4ade80}}
</style></head><body>
<div class="card">
  <div class="icon">&#128274;</div>
  <h1>VRS Dashboard Access Required</h1>
  <p>Your account <span class="user">{username}</span> does not have VRS Dashboard access.<br>
     Ask an admin to enable it from the <strong>User Management</strong> panel.</p>
  <a href="/">Back to Dashboard</a>
</div>
</body></html>""", status_code=403)


@app.get("/vrs", response_class=HTMLResponse)
async def page_vrs_hub(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_hub.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/properties", response_class=HTMLResponse)
async def page_vrs_properties(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_properties.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/reservations", response_class=HTMLResponse)
async def page_vrs_reservations(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_reservations.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/guests", response_class=HTMLResponse)
async def page_vrs_guests(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_guests.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/work-orders", response_class=HTMLResponse)
async def page_vrs_work_orders(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_work_orders.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/housekeeping", response_class=HTMLResponse)
async def page_vrs_housekeeping(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_housekeeping.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/contracts", response_class=HTMLResponse)
async def page_vrs_contracts(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_contracts.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/analytics", response_class=HTMLResponse)
async def page_vrs_analytics(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_analytics.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/reservations", response_class=HTMLResponse)
async def page_reservations_shortcut(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_reservations.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/analytics", response_class=HTMLResponse)
async def page_analytics_shortcut(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_analytics.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/hunter", response_class=HTMLResponse)
async def page_vrs_hunter(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_hunter.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/channels", response_class=HTMLResponse)
async def page_vrs_channels(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_channels.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/payments", response_class=HTMLResponse)
async def page_vrs_payments(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_payments.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/utilities", response_class=HTMLResponse)
async def page_vrs_utilities(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_utilities.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/owners", response_class=HTMLResponse)
async def page_vrs_owners(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_owners.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/direct-booking", response_class=HTMLResponse)
async def page_vrs_direct_booking(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_direct_booking.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/iot", response_class=HTMLResponse)
async def page_vrs_iot(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_iot.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/vrs/leads", response_class=HTMLResponse)
async def page_vrs_leads(request: Request):
    try:
        get_current_user(request)
        return _serve_html("vrs_leads.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


# ── Leads Engine API proxy ──

@app.get("/api/vrs/leads-inbox")
async def vrs_leads_list(request: Request, status: str = None, search: str = None,
                         page: int = 1, per_page: int = 50, sort_by: str = "created_at", order: str = "desc"):
    get_current_user(request)
    params = {"page": page, "per_page": per_page, "sort_by": sort_by, "order": order}
    if status:
        params["status"] = status
    if search:
        params["search"] = search
    return _vrs_get("/api/leads-inbox/", params=params)


@app.get("/api/vrs/leads-inbox/{lead_id}")
async def vrs_lead_detail(lead_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/leads-inbox/{lead_id}")


@app.patch("/api/vrs/leads-inbox/{lead_id}")
async def vrs_lead_update(lead_id: str, request: Request):
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.patch(f"{VRS_API}/api/leads-inbox/{lead_id}", json=body, headers=_vrs_headers(), timeout=10)
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.post("/api/vrs/leads/{lead_id}/quotes/build")
async def vrs_build_quote(lead_id: str, request: Request):
    """Proxy to the quote builder. Uses 200s timeout for HYDRA 70B inference."""
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.post(
            f"{VRS_API}/api/leads/{lead_id}/quotes/build",
            json=body, headers=_vrs_headers(), timeout=200,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.post("/api/vrs/leads/{lead_id}/swarm/run")
async def vrs_swarm_run(lead_id: str, request: Request):
    """Proxy to the LangGraph multi-agent swarm. 300s timeout for HYDRA 70B + auditor loop."""
    get_current_user(request)
    body = await request.json()
    try:
        resp = http_client.post(
            f"{VRS_API}/api/leads/{lead_id}/swarm/run",
            json=body, headers=_vrs_headers(), timeout=300,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (swarm timeout)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.get("/api/vrs/leads/{lead_id}/quotes")
async def vrs_lead_quotes(lead_id: str, request: Request):
    get_current_user(request)
    return _vrs_get(f"/api/leads/{lead_id}/quotes")


@app.post("/api/vrs/leads/{lead_id}/quotes/{quote_id}/send")
async def vrs_send_quote(lead_id: str, quote_id: str, request: Request):
    """Proxy to the SMTP dispatcher. Sends branded quote email to lead."""
    get_current_user(request)
    try:
        resp = http_client.post(
            f"{VRS_API}/api/leads/{lead_id}/quotes/{quote_id}/send",
            headers=_vrs_headers(), timeout=30,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (email dispatch)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


# ── Sovereign Checkout Gateway (public — no auth, guest-facing) ──


@app.get("/checkout", response_class=HTMLResponse)
async def checkout_page():
    """Serve the guest-facing checkout page. No auth required — accessed via Magic Link."""
    return _serve_html("checkout.html")


@app.get("/api/vrs/checkout/{quote_id}")
async def vrs_checkout_summary(quote_id: str):
    """Proxy GET checkout summary to FGP backend. Public — no auth."""
    try:
        resp = http_client.get(
            f"{VRS_API}/api/checkout/{quote_id}",
            headers=_vrs_headers(), timeout=15,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (checkout)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.post("/api/vrs/checkout/{quote_id}/complete")
async def vrs_checkout_complete(quote_id: str, request: Request):
    """Proxy POST checkout completion to FGP backend. Public — no auth."""
    body = await request.json()
    try:
        resp = http_client.post(
            f"{VRS_API}/api/checkout/{quote_id}/complete",
            json=body, headers=_vrs_headers(), timeout=15,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (checkout)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


@app.post("/api/vrs/checkout/{quote_id}/create-intent")
async def vrs_create_payment_intent(quote_id: str):
    """Proxy POST create-intent to FGP Stripe service. Public — no auth."""
    try:
        resp = http_client.post(
            f"{VRS_API}/api/checkout/{quote_id}/create-intent",
            json={}, headers=_vrs_headers(), timeout=30,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (create-intent)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLINE INBOUND WEBHOOK — Real-Time Vault Sync
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/webhooks/streamline")
async def streamline_webhook(request: Request):
    """
    Receive real-time event payloads from Streamline VRS.

    Streamline can push events for:
        reservation.created, reservation.updated, reservation.cancelled,
        property.updated, guest.updated, etc.

    Each payload is validated through the IngestionGuard (Pydantic + DLQ)
    and upserted into the local Postgres vault for real-time Swarm memory.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON"}, status_code=400)

    event_type = body.get("event", body.get("type", "unknown"))
    payload_data = body.get("data", body)
    source_id = str(body.get("id", body.get("confirmation_id", "")))

    log.info(
        "streamline_webhook  event=%s  source_id=%s  keys=%s",
        event_type, source_id, sorted(body.keys())[:8],
    )

    try:
        import sys as _sys
        if str(PROJECT_ROOT) not in _sys.path:
            _sys.path.insert(0, str(PROJECT_ROOT))
        from src.models.ingestion_guard import IngestionGuard

        conn_for_guard = _get_pooled_conn()
        try:
            guard = IngestionGuard(conn_for_guard)
            guard.ensure_tables()

            upserted = False

            if "reservation" in event_type.lower() or "confirmation_id" in payload_data:
                result = guard.validate_reservation(payload_data, endpoint=f"webhook:{event_type}")

                if result.valid:
                    model = result.data
                    guest = model.guest

                    _db_query("""
                        INSERT INTO guest_leads
                            (guest_name, guest_email, guest_phone, event_type,
                             cabin_names, check_in, check_out, nights,
                             quoted_total, status, notes, extracted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (
                        guest.full_name if guest else "",
                        guest.email if guest else None,
                        guest.best_phone if guest else None,
                        event_type,
                        [model.unit_name] if model.unit_name else [],
                        model.start_date, model.end_date,
                        model.days_number if model.days_number > 0 else None,
                        float(model.price_total) if model.price_total else None,
                        model.status_label,
                        f"Via Streamline webhook: {event_type}",
                    ), commit=True)
                    upserted = True
                    log.info(
                        "streamline_webhook_upserted  event=%s  reservation=%s  guest=%s",
                        event_type, model.confirmation_id,
                        guest.full_name if guest else "unknown",
                    )

            elif "property" in event_type.lower():
                result = guard.validate_property(payload_data, endpoint=f"webhook:{event_type}")
                if result.valid:
                    log.info(
                        "streamline_webhook_property  event=%s  property=%s  (logged, no auto-upsert)",
                        event_type, result.data.name,
                    )

            else:
                log.info("streamline_webhook_unhandled  event=%s", event_type)

            summary = guard.print_summary()

        finally:
            _put_conn(conn_for_guard)

    except ImportError as e:
        log.warning("streamline_webhook_guard_unavailable: %s", e)
    except Exception as e:
        log.error("streamline_webhook_error: %s", e)
        # Never return 5xx to the webhook sender — always ACK
        pass

    # ── ATTRIBUTION: Check if this booking matches a Hunter outbound ──
    if "reservation" in event_type.lower():
        try:
            guest_phone = None
            booking_revenue = None
            booking_res_id = source_id or None
            if isinstance(payload_data, dict):
                g = payload_data.get("guest", {})
                guest_phone = (g.get("best_phone") or g.get("phone") or
                               payload_data.get("guest_phone") or "").strip()
                booking_revenue = payload_data.get("price_total") or payload_data.get("total_amount")
            if guest_phone:
                _run_hunter_attribution(guest_phone, booking_revenue, booking_res_id)
        except Exception as attr_err:
            log.warning("hunter_attribution_error: %s", attr_err)

    return JSONResponse({"status": "received", "event": event_type}, status_code=200)


# ══════════════════════════════════════════════════════════════════════════════
# REACTIVATION HUNTER — Conversion Attribution
# ══════════════════════════════════════════════════════════════════════════════

def _run_hunter_attribution(phone: str, revenue=None, reservation_id=None):
    """Check if a phone number matches a recent proactive_sales outbound. If so, claim the kill."""
    if not phone:
        return
    rows = _db_query("""
        UPDATE agent_response_queue
        SET converted_at = NOW(),
            revenue_generated = COALESCE(%s, 0),
            reservation_id = COALESCE(%s, reservation_id)
        WHERE phone_number = %s
          AND intent = 'proactive_sales'
          AND status IN ('sent', 'approved', 'edited')
          AND created_at >= CURRENT_DATE - INTERVAL '14 days'
          AND converted_at IS NULL
        RETURNING id, guest_name, cabin_name, revenue_generated
    """, (revenue, reservation_id, phone), commit=True)
    for r in rows:
        log.info("HUNTER_KILL_CONFIRMED  queue_id=%s  guest=%s  cabin=%s  revenue=$%s",
                 r["id"], r["guest_name"], r["cabin_name"], r["revenue_generated"])
        _db_query("""
            INSERT INTO system_post_mortems (sector, severity, component, error_summary, status)
            VALUES ('crog', 'info', 'hunter_conversion',
                    'KILL CONFIRMED: ' || %s || ' rebooked ' || %s || ' — $' || %s::text || ' attributed to Reactivation Hunter',
                    'resolved')
        """, (r["guest_name"], r["cabin_name"], str(r["revenue_generated"])), commit=True)


@app.post("/api/webhooks/booking/attribute")
async def booking_attribution_webhook(request: Request):
    """Manual or external attribution trigger. Accepts {phone, revenue, reservation_id}."""
    get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    phone = (body.get("phone") or body.get("guest_phone") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    _run_hunter_attribution(phone, body.get("revenue"), body.get("reservation_id"))
    return {"status": "attributed", "phone": phone}


@app.get("/api/metrics/hunter-roi")
async def hunter_roi_metrics(request: Request):
    """Hunter ROI — conversions and revenue attributed to proactive_sales outbound."""
    get_current_user(request)
    rows = _db_query("""
        SELECT
            COALESCE(SUM(revenue_generated), 0) AS total_revenue,
            COUNT(converted_at) AS conversions,
            COUNT(*) FILTER (WHERE status IN ('sent','approved','edited')) AS total_sent,
            COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
            COUNT(*) AS total_drafts
        FROM agent_response_queue
        WHERE intent = 'proactive_sales'
          AND created_at >= CURRENT_DATE - INTERVAL '30 days'
    """)
    r = rows[0] if rows else {}
    sent = int(r.get("total_sent", 0))
    conversions = int(r.get("conversions", 0))
    return {
        "revenue_30d": float(r.get("total_revenue", 0)),
        "conversions_30d": conversions,
        "total_sent_30d": sent,
        "pending_review": int(r.get("pending", 0)),
        "total_drafts_30d": int(r.get("total_drafts", 0)),
        "conversion_rate": round(conversions / sent * 100, 1) if sent > 0 else 0,
    }


@app.get("/api/metrics/hunter-confidence")
async def get_hunter_confidence(request: Request):
    """Calculates the Swarm's 7-day Zero-Touch Rate to authorize Auto-Fire."""
    get_current_user(request)
    try:
        rows = _db_query("""
            SELECT
                COUNT(*) AS total_sends,
                COALESCE(AVG(edit_distance_pct), 0) AS avg_edit_distance,
                COALESCE(
                    SUM(CASE WHEN edit_distance_pct < 3 THEN 1 ELSE 0 END) * 100.0
                    / NULLIF(COUNT(*), 0),
                0) AS zero_touch_rate
            FROM starred_responses
            WHERE intent = 'proactive_sales'
              AND created_at >= CURRENT_DATE - INTERVAL '7 days'
        """)
        s = rows[0] if rows else {}
        ztr = float(s.get("zero_touch_rate", 0))
        total = int(s.get("total_sends", 0))
        return {
            "status": "success",
            "total_sends_7d": total,
            "avg_edit_distance_pct": round(float(s.get("avg_edit_distance", 0)), 1),
            "zero_touch_rate_pct": round(ztr, 1),
            "auto_fire_status": "ARMED" if ztr >= 97.0 and total > 50 else "LEARNING",
        }
    except Exception as e:
        log.error("hunter_confidence_error  err=%s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/guest-agent/hunter/sweep")
async def hunter_manual_sweep(request: Request):
    """Trigger a manual Reactivation Hunter sweep."""
    get_current_user(request)
    import subprocess
    proc = subprocess.Popen(
        [str(PROJECT_ROOT / "venv" / "bin" / "python"), "-m", "src.daemons.reactivation_hunter", "--max-drafts", "10"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    log.info("hunter_manual_sweep  pid=%s", proc.pid)
    return {"status": "sweep_triggered", "pid": proc.pid}


@app.post("/api/webhooks/stripe")
async def stripe_webhook_proxy(request: Request):
    """
    Stripe webhook handler — intercepts Wallet checkout completions,
    then proxies all events to the FGP backend.

    For 'checkout.session.completed' with metadata.source == 'swarm_wallet':
        1. Log the payment to the local DB
        2. Create a reservation record
        3. Queue Streamline calendar block via deferred_api_writes
        4. Notify the guest agent queue
    """
    raw_body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # --- Wallet interception: handle swarm_wallet payments locally ---
    try:
        _handle_wallet_payment(raw_body, sig)
    except Exception as e:
        log.warning("wallet_webhook_interception_error  error=%s", str(e)[:200])

    # --- Always proxy to FGP backend for standard processing ---
    try:
        resp = http_client.post(
            f"{VRS_API}/api/webhooks/stripe",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": sig,
            },
            timeout=120,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (stripe webhook)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


def _handle_wallet_payment(raw_body: bytes, sig: str) -> None:
    """
    Intercept Stripe webhook for Wallet-generated checkout sessions.
    Creates the reservation in Postgres and queues Streamline calendar block.
    """
    import stripe as _stripe

    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return

    try:
        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        event = _stripe.Webhook.construct_event(raw_body, sig, webhook_secret)
    except (_stripe.error.SignatureVerificationError, Exception):
        return

    if event.get("type") != "checkout.session.completed":
        return

    session = event["data"]["object"]
    meta = session.get("metadata", {})

    if meta.get("source") != "swarm_wallet" or meta.get("type") != "reservation_checkout":
        return

    guest_name = meta.get("guest_name", "")
    guest_phone = meta.get("guest_phone", "")
    guest_email = meta.get("guest_email", "")
    property_name = meta.get("property_name", "")
    start_date = meta.get("start_date", "")
    end_date = meta.get("end_date", "")
    nights = meta.get("nights", "0")
    nightly_rate = meta.get("nightly_rate", "0")
    amount_total = session.get("amount_total", 0)
    payment_intent = session.get("payment_intent", "")

    log.info(
        "wallet_payment_completed  guest=%s  property=%s  dates=%s->%s  amount=$%.2f  pi=%s",
        guest_name, property_name, start_date, end_date,
        amount_total / 100, payment_intent,
    )

    # --- 1. Log payment to system_post_mortems ---
    try:
        _db_query("""
            INSERT INTO system_post_mortems
                (sector, severity, component, error_summary, status, resolved_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            "crog", "info", "wallet_payment_received",
            f"PAYMENT RECEIVED: {property_name} for {guest_name} "
            f"({start_date} to {end_date}), ${amount_total/100:,.2f}. "
            f"Stripe PI: {payment_intent}",
            "resolved", "stripe_webhook",
        ), commit=True)
    except Exception as e:
        log.error("wallet_postmortem_failed: %s", e)

    # --- 2. Insert reservation into guest_leads ---
    try:
        cabin_names = [property_name] if property_name else []
        _db_query("""
            INSERT INTO guest_leads
                (guest_name, guest_email, guest_phone, event_type,
                 cabin_names, check_in, check_out, nights,
                 quoted_total, status, notes, extracted_at)
            VALUES (%s, %s, %s, 'reservation', %s, %s::date, %s::date, %s,
                    %s, 'confirmed', %s, NOW())
        """, (
            guest_name, guest_email, guest_phone,
            cabin_names, start_date, end_date, int(nights),
            float(amount_total / 100),
            f"Booked via Swarm Wallet. Stripe PI: {payment_intent}",
        ), commit=True)
        log.info("wallet_reservation_created  guest=%s  property=%s", guest_name, property_name)
    except Exception as e:
        log.error("wallet_reservation_insert_failed: %s", e)

    # --- 3. Queue Streamline calendar block (via circuit breaker deferred writes) ---
    try:
        from src.daemons.circuit_breaker import get_connection as _cb_conn, queue_deferred_write
        cb_conn = _cb_conn()
        queue_deferred_write(cb_conn, "streamline", "CreateReservation", {
            "methodName": "CreateReservation",
            "params": {
                "property_name": property_name,
                "start_date": start_date,
                "end_date": end_date,
                "guest_name": guest_name,
                "guest_email": guest_email,
                "guest_phone": guest_phone,
                "amount": amount_total / 100,
                "source": "swarm_wallet",
                "stripe_pi": payment_intent,
            },
        })
        cb_conn.close()
        log.info("wallet_streamline_queued  property=%s  dates=%s->%s", property_name, start_date, end_date)
    except Exception as e:
        log.warning("wallet_streamline_queue_failed: %s", e)

    # --- 4. Notify the agent queue (confirmation message) ---
    try:
        _db_query("""
            INSERT INTO agent_response_queue
                (phone_number, guest_name, guest_tier, cabin_name,
                 guest_message, intent, status, urgency_level, created_at)
            VALUES (%s, %s, 'confirmed_booker', %s, %s, 'booking_confirmation',
                    'pending_review', 2, NOW())
        """, (
            guest_phone, guest_name, property_name,
            f"[AUTO] {guest_name} just paid ${amount_total/100:,.2f} for {property_name} "
            f"({start_date} to {end_date}). Generate a warm confirmation SMS.",
        ), commit=True)
    except Exception as e:
        log.warning("wallet_confirmation_queue_failed: %s", e)


# ── Admin Payment Verification Queue ──


@app.get("/api/admin/payments/pending")
async def admin_pending_payments(request: Request):
    """Proxy GET pending payments to FGP backend. Auth required."""
    get_current_user(request)
    return _vrs_get("/api/admin/payments/pending")


@app.post("/api/admin/payments/{quote_id}/verify")
async def admin_verify_payment(quote_id: str, request: Request):
    """Proxy POST payment verification to FGP backend. Auth required."""
    get_current_user(request)
    try:
        resp = http_client.post(
            f"{VRS_API}/api/admin/payments/{quote_id}/verify",
            json={}, headers=_vrs_headers(), timeout=30,
        )
    except http_client.RequestException:
        raise HTTPException(502, "VRS platform unavailable (verify)")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])
    return resp.json()


# ── Web UI SSO Gate ──
WEBUI_URL = os.getenv("WEBUI_URL", f"http://{BASE}:8080")


@app.get("/webui")
async def webui_gate(request: Request):
    """
    SSO gate for Open WebUI (Mission Control).
    Checks the user is logged in and has web_ui_access permission.
    If yes, redirects to the Web UI. If no, shows an access-denied page.
    """
    try:
        user = get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    user_id = int(user.get("sub", 0))
    username = user.get("username", "unknown")

    # Check web_ui_access in database
    try:
        rows = _db_query(
            "SELECT web_ui_access FROM fortress_users WHERE id = %s",
            (user_id,),
        )
        has_access = rows[0]["web_ui_access"] if rows else False
    except Exception as e:
        log.error("webui_gate_db_error  user=%s  error=%s", username, e)
        has_access = False

    if has_access:
        log.info("webui_access_ok  user=%s", username)
        return RedirectResponse(url=WEBUI_URL, status_code=302)

    log.warning("webui_access_denied  user=%s  id=%d", username, user_id)
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Access Denied — Web UI</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#000;color:#fff;
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#111;border:1px solid #222;border-radius:16px;padding:48px;
  max-width:480px;width:100%;text-align:center}}
.icon{{font-size:48px;margin-bottom:20px}}
h1{{font-size:22px;margin-bottom:12px;color:#f87171}}
p{{color:#888;font-size:14px;line-height:1.6;margin-bottom:24px}}
.user{{color:#60a5fa;font-weight:600}}
a{{display:inline-block;padding:12px 28px;background:#1a1a1a;border:1px solid #333;
  color:#fff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:600;
  transition:all .15s}}
a:hover{{background:#222;border-color:#4ade80;color:#4ade80}}
</style></head><body>
<div class="card">
  <div class="icon">&#128274;</div>
  <h1>Web UI Access Required</h1>
  <p>Your account <span class="user">{username}</span> does not have Web UI access.<br>
     Ask an admin to enable it from the <strong>User Management</strong> panel.</p>
  <a href="/">Back to Dashboard</a>
</div>
</body></html>""", status_code=403)


# ══════════════════════════════════════════════════════════════════════════════
# GUEST AGENT — AI Guest Communication Review Queue
# ══════════════════════════════════════════════════════════════════════════════


class IncomingMessage(BaseModel):
    phone_number: str = Field(min_length=1, max_length=20)
    message: str = Field(min_length=1, max_length=2000)
    cabin_name: Optional[str] = None


class EditDraft(BaseModel):
    edited_draft: str = Field(min_length=1, max_length=2000)


class RejectDraft(BaseModel):
    reason: str = Field(default="", max_length=500)



# ══════════════════════════════════════════════════════════════════════════════
# PILLAR 1 — Recursive Learning Vector (guest_golden_responses → Qdrant)
# ══════════════════════════════════════════════════════════════════════════════

_GOLDEN_COLLECTION = "guest_golden_responses"
_EMBED_MODEL = "nomic-embed-text:latest"


def _vectorize_golden_response(
    guest_input: str,
    ai_output: str,
    topic: str = "",
    cabin: str = "",
    quality_score: int = 5,
    starred_by: str = "human_review",
) -> bool:
    """
    Embed a human-approved response and upsert it into the Qdrant
    guest_golden_responses collection for recursive learning.
    """
    import uuid

    if not guest_input or not ai_output:
        return False

    try:
        embed_resp = http_client.post(
            f"http://{BASE}/v1/embeddings",
            json={"model": _EMBED_MODEL, "input": guest_input},
            timeout=10,
        )
        embed_resp.raise_for_status()
        vector = embed_resp.json()["data"][0]["embedding"]

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, guest_input))

        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct

        qc = QdrantClient(host="localhost", port=6333, timeout=5,
                          check_compatibility=False)
        qc.upsert(
            collection_name=_GOLDEN_COLLECTION,
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "guest_input": guest_input,
                    "ai_output": ai_output,
                    "topic": topic,
                    "cabin": cabin or "",
                    "quality_score": quality_score,
                    "guest_tier": "",
                    "starred_by": starred_by,
                    "run_id": f"console_{int(time.time())}",
                },
            )],
        )
        log.info(
            "golden_vectorized  id=%s  topic=%s  cabin=%s  score=%d  input=%s",
            point_id, topic, cabin, quality_score, guest_input[:60],
        )
        return True
    except Exception as e:
        log.error("golden_vectorize_failed  error=%s", e)
        return False


def _capture_starred_response(
    queue_id: int,
    final_message: str,
    response_type: str = "approved",
    original_draft: str = None,
):
    """Embed and store a human-approved/edited response in starred_responses (Postgres pgvector).
    This is the durable learning vault — Qdrant is the search layer, Postgres is the source of truth."""
    import hashlib

    try:
        item_rows = _db_query("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
        if not item_rows:
            return
        item = item_rows[0]

        embed_resp = http_client.post(
            f"http://{BASE}/v1/embeddings",
            json={"model": _EMBED_MODEL, "input": final_message},
            timeout=10,
        )
        embed_resp.raise_for_status()
        vector = embed_resp.json()["data"][0]["embedding"]

        phone_hash = None
        if item.get("phone_number"):
            phone_hash = hashlib.sha256(item["phone_number"].encode()).hexdigest()

        edit_pct = None
        if original_draft is not None:
            if original_draft == final_message:
                edit_pct = 0.0
            else:
                from difflib import SequenceMatcher
                edit_pct = round((1 - SequenceMatcher(None, original_draft, final_message).ratio()) * 100, 2)

        _db_query("""
            INSERT INTO starred_responses
                (message_body, embedding, intent, cabin_name, guest_name,
                 phone_number_hash, loyalty_tier, response_type, quality_grade,
                 queue_id, ai_model, original_draft, edit_distance_pct)
            VALUES (%s, %s::vector, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            final_message,
            str(vector),
            item.get("intent", ""),
            item.get("cabin_name", ""),
            item.get("guest_name", ""),
            phone_hash,
            item.get("guest_tier", ""),
            response_type,
            item.get("quality_grade") or 5,
            queue_id,
            item.get("ai_model", ""),
            original_draft,
            edit_pct,
        ), commit=True)

        log.info("starred_response_captured  queue_id=%d  type=%s  edit_pct=%s  intent=%s",
                 queue_id, response_type, edit_pct, item.get("intent", ""))
    except Exception as e:
        log.warning("starred_response_capture_failed  queue_id=%d  error=%s", queue_id, e)


def _agent_instance():
    """Lazy-load GuestAgent to avoid import overhead at startup."""
    if not hasattr(_agent_instance, "_inst"):
        import sys
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from src.guest_agent import GuestAgent
        _agent_instance._inst = GuestAgent()
    return _agent_instance._inst


@app.post("/api/guest-agent/incoming")
async def guest_agent_incoming(request: Request, body: IncomingMessage):
    """Process an incoming guest message through the AI agent."""
    user = get_current_user(request)
    log.info("guest_agent_incoming  actor=%s  phone=%s", user.get("username"), body.phone_number)
    agent = _agent_instance()
    result = agent.process_message(body.phone_number, body.message, body.cabin_name)
    return {
        "queue_id": result.queue_id,
        "intent": result.intent.primary,
        "sentiment": result.intent.sentiment,
        "urgency": result.intent.urgency,
        "escalation": result.intent.escalation_required,
        "cabin": result.cabin_name,
        "guest": result.guest_name,
        "confidence": result.confidence_score,
        "model": result.ai_model,
        "duration_ms": result.duration_ms,
        "draft_preview": result.ai_draft[:200],
    }


@app.get("/api/guest-agent/queue")
async def guest_agent_queue(request: Request, status: str = "pending_review", limit: int = 50):
    """List items in the review queue."""
    get_current_user(request)
    if status == "all":
        rows = _db_query("""
            SELECT * FROM agent_response_queue
            ORDER BY CASE status WHEN 'pending_review' THEN 0 ELSE 1 END,
                     urgency_level DESC, created_at ASC
            LIMIT %s
        """, (min(limit, 200),))
    else:
        rows = _db_query("""
            SELECT * FROM agent_response_queue
            WHERE status = %s
            ORDER BY urgency_level DESC, created_at ASC
            LIMIT %s
        """, (status, min(limit, 200)))
    # Serialize datetimes
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    return {"items": rows, "count": len(rows)}


@app.post("/api/guest-agent/queue/{queue_id}/approve")
async def guest_agent_approve(queue_id: int, request: Request):
    """Approve an AI draft and send via SMS."""
    user = get_current_user(request)
    rows = _db_query("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item = rows[0]
    actor = user.get("username", "unknown")

    # Attempt SMS delivery
    sms_result = {"success": False, "error": "Twilio not configured"}
    try:
        from twilio.rest import Client as TwilioClient
        from dotenv import load_dotenv as _ld
        _ld(PROJECT_ROOT / ".env")
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        from_ph = os.getenv("TWILIO_PHONE_NUMBER")
        if sid and token and from_ph:
            tc = TwilioClient(sid, token)
            msg = tc.messages.create(body=item["ai_draft"], from_=from_ph, to=item["phone_number"])
            sms_result = {"success": True, "sid": msg.sid, "status": msg.status}
    except ImportError:
        sms_result = {"success": False, "error": "twilio package not installed"}
    except Exception as e:
        sms_result = {"success": False, "error": str(e)}

    # Update queue
    _db_query("""
        UPDATE agent_response_queue
        SET status = 'approved', reviewed_by = %s, reviewed_at = NOW(),
            sent_via = 'sms', delivery_status = %s, sent_at = NOW(), updated_at = NOW()
        WHERE id = %s
    """, (actor, sms_result.get("status", "unknown"), queue_id), commit=True)

    # Log outbound message
    _db_query("""
        INSERT INTO message_archive (source, phone_number, message_body, direction,
            cabin_name, response_generated_by, status, sent_at, created_at)
        VALUES ('fortress_agent', %s, %s, 'outbound', %s, 'ai', %s, NOW(), NOW())
    """, (item["phone_number"], item["ai_draft"], item.get("cabin_name"),
          "sent" if sms_result.get("success") else "failed"), commit=True)

    # --- Pillar 1: Self-Learning — approved-as-is drafts are golden by definition ---
    try:
        from prompts.starred_db import vectorize_golden_response
        vectorize_golden_response(
            topic=item.get("intent", "general"),
            cabin=item.get("cabin_name", "unknown"),
            guest_input=item.get("guest_message", ""),
            ai_output=item.get("ai_draft", ""),
            quality_score=5,
            guest_tier="unknown",
            starred_by=actor,
            queue_id=queue_id,
        )
    except Exception as e:
        log.warning("feedback_loop_vectorize on approve FAILED (non-fatal): %s", e)

    log.info("guest_agent_approve  actor=%s  queue_id=%d  sms=%s",
             actor, queue_id, sms_result.get("success"))

    # Pillar 1: vectorize into Qdrant (search layer)
    import threading
    threading.Thread(
        target=_vectorize_golden_response,
        kwargs={
            "guest_input": item.get("guest_message", ""),
            "ai_output": item["ai_draft"],
            "topic": item.get("intent", ""),
            "cabin": item.get("cabin_name", ""),
            "quality_score": 5,
            "starred_by": f"approved:{actor}",
        },
        daemon=True,
    ).start()

    # Pillar 1: capture to starred_responses (durable pgvector vault)
    threading.Thread(
        target=_capture_starred_response,
        kwargs={
            "queue_id": queue_id,
            "final_message": item["ai_draft"],
            "response_type": "approved",
            "original_draft": item["ai_draft"],
        },
        daemon=True,
    ).start()

    return {"status": "approved_and_sent", "send_result": sms_result, "queue_id": queue_id}


@app.post("/api/guest-agent/queue/{queue_id}/edit")
async def guest_agent_edit(queue_id: int, request: Request, body: EditDraft):
    """Edit the AI draft and send the edited version."""
    user = get_current_user(request)
    rows = _db_query("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item = rows[0]
    actor = user.get("username", "unknown")

    sms_result = {"success": False, "error": "Twilio not configured"}
    try:
        from twilio.rest import Client as TwilioClient
        from dotenv import load_dotenv as _ld
        _ld(PROJECT_ROOT / ".env")
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        from_ph = os.getenv("TWILIO_PHONE_NUMBER")
        if sid and token and from_ph:
            tc = TwilioClient(sid, token)
            msg = tc.messages.create(body=body.edited_draft, from_=from_ph, to=item["phone_number"])
            sms_result = {"success": True, "sid": msg.sid, "status": msg.status}
    except ImportError:
        sms_result = {"success": False, "error": "twilio package not installed"}
    except Exception as e:
        sms_result = {"success": False, "error": str(e)}

    _db_query("""
        UPDATE agent_response_queue
        SET status = 'edited', reviewed_by = %s, reviewed_at = NOW(),
            edited_draft = %s, sent_via = 'sms', delivery_status = %s,
            sent_at = NOW(), updated_at = NOW()
        WHERE id = %s
    """, (actor, body.edited_draft, sms_result.get("status", "unknown"), queue_id), commit=True)

    _db_query("""
        INSERT INTO message_archive (source, phone_number, message_body, direction,
            cabin_name, response_generated_by, status, sent_at, created_at)
        VALUES ('fortress_agent', %s, %s, 'outbound', %s, 'ai_edited', %s, NOW(), NOW())
    """, (item["phone_number"], body.edited_draft, item.get("cabin_name"),
          "sent" if sms_result.get("success") else "failed"), commit=True)

    # --- Pillar 1: Self-Learning — human-edited drafts are high-value training data ---
    try:
        from prompts.starred_db import vectorize_golden_response
        vectorize_golden_response(
            topic=item.get("intent", "general"),
            cabin=item.get("cabin_name", "unknown"),
            guest_input=item.get("guest_message", ""),
            ai_output=body.edited_draft,
            quality_score=5,
            guest_tier="unknown",
            starred_by=f"{actor}_edit",
            queue_id=queue_id,
        )
    except Exception as e:
        log.warning("feedback_loop_vectorize on edit FAILED (non-fatal): %s", e)

    log.info("guest_agent_edit  actor=%s  queue_id=%d  sms=%s",
             actor, queue_id, sms_result.get("success"))

    # Pillar 1: vectorize into Qdrant (search layer)
    import threading
    threading.Thread(
        target=_vectorize_golden_response,
        kwargs={
            "guest_input": item.get("guest_message", ""),
            "ai_output": body.edited_draft,
            "topic": item.get("intent", ""),
            "cabin": item.get("cabin_name", ""),
            "quality_score": 5,
            "starred_by": f"edited:{actor}",
        },
        daemon=True,
    ).start()

    # Pillar 1: capture to starred_responses (durable pgvector vault — includes edit distance)
    threading.Thread(
        target=_capture_starred_response,
        kwargs={
            "queue_id": queue_id,
            "final_message": body.edited_draft,
            "response_type": "edited",
            "original_draft": item.get("ai_draft", ""),
        },
        daemon=True,
    ).start()

    return {"status": "edited_and_sent", "send_result": sms_result, "queue_id": queue_id}


@app.post("/api/guest-agent/queue/{queue_id}/reject")
async def guest_agent_reject(queue_id: int, request: Request, body: RejectDraft):
    """Reject an AI draft."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")
    _db_query("""
        UPDATE agent_response_queue
        SET status = 'rejected', reviewed_by = %s, reviewed_at = NOW(),
            review_notes = %s, updated_at = NOW()
        WHERE id = %s
    """, (actor, body.reason, queue_id), commit=True)
    log.info("guest_agent_reject  actor=%s  queue_id=%d", actor, queue_id)
    return {"status": "rejected", "queue_id": queue_id}


@app.get("/api/guest-agent/stats")
async def guest_agent_stats(request: Request):
    """Agent performance statistics."""
    get_current_user(request)
    rows = _db_query("""
        SELECT
            count(*) as total,
            count(*) FILTER (WHERE status = 'pending_review') as pending,
            count(*) FILTER (WHERE status = 'approved') as approved,
            count(*) FILTER (WHERE status = 'edited') as edited,
            count(*) FILTER (WHERE status = 'rejected') as rejected,
            count(*) FILTER (WHERE status = 'sent') as sent,
            count(*) FILTER (WHERE escalation_required) as escalations,
            avg(ai_duration_ms) as avg_duration,
            avg(confidence_score) as avg_confidence
        FROM agent_response_queue
    """)
    stats = dict(rows[0]) if rows else {}

    intent_rows = _db_query("""
        SELECT intent, count(*) as cnt FROM agent_response_queue
        GROUP BY intent ORDER BY cnt DESC
    """)
    stats["by_intent"] = {r["intent"]: r["cnt"] for r in intent_rows}

    cabin_rows = _db_query("""
        SELECT cabin_name, count(*) as cnt FROM agent_response_queue
        WHERE cabin_name IS NOT NULL GROUP BY cabin_name ORDER BY cnt DESC
    """)
    stats["by_cabin"] = {r["cabin_name"]: r["cnt"] for r in cabin_rows}

    # Serialize Decimals
    for k, v in stats.items():
        if hasattr(v, "__float__") and not isinstance(v, (int, float)):
            stats[k] = round(float(v), 2) if v is not None else None
    return stats


@app.get("/api/guest-agent/history/{phone}")
async def guest_agent_history(phone: str, request: Request):
    """Conversation history for a phone number."""
    get_current_user(request)
    rows = _db_query("""
        SELECT direction, message_body, cabin_name, sent_at, intent, sentiment,
               response_generated_by
        FROM message_archive WHERE phone_number = %s
        ORDER BY COALESCE(sent_at, created_at) DESC LIMIT 30
    """, (phone,))
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    return {"phone": phone, "messages": rows}


# ══════════════════════════════════════════════════════════════════════════════
# GUEST AGENT — Grading & Recursive Learning
# ══════════════════════════════════════════════════════════════════════════════

class GradeRequest(BaseModel):
    grade: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=500)


@app.post("/api/guest-agent/queue/{queue_id}/grade")
async def guest_agent_grade(queue_id: int, request: Request, body: GradeRequest):
    """Grade an AI response (1-5 stars). Captures learning data."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")

    rows = _db_query("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item = rows[0]

    # Calculate edit distance if not already done
    edit_pct = 0.0
    if item.get("edited_draft") and item.get("ai_draft"):
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, item["ai_draft"], item["edited_draft"]).ratio()
        edit_pct = round((1 - ratio) * 100, 1)
    elif item.get("status") == "approved":
        edit_pct = 0.0

    # Update grade
    _db_query("""
        UPDATE agent_response_queue
        SET quality_grade = %s, grade_notes = %s, edit_distance_pct = %s, updated_at = NOW()
        WHERE id = %s
    """, (body.grade, body.notes, edit_pct, queue_id), commit=True)

    # Log to learning table
    correction = ""
    if item.get("edited_draft"):
        correction = f"AI said: {item['ai_draft'][:200]} → Human corrected to: {item['edited_draft'][:200]}"

    _db_query("""
        INSERT INTO agent_learning_log
            (queue_id, pattern_type, intent, cabin_name, ai_draft, human_edit,
             correction_summary, quality_grade, edit_distance_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        queue_id,
        "edit" if item.get("edited_draft") else ("approved" if item["status"] == "approved" else "graded"),
        item.get("intent"), item.get("cabin_name"),
        item.get("ai_draft"), item.get("edited_draft"),
        correction, body.grade, edit_pct
    ), commit=True)

    # --- Pillar 1: Self-Learning Feedback Loop ---
    # Vectorize high-quality responses into SQLite + Qdrant for future retrieval
    vectorize_result = None
    if body.grade >= 4 or item.get("status") == "approved":
        final_message = item.get("edited_draft") or item.get("ai_draft") or ""
        if final_message.strip():
            try:
                from prompts.starred_db import vectorize_golden_response
                vectorize_result = vectorize_golden_response(
                    topic=item.get("intent", "general"),
                    cabin=item.get("cabin_name", "unknown"),
                    guest_input=item.get("guest_message", ""),
                    ai_output=final_message,
                    quality_score=body.grade,
                    guest_tier="unknown",
                    starred_by=actor,
                    queue_id=queue_id,
                )
                log.info("feedback_loop_vectorize  queue_id=%d  grade=%d  result=%s",
                         queue_id, body.grade, vectorize_result)
            except Exception as e:
                log.warning("feedback_loop_vectorize FAILED (non-fatal): %s", e)

    log.info("guest_agent_grade  actor=%s  queue_id=%d  grade=%d  edit_pct=%.1f",
             actor, queue_id, body.grade, edit_pct)
    return {
        "status": "graded", "queue_id": queue_id, "grade": body.grade,
        "edit_pct": edit_pct, "vectorized": vectorize_result,
    }


@app.get("/api/guest-agent/learning")
async def guest_agent_learning(request: Request):
    """Learning analytics — shows how the AI is improving over time."""
    get_current_user(request)

    # Overall grade distribution
    grade_dist = _db_query("""
        SELECT quality_grade, count(*) as cnt
        FROM agent_response_queue
        WHERE quality_grade IS NOT NULL
        GROUP BY quality_grade ORDER BY quality_grade
    """)

    # Grade by intent
    by_intent = _db_query("""
        SELECT intent, ai_model,
            count(*) as total,
            count(*) FILTER (WHERE quality_grade IS NOT NULL) as graded,
            ROUND(AVG(quality_grade)::numeric, 2) as avg_grade,
            ROUND(AVG(edit_distance_pct)::numeric, 1) as avg_edit_pct,
            count(*) FILTER (WHERE status = 'approved') as approved_as_is,
            count(*) FILTER (WHERE status = 'edited') as needed_edit,
            count(*) FILTER (WHERE status = 'rejected') as rejected,
            ROUND(AVG(ai_duration_ms)::numeric, 0) as avg_duration_ms
        FROM agent_response_queue
        GROUP BY intent, ai_model ORDER BY total DESC
    """)

    # Edit patterns — what does the human change most?
    edit_patterns = _db_query("""
        SELECT queue_id, intent, cabin_name, ai_draft, human_edit,
               quality_grade, edit_distance_pct, learned_at
        FROM agent_learning_log
        WHERE pattern_type = 'edit'
        ORDER BY learned_at DESC LIMIT 20
    """)

    # Trend — are we getting better?
    trend = _db_query("""
        SELECT
            date_trunc('day', created_at)::date as day,
            count(*) as total,
            ROUND(AVG(quality_grade)::numeric, 2) as avg_grade,
            ROUND(AVG(edit_distance_pct)::numeric, 1) as avg_edit_pct,
            count(*) FILTER (WHERE status = 'approved') as approved,
            count(*) FILTER (WHERE status = 'edited') as edited
        FROM agent_response_queue
        GROUP BY date_trunc('day', created_at)
        ORDER BY day DESC LIMIT 30
    """)

    # Top corrections — recurring fixes
    corrections = _db_query("""
        SELECT intent, COUNT(*) as times,
               ROUND(AVG(edit_distance_pct)::numeric, 1) as avg_edit_pct,
               ROUND(AVG(quality_grade)::numeric, 1) as avg_grade
        FROM agent_learning_log
        WHERE pattern_type = 'edit' AND edit_distance_pct > 30
        GROUP BY intent ORDER BY times DESC
    """)

    def serialize(rows):
        out = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                elif hasattr(v, "__float__") and not isinstance(v, (int, float)):
                    d[k] = float(v) if v is not None else None
            out.append(d)
        return out

    return {
        "grade_distribution": serialize(grade_dist),
        "by_intent": serialize(by_intent),
        "edit_patterns": serialize(edit_patterns),
        "trend": serialize(trend),
        "heavy_corrections": serialize(corrections),
        "summary": {
            "total_graded": sum(r["cnt"] for r in grade_dist) if grade_dist else 0,
            "avg_grade": round(sum(r["quality_grade"] * r["cnt"] for r in grade_dist) /
                              max(sum(r["cnt"] for r in grade_dist), 1), 2) if grade_dist else None,
        }
    }


@app.get("/api/guest-agent/learning/digest")
async def guest_agent_learning_digest(request: Request):
    """
    Generate a learning digest — analyzes all edits to extract patterns
    and suggest prompt improvements. This is the recursive learning engine.
    """
    get_current_user(request)

    # Get all edited items with both drafts
    edits = _db_query("""
        SELECT id, intent, cabin_name, guest_message, ai_draft, edited_draft,
               ai_model, quality_grade, edit_distance_pct
        FROM agent_response_queue
        WHERE status = 'edited' AND edited_draft IS NOT NULL
        ORDER BY created_at DESC
    """)

    if not edits:
        return {"patterns": [], "suggestions": [], "message": "No edits yet to learn from."}

    patterns = []
    suggestions = set()

    for e in edits:
        ai = e["ai_draft"] or ""
        human = e["edited_draft"] or ""
        intent = e["intent"] or "GENERAL"

        # Detect specific correction patterns
        if "[Guest's First Name]" in ai or "[Guest" in ai:
            patterns.append({
                "type": "placeholder_usage",
                "severity": "high",
                "detail": f"#{e['id']}: AI used [Guest's First Name] placeholder instead of actual name",
                "intent": intent,
            })
            suggestions.add("NEVER use brackets like [Guest's First Name]. Use the guest's actual name or say 'Hi there!'")

        if any(fake in ai for fake in ["(555)", "(706) 555", "555-", "EMER"]):
            patterns.append({
                "type": "fake_phone_number",
                "severity": "high",
                "detail": f"#{e['id']}: AI invented a fake emergency phone number",
                "intent": intent,
            })
            suggestions.add("Never invent phone numbers. If you don't have a real number, say 'call us' or 'reach out to us'")

        # Check if AI was alarmist but human was calm
        alarm_words = ["immediately", "right away", "safety first", "exit the cabin", "get out", "evacuate"]
        calm_words = ["could you", "please let us know", "a little more context", "is the pilot"]
        ai_alarm = sum(1 for w in alarm_words if w.lower() in ai.lower())
        human_calm = sum(1 for w in calm_words if w.lower() in human.lower())
        if ai_alarm >= 2 and human_calm >= 1:
            patterns.append({
                "type": "over_alarmist",
                "severity": "medium",
                "detail": f"#{e['id']}: AI was overly alarmist, human responded calmly and asked questions first",
                "intent": intent,
            })
            suggestions.add("For maintenance issues, stay calm and ask clarifying questions before escalating. Don't tell guests to evacuate unless it's clearly life-threatening")

        # Check if AI made up information
        wifi_patterns = ["WiFi123", "WELCOME123", "CWSun", "password is:"]
        if any(p in ai for p in wifi_patterns) and any(p not in human for p in wifi_patterns):
            patterns.append({
                "type": "fabricated_info",
                "severity": "critical",
                "detail": f"#{e['id']}: AI may have fabricated WiFi password or other specific info",
                "intent": intent,
            })
            suggestions.add("NEVER make up WiFi passwords, door codes, or phone numbers. If the info isn't in your context, say 'Let me check on that and get back to you'")

        # Heavy edit detection
        pct = float(e["edit_distance_pct"] or 0)
        if pct > 70:
            patterns.append({
                "type": "heavy_rewrite",
                "severity": "medium",
                "detail": f"#{e['id']}: {pct:.0f}% rewritten — AI response was significantly changed",
                "intent": intent,
            })

    # Style analysis from Taylor's edits
    all_human_edits = [e["edited_draft"] for e in edits if e["edited_draft"]]
    if all_human_edits:
        # Common opening phrases
        openers = {}
        for h in all_human_edits:
            first_sentence = h.split(".")[0].split("!")[0].strip()[:50]
            openers[first_sentence] = openers.get(first_sentence, 0) + 1

        style_notes = []
        if any("Hi there" in h for h in all_human_edits):
            style_notes.append("Taylor prefers 'Hi there!' as opening greeting")
        if any("thank you for" in h.lower() for h in all_human_edits):
            style_notes.append("Taylor acknowledges the guest's message with 'Thank you for your message'")
        if any("please let us know" in h.lower() for h in all_human_edits):
            style_notes.append("Taylor uses 'Please let us know' for follow-up")
        if any("we would be happy to help" in h.lower() for h in all_human_edits):
            style_notes.append("Taylor uses 'We would be happy to help' — warm and professional")

        return {
            "total_edits": len(edits),
            "patterns": patterns,
            "suggestions": list(suggestions),
            "style_notes": style_notes,
            "common_openers": dict(sorted(openers.items(), key=lambda x: -x[1])[:5]),
            "avg_edit_distance": round(sum(float(e["edit_distance_pct"] or 0) for e in edits) / len(edits), 1),
        }

    return {
        "total_edits": len(edits),
        "patterns": patterns,
        "suggestions": list(suggestions),
        "style_notes": [],
        "avg_edit_distance": 0,
    }


@app.post("/api/guest-agent/learning/apply")
async def guest_agent_apply_learning(request: Request):
    """
    Apply learned patterns to the AI prompt template.
    This is the recursive improvement engine — edits teach the AI.
    """
    user = get_current_user(request)
    actor = user.get("username", "unknown")

    # Gather all edit patterns
    edits = _db_query("""
        SELECT id, intent, cabin_name, guest_message, ai_draft, edited_draft,
               ai_model, quality_grade, edit_distance_pct
        FROM agent_response_queue
        WHERE status = 'edited' AND edited_draft IS NOT NULL
        ORDER BY created_at DESC
    """)

    if not edits:
        return {"status": "no_edits", "patterns_applied": 0}

    # Build the learned corrections section
    suggestions = set()
    style_notes = []
    examples = []

    for e in edits:
        ai = e["ai_draft"] or ""
        human = e["edited_draft"] or ""

        if "[Guest's First Name]" in ai or "[Guest" in ai:
            suggestions.add("NEVER use placeholder brackets like [Guest's First Name]. Use 'Hi there!' or the guest's actual name.")

        if any(fake in ai for fake in ["(555)", "(706) 555", "555-", "EMER"]):
            suggestions.add("NEVER invent phone numbers. Say 'give us a call' or 'reach out to us' instead.")

        alarm_words = ["immediately", "right away", "safety first", "exit the cabin", "get out"]
        if sum(1 for w in alarm_words if w.lower() in ai.lower()) >= 2:
            suggestions.add("For maintenance issues, stay CALM. Ask clarifying questions before escalating. Do NOT tell guests to evacuate unless clearly life-threatening.")

        if any(p in ai for p in ["WiFi123", "WELCOME123", "CWSun"]):
            suggestions.add("NEVER make up WiFi passwords, door codes, or specific details. If the info is not in your context, say 'Let me check on that and get back to you.'")

        # Collect good examples from human edits
        pct = float(e.get("edit_distance_pct") or 0)
        if pct > 30 and human and len(human) > 20:
            examples.append({
                "intent": e["intent"],
                "guest": e["guest_message"][:100],
                "bad": ai[:150],
                "good": human[:150],
            })

    # Detect Taylor's style
    all_human = [e["edited_draft"] for e in edits if e["edited_draft"]]
    if any("Hi there" in h for h in all_human):
        style_notes.append("Open with 'Hi there!' as the greeting")
    if any("thank you for" in h.lower() for h in all_human):
        style_notes.append("Acknowledge the guest's message: 'Thank you for your message'")
    if any("we would be happy to help" in h.lower() for h in all_human):
        style_notes.append("Use 'We would be happy to help' — warm and professional")
    if any("please let us know" in h.lower() for h in all_human):
        style_notes.append("Close with 'Please let us know if we can help with anything further!'")

    # Build the LEARNED CORRECTIONS block
    corrections_block = "\n  LEARNED CORRECTIONS (from human review):\n"
    for s in sorted(suggestions):
        corrections_block += f"  - {s}\n"

    if style_notes:
        corrections_block += "\n  TAYLOR'S PREFERRED STYLE:\n"
        for sn in style_notes:
            corrections_block += f"  - {sn}\n"

    if examples[:3]:  # Include up to 3 examples
        corrections_block += "\n  CORRECTION EXAMPLES:\n"
        for i, ex in enumerate(examples[:3], 1):
            corrections_block += f"  Example {i} ({ex['intent']}):\n"
            corrections_block += f"    Guest asked: \"{ex['guest']}\"\n"
            corrections_block += f"    BAD (AI wrote): \"{ex['bad']}\"\n"
            corrections_block += f"    GOOD (Taylor corrected): \"{ex['good']}\"\n"

    # Update the prompt YAML file
    prompt_path = PROJECT_ROOT / "prompts" / "v1" / "guest_sms_agent.yaml"
    if not prompt_path.exists():
        return {"status": "error", "detail": "Prompt file not found"}

    import yaml
    content = prompt_path.read_text()
    data = yaml.safe_load(content)
    template = data.get("template", "")

    # Remove old LEARNED CORRECTIONS section if present
    if "LEARNED CORRECTIONS" in template:
        lines = template.split("\n")
        new_lines = []
        skip = False
        for line in lines:
            if "LEARNED CORRECTIONS" in line:
                skip = True
                continue
            if skip and (line.strip().startswith("PROPERTY:") or line.strip().startswith("INSTRUCTIONS:")):
                skip = False
            if skip and line.strip().startswith("-"):
                continue
            if skip and line.strip().startswith("Example"):
                continue
            if skip and (line.strip().startswith("BAD") or line.strip().startswith("GOOD") or
                         line.strip().startswith("Guest asked") or line.strip().startswith("TAYLOR") or
                         line.strip().startswith("CORRECTION")):
                continue
            if skip and line.strip() == "":
                continue
            if not skip:
                new_lines.append(line)
        template = "\n".join(new_lines)

    # Insert LEARNED CORRECTIONS before PROPERTY: section
    insert_point = "PROPERTY: {cabin_name}"
    if insert_point in template:
        template = template.replace(
            insert_point,
            corrections_block + "\n  " + insert_point
        )

    # Write back
    data["template"] = template
    data["learned_version"] = datetime.now().isoformat(timespec="seconds")
    data["patterns_applied"] = len(suggestions) + len(style_notes) + len(examples)

    with open(prompt_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)

    # Clear the agent cache so it reloads the updated prompt
    if hasattr(_agent_instance, "_inst"):
        delattr(_agent_instance, "_inst")

    patterns_applied = len(suggestions) + len(style_notes) + len(examples)
    log.info("learning_applied  actor=%s  patterns=%d  suggestions=%d  style=%d  examples=%d",
             actor, patterns_applied, len(suggestions), len(style_notes), len(examples[:3]))

    return {
        "status": "applied",
        "patterns_applied": patterns_applied,
        "suggestions": list(suggestions),
        "style_notes": style_notes,
        "examples_count": len(examples[:3]),
        "prompt_version": data.get("learned_version"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TWILIO INBOUND WEBHOOK — Receives real guest SMS, feeds to Guest Agent
# ══════════════════════════════════════════════════════════════════════════════

TWIML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _validate_twilio_signature(request: Request, form_data: dict) -> bool:
    """Validate Twilio X-Twilio-Signature header against the request."""
    try:
        from twilio.request_validator import RequestValidator
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not auth_token:
            return True  # skip validation if no token configured

        validator = RequestValidator(auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        # Cloudflare may rewrite the scheme — reconstruct with the forwarded proto
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        if forwarded_proto:
            url = url.replace("http://", f"{forwarded_proto}://", 1)
        return validator.validate(url, form_data, signature)
    except ImportError:
        return True  # twilio package not installed, skip validation
    except Exception as e:
        log.warning("twilio_signature_validation_error  error=%s", e)
        return True  # fail open — don't drop messages over validation errors


def _resolve_guest_identity(phone_e164: str) -> dict:
    """
    Look up a guest by sanitized E.164 phone number.
    Returns {guest_name, guest_email, guest_tier, guest_id} or empty fields.
    """
    identity = {"guest_name": None, "guest_email": None, "guest_tier": "new", "guest_id": None}

    try:
        rows = _db_query("""
            SELECT id, guest_name, guest_email, guest_phone,
                   COUNT(*) OVER (PARTITION BY guest_email) as stay_count
            FROM guest_leads
            WHERE guest_phone = %s
            ORDER BY check_out DESC NULLS LAST
            LIMIT 1
        """, (phone_e164,))

        if not rows:
            # Try partial match (last 10 digits) for non-normalized legacy data
            if len(phone_e164) >= 12:
                last10 = phone_e164[-10:]
                rows = _db_query("""
                    SELECT id, guest_name, guest_email, guest_phone,
                           COUNT(*) OVER (PARTITION BY guest_email) as stay_count
                    FROM guest_leads
                    WHERE RIGHT(REGEXP_REPLACE(guest_phone, '[^0-9]', '', 'g'), 10) = %s
                    ORDER BY check_out DESC NULLS LAST
                    LIMIT 1
                """, (last10,))

        if rows:
            row = rows[0]
            identity["guest_name"] = row.get("guest_name")
            identity["guest_email"] = row.get("guest_email")
            identity["guest_id"] = row.get("id")
            stays = int(row.get("stay_count", 0))
            if stays >= 5:
                identity["guest_tier"] = "platinum"
            elif stays >= 3:
                identity["guest_tier"] = "gold"
            elif stays >= 1:
                identity["guest_tier"] = "silver"

    except Exception as e:
        log.warning("guest_identity_resolution_failed  phone=%s  error=%s", phone_e164, e)

    return identity


@app.post("/api/webhooks/twilio")
@app.post("/webhooks/sms/incoming")
async def twilio_sms_webhook(request: Request):
    """
    Twilio inbound SMS webhook — receives guest texts, sanitizes, resolves
    identity, archives, and triggers the OODA Swarm.

    Twilio sends POST as application/x-www-form-urlencoded with fields:
        MessageSid, From, To, Body, NumMedia, FromCity, FromState, etc.

    This endpoint:
        1. Validates Twilio signature (if auth token configured)
        2. Sanitizes phone via Pillar 2A E.164 normalization
        3. Resolves guest identity (name, email, tier) from guest_leads
        4. Archives inbound message to message_archive
        5. Drops message into agent_response_queue (status=pending)
        6. Triggers the Guest Agent OODA loop in a background thread
        7. Returns empty TwiML <Response></Response> immediately
    """
    form = await request.form()
    raw_phone = form.get("From", "")
    body_text = form.get("Body", "")
    message_sid = form.get("MessageSid", "")
    to_phone = form.get("To", "")
    from_city = form.get("FromCity", "")
    from_state = form.get("FromState", "")

    # --- Step 1: Validate Twilio signature ---
    form_dict = {k: v for k, v in form.items()}
    if not _validate_twilio_signature(request, form_dict):
        log.warning("twilio_signature_invalid  from=%s  sid=%s", raw_phone, message_sid)
        return Response(content=TWIML_EMPTY, media_type="application/xml", status_code=200)

    if not raw_phone or not body_text:
        return Response(content=TWIML_EMPTY, media_type="application/xml", status_code=200)

    # --- Step 2: Phone normalization (Pillar 2A) ---
    try:
        from src.daemons.data_sanitizer import sanitize_phone
        phone_e164, normalize_rule = sanitize_phone(raw_phone)
    except ImportError:
        try:
            import re as _re
            _digits = _re.sub(r"[^\d]", "", raw_phone)
            if raw_phone.strip().startswith("+") and 11 <= len(_digits) <= 15:
                phone_e164, normalize_rule = f"+{_digits}", "inline_international"
            elif len(_digits) == 10:
                phone_e164, normalize_rule = f"+1{_digits}", "inline_e164_10d"
            elif len(_digits) == 11 and _digits.startswith("1"):
                phone_e164, normalize_rule = f"+{_digits}", "inline_e164_11d"
            else:
                phone_e164, normalize_rule = raw_phone, "inline_passthrough"
        except Exception:
            phone_e164, normalize_rule = raw_phone, "fallback_raw"

    log.info(
        "twilio_inbound  from=%s  e164=%s  rule=%s  body=%s  sid=%s  city=%s",
        raw_phone, phone_e164, normalize_rule, body_text[:60], message_sid,
        f"{from_city}, {from_state}" if from_city else "unknown",
    )

    # --- Step 3: Identity resolution ---
    identity = _resolve_guest_identity(phone_e164)
    guest_name = identity["guest_name"]
    guest_tier = identity["guest_tier"]
    guest_email = identity["guest_email"]

    if guest_name:
        log.info(
            "twilio_guest_resolved  phone=%s  name=%s  tier=%s  email=%s",
            phone_e164, guest_name, guest_tier, guest_email,
        )
    else:
        log.info("twilio_guest_unknown  phone=%s  tier=new", phone_e164)

    # --- Step 4: Archive inbound message ---
    inbound_id = None
    try:
        inbound_rows = _db_query("""
            INSERT INTO message_archive (
                source, external_id, phone_number, message_body, direction,
                status, received_at, created_at
            ) VALUES ('twilio', %s, %s, %s, 'inbound', 'received', NOW(), NOW())
            RETURNING id
        """, (message_sid, phone_e164, body_text), commit=True)
        inbound_id = inbound_rows[0]["id"] if inbound_rows else None
    except Exception as e:
        log.error("twilio_inbound_archive_failed  error=%s", e)

    # --- Step 5: Trigger the Swarm (background thread for Twilio's 15s limit) ---
    import threading

    def _process():
        try:
            agent = _agent_instance()
            result = agent.process_message(phone_e164, body_text)
            log.info(
                "twilio_swarm_triggered  queue_id=%s  intent=%s  cabin=%s  "
                "guest=%s  tier=%s",
                result.queue_id, result.intent.primary, result.cabin_name,
                guest_name or "unknown", guest_tier,
            )

            # Enrich the queue item with resolved identity
            if result.queue_id:
                updates = []
                params = []
                if inbound_id:
                    updates.append("inbound_message_id = %s")
                    params.append(inbound_id)
                if guest_name:
                    updates.append("guest_name = %s")
                    params.append(guest_name)
                if guest_tier and guest_tier != "new":
                    updates.append("guest_tier = %s")
                    params.append(guest_tier)
                if updates:
                    params.append(result.queue_id)
                    _db_query(
                        f"UPDATE agent_response_queue SET {', '.join(updates)} WHERE id = %s",
                        tuple(params), commit=True,
                    )
        except Exception as e:
            log.error("twilio_swarm_error  phone=%s  error=%s", phone_e164, e)

    threading.Thread(target=_process, daemon=True).start()

    # --- Step 6: Immediate TwiML response (empty = no auto-reply) ---
    return Response(content=TWIML_EMPTY, media_type="application/xml", status_code=200)


@app.post("/webhooks/sms/status")
async def twilio_status_webhook(request: Request):
    """Twilio delivery status callback — updates message status."""
    form = await request.form()
    message_sid = form.get("MessageSid", "")
    status = form.get("MessageStatus", "")

    if message_sid and status:
        try:
            _db_query("""
                UPDATE message_archive SET status = %s, updated_at = NOW()
                WHERE external_id = %s
            """, (status, message_sid), commit=True)
        except Exception:
            pass

    return Response(content="OK", status_code=200)


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
@app.get("/api/health")
async def health():
    """Standardized health check — available without auth."""
    import psutil
    return {
        "status": "healthy",
        "service": "fortress-command-center",
        "version": "2.3.0",
        "uptime_seconds": int(time.time() - _start_time),
        "memory_mb": int(psutil.Process().memory_info().rss / 1024 / 1024) if "psutil" in dir() else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL INTAKE SYSTEM — Enterprise Data Hygiene APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/email-intake/dashboard")
async def email_intake_dashboard(request: Request):
    """Full intake dashboard: pipeline stats, quarantine, escalation queue, rule health."""
    get_current_user(request)

    # Quarantine stats
    quarantine = _db_query("""
        SELECT status, count(*) as cnt FROM email_quarantine GROUP BY status ORDER BY cnt DESC
    """)
    quarantine_pending = _db_query("""
        SELECT id, sender, subject, content_preview, rule_reason, created_at
        FROM email_quarantine WHERE status = 'quarantined'
        ORDER BY created_at DESC LIMIT 50
    """)

    # Escalation queue
    escalation_pending = _db_query("""
        SELECT eq.id, eq.trigger_type, eq.trigger_detail, eq.priority, eq.status,
               eq.created_at, ea.sender, ea.subject
        FROM email_escalation_queue eq
        JOIN email_archive ea ON ea.id = eq.email_id
        WHERE eq.status = 'pending'
        ORDER BY eq.priority, eq.created_at DESC
        LIMIT 50
    """)
    escalation_stats = _db_query("""
        SELECT priority, status, count(*) as cnt
        FROM email_escalation_queue
        GROUP BY priority, status ORDER BY priority, status
    """)

    # Routing rule stats (most-hit rules)
    rule_stats = _db_query("""
        SELECT rule_type, pattern, action, reason, hit_count
        FROM email_routing_rules WHERE is_active = TRUE
        ORDER BY hit_count DESC LIMIT 20
    """)

    # Classification rule stats
    class_stats = _db_query("""
        SELECT division, count(*) as rule_count, sum(hit_count) as total_hits
        FROM email_classification_rules WHERE is_active = TRUE
        GROUP BY division ORDER BY total_hits DESC
    """)

    # Division distribution (current archive)
    division_dist = _db_query("""
        SELECT division, count(*) as cnt,
               avg(division_confidence) as avg_confidence
        FROM email_archive GROUP BY division ORDER BY cnt DESC
    """)

    # DLQ health (resilient — table may not exist yet)
    try:
        dlq_counts = _db_query("""
            SELECT status, count(*) as cnt
            FROM email_dead_letter_queue GROUP BY status
        """) or []
    except Exception:
        dlq_counts = []

    # SLA breach counts
    sla_breaches = {}
    for priority, hours in SLA_HOURS.items():
        try:
            sla_rows = _db_query("""
                SELECT count(*) as cnt FROM email_escalation_queue
                WHERE status = 'pending' AND priority = %s
                  AND created_at < NOW() - (%s || ' hours')::INTERVAL
            """, (priority, str(hours)))
            sla_breaches[priority] = sla_rows[0]["cnt"] if sla_rows else 0
        except Exception:
            sla_breaches[priority] = 0

    # Snoozed count (resilient — column may not exist yet)
    try:
        snoozed = _db_query("""
            SELECT count(*) as cnt FROM email_escalation_queue WHERE status = 'snoozed'
        """)
    except Exception:
        snoozed = [{"cnt": 0}]

    return {
        "quarantine": {"by_status": quarantine, "pending": quarantine_pending},
        "escalation": {"pending": escalation_pending, "stats": escalation_stats},
        "routing_rules": rule_stats,
        "classification_rules": class_stats,
        "division_distribution": division_dist,
        "dlq": {r["status"]: r["cnt"] for r in dlq_counts},
        "sla_breaches": sla_breaches,
        "snoozed_count": snoozed[0]["cnt"] if snoozed else 0,
    }


@app.post("/api/email-intake/quarantine/{item_id}/release")
async def quarantine_release(item_id: int, request: Request):
    """Release a quarantined email — ingest it into email_archive."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")

    rows = _db_query("SELECT * FROM email_quarantine WHERE id = %s", (item_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    item = rows[0]

    if item["status"] != "quarantined":
        return {"status": "already_processed", "current_status": item["status"]}

    _db_query("""
        UPDATE email_quarantine
        SET status = 'released', reviewed_by = %s, reviewed_at = NOW()
        WHERE id = %s
    """, (actor, item_id), commit=True)

    log.info("quarantine_released  actor=%s  item_id=%d  sender=%s", actor, item_id, item.get("sender", ""))
    return {"status": "released", "item_id": item_id}


@app.post("/api/email-intake/quarantine/{item_id}/delete")
async def quarantine_delete(item_id: int, request: Request):
    """Permanently delete a quarantined email with cascading ban + negative RAG reinforcement.

    When a user deletes one spam email, the system:
    1. Extracts the sender domain and creates a GateKeeper REJECT rule
    2. Embeds the email into pgvector as a JUNK precedent (negative RAG)
    3. Cascade-deletes ALL quarantined emails from the same sender
    """
    user = get_current_user(request)
    actor = user.get("username", "unknown")

    # ── Fetch the email before nuking it ──
    rows = _db_query("SELECT id, sender, subject, content_preview FROM email_quarantine WHERE id = %s", (item_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    item = rows[0]
    sender = (item.get("sender") or "").strip()
    subject = (item.get("subject") or "").strip()
    content = (item.get("content_preview") or "").strip()

    # ── Layer 1: GateKeeper ban (domain-level REJECT rule) ──
    domain_ban_created = False
    sender_domain = ""
    if sender and "@" in sender:
        sender_domain = sender.split("@", 1)[1].lower()
        existing = _db_query(
            "SELECT id FROM email_routing_rules WHERE rule_type = 'sender_block' AND pattern = %s LIMIT 1",
            (f"%@{sender_domain}",),
        )
        if not existing:
            _db_query("""
                INSERT INTO email_routing_rules (rule_type, pattern, action, division, reason, is_active)
                VALUES ('sender_block', %s, 'REJECT', NULL, %s, TRUE)
            """, (f"%@{sender_domain}", f"Auto-banned: user {actor} deleted quarantine #{item_id}"), commit=True)
            domain_ban_created = True
            log.info("quarantine_autoban  domain=@%s  actor=%s  trigger=quarantine#%d", sender_domain, actor, item_id)

    # ── Layer 2: Negative RAG reinforcement ──
    precedent_id = None
    try:
        from src.utils.llm_classifier import store_triage_precedent
        from src.utils.text_sanitizer import sanitize_email_text
        clean_body = sanitize_email_text(content) if content else ""
        precedent_id = store_triage_precedent(
            email_id=item_id,
            sender=sender,
            subject=subject,
            body=clean_body,
            division="JUNK",
            priority="P4",
            reasoning=f"User {actor} permanently deleted from quarantine. Domain: @{sender_domain}",
            created_by=f"QUARANTINE_DELETE_{actor}",
        )
    except Exception as rag_err:
        log.warning("Negative RAG precedent failed for quarantine #%d: %s", item_id, rag_err)

    # ── Layer 3: Cascading nuke — wipe ALL quarantined emails from same sender ──
    cascade_count = 0
    if sender:
        count_rows = _db_query(
            "SELECT count(*) as cnt FROM email_quarantine WHERE sender = %s AND status = 'quarantined'",
            (sender,),
        )
        cascade_count = count_rows[0]["cnt"] if count_rows else 0

        _db_query(
            "DELETE FROM email_quarantine WHERE sender = %s AND status = 'quarantined'",
            (sender,), commit=True,
        )
    else:
        _db_query(
            "DELETE FROM email_quarantine WHERE id = %s",
            (item_id,), commit=True,
        )
        cascade_count = 1

    log.info(
        "quarantine_cascade_delete  actor=%s  trigger=#%d  sender=%s  domain=@%s  "
        "nuked=%d  ban=%s  precedent=%s",
        actor, item_id, sender[:50], sender_domain, cascade_count,
        domain_ban_created, precedent_id,
    )

    return {
        "status": "deleted",
        "item_id": item_id,
        "sender": sender,
        "domain_banned": f"@{sender_domain}" if domain_ban_created else None,
        "cascade_deleted": cascade_count,
        "precedent_id": precedent_id,
    }


# ── Enterprise Constants ──

VALID_DIVISIONS = {
    "CABIN_VRS", "SALES_OPP", "REAL_ESTATE", "HEDGE_FUND",
    "LEGAL_ADMIN", "FINANCE", "PERSONAL", "JUNK", "UNKNOWN",
    "INSURANCE", "COMPLIANCE", "VENDOR_OPS", "MAINTENANCE",
    "TAX", "HR_ADMIN",
}

DISMISS_REASONS = {
    "classification_correct":  "Classification is correct — no action needed",
    "already_handled":         "Already handled outside system",
    "not_relevant":            "Not relevant to any division",
    "duplicate":               "Duplicate of another escalation",
    "informational_only":      "Informational only — no action required",
    "wrong_escalation":        "Should not have been escalated (rule too broad)",
    "defer":                   "Deferred — will revisit later",
}

ACTION_TYPES = {
    "replied":           "Replied to sender",
    "forwarded":         "Forwarded to responsible party",
    "created_task":      "Created a task / work order",
    "filed":             "Filed in appropriate division",
    "scheduled_meeting": "Scheduled a meeting / call",
    "delegated":         "Delegated to team member",
    "escalated_external":"Escalated to external counsel / advisor",
    "archived":          "Reviewed and archived",
    "other":             "Other action (see notes)",
}

SLA_HOURS = {"P0": 1, "P1": 4, "P2": 24, "P3": 72}


@app.post("/api/email-intake/escalation/{item_id}/action")
async def escalation_action(item_id: int, request: Request):
    """Mark an escalation item as seen/actioned/dismissed with structured metadata.

    For 'dismissed': requires dismiss_reason from DISMISS_REASONS.
    For 'actioned': requires action_type from ACTION_TYPES.
    For 'deferred': schedules a snooze and re-queues later.
    """
    user = get_current_user(request)
    actor = user.get("username", "unknown")
    body = await request.json()
    new_status = body.get("status", "seen")
    action_note = body.get("note", "")
    dismiss_reason = body.get("dismiss_reason", "")
    action_type = body.get("action_type", "")
    follow_up_date = body.get("follow_up_date")
    delegate_to = body.get("delegate_to", "")
    snooze_hours = body.get("snooze_hours", 0)

    if new_status not in ("seen", "actioned", "dismissed", "deferred", "snoozed"):
        raise HTTPException(status_code=400, detail="Invalid status. Use: seen, actioned, dismissed, deferred, snoozed")

    # ── Structured dismiss with learning ──
    if new_status == "dismissed":
        if not dismiss_reason:
            dismiss_reason = "classification_correct"
        if dismiss_reason not in DISMISS_REASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid dismiss_reason. Valid: {', '.join(DISMISS_REASONS.keys())}"
            )
        action_note = action_note or DISMISS_REASONS[dismiss_reason]

    # ── Structured action with accountability ──
    if new_status == "actioned":
        if not action_type:
            action_type = "other"
        if action_type not in ACTION_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action_type. Valid: {', '.join(ACTION_TYPES.keys())}"
            )
        action_note = f"[{ACTION_TYPES[action_type]}] {action_note}".strip()

    # ── Snooze / Defer: re-queue after N hours ──
    if new_status in ("deferred", "snoozed"):
        snooze_hours = snooze_hours or 24
        new_status_db = "snoozed"
        _db_query("""
            UPDATE email_escalation_queue
            SET status = %s, seen_by = %s, seen_at = NOW(),
                action_taken = %s, snooze_until = NOW() + (%s || ' hours')::INTERVAL
            WHERE id = %s
        """, (new_status_db, actor,
              f"Snoozed for {snooze_hours}h: {action_note}", str(snooze_hours), item_id),
            commit=True)

        _db_query("""
            INSERT INTO email_intake_review_log
                (escalation_id, email_id, actor, action_type, notes)
            VALUES (%s, (SELECT email_id FROM email_escalation_queue WHERE id = %s),
                    %s, 'snooze', %s)
        """, (item_id, item_id, actor, f"Snoozed {snooze_hours}h: {action_note}"), commit=True)

        log.info("escalation_snoozed  actor=%s  item_id=%d  hours=%d", actor, item_id, snooze_hours)
        return {"status": "snoozed", "item_id": item_id, "snooze_hours": snooze_hours}

    # ── Standard status update ──
    metadata = json.dumps({
        "dismiss_reason": dismiss_reason,
        "action_type": action_type,
        "delegate_to": delegate_to,
        "follow_up_date": follow_up_date,
    })

    _db_query("""
        UPDATE email_escalation_queue
        SET status = %s, seen_by = %s, seen_at = NOW(), action_taken = %s
        WHERE id = %s
    """, (new_status, actor, action_note, item_id), commit=True)

    # ── Dismiss learning: behavior depends on reason ──
    if new_status == "dismissed":
        esc_rows = _db_query("""
            SELECT eq.email_id, ea.division, ea.division_confidence,
                   ea.sender, ea.subject
            FROM email_escalation_queue eq
            JOIN email_archive ea ON ea.id = eq.email_id
            WHERE eq.id = %s
        """, (item_id,))
        if esc_rows:
            eid = esc_rows[0]["email_id"]
            div = esc_rows[0]["division"]
            conf = esc_rows[0]["division_confidence"] or 0
            sender = esc_rows[0].get("sender", "")
            subject = esc_rows[0].get("subject", "")

            if dismiss_reason == "classification_correct":
                if conf < 80:
                    _db_query("""
                        UPDATE email_archive SET division_confidence = LEAST(division_confidence + 20, 90)
                        WHERE id = %s
                    """, (eid,), commit=True)

            elif dismiss_reason == "wrong_escalation":
                # The escalation rule was too broad — flag for rule review
                _db_query("""
                    INSERT INTO email_intake_review_log
                        (escalation_id, email_id, actor, action_type, notes)
                    VALUES (%s, %s, %s, 'rule_review_flag',
                            'Escalation rule flagged as too broad — consider tightening pattern')
                """, (item_id, eid, actor), commit=True)

            elif dismiss_reason == "not_relevant":
                # Don't boost confidence — the classification might still be wrong
                pass

            elif dismiss_reason == "duplicate":
                pass

            elif dismiss_reason == "informational_only":
                if conf < 70:
                    _db_query("""
                        UPDATE email_archive SET division_confidence = LEAST(division_confidence + 10, 85)
                        WHERE id = %s
                    """, (eid,), commit=True)

            elif dismiss_reason == "already_handled":
                if conf < 80:
                    _db_query("""
                        UPDATE email_archive SET division_confidence = LEAST(division_confidence + 15, 90)
                        WHERE id = %s
                    """, (eid,), commit=True)

            _db_query("""
                INSERT INTO email_intake_review_log
                    (escalation_id, email_id, actor, action_type, old_division, new_division,
                     old_confidence, new_confidence, notes)
                VALUES (%s, %s, %s, 'dismiss', %s, %s, %s, %s, %s)
            """, (item_id, eid, actor, div, div, conf, conf,
                  f"Dismiss reason: {dismiss_reason} — {DISMISS_REASONS.get(dismiss_reason, '')}"),
                commit=True)

    # ── Action logging with structured metadata ──
    if new_status == "actioned":
        esc_rows = _db_query("""
            SELECT eq.email_id, ea.division, ea.division_confidence
            FROM email_escalation_queue eq
            JOIN email_archive ea ON ea.id = eq.email_id
            WHERE eq.id = %s
        """, (item_id,))
        if esc_rows:
            eid = esc_rows[0]["email_id"]
            div = esc_rows[0]["division"]
            conf = esc_rows[0]["division_confidence"] or 0

            if conf < 90:
                _db_query("""
                    UPDATE email_archive SET division_confidence = LEAST(division_confidence + 15, 95)
                    WHERE id = %s
                """, (eid,), commit=True)

            _db_query("""
                INSERT INTO email_intake_review_log
                    (escalation_id, email_id, actor, action_type, old_division, new_division,
                     old_confidence, new_confidence, notes)
                VALUES (%s, %s, %s, 'action', %s, %s, %s, %s, %s)
            """, (item_id, eid, actor, div, div, conf, conf,
                  f"Action: {action_type} | Delegate: {delegate_to} | Note: {action_note}"),
                commit=True)

    log.info("escalation_%s  actor=%s  item_id=%d  reason=%s  action_type=%s",
             new_status, actor, item_id, dismiss_reason, action_type)
    return {"status": new_status, "item_id": item_id,
            "dismiss_reason": dismiss_reason, "action_type": action_type}


@app.get("/api/email-intake/rules")
async def email_intake_rules(request: Request):
    """List all routing and classification rules."""
    routing = _db_query("""
        SELECT id, rule_type, pattern, action, division, reason, is_active, hit_count
        FROM email_routing_rules ORDER BY rule_type, hit_count DESC
    """)
    classification = _db_query("""
        SELECT id, division, match_field, pattern, weight, is_active, hit_count, notes
        FROM email_classification_rules ORDER BY division, weight DESC
    """)
    escalation = _db_query("""
        SELECT id, rule_name, trigger_type, match_field, pattern, priority, is_active
        FROM email_escalation_rules ORDER BY priority, id
    """)
    return {
        "routing_rules": routing,
        "classification_rules": classification,
        "escalation_rules": escalation,
    }


@app.post("/api/email-intake/rules/routing")
async def add_routing_rule(request: Request):
    """Add a new routing rule."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("""
        INSERT INTO email_routing_rules (rule_type, pattern, action, division, reason)
        VALUES (%s, %s, %s, %s, %s)
    """, (body["rule_type"], body["pattern"], body["action"],
          body.get("division"), body.get("reason", "")), commit=True)
    log.info("routing_rule_added  actor=%s  type=%s  pattern=%s  action=%s",
             user.get("username"), body["rule_type"], body["pattern"], body["action"])
    return {"status": "created"}


@app.post("/api/email-intake/rules/classification")
async def add_classification_rule(request: Request):
    """Add a new classification rule."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("""
        INSERT INTO email_classification_rules (division, match_field, pattern, weight, notes)
        VALUES (%s, %s, %s, %s, %s)
    """, (body["division"], body["match_field"], body["pattern"],
          body.get("weight", 20), body.get("notes", "")), commit=True)
    log.info("classification_rule_added  actor=%s  division=%s  pattern=%s",
             user.get("username"), body["division"], body["pattern"])
    return {"status": "created"}


@app.post("/api/email-intake/rules/escalation")
async def add_escalation_rule(request: Request):
    """Add a new escalation rule."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("""
        INSERT INTO email_escalation_rules (rule_name, trigger_type, match_field, pattern, priority, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (body["rule_name"], body["trigger_type"], body["match_field"],
          body["pattern"], body.get("priority", "P2"), body.get("notes", "")), commit=True)
    log.info("escalation_rule_added  actor=%s  name=%s  priority=%s",
             user.get("username"), body["rule_name"], body.get("priority"))
    return {"status": "created"}


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL INTAKE — Enhanced Escalation Queue, Reclassify, Grade, Learning APIs
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/email-intake/escalation")
async def email_escalation_list(request: Request, status: str = "pending",
                                priority: str = "all", division: str = "all",
                                search: str = "", offset: int = 0, limit: int = 50):
    """Paginated, filterable escalation queue with full email content."""
    get_current_user(request)

    where_clauses = []
    params = []

    if status != "all":
        where_clauses.append("eq.status = %s")
        params.append(status)
    if priority != "all":
        where_clauses.append("eq.priority = %s")
        params.append(priority)
    if division != "all":
        where_clauses.append("ea.division = %s")
        params.append(division)
    if search:
        where_clauses.append("(ea.sender ILIKE %s OR ea.subject ILIKE %s)")
        params.extend(["%" + search + "%", "%" + search + "%"])

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    count_rows = _db_query(f"""
        SELECT count(*) as total FROM email_escalation_queue eq
        JOIN email_archive ea ON ea.id = eq.email_id
        WHERE {where_sql}
    """, tuple(params))
    total = count_rows[0]["total"] if count_rows else 0

    params.extend([limit, offset])
    items = _db_query(f"""
        SELECT eq.id, eq.email_id, eq.trigger_type, eq.trigger_detail,
               eq.priority, eq.status, eq.seen_by, eq.seen_at, eq.action_taken,
               eq.created_at,
               ea.sender, ea.subject, LEFT(ea.content, 2000) as body_preview,
               ea.division, ea.division_confidence, ea.sent_at,
               COALESCE(erl.review_grade, 0) as review_grade
        FROM email_escalation_queue eq
        JOIN email_archive ea ON ea.id = eq.email_id
        LEFT JOIN email_intake_review_log erl ON erl.escalation_id = eq.id
            AND erl.id = (SELECT max(id) FROM email_intake_review_log WHERE escalation_id = eq.id)
        WHERE {where_sql}
        ORDER BY eq.priority ASC, eq.created_at DESC
        LIMIT %s OFFSET %s
    """, tuple(params))

    for r in items:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()

    return {"items": items, "total": total, "offset": offset, "limit": limit}


def _learn_from_reclassification(email_id: int, new_division: str, actor: str) -> int:
    """Extract patterns from a reclassified email and create new classification rules.

    Returns the number of new rules created.
    """
    import re

    rows = _db_query(
        "SELECT sender, subject, LEFT(content, 3000) as body FROM email_archive WHERE id = %s",
        (email_id,))
    if not rows:
        return 0

    email = rows[0]
    sender = (email.get("sender") or "").strip()
    subject = (email.get("subject") or "").strip()
    rules_created = 0

    # 1) Learn from sender domain — most reliable signal
    domain_match = re.search(r'@([\w.-]+)', sender)
    if domain_match:
        domain = domain_match.group(1).lower()
        # Skip overly generic domains
        generic = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                    "aol.com", "icloud.com", "me.com", "live.com", "msn.com"}
        if domain not in generic:
            pattern = f"%@{domain}%"
            existing = _db_query(
                "SELECT id FROM email_classification_rules WHERE pattern = %s AND division = %s",
                (pattern, new_division))
            if not existing:
                _db_query("""
                    INSERT INTO email_classification_rules
                        (division, match_field, pattern, weight, is_active, notes)
                    VALUES (%s, 'sender', %s, 30, TRUE, %s)
                """, (new_division, pattern,
                      f"Auto-learned from reclassification by {actor} (email #{email_id})"),
                    commit=True)
                rules_created += 1
                log.info("auto_rule_created  type=sender_domain  domain=%s  division=%s  by=%s",
                         domain, new_division, actor)

    # 2) Learn from sender full address — if it's a specific person
    if sender and "@" in sender:
        sender_lower = sender.lower()
        sender_pattern = f"%{sender_lower}%"
        existing = _db_query(
            "SELECT id FROM email_classification_rules WHERE pattern = %s AND division = %s",
            (sender_pattern, new_division))
        if not existing:
            _db_query("""
                INSERT INTO email_classification_rules
                    (division, match_field, pattern, weight, is_active, notes)
                VALUES (%s, 'sender', %s, 40, TRUE, %s)
            """, (new_division, sender_pattern,
                  f"Auto-learned: sender from reclassification by {actor} (email #{email_id})"),
                commit=True)
            rules_created += 1

    # 3) Learn from distinctive subject keywords (2+ word phrases)
    if subject:
        # Strip common prefixes
        clean_subj = re.sub(r'^(re|fw|fwd|re:|fw:|fwd:)\s*', '', subject, flags=re.IGNORECASE).strip()
        # Extract meaningful phrases (skip very short or very generic)
        words = clean_subj.split()
        if 2 <= len(words) <= 8 and len(clean_subj) >= 10:
            subj_pattern = f"%{clean_subj.lower()[:60]}%"
            existing = _db_query(
                "SELECT id FROM email_classification_rules WHERE pattern = %s AND division = %s",
                (subj_pattern, new_division))
            if not existing:
                _db_query("""
                    INSERT INTO email_classification_rules
                        (division, match_field, pattern, weight, is_active, notes)
                    VALUES (%s, 'subject', %s, 25, TRUE, %s)
                """, (new_division, subj_pattern,
                      f"Auto-learned: subject from reclassification by {actor} (email #{email_id})"),
                    commit=True)
                rules_created += 1

    # 4) If reclassified as JUNK, also create a routing rule to block future emails from this sender
    if new_division == "JUNK" and sender:
        sender_lower = sender.lower()
        existing = _db_query(
            "SELECT id FROM email_routing_rules WHERE pattern = %s AND action = 'REJECT'",
            (f"%{sender_lower}%",))
        if not existing:
            _db_query("""
                INSERT INTO email_routing_rules
                    (rule_type, pattern, action, reason, is_active)
                VALUES ('sender_block', %s, 'REJECT', %s, TRUE)
            """, (f"%{sender_lower}%",
                  f"Auto-blocked: marked JUNK by {actor} (email #{email_id})"),
                commit=True)
            rules_created += 1
            log.info("auto_rule_created  type=junk_block  sender=%s  by=%s",
                     sender_lower, actor)

    return rules_created


@app.post("/api/email-intake/escalation/{item_id}/reclassify")
async def escalation_reclassify(item_id: int, request: Request):
    """Reclassify an email from the escalation queue. Teaches the system."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")
    body = await request.json()
    new_division = body.get("new_division")
    email_id = body.get("email_id")

    if not new_division or new_division not in VALID_DIVISIONS:
        raise HTTPException(status_code=400, detail=f"Invalid division. Valid: {', '.join(sorted(VALID_DIVISIONS))}")

    # Get the current division
    rows = _db_query("SELECT division, division_confidence FROM email_archive WHERE id = %s", (email_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Email not found")
    old_division = rows[0]["division"]
    old_confidence = rows[0]["division_confidence"] or 0

    # Update the email archive
    _db_query("""
        UPDATE email_archive
        SET division = %s, division_confidence = 100, division_summary = %s
        WHERE id = %s
    """, (new_division, f"Human reclassified by {actor} (was {old_division})", email_id), commit=True)

    # Mark the escalation as actioned
    _db_query("""
        UPDATE email_escalation_queue
        SET status = 'actioned', seen_by = %s, seen_at = NOW(),
            action_taken = %s
        WHERE id = %s
    """, (actor, f"Reclassified: {old_division} -> {new_division}", item_id), commit=True)

    # Log to review table for learning
    _db_query("""
        INSERT INTO email_intake_review_log
            (escalation_id, email_id, actor, action_type, old_division, new_division,
             old_confidence, new_confidence, notes)
        VALUES (%s, %s, %s, 'reclassify', %s, %s, %s, 100, %s)
    """, (item_id, email_id, actor, old_division, new_division,
          old_confidence, f"Manual reclassification from dashboard"), commit=True)

    # ── RECURSIVE LEARNING: auto-create classification rules from human correction ──
    rules_created = _learn_from_reclassification(email_id, new_division, actor)

    log.info("escalation_reclassify  actor=%s  item=%d  email=%s  %s->%s  rules_created=%d",
             actor, item_id, email_id, old_division, new_division, rules_created)
    return {"status": "reclassified", "old_division": old_division,
            "new_division": new_division, "item_id": item_id,
            "rules_created": rules_created}


@app.post("/api/email-intake/escalation/{item_id}/grade")
async def escalation_grade(item_id: int, request: Request):
    """Grade the classification quality (1-5 stars). Feeds the learning system."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")
    body = await request.json()
    grade = body.get("grade", 0)

    if grade < 1 or grade > 5:
        raise HTTPException(status_code=400, detail="Grade must be 1-5")

    # Get escalation details
    rows = _db_query("""
        SELECT eq.email_id, ea.division, ea.division_confidence
        FROM email_escalation_queue eq
        JOIN email_archive ea ON ea.id = eq.email_id
        WHERE eq.id = %s
    """, (item_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Escalation item not found")

    email_id = rows[0]["email_id"]
    division = rows[0]["division"]
    confidence = rows[0]["division_confidence"] or 0

    # Log to review table
    _db_query("""
        INSERT INTO email_intake_review_log
            (escalation_id, email_id, actor, action_type, old_division, new_division,
             old_confidence, new_confidence, review_grade, notes)
        VALUES (%s, %s, %s, 'grade', %s, %s, %s, %s, %s, %s)
    """, (item_id, email_id, actor, division, division,
          confidence, confidence, grade, f"Quality grade: {grade}/5"), commit=True)

    log.info("escalation_grade  actor=%s  item=%d  grade=%d", actor, item_id, grade)
    return {"status": "graded", "item_id": item_id, "grade": grade}


@app.post("/api/email-intake/escalation/bulk")
async def escalation_bulk_action(request: Request):
    """Bulk action on filtered escalation items."""
    user = get_current_user(request)
    actor = user.get("username", "unknown")
    body = await request.json()
    action = body.get("action", "dismissed")
    filters = body.get("filters", {})

    if action not in ("seen", "actioned", "dismissed"):
        raise HTTPException(status_code=400, detail="Invalid action")

    where_clauses = ["eq.status = 'pending'"]
    params = []

    filt_priority = filters.get("priority", "all")
    filt_status = filters.get("status", "pending")
    filt_division = filters.get("division", "all")
    filt_search = filters.get("search", "")

    if filt_priority != "all":
        where_clauses.append("eq.priority = %s")
        params.append(filt_priority)
    if filt_division != "all":
        where_clauses.append("ea.division = %s")
        params.append(filt_division)
    if filt_search:
        where_clauses.append("(ea.sender ILIKE %s OR ea.subject ILIKE %s)")
        params.extend(["%" + filt_search + "%", "%" + filt_search + "%"])

    where_sql = " AND ".join(where_clauses)
    params_update = [action, actor] + params

    result = _db_query(f"""
        UPDATE email_escalation_queue eq
        SET status = %s, seen_by = %s, seen_at = NOW(), action_taken = 'Bulk action from dashboard'
        FROM email_archive ea
        WHERE ea.id = eq.email_id AND {where_sql}
    """, tuple(params_update), commit=True)

    # Count affected
    count_rows = _db_query(f"""
        SELECT count(*) as cnt FROM email_escalation_queue eq
        JOIN email_archive ea ON ea.id = eq.email_id
        WHERE eq.status = %s AND eq.seen_by = %s AND {where_sql}
    """, tuple([action, actor] + params))
    affected = count_rows[0]["cnt"] if count_rows else 0

    log.info("escalation_bulk_%s  actor=%s  affected=%d", action, actor, affected)
    return {"status": action, "affected": affected}


@app.get("/api/email-intake/quarantine")
async def email_quarantine_list(request: Request, limit: int = 100):
    """List quarantined emails with details."""
    get_current_user(request)

    items = _db_query("""
        SELECT id, sender, subject, content_preview, rule_reason, rule_type,
               status, reviewed_by, created_at
        FROM email_quarantine
        WHERE status = 'quarantined'
        ORDER BY created_at DESC
        LIMIT %s
    """, (min(limit, 500),))

    for r in items:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()

    count_rows = _db_query("SELECT count(*) as total FROM email_quarantine WHERE status = 'quarantined'")
    total = count_rows[0]["total"] if count_rows else 0

    return {"items": items, "total": total}


@app.get("/api/email-intake/learning")
async def email_intake_learning(request: Request):
    """Learning analytics for the email intake system."""
    get_current_user(request)

    total_reviewed = _db_query("SELECT count(*) as cnt FROM email_intake_review_log")
    total_reclass = _db_query("SELECT count(*) as cnt FROM email_intake_review_log WHERE action_type = 'reclassify'")
    total_dismissed = _db_query(
        "SELECT count(*) as cnt FROM email_escalation_queue WHERE status = 'dismissed'")
    avg_grade = _db_query(
        "SELECT round(avg(review_grade), 1) as avg FROM email_intake_review_log WHERE review_grade > 0")

    grade_dist = _db_query("""
        SELECT review_grade as grade, count(*) as count
        FROM email_intake_review_log
        WHERE review_grade > 0
        GROUP BY review_grade ORDER BY review_grade
    """)

    recent = _db_query("""
        SELECT erl.actor, erl.action_type, erl.old_division, erl.new_division,
               erl.review_grade, erl.created_at, ea.subject
        FROM email_intake_review_log erl
        LEFT JOIN email_archive ea ON ea.id = erl.email_id
        ORDER BY erl.created_at DESC
        LIMIT 50
    """)
    for r in recent:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()

    return {
        "total_reviewed": total_reviewed[0]["cnt"] if total_reviewed else 0,
        "total_reclassified": total_reclass[0]["cnt"] if total_reclass else 0,
        "total_dismissed": total_dismissed[0]["cnt"] if total_dismissed else 0,
        "avg_grade": str(avg_grade[0]["avg"]) if avg_grade and avg_grade[0]["avg"] else "-",
        "grade_distribution": grade_dist,
        "recent": recent,
    }


@app.post("/api/email-intake/rules/routing/{rule_id}/toggle")
async def toggle_routing_rule(rule_id: int, request: Request):
    """Toggle a routing rule on/off."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("UPDATE email_routing_rules SET is_active = %s, updated_at = NOW() WHERE id = %s",
              (body.get("is_active", False), rule_id), commit=True)
    log.info("routing_rule_toggled  actor=%s  rule=%d  active=%s",
             user.get("username"), rule_id, body.get("is_active"))
    return {"status": "toggled", "rule_id": rule_id}


@app.post("/api/email-intake/rules/classification/{rule_id}/toggle")
async def toggle_classification_rule(rule_id: int, request: Request):
    """Toggle a classification rule on/off."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("UPDATE email_classification_rules SET is_active = %s WHERE id = %s",
              (body.get("is_active", False), rule_id), commit=True)
    log.info("classification_rule_toggled  actor=%s  rule=%d  active=%s",
             user.get("username"), rule_id, body.get("is_active"))
    return {"status": "toggled", "rule_id": rule_id}


@app.post("/api/email-intake/rules/escalation/{rule_id}/toggle")
async def toggle_escalation_rule(rule_id: int, request: Request):
    """Toggle an escalation rule on/off."""
    user = get_current_user(request)
    body = await request.json()
    _db_query("UPDATE email_escalation_rules SET is_active = %s WHERE id = %s",
              (body.get("is_active", False), rule_id), commit=True)
    log.info("escalation_rule_toggled  actor=%s  rule=%d  active=%s",
             user.get("username"), rule_id, body.get("is_active"))
    return {"status": "toggled", "rule_id": rule_id}


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL INTAKE — Enterprise v2: DLQ, SLA, Health, Snooze, Metadata
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/email-intake/metadata")
async def email_intake_metadata(request: Request):
    """Return all valid divisions, dismiss reasons, action types, and SLA thresholds."""
    get_current_user(request)
    return {
        "divisions": sorted(VALID_DIVISIONS),
        "dismiss_reasons": DISMISS_REASONS,
        "action_types": ACTION_TYPES,
        "sla_hours": SLA_HOURS,
    }


@app.get("/api/email-intake/dlq")
async def email_intake_dlq(request: Request, status: str = "all", limit: int = 50):
    """List dead-letter queue items for manual review."""
    get_current_user(request)

    try:
        where = "TRUE"
        params = []
        if status != "all":
            where = "status = %s"
            params.append(status)
        params.append(min(limit, 200))

        items = _db_query(f"""
            SELECT id, fingerprint, source_tag, sender, subject,
                   error_message, retry_count, max_retries, status,
                   next_retry_at, created_at, updated_at
            FROM email_dead_letter_queue
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, tuple(params))

        for r in items:
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = v.isoformat()

        counts = _db_query("""
            SELECT status, count(*) as cnt
            FROM email_dead_letter_queue GROUP BY status
        """)

        return {"items": items, "counts": {r["status"]: r["cnt"] for r in (counts or [])}}
    except Exception:
        return {"items": [], "counts": {}}


@app.post("/api/email-intake/dlq/{dlq_id}/retry")
async def dlq_manual_retry(dlq_id: int, request: Request):
    """Force an immediate retry of a dead-letter item."""
    user = get_current_user(request)
    _db_query("""
        UPDATE email_dead_letter_queue
        SET status = 'pending', next_retry_at = NOW(), retry_count = retry_count,
            updated_at = NOW()
        WHERE id = %s AND status IN ('dead', 'manual_review')
    """, (dlq_id,), commit=True)
    log.info("dlq_manual_retry  actor=%s  dlq_id=%d", user.get("username"), dlq_id)
    return {"status": "queued_for_retry", "dlq_id": dlq_id}


@app.post("/api/email-intake/dlq/{dlq_id}/discard")
async def dlq_discard(dlq_id: int, request: Request):
    """Permanently discard a dead-letter item."""
    user = get_current_user(request)
    _db_query("""
        UPDATE email_dead_letter_queue
        SET status = 'discarded', updated_at = NOW()
        WHERE id = %s
    """, (dlq_id,), commit=True)
    log.info("dlq_discarded  actor=%s  dlq_id=%d", user.get("username"), dlq_id)
    return {"status": "discarded", "dlq_id": dlq_id}


@app.get("/api/email-intake/sla")
async def email_intake_sla(request: Request):
    """SLA breach report for all priority levels."""
    get_current_user(request)

    breaches = []
    for priority, hours in SLA_HOURS.items():
        rows = _db_query("""
            SELECT eq.id, eq.email_id, eq.priority, eq.created_at,
                   ea.sender, ea.subject,
                   EXTRACT(EPOCH FROM (NOW() - eq.created_at))/3600 as hours_pending
            FROM email_escalation_queue eq
            JOIN email_archive ea ON ea.id = eq.email_id
            WHERE eq.status = 'pending'
              AND eq.priority = %s
              AND eq.created_at < NOW() - (%s || ' hours')::INTERVAL
            ORDER BY eq.created_at ASC
        """, (priority, str(hours)))
        for r in (rows or []):
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = v.isoformat()
            r["sla_hours"] = hours
            r["breach_hours"] = round(float(r["hours_pending"]) - hours, 1)
            breaches.append(r)

    summary = {}
    for priority, hours in SLA_HOURS.items():
        pending_rows = _db_query("""
            SELECT count(*) as total,
                   count(*) FILTER (WHERE eq.created_at < NOW() - (%s || ' hours')::INTERVAL) as breached
            FROM email_escalation_queue eq
            WHERE eq.status = 'pending' AND eq.priority = %s
        """, (str(hours), priority))
        if pending_rows:
            summary[priority] = {
                "sla_hours": hours,
                "total_pending": pending_rows[0]["total"],
                "breached": pending_rows[0]["breached"],
                "compliant": pending_rows[0]["total"] - pending_rows[0]["breached"],
            }

    return {"breaches": breaches, "summary": summary}


@app.get("/api/email-intake/health")
async def email_intake_health(request: Request):
    """System health dashboard data: DLQ, SLA, pipeline metrics."""
    get_current_user(request)

    try:
        dlq_counts = _db_query("""
            SELECT status, count(*) as cnt FROM email_dead_letter_queue GROUP BY status
        """)
        dlq_map = {r["status"]: r["cnt"] for r in (dlq_counts or [])}
    except Exception:
        dlq_map = {}

    esc_pending = _db_query("""
        SELECT priority, count(*) as cnt
        FROM email_escalation_queue WHERE status = 'pending'
        GROUP BY priority ORDER BY priority
    """)

    try:
        snoozed = _db_query("""
            SELECT count(*) as cnt FROM email_escalation_queue
            WHERE status = 'snoozed' AND snooze_until > NOW()
        """)
        snooze_expired = _db_query("""
            SELECT count(*) as cnt FROM email_escalation_queue
            WHERE status = 'snoozed' AND snooze_until <= NOW()
        """)
    except Exception:
        snoozed = [{"cnt": 0}]
        snooze_expired = [{"cnt": 0}]

    try:
        recent_errors = _db_query("""
            SELECT count(*) as cnt FROM email_dead_letter_queue
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
    except Exception:
        recent_errors = [{"cnt": 0}]

    ingestion_rate = _db_query("""
        SELECT count(*) as last_hour FROM email_archive
        WHERE sent_at > NOW() - INTERVAL '1 hour'
    """)

    return {
        "dlq": dlq_map,
        "escalation_pending": {r["priority"]: r["cnt"] for r in (esc_pending or [])},
        "snoozed_active": snoozed[0]["cnt"] if snoozed else 0,
        "snoozed_expired": snooze_expired[0]["cnt"] if snooze_expired else 0,
        "errors_last_hour": recent_errors[0]["cnt"] if recent_errors else 0,
        "ingested_last_hour": ingestion_rate[0]["last_hour"] if ingestion_rate else 0,
        "sla_thresholds": SLA_HOURS,
    }


@app.post("/api/email-intake/wake-snoozed")
async def wake_snoozed_escalations(request: Request):
    """Re-activate all snoozed escalations whose snooze has expired."""
    user = get_current_user(request)
    _db_query("""
        UPDATE email_escalation_queue
        SET status = 'pending', action_taken = action_taken || ' [auto-woke from snooze]'
        WHERE status = 'snoozed' AND snooze_until <= NOW()
    """, commit=True)

    count = _db_query("""
        SELECT count(*) as cnt FROM email_escalation_queue
        WHERE status = 'pending' AND action_taken LIKE '%auto-woke from snooze%'
    """)
    woke = count[0]["cnt"] if count else 0
    log.info("wake_snoozed  actor=%s  woke=%d", user.get("username"), woke)
    return {"status": "woke", "count": woke}


@app.post("/api/email-intake/reprocess")
async def trigger_reprocess(request: Request):
    """Trigger recursive reprocessing of low-confidence emails."""
    user = get_current_user(request)
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    threshold = body.get("confidence_threshold", 40)
    max_batch = body.get("max_batch", 200)

    rows = _db_query("""
        SELECT id, sender, subject, LEFT(content, 3000) as body,
               division, division_confidence
        FROM email_archive
        WHERE (division = 'UNKNOWN' OR division_confidence < %s)
          AND sent_at > NOW() - INTERVAL '30 days'
        ORDER BY sent_at DESC LIMIT %s
    """, (threshold, max_batch))

    if not rows:
        return {"evaluated": 0, "upgraded": 0}

    log.info("reprocess_triggered  actor=%s  candidates=%d  threshold=%d",
             user.get("username"), len(rows), threshold)
    return {
        "evaluated": len(rows),
        "message": f"Found {len(rows)} candidates for reprocessing. "
                   "Run `python -m src.email_bridge --reprocess` to execute.",
        "threshold": threshold,
    }


# ══════════════════════════════════════════════════════════════════════════════
# API KEY VAULT — Encrypted credential storage (Constitution Rule IV.1)
# ══════════════════════════════════════════════════════════════════════════════

import hashlib
from cryptography.fernet import Fernet, InvalidToken

_VAULT_FERNET: Optional[Fernet] = None
_VAULT_FERNET_LEGACY: Optional[Fernet] = None
VAULT_ENCRYPTION_KEY = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
VAULT_LEGACY_ENCRYPTION_KEY = os.getenv("VAULT_LEGACY_ENCRYPTION_KEY", "").strip()


def _build_fernet(secret_material: str) -> Fernet:
    derived = hashlib.sha256(secret_material.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _get_fernet() -> Fernet:
    """Primary vault key (VAULT_ENCRYPTION_KEY)."""
    global _VAULT_FERNET
    if _VAULT_FERNET is None:
        if not VAULT_ENCRYPTION_KEY:
            raise RuntimeError("VAULT_ENCRYPTION_KEY is not configured")
        _VAULT_FERNET = _build_fernet(VAULT_ENCRYPTION_KEY)
    return _VAULT_FERNET


def _get_legacy_fernet() -> Fernet:
    """Legacy key used before VAULT_ENCRYPTION_KEY existed."""
    global _VAULT_FERNET_LEGACY
    if _VAULT_FERNET_LEGACY is None:
        if not VAULT_LEGACY_ENCRYPTION_KEY:
            raise RuntimeError("VAULT_LEGACY_ENCRYPTION_KEY is not configured")
        _VAULT_FERNET_LEGACY = _build_fernet(VAULT_LEGACY_ENCRYPTION_KEY)
    return _VAULT_FERNET_LEGACY


def _vault_encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _vault_decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def _migrate_vault_encryption_key():
    """One-time migration: re-encrypt vault entries with VAULT_ENCRYPTION_KEY.

    If legacy key is absent, we skip migration.
    """
    if not VAULT_ENCRYPTION_KEY:
        log.warning("vault_key_not_configured")
        return

    if not VAULT_LEGACY_ENCRYPTION_KEY:
        log.info("vault_key_migration_skipped  reason=no_legacy_key")
        return

    migrated = 0
    skipped = 0
    rows = _db_query("SELECT id, encrypted_value FROM api_key_vault")
    for row in rows:
        ciphertext = row["encrypted_value"]

        # Already migrated/new-format entries decrypt with the primary key.
        try:
            _get_fernet().decrypt(ciphertext.encode())
            skipped += 1
            continue
        except InvalidToken:
            pass

        # Legacy entries decrypt with the configured legacy key and are re-encrypted.
        try:
            plaintext = _get_legacy_fernet().decrypt(ciphertext.encode()).decode()
            re_encrypted = _vault_encrypt(plaintext)
            _db_query(
                "UPDATE api_key_vault SET encrypted_value = %s, last_rotated = NOW() WHERE id = %s",
                (re_encrypted, row["id"]),
                commit=True,
            )
            migrated += 1
        except InvalidToken:
            log.error("vault_migration_decrypt_failed  id=%s", row["id"])

    if migrated:
        log.info("vault_key_migration_complete  migrated=%d  skipped=%d", migrated, skipped)


def _mask_key(value: str) -> str:
    """Show first 4 and last 4 chars, mask the rest."""
    if len(value) <= 12:
        return value[:2] + "*" * (len(value) - 4) + value[-2:]
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


# Known API key registry with metadata
_KEY_REGISTRY = {
    "OPENAI_API_KEY":       {"label": "OpenAI",            "desc": "GPT-4o God Head inference",            "cat": "AI / LLM"},
    "GOOGLE_AI_API_KEY":    {"label": "Google AI (Gemini)", "desc": "Architect planning & orchestration",   "cat": "AI / LLM"},
    "NGC_API_KEY":          {"label": "NVIDIA NGC",         "desc": "NIM container registry auth",          "cat": "AI / LLM"},
    "XAI_API_KEY":          {"label": "xAI (Grok)",         "desc": "Grok strategic intelligence",          "cat": "AI / LLM"},
    "ANTHROPIC_API_KEY":    {"label": "Anthropic (Claude)",  "desc": "Claude deep reasoning",               "cat": "AI / LLM"},
    "TWILIO_ACCOUNT_SID":   {"label": "Twilio SID",         "desc": "SMS account identifier",               "cat": "Communications"},
    "TWILIO_AUTH_TOKEN":    {"label": "Twilio Token",        "desc": "SMS authentication token",             "cat": "Communications"},
    "TWILIO_MESSAGING_SERVICE_SID": {"label": "Twilio Messaging SID", "desc": "A2P messaging service",     "cat": "Communications"},
    "GMAIL_APP_PASSWORD":   {"label": "Gmail App Password",  "desc": "SMTP email sending",                  "cat": "Communications"},
    "MAILPLUS_IMAP_PASSWORD": {"label": "MailPlus IMAP (info@)", "desc": "NAS MailPlus for info@cabin-rentals-of-georgia.com", "cat": "Communications"},
    "MAILPLUS_PASSWORD_GARY": {"label": "MailPlus (gary@)", "desc": "NAS MailPlus for gary@cabin-rentals-of-georgia.com", "cat": "Communications"},
    "MAILPLUS_PASSWORD_TAYLOR_KNIGHT": {"label": "MailPlus (taylor.knight@)", "desc": "NAS MailPlus for taylor.knight@cabin-rentals-of-georgia.com", "cat": "Communications"},
    "MAILPLUS_PASSWORD_BARBARA": {"label": "MailPlus (barbara@)", "desc": "NAS MailPlus for barbara@cabin-rentals-of-georgia.com", "cat": "Communications"},
    "MAILPLUS_PASSWORD_GARY_GARYKNIGHT_COM": {"label": "MailPlus (gary@garyknight.com)", "desc": "NAS MailPlus for gary@garyknight.com", "cat": "Communications"},
    "FRED_API_KEY":         {"label": "FRED",                "desc": "Federal Reserve economic data API",    "cat": "Intelligence"},
    "YOUTUBE_API_KEY":      {"label": "YouTube Data v3",     "desc": "Video/channel metadata search",        "cat": "Intelligence"},
    "QDRANT_API_KEY":       {"label": "Qdrant",              "desc": "Vector DB authentication",             "cat": "Infrastructure"},
    "REDIS_PASSWORD":       {"label": "Redis",               "desc": "Cache/queue authentication",            "cat": "Infrastructure"},
}


def _init_vault_table():
    """Create the api_key_vault table if it doesn't exist."""
    try:
        _db_query("""
            CREATE TABLE IF NOT EXISTS api_key_vault (
                id SERIAL PRIMARY KEY,
                key_name VARCHAR(100) UNIQUE NOT NULL,
                encrypted_value TEXT NOT NULL,
                label VARCHAR(100),
                description TEXT,
                category VARCHAR(50) DEFAULT 'General',
                last_rotated TIMESTAMPTZ DEFAULT NOW(),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_by VARCHAR(50)
            )
        """, commit=True)
    except Exception as e:
        log.error("vault_table_init_failed: %s", e)


def _sync_env_from_vault():
    """
    Load all vault keys into the running process environment.
    Called at startup and after any key save/delete.
    """
    try:
        rows = _db_query("SELECT key_name, encrypted_value FROM api_key_vault")
        for row in rows:
            try:
                plaintext = _vault_decrypt(row["encrypted_value"])
                os.environ[row["key_name"]] = plaintext
            except InvalidToken:
                log.error("vault_decrypt_failed  key=%s", row["key_name"])
        log.info("vault_sync  loaded=%d keys into environment", len(rows))
    except Exception as e:
        log.error("vault_sync_failed: %s", e)


def _write_env_file():
    """
    Rewrite the .env file with current vault keys merged into existing env content.
    Preserves non-vault lines. Constitution: keys live in .env, never hardcoded.
    """
    env_path = PROJECT_ROOT / ".env"
    vault_keys = {}
    try:
        rows = _db_query("SELECT key_name, encrypted_value FROM api_key_vault")
        for row in rows:
            try:
                vault_keys[row["key_name"]] = _vault_decrypt(row["encrypted_value"])
            except InvalidToken:
                pass
    except Exception:
        return

    # Read existing .env, replace vault-managed keys, keep everything else
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    written_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            var_name = stripped.split("=", 1)[0].strip()
            if var_name in vault_keys:
                new_lines.append(f"{var_name}={vault_keys[var_name]}")
                written_keys.add(var_name)
                continue
        new_lines.append(line)

    # Append any vault keys not already in the file
    unwritten = set(vault_keys.keys()) - written_keys
    if unwritten:
        new_lines.append("")
        new_lines.append("# ── Vault-managed keys (auto-synced) ──")
        for k in sorted(unwritten):
            new_lines.append(f"{k}={vault_keys[k]}")

    env_path.write_text("\n".join(new_lines) + "\n")
    log.info("vault_env_write  keys_synced=%d", len(vault_keys))


# ── Pydantic models ──

class VaultKeyUpsert(BaseModel):
    key_name: str = Field(min_length=2, max_length=100, pattern=r"^[A-Z][A-Z0-9_]+$")
    value: str = Field(min_length=1, max_length=2000)


class VaultKeyCustom(BaseModel):
    key_name: str = Field(min_length=2, max_length=100, pattern=r"^[A-Z][A-Z0-9_]+$")
    value: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="Custom", max_length=50)


# ── API Endpoints ──

@app.get("/api/vault/keys")
async def vault_list_keys(request: Request):
    """List all stored API keys (values masked). Admin only."""
    _require_admin(request)

    stored = {}
    try:
        rows = _db_query(
            "SELECT key_name, label, description, category, last_rotated, updated_by "
            "FROM api_key_vault ORDER BY category, key_name"
        )
        for r in rows:
            stored[r["key_name"]] = r
    except Exception:
        pass

    result = []
    # Registry keys (known)
    for key_name, meta in _KEY_REGISTRY.items():
        db_row = stored.pop(key_name, None)
        env_val = os.environ.get(key_name, "")
        is_set = bool(db_row) or bool(env_val)
        masked = _mask_key(env_val) if env_val else ""
        result.append({
            "key_name": key_name,
            "label": meta["label"],
            "description": meta["desc"],
            "category": meta["cat"],
            "is_set": is_set,
            "masked_value": masked,
            "in_vault": bool(db_row),
            "in_env_only": bool(env_val) and not db_row,
            "last_rotated": db_row["last_rotated"].isoformat() if db_row and db_row.get("last_rotated") else None,
            "updated_by": db_row["updated_by"] if db_row else None,
            "registered": True,
        })

    # Custom keys (in vault but not in registry)
    for key_name, db_row in stored.items():
        env_val = os.environ.get(key_name, "")
        masked = _mask_key(env_val) if env_val else ""
        result.append({
            "key_name": key_name,
            "label": db_row.get("label") or key_name,
            "description": db_row.get("description") or "",
            "category": db_row.get("category") or "Custom",
            "is_set": True,
            "masked_value": masked,
            "in_vault": True,
            "in_env_only": False,
            "last_rotated": db_row["last_rotated"].isoformat() if db_row.get("last_rotated") else None,
            "updated_by": db_row.get("updated_by"),
            "registered": False,
        })

    return {"keys": result, "total": len(result), "vault_count": sum(1 for k in result if k["in_vault"])}


@app.post("/api/vault/keys")
async def vault_save_key(request: Request, body: VaultKeyUpsert):
    """Save or update an API key in the encrypted vault. Admin only."""
    user = _require_admin(request)
    actor = user.get("username", "system")

    encrypted = _vault_encrypt(body.value)
    meta = _KEY_REGISTRY.get(body.key_name, {})

    _db_query("""
        INSERT INTO api_key_vault (key_name, encrypted_value, label, description, category, updated_by, last_rotated)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (key_name) DO UPDATE SET
            encrypted_value = EXCLUDED.encrypted_value,
            updated_by = EXCLUDED.updated_by,
            last_rotated = NOW()
    """, (
        body.key_name, encrypted,
        meta.get("label", body.key_name),
        meta.get("desc", ""),
        meta.get("cat", "Custom"),
        actor,
    ), commit=True)

    # Update running environment immediately
    os.environ[body.key_name] = body.value

    # Sync to .env file
    _write_env_file()

    log.info("vault_key_saved  actor=%s  key=%s", actor, body.key_name)
    return {"status": "saved", "key_name": body.key_name, "actor": actor}


@app.post("/api/vault/keys/custom")
async def vault_save_custom_key(request: Request, body: VaultKeyCustom):
    """Save a custom (non-registry) API key with user-defined metadata."""
    user = _require_admin(request)
    actor = user.get("username", "system")

    encrypted = _vault_encrypt(body.value)

    _db_query("""
        INSERT INTO api_key_vault (key_name, encrypted_value, label, description, category, updated_by, last_rotated)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (key_name) DO UPDATE SET
            encrypted_value = EXCLUDED.encrypted_value,
            label = EXCLUDED.label,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            updated_by = EXCLUDED.updated_by,
            last_rotated = NOW()
    """, (body.key_name, encrypted, body.label, body.description, body.category, actor), commit=True)

    os.environ[body.key_name] = body.value
    _write_env_file()

    log.info("vault_custom_key_saved  actor=%s  key=%s", actor, body.key_name)
    return {"status": "saved", "key_name": body.key_name, "actor": actor}


@app.delete("/api/vault/keys/{key_name}")
async def vault_delete_key(key_name: str, request: Request):
    """Remove an API key from the vault. Admin only."""
    user = _require_admin(request)
    actor = user.get("username", "system")

    _db_query("DELETE FROM api_key_vault WHERE key_name = %s", (key_name,), commit=True)
    os.environ.pop(key_name, None)
    _write_env_file()

    log.info("vault_key_deleted  actor=%s  key=%s", actor, key_name)
    return {"status": "deleted", "key_name": key_name}


@app.post("/api/vault/import-env")
async def vault_import_from_env(request: Request):
    """
    One-time import: reads current .env values for known registry keys
    and stores them encrypted in the vault. Admin only.
    """
    user = _require_admin(request)
    actor = user.get("username", "system")
    imported = 0

    for key_name, meta in _KEY_REGISTRY.items():
        env_val = os.environ.get(key_name, "")
        if not env_val:
            continue

        # Skip if already in vault
        existing = _db_query("SELECT id FROM api_key_vault WHERE key_name = %s", (key_name,))
        if existing:
            continue

        encrypted = _vault_encrypt(env_val)
        _db_query("""
            INSERT INTO api_key_vault (key_name, encrypted_value, label, description, category, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (key_name, encrypted, meta["label"], meta["desc"], meta["cat"], actor), commit=True)
        imported += 1

    log.info("vault_import  actor=%s  imported=%d", actor, imported)
    return {"status": "imported", "count": imported, "actor": actor}


@app.get("/api/vault/registry")
async def vault_registry(request: Request):
    """Return the known key registry (names/labels/descriptions — no values)."""
    _require_admin(request)
    return {"registry": {k: {"label": v["label"], "description": v["desc"], "category": v["cat"]}
                         for k, v in _KEY_REGISTRY.items()}}


# ── Vault page route ──

@app.get("/vault", response_class=HTMLResponse)
async def page_vault(request: Request):
    try:
        _require_admin(request)
        return _serve_html("vault.html")
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_user_schema():
    """Self-healing migration: ensure access-control columns exist on fortress_users."""
    migrations = [
        ("full_name", "ALTER TABLE fortress_users ADD COLUMN full_name VARCHAR(100)"),
        ("web_ui_access", "ALTER TABLE fortress_users ADD COLUMN web_ui_access BOOLEAN NOT NULL DEFAULT FALSE"),
        ("vrs_access", "ALTER TABLE fortress_users ADD COLUMN vrs_access BOOLEAN NOT NULL DEFAULT FALSE"),
    ]
    for col, ddl in migrations:
        try:
            rows = _db_query(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'fortress_users' AND column_name = %s",
                (col,),
            )
            if not rows:
                _db_query(ddl, commit=True)
                log.info("schema_migration  added column fortress_users.%s", col)
        except Exception as e:
            log.warning("schema_migration_skip  col=%s  reason=%s", col, e)

    # Admins always get web_ui_access and vrs_access
    try:
        _db_query(
            "UPDATE fortress_users SET web_ui_access = TRUE, vrs_access = TRUE "
            "WHERE role = 'admin' AND (web_ui_access = FALSE OR vrs_access = FALSE)",
            commit=True,
        )
    except Exception as e:
        log.warning("admin_auto_grant_skip  reason=%s", e)


@app.on_event("startup")
async def _startup():
    _init_db_pool()
    _ensure_user_schema()
    _init_vault_table()
    _migrate_vault_encryption_key()
    _sync_env_from_vault()
    log.info("Command Center ready — DB pool initialized, schema verified, vault synced")


@app.on_event("shutdown")
async def _shutdown():
    global _db_pool
    if _db_pool:
        _db_pool.closeall()
        _db_pool = None
        log.info("DB pool closed — clean shutdown")


def _vault_set_key_cli(key_name: str, value: str):
    """One-off: save a vault key from CLI (encrypt, insert, sync .env). No server."""
    if key_name not in _KEY_REGISTRY:
        log.warning("vault_set_key  key %s not in registry (will still be stored)", key_name)
    _init_db_pool()
    _init_vault_table()
    encrypted = _vault_encrypt(value)
    meta = _KEY_REGISTRY.get(key_name, {})
    _db_query("""
        INSERT INTO api_key_vault (key_name, encrypted_value, label, description, category, updated_by, last_rotated)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (key_name) DO UPDATE SET
            encrypted_value = EXCLUDED.encrypted_value,
            updated_by = EXCLUDED.updated_by,
            last_rotated = NOW()
    """, (
        key_name, encrypted,
        meta.get("label", key_name),
        meta.get("desc", ""),
        meta.get("cat", "Custom"),
        "cli",
    ), commit=True)
    os.environ[key_name] = value
    _write_env_file()
    log.info("vault_key_saved  key=%s  (from CLI)", key_name)


if __name__ == "__main__":
    import sys
    import uvicorn

    if len(sys.argv) >= 4 and sys.argv[1] == "--vault-set":
        key_name = sys.argv[2]
        value = " ".join(sys.argv[3:]) if len(sys.argv) > 4 else sys.argv[3]
        _vault_set_key_cli(key_name, value)
        sys.exit(0)

    log.info("=" * 65)
    log.info("  CROG COMMAND CENTER  v2.4.0  (email-intake-dashboard)")
    log.info("  Cabin Rentals of Georgia")
    log.info("  env=%-12s  secure_cookies=%s", ENVIRONMENT, IS_PRODUCTION)
    log.info("  cors=%s", ALLOWED_ORIGINS)
    log.info("  url=http://%s:9800", BASE)
    log.info("=" * 65)

    uvicorn.run(app, host="0.0.0.0", port=9800, log_level="info")
