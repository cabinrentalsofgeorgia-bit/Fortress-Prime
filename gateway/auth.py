"""
Gateway Authentication — JWT + API Keys
==========================================
Provides FastAPI dependencies for route protection.

Auth methods:
    1. Bearer <jwt>         — For human users (dashboard, mobile)
    2. ApiKey frt_<hex>     — For cron jobs and service-to-service

Roles:
    admin       Full access to all endpoints
    operator    Read/write ops + legal
    viewer      Read-only access to all endpoints

Usage in routes:
    from gateway.auth import require_auth, require_role

    @router.get("/secret", dependencies=[Depends(require_role("admin"))])
    def secret_endpoint(): ...

    @router.get("/data")
    def data_endpoint(user=Depends(require_auth)): ...
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import bcrypt as _bcrypt


# ---------------------------------------------------------------------------
# Bcrypt helpers (replaces passlib which is broken on Python 3.12 + bcrypt 5.x)
# ---------------------------------------------------------------------------

class _BcryptCompat:
    """Drop-in replacement for passlib.hash.bcrypt with the raw bcrypt library."""

    @staticmethod
    def hash(secret: str) -> str:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        return _bcrypt.hashpw(secret, _bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def verify(secret: str, hashed: str) -> bool:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if isinstance(hashed, str):
            hashed = hashed.encode("utf-8")
        try:
            return _bcrypt.checkpw(secret, hashed)
        except (ValueError, TypeError):
            return False

bcrypt = _BcryptCompat()

logger = logging.getLogger("gateway.auth")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Routes that bypass authentication entirely
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/v1/auth/login",
    "/v1/webhook/plaid",
}

# Prefix patterns that are public
PUBLIC_PREFIXES = (
    "/static/",
    "/ui/",
)

# ---------------------------------------------------------------------------
# Security scheme
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: int,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET not configured in environment")

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=JWT_EXPIRE_HOURS)
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# API key verification
# ---------------------------------------------------------------------------

def _verify_api_key(raw_key: str) -> dict:
    """
    Look up an API key in the database.
    Returns a user-like dict with scopes.
    """
    from gateway.db import get_cursor

    with get_cursor() as cur:
        # Find all active keys that match the prefix (fast filter)
        prefix = raw_key[:12]
        cur.execute(
            """SELECT k.id, k.key_hash, k.name, k.scopes, k.owner_id,
                      u.username, u.role
               FROM fortress_api_keys k
               LEFT JOIN fortress_users u ON u.id = k.owner_id
               WHERE k.key_prefix = %s AND k.is_active = TRUE""",
            (prefix,),
        )
        rows = cur.fetchall()

    # Verify the full hash (bcrypt is slow by design — only runs on prefix match)
    for row in rows:
        if bcrypt.verify(raw_key, row["key_hash"]):
            # Update last_used timestamp (fire and forget)
            try:
                from gateway.db import get_cursor as _gc
                with _gc(commit=True) as c:
                    c.execute(
                        "UPDATE fortress_api_keys SET last_used = NOW() WHERE id = %s",
                        (row["id"],),
                    )
            except Exception:
                pass

            return {
                "sub": str(row["owner_id"] or 0),
                "username": row["name"],
                "role": row["role"] or "service",
                "scopes": row["scopes"] or [],
                "auth_method": "api_key",
            }

    raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Core dependency: get current user
# ---------------------------------------------------------------------------

def _is_public(path: str) -> bool:
    """Check if a path bypasses authentication."""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency: extracts and validates credentials.

    Supports:
        Authorization: Bearer <jwt>
        Authorization: ApiKey frt_<hex>

    Returns a dict with: sub, username, role, (scopes for API keys)
    """
    path = request.url.path

    # Public endpoints skip auth
    if _is_public(path):
        return {"sub": "0", "username": "anonymous", "role": "public"}

    # Try Authorization header
    auth_header = request.headers.get("Authorization", "")

    # API key auth
    if auth_header.startswith("ApiKey "):
        raw_key = auth_header[7:].strip()
        return _verify_api_key(raw_key)

    # Bearer JWT auth
    if credentials and credentials.credentials:
        payload = decode_token(credentials.credentials)
        payload["auth_method"] = "jwt"
        return payload

    # No valid credentials
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide: Bearer <jwt> or ApiKey <key>",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Role-based access
# ---------------------------------------------------------------------------

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1, "public": 0, "service": 2}


def require_role(minimum_role: str):
    """
    FastAPI dependency factory: require a minimum role level.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
    """
    min_level = ROLE_HIERARCHY.get(minimum_role, 0)

    async def _check(user: dict = Depends(require_auth)):
        user_level = ROLE_HIERARCHY.get(user.get("role", ""), 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role '{minimum_role}' or higher",
            )
        return user

    return _check


def require_scope(scope: str):
    """
    FastAPI dependency factory: require a specific scope (for API keys).

    Usage:
        @router.post("/task", dependencies=[Depends(require_scope("ops:write"))])
    """
    async def _check(user: dict = Depends(require_auth)):
        # JWT users with admin/operator role bypass scope checks
        if user.get("auth_method") == "jwt":
            return user
        # API keys must have the specific scope
        user_scopes = user.get("scopes", [])
        if scope not in user_scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scope: {scope}",
            )
        return user

    return _check
