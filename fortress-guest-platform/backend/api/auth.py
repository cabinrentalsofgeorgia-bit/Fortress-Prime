"""
Authentication API — login, register, profile, change password, SSO
"""
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import (
    RoleChecker,
    _coerce_staff_role,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from backend.models.staff import STAFF_ROLE_VALUES, StaffRole, StaffUser

logger = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    # Seconds; matches JWT exp and BFF fortress_session maxAge when provided.
    expires_in: int


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str
    last_name: str
    role: str = StaffRole.REVIEWER.value
    notification_phone: Optional[str] = None
    notification_email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    last_login_at: Optional[str] = None
    notification_phone: Optional[str] = None
    notification_email: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    notification_phone: Optional[str] = None
    notification_email: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_dict(u: StaffUser) -> dict:
    normalized_role = _coerce_staff_role(u.role)
    return {
        "id": str(u.id),
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "role": normalized_role.value,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "notification_phone": u.notification_phone,
        "notification_email": u.notification_email,
    }


def _owner_cookie_secure(request: Request) -> bool:
    host = (request.url.hostname or "").strip().lower()
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return False
    return settings.environment != "development"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(client_ip)

    result = await db.execute(
        select(StaffUser).where(StaffUser.email == body.email.lower())
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        logger.warning("login_failed", email=body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        logger.warning("login_inactive_user", email=body.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    user.last_login_at = datetime.utcnow()
    await db.commit()

    normalized_role = _coerce_staff_role(user.role)
    token = create_access_token(
        user_id=str(user.id),
        role=normalized_role,
        email=user.email,
    )

    logger.info("login_success", user_id=str(user.id), role=user.role)
    return LoginResponse(
        access_token=token,
        user=_user_dict(user),
        expires_in=_access_token_ttl_seconds(),
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    """Create a new staff user (admin only)."""
    existing = await db.execute(
        select(StaffUser).where(StaffUser.email == body.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    try:
        requested_role = StaffRole(body.role.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role. Must be one of: {', '.join(STAFF_ROLE_VALUES)}",
        ) from exc

    user = StaffUser(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role=requested_role,
        notification_phone=body.notification_phone,
        notification_email=body.notification_email,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user_registered", user_id=str(user.id), role=user.role, by=str(admin.id))
    return UserResponse(**_user_dict(user))


@router.get("/me", response_model=UserResponse)
async def get_me(user: StaffUser = Depends(get_current_user)):
    return UserResponse(**_user_dict(user))


@router.put("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.notification_phone is not None:
        user.notification_phone = body.notification_phone
    if body.notification_email is not None:
        user.notification_email = body.notification_email
    user.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("profile_updated", user_id=str(user.id))
    return UserResponse(**_user_dict(user))


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("password_changed", user_id=str(user.id))
    return {"status": "password_updated"}


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
):
    """List all staff users (admin only)."""
    result = await db.execute(
        select(StaffUser).order_by(StaffUser.first_name)
    )
    return [UserResponse(**_user_dict(u)) for u in result.scalars()]


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    body: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    """Admin resets another user's password (no old password required)."""
    from uuid import UUID
    result = await db.execute(select(StaffUser).where(StaffUser.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.password_hash = hash_password(body.new_password)
    target.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("admin_password_reset", target_user=user_id, by=str(admin.id))
    return {"status": "password_reset", "user_id": user_id}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
):
    """Deactivate a user (admin only). Does not delete."""
    from uuid import UUID

    result = await db.execute(select(StaffUser).where(StaffUser.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if str(target.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target.is_active = False
    target.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("user_deactivated", user_id=user_id, by=str(admin.id))
    return {"status": "deactivated"}


# ---------------------------------------------------------------------------
# SSO — Single Sign-On via Gateway token
# ---------------------------------------------------------------------------

GATEWAY_ROLE_MAP = {
    "admin": StaffRole.SUPER_ADMIN,
    "operator": StaffRole.MANAGER,
    "manager": StaffRole.MANAGER,
    "reviewer": StaffRole.REVIEWER,
    "viewer": StaffRole.REVIEWER,
}

_sso_rate_buckets: dict[str, list[float]] = defaultdict(list)
SSO_RATE_LIMIT = 10
SSO_RATE_WINDOW = 60

_login_rate_buckets: dict[str, list[float]] = defaultdict(list)
LOGIN_RATE_LIMIT = 25
LOGIN_RATE_WINDOW = 60


def _access_token_ttl_seconds() -> int:
    return max(300, int(settings.jwt_expiration_hours * 3600))


def _check_login_rate_limit(client_ip: str) -> None:
    """Sliding-window limit on password login attempts per client IP."""
    now = time.monotonic()
    bucket = _login_rate_buckets[client_ip]
    _login_rate_buckets[client_ip] = [t for t in bucket if now - t < LOGIN_RATE_WINDOW]
    if len(_login_rate_buckets[client_ip]) >= LOGIN_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in 60 seconds.",
            headers={"Retry-After": "60"},
        )
    _login_rate_buckets[client_ip].append(now)


def _check_sso_rate_limit(client_ip: str):
    """Simple in-memory sliding-window rate limiter for the SSO endpoint."""
    now = time.monotonic()
    bucket = _sso_rate_buckets[client_ip]
    _sso_rate_buckets[client_ip] = [t for t in bucket if now - t < SSO_RATE_WINDOW]
    if len(_sso_rate_buckets[client_ip]) >= SSO_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many SSO attempts. Try again in 60 seconds.",
            headers={"Retry-After": "60"},
        )
    _sso_rate_buckets[client_ip].append(now)


class SSORequest(BaseModel):
    gateway_token: str


@router.post("/sso", response_model=LoginResponse)
async def sso_login(
    body: SSORequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a gateway JWT, validate it against the gateway API, then
    find-or-create a local staff_user and issue a local VRS token.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_sso_rate_limit(client_ip)

    gateway_user = await _validate_gateway_token(body.gateway_token)

    gw_email = (gateway_user.get("email") or "").lower().strip()
    gw_username = gateway_user.get("username", "")
    gw_role = gateway_user.get("role", "viewer")
    gw_full_name = gateway_user.get("full_name") or gw_username

    if not gw_email:
        gw_email = f"{gw_username}@fortress.local"

    result = await db.execute(
        select(StaffUser).where(StaffUser.email == gw_email)
    )
    user = result.scalar_one_or_none()

    vrs_role = GATEWAY_ROLE_MAP.get(gw_role, StaffRole.REVIEWER)

    if user is None:
        name_parts = gw_full_name.split(None, 1) if gw_full_name else [gw_username]
        first_name = name_parts[0] if name_parts else gw_username
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        user = StaffUser(
            email=gw_email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            first_name=first_name,
            last_name=last_name,
            role=vrs_role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("sso_user_provisioned", email=gw_email, role=vrs_role.value, gateway_user=gw_username)
    else:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="VRS account is deactivated",
            )
        user.role = vrs_role
        user.last_login_at = datetime.utcnow()
        await db.commit()

    token = create_access_token(
        user_id=str(user.id),
        role=user.role,
        email=user.email,
    )

    logger.info("sso_login_success", user_id=str(user.id), gateway_user=gw_username)
    return LoginResponse(
        access_token=token,
        user=_user_dict(user),
        expires_in=_access_token_ttl_seconds(),
    )


@router.get("/command-center-url")
async def get_command_center_url():
    """Return the Command Center URL so the frontend can redirect there."""
    return {"url": settings.command_center_url}


async def _validate_gateway_token(token: str) -> dict:
    """Call the gateway's /v1/auth/me to validate a gateway JWT."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.gateway_api_url}/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.warning("sso_gateway_rejected", status=resp.status_code)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Gateway token is invalid or expired",
            )
        return resp.json()
    except httpx.RequestError as e:
        logger.error("sso_gateway_unreachable", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach gateway for SSO validation",
        )


# ---------------------------------------------------------------------------
# Owner Magic Link Authentication (Passwordless)
# ---------------------------------------------------------------------------
import hashlib
from sqlalchemy import text


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerify(BaseModel):
    token: str


@router.post("/owner/request-magic-link")
async def request_magic_link(req: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    """Generates a secure, 24-hour magic link for property owners.

    Always returns 200 regardless of whether the email exists to prevent
    email enumeration attacks.
    """
    email = req.email.lower().strip()

    result = await db.execute(
        text("SELECT sl_owner_id, owner_name FROM owner_property_map WHERE LOWER(email) = :email LIMIT 1"),
        {"email": email},
    )
    owner = result.fetchone()

    if owner:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires = datetime.now(timezone.utc) + timedelta(hours=24)

        await db.execute(
            text("""
                INSERT INTO owner_magic_tokens (token_hash, owner_email, sl_owner_id, expires_at)
                VALUES (:hash, :email, :oid, :exp)
            """),
            {"hash": token_hash, "email": email, "oid": owner.sl_owner_id, "exp": expires},
        )
        await db.commit()

        login_url = f"https://crog-ai.com/owner-login?token={raw_token}"
        logger.info(
            "owner_magic_link_generated",
            owner_email=email,
            sl_owner_id=owner.sl_owner_id,
            expires_at=expires.isoformat(),
            login_url=login_url,
        )

    return {"status": "success", "message": "If the email is on file, a login link has been sent."}


@router.post("/owner/verify-magic-link")
async def verify_magic_link(
    req: MagicLinkVerify,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Validates the raw token against the stored hash and issues a JWT via HttpOnly cookie."""
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()

    result = await db.execute(
        text("""
            SELECT id, sl_owner_id, owner_email, expires_at, used_at
            FROM owner_magic_tokens
            WHERE token_hash = :hash
        """),
        {"hash": token_hash},
    )
    token_record = result.fetchone()

    if not token_record:
        raise HTTPException(status_code=401, detail="Invalid login link.")
    if token_record.used_at:
        raise HTTPException(status_code=401, detail="Link already used. Please request a new one.")
    if token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Link expired. Please request a new one.")

    await db.execute(
        text("UPDATE owner_magic_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": token_record.id},
    )
    await db.commit()

    prop_result = await db.execute(
        text("SELECT unit_id, property_name FROM owner_property_map WHERE sl_owner_id = :oid"),
        {"oid": token_record.sl_owner_id},
    )
    properties = [{"unit_id": p.unit_id, "name": p.property_name} for p in prop_result.fetchall()]

    access_token = create_access_token(
        user_id=token_record.sl_owner_id,
        role="owner",
        email=token_record.owner_email,
    )

    response.set_cookie(
        key="fgp_owner_token",
        value=access_token,
        httponly=True,
        secure=_owner_cookie_secure(request),
        samesite="lax",
        max_age=86400,
        path="/",
    )

    logger.info(
        "owner_magic_link_verified",
        sl_owner_id=token_record.sl_owner_id,
        property_count=len(properties),
    )

    return {
        "status": "success",
        "owner": {
            "owner_id": token_record.sl_owner_id,
            "email": token_record.owner_email,
            "properties": properties,
        },
    }


@router.post("/owner/logout")
async def owner_logout(request: Request, response: Response):
    """Clears the HttpOnly owner cookie. JavaScript cannot do this."""
    response.delete_cookie(
        key="fgp_owner_token",
        path="/",
        httponly=True,
        secure=_owner_cookie_secure(request),
        samesite="lax",
    )
    return {"status": "logged_out"}
