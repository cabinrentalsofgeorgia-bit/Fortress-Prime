"""
Authentication & Authorization core
- bcrypt password hashing
- JWT token creation and verification
- FastAPI dependency for protected routes
"""
from datetime import datetime, timedelta, timezone
import os
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
    if not RSA_PRIVATE_KEY:
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
    return jwt.encode(payload, RSA_PRIVATE_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    if not RSA_PUBLIC_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT RSA public key is not configured",
        )
    try:
        return jwt.decode(token, RSA_PUBLIC_KEY, algorithms=[ALGORITHM])
    except JWTError:
        legacy_secret = (os.getenv("JWT_SECRET_KEY") or settings.jwt_secret_key or "").strip()
        if not legacy_secret:
            raise
        # Backward-compatible fallback for legacy HS256 tokens.
        return jwt.decode(token, legacy_secret, algorithms=["HS256"])


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
