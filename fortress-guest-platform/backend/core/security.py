"""
Authentication & Authorization core
- bcrypt password hashing
- JWT token creation and verification
- FastAPI dependency for protected routes
"""
import base64
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
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
from backend.models.staff import STAFF_ROLE_VALUES, StaffRole, StaffUser

logger = structlog.get_logger()

bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = settings.jwt_algorithm
RSA_PRIVATE_KEY = settings.jwt_rsa_private_key
RSA_PUBLIC_KEY = settings.jwt_rsa_public_key

LEGACY_STAFF_ROLE_MAP: dict[str, "StaffRole"] = {
    "admin": StaffRole.SUPER_ADMIN,
    "superadmin": StaffRole.SUPER_ADMIN,
    "operator": StaffRole.MANAGER,
    "manager": StaffRole.MANAGER,
    "staff": StaffRole.REVIEWER,
    "reviewer": StaffRole.REVIEWER,
    "viewer": StaffRole.REVIEWER,
}


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
    if not hashed.startswith("$2"):
        logger.warning("password_hash_scheme_unsupported", prefix=hashed[:8])
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError as exc:
        logger.warning("bcrypt_verify_failed", error=str(exc))
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


def _coerce_staff_role(raw_role: StaffRole | str | None) -> StaffRole:
    if isinstance(raw_role, StaffRole):
        return raw_role
    normalized_role = (raw_role or "").strip().lower()
    legacy_role = LEGACY_STAFF_ROLE_MAP.get(normalized_role)
    if legacy_role is not None:
        return legacy_role
    try:
        return StaffRole(normalized_role)
    except ValueError as exc:
        logger.warning("staff_role_invalid", role=normalized_role, allowed_roles=STAFF_ROLE_VALUES)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User role is invalid. Contact a super admin.",
        ) from exc


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
    user.role = _coerce_staff_role(user.role)
    return user


STAFF_SYSTEM_HEALTH_WS_ROLES: frozenset[StaffRole] = frozenset(
    {StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER}
)


async def load_staff_user_from_token_string(db: AsyncSession, token: str) -> StaffUser | None:
    """Resolve a staff user from a raw JWT access token string (WebSocket query param, etc.)."""
    raw = (token or "").strip()
    if not raw:
        return None
    try:
        payload = decode_token(raw)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            return None
    except JWTError as exc:
        logger.warning("ws_token_invalid", error=str(exc))
        return None

    try:
        uid = UUID(user_id)
    except ValueError:
        return None

    result = await db.execute(select(StaffUser).where(StaffUser.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    try:
        user.role = _coerce_staff_role(user.role)
    except HTTPException:
        return None
    return user


def staff_allowed_for_system_health_stream(user: StaffUser) -> bool:
    """Same role gate as REST GET /api/system/health/ (PULSE_ACCESS)."""
    try:
        role = _coerce_staff_role(user.role)
    except HTTPException:
        return False
    return role in STAFF_SYSTEM_HEALTH_WS_ROLES


class RoleChecker:
    """Reusable dependency for hierarchical staff role enforcement."""

    def __init__(self, allowed_roles: Iterable[StaffRole | str]) -> None:
        normalized_roles: list[StaffRole] = []
        for raw_role in allowed_roles:
            normalized_roles.append(_coerce_staff_role(raw_role))
        if not normalized_roles:
            raise ValueError("RoleChecker requires at least one allowed role")
        self.allowed_roles = tuple(normalized_roles)

    async def __call__(
        self,
        user: StaffUser = Depends(get_current_user),
    ) -> StaffUser:
        user_role = _coerce_staff_role(user.role)
        if user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden. Required role: "
                    + ", ".join(role.value for role in self.allowed_roles)
                ),
            )
        user.role = user_role
        return user


async def require_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    """Backward-compatible alias for super-admin-only routes."""
    return await RoleChecker([StaffRole.SUPER_ADMIN])(user)


async def require_manager_or_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    """Backward-compatible alias for manager or super-admin routes."""
    return await RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])(user)


async def require_operator_manager_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    """Legacy operator access now resolves to manager or super-admin."""
    return await RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])(user)


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
