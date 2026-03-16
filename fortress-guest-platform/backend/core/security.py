"""
Authentication & Authorization core
- bcrypt password hashing
- JWT token creation and verification
- FastAPI dependency for protected routes
"""
from datetime import datetime, timedelta, timezone
import os
import base64
from typing import Optional
from uuid import UUID

import bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.staff import StaffUser

logger = structlog.get_logger()

bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = settings.jwt_algorithm
RSA_PRIVATE_KEY = settings.jwt_rsa_private_key
RSA_PUBLIC_KEY = settings.jwt_rsa_public_key


def _decode_if_base64_pem(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    if value.startswith("-----BEGIN"):
        return value
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return value


def _decode_rs256(token: str) -> dict:
    public_key = _decode_if_base64_pem(RSA_PUBLIC_KEY)
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT RSA public key is not configured",
        )
    return jwt.decode(token, public_key, algorithms=["RS256"])


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(
    user_id: str,
    role: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    private_key = _decode_if_base64_pem(RSA_PRIVATE_KEY)
    if not private_key:
        raise RuntimeError("JWT RSA private key is not configured")

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.jwt_expiration_hours)
    )
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    headers = {"kid": settings.jwt_key_id}
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


def decode_token(token: str) -> dict:
    """RS256 only — HS256 is permanently rejected."""
    try:
        header = jwt.get_unverified_header(token) or {}
        algorithm = (header.get("alg") or "").upper()
        key_id = (header.get("kid") or "").strip()
    except Exception as exc:
        logger.warning("jwt_header_invalid", error=str(exc))
        raise JWTError("Malformed JWT header") from exc

    if algorithm != "RS256" and algorithm:
        raise JWTError(f"Unsupported JWT algorithm: {algorithm}")

    payload = _decode_rs256(token)

    configured_kid = (settings.jwt_key_id or "").strip()
    if key_id and configured_kid and key_id != configured_kid:
        logger.warning("jwt_kid_mismatch", token_kid=key_id, expected_kid=configured_kid)
        raise JWTError("Token key id mismatch")

    return payload


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> StaffUser:
    """FastAPI dependency — extracts and validates JWT, returns the StaffUser."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise JWTError("Missing sub claim")
    except JWTError as e:
        logger.warning("jwt_invalid", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(StaffUser).where(StaffUser.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return user


async def require_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    """Dependency that requires the user to have the 'admin' role."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_manager_or_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    if user.role not in ("admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or admin access required",
        )
    return user


async def require_operator_manager_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    if user.role not in ("admin", "manager", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator, manager, or admin access required",
        )
    return user


# ---------------------------------------------------------------------------
# Owner-Scoped Fiduciary Middleware (Magic Link JWT)
# ---------------------------------------------------------------------------
from fastapi import Request as _Request


async def get_current_owner(
    request: _Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Extracts owner JWT from HttpOnly cookie (primary) or Bearer header (fallback).

    Returns a dict with sl_owner_id, email, properties, and unit_ids
    so downstream route handlers can filter queries to owned properties only.
    """
    token: Optional[str] = request.cookies.get("fgp_owner_token")
    if not token and creds is not None:
        token = creds.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
        sl_owner_id: str = payload.get("sub")
        role: str = payload.get("role")
        email: str = payload.get("email")

        if sl_owner_id is None or role != "owner":
            raise JWTError("Missing sub or invalid role")
    except JWTError as e:
        logger.warning("owner_jwt_invalid", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate owner credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from sqlalchemy import text
    result = await db.execute(
        text("SELECT unit_id, property_name FROM owner_property_map WHERE sl_owner_id = :oid"),
        {"oid": sl_owner_id},
    )
    properties = [{"unit_id": row.unit_id, "name": row.property_name} for row in result.fetchall()]

    if not properties:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active properties assigned to this owner",
        )

    return {
        "sl_owner_id": sl_owner_id,
        "email": email,
        "properties": properties,
        "unit_ids": [p["unit_id"] for p in properties],
    }
