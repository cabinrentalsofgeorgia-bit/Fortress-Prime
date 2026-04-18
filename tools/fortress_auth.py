#!/usr/bin/env python3
"""
FORTRESS PRIME — Shared Authentication & Security Middleware
=============================================================
Enterprise-grade auth module shared by all Fortress dashboards.
Reuses the JWT tokens issued by master_console.py (Command Center).

Usage in any FastAPI app:
    from fortress_auth import apply_fortress_security, require_auth

    app = FastAPI()
    apply_fortress_security(app)  # adds CORS, rate limiting, security headers

    @app.get("/api/protected")
    async def protected(user: dict = Depends(require_auth)):
        return {"msg": f"Hello {user['username']}"}

Auth Flow:
    1. User logs into Command Center (port 9800) → gets JWT cookie
    2. Other dashboards read the same cookie → verify with shared JWT_SECRET
    3. No login page needed on sub-dashboards; redirect to Command Center if not authed
"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    from dotenv import load_dotenv
    _project_root = Path(__file__).resolve().parent.parent
    load_dotenv(_project_root / ".env")
except ImportError:
    pass

log = logging.getLogger("fortress.auth")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG (from environment — never hardcoded)
# ══════════════════════════════════════════════════════════════════════════════

BASE_IP = os.getenv("BASE_IP", "192.168.0.100")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
COOKIE_NAME = "fortress_session"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"
COMMAND_CENTER_URL = f"http://{BASE_IP}:9800"

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        f"http://{BASE_IP}:9800,http://{BASE_IP}:9876,http://{BASE_IP}:9877,"
        f"http://{BASE_IP}:9878,http://localhost:9800,http://localhost:9876,"
        f"http://localhost:9877,http://localhost:9878",
    ).split(",")
    if o.strip()
]

# Health endpoints that should never require auth
PUBLIC_PATHS = {"/api/health", "/health", "/healthz", "/api/bridge/status"}


# ══════════════════════════════════════════════════════════════════════════════
# JWT VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def _verify_jwt(token: str) -> dict:
    """Decode and verify a JWT token. Returns payload dict or raises."""
    try:
        from jose import jwt as jose_jwt, JWTError
    except ImportError:
        log.warning("python-jose not installed — auth disabled")
        return {"username": "anonymous", "role": "admin"}

    if not JWT_SECRET:
        log.warning("JWT_SECRET not set — auth disabled")
        return {"username": "anonymous", "role": "admin"}

    try:
        return jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_auth(request: Request) -> dict:
    """FastAPI dependency: extract & verify JWT from cookie or Authorization header."""
    # Check cookie first (browser sessions)
    token = request.cookies.get(COOKIE_NAME)

    # Fallback to Authorization header (API clients)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        # For browser requests, redirect to login
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            raise HTTPException(
                status_code=307,
                headers={"Location": f"{COMMAND_CENTER_URL}/login?next={request.url}"},
            )
        raise HTTPException(status_code=401, detail="Authentication required")

    return _verify_jwt(token)


def require_admin(request: Request) -> dict:
    """FastAPI dependency: require admin role."""
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ══════════════════════════════════════════════════════════════════════════════

def _setup_rate_limiter(app: FastAPI):
    """Add slowapi rate limiter to FastAPI app."""
    try:
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded

        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter

        @app.exception_handler(RateLimitExceeded)
        async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
            log.warning("rate_limit  ip=%s  path=%s", get_remote_address(request), request.url.path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Try again in 60 seconds."},
                headers={"Retry-After": "60"},
            )

        return limiter
    except ImportError:
        log.warning("slowapi not installed — rate limiting disabled")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECURITY MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════

def apply_fortress_security(
    app: FastAPI,
    *,
    require_login: bool = True,
    custom_origins: list = None,
):
    """
    Apply full Fortress security stack to any FastAPI app:
      - CORS with explicit origin whitelist
      - Security response headers
      - Authentication middleware (redirect to Command Center if not logged in)
      - Rate limiting

    Args:
        app: FastAPI application instance
        require_login: If True, all non-public paths require JWT auth
        custom_origins: Override default CORS origins
    """
    origins = custom_origins or ALLOWED_ORIGINS

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
        max_age=3600,
    )

    # Rate limiter
    limiter = _setup_rate_limiter(app)

    @app.middleware("http")
    async def fortress_security_middleware(request: Request, call_next):
        path = request.url.path

        # Always allow health checks
        if path in PUBLIC_PATHS:
            response = await call_next(request)
            _add_security_headers(response)
            return response

        # Auth check for protected paths
        if require_login:
            token = request.cookies.get(COOKIE_NAME)
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

            if not token:
                accept = request.headers.get("accept", "")
                if "text/html" in accept:
                    return RedirectResponse(
                        url=f"{COMMAND_CENTER_URL}/login?next={request.url}",
                        status_code=307,
                    )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )

            try:
                user = _verify_jwt(token)
                request.state.user = user
            except HTTPException:
                accept = request.headers.get("accept", "")
                if "text/html" in accept:
                    return RedirectResponse(
                        url=f"{COMMAND_CENTER_URL}/login",
                        status_code=307,
                    )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired session"},
                )

        response = await call_next(request)
        _add_security_headers(response)
        return response

    return limiter


def _add_security_headers(response):
    """Add enterprise security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPER (environment-driven, no hardcoded creds)
# ══════════════════════════════════════════════════════════════════════════════

def get_db_config() -> dict:
    """Return DB connection params from environment — never hardcoded."""
    config = {
        "dbname": os.getenv("DB_NAME", "fortress_db"),
        "user": os.getenv("LEGAL_DB_USER", os.getenv("DB_USER", "admin")),
    }
    host = os.getenv("LEGAL_DB_HOST", os.getenv("DB_HOST", ""))
    if host:
        config["host"] = host
        config["port"] = int(os.getenv("DB_PORT", "5432"))
    pw = os.getenv("LEGAL_DB_PASS", os.getenv("DB_PASSWORD", ""))
    if pw:
        config["password"] = pw
    return config


def get_psql_env() -> str:
    """Return a safe PGPASSWORD prefix for shell commands, from env only."""
    pw = os.getenv("LEGAL_DB_PASS", os.getenv("DB_PASSWORD", ""))
    user = os.getenv("LEGAL_DB_USER", os.getenv("DB_USER", "admin"))
    db = os.getenv("DB_NAME", "fortress_db")
    if pw:
        return f'PGPASSWORD="{pw}" psql -h 127.0.0.1 -U {user} -d {db}'
    return f"psql -U {user} -d {db}"
