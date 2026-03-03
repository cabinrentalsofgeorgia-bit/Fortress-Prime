"""
Gateway Users — Auth Endpoints
=================================
POST /v1/auth/login       — Get JWT token
POST /v1/auth/refresh     — Refresh JWT
GET  /v1/auth/me          — Current user info
POST /v1/auth/users       — Create user (admin only)
POST /v1/auth/api-keys    — Create API key (admin only)
GET  /v1/auth/api-keys    — List API keys (admin only)
DELETE /v1/auth/api-keys/{key_id} — Revoke API key (admin only)
GET  /v1/auth/admin/users — List all users (admin only)
POST /v1/auth/admin/users/{user_id}/reset-password — Reset password (admin only)
POST /v1/auth/profile/password — Change own password (authenticated)
"""

import secrets
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from gateway.auth import (
    bcrypt,
    create_access_token,
    require_auth,
    require_role,
    decode_token,
)
from gateway.db import get_cursor

logger = logging.getLogger("gateway.users")

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = ""
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="viewer", pattern=r"^(admin|operator|viewer)$")


class UserInfo(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[str] = None
    last_login: Optional[str] = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: List[str] = []


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: Optional[List[str]] = None
    created_at: Optional[str] = None
    last_used: Optional[str] = None
    raw_key: Optional[str] = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class SignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UsernameChangeRequest(BaseModel):
    new_username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Authenticate with username/password, receive a JWT."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, username, password, role, is_active"
            " FROM fortress_users WHERE username = %s",
            (body.username,),
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    if not bcrypt.verify(body.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_users SET last_login = NOW() WHERE id = %s",
            (user["id"],),
        )

    token = create_access_token(user["id"], user["username"], user["role"])
    logger.info("Login: %s", user["username"])

    return LoginResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


# ---------------------------------------------------------------------------
# Public Signup
# ---------------------------------------------------------------------------

@router.post("/signup")
def signup(body: SignupRequest):
    """Public user registration. Creates a viewer account."""
    hashed = bcrypt.hash(body.password)
    full_name = f"{body.first_name} {body.last_name}".strip()

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO fortress_users (username, email, password, role, full_name)"
                " VALUES (%s, %s, %s, 'viewer', %s)"
                " RETURNING id, username, email, role, is_active,"
                " created_at::text, last_login::text",
                (body.username, body.email, hashed, full_name),
            )
            row = cur.fetchone()
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Username '{body.username}' already exists",
            )
        raise

    logger.info("Signup: %s (%s)", body.username, body.email)
    return dict(row)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

@router.post("/refresh")
def refresh_token(user=Depends(require_auth)):
    """Refresh an existing JWT (must be authenticated)."""
    token = create_access_token(
        int(user["sub"]), user["username"], user["role"]
    )
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@router.get("/me")
def get_me(user=Depends(require_auth)):
    """Get current authenticated user info."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active,"
            " created_at::text, last_login::text"
            " FROM fortress_users WHERE id = %s",
            (int(user["sub"]),),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return dict(row)


# ---------------------------------------------------------------------------
# Create user (admin)
# ---------------------------------------------------------------------------

@router.post("/users", dependencies=[Depends(require_role("admin"))])
def create_user(body: UserCreate):
    """Create a new user (admin only)."""
    hashed = bcrypt.hash(body.password)

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO fortress_users (username, email, password, role)"
                " VALUES (%s, %s, %s, %s)"
                " RETURNING id, username, email, role, is_active,"
                " created_at::text, last_login::text",
                (body.username, body.email, hashed, body.role),
            )
            row = cur.fetchone()
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Username '{body.username}' already exists",
            )
        raise

    logger.info("Created user: %s", body.username)
    return dict(row)


# ---------------------------------------------------------------------------
# Admin: list all users
# ---------------------------------------------------------------------------

@router.get("/admin/users", dependencies=[Depends(require_role("admin"))])
def admin_list_users():
    """List all users with account details (admin only). Passwords are never returned."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active,"
            " created_at::text, last_login::text"
            " FROM fortress_users"
            " ORDER BY id"
        )
        rows = cur.fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin: update user role
# ---------------------------------------------------------------------------

@router.patch(
    "/admin/users/{user_id}/role",
    dependencies=[Depends(require_role("admin"))],
)
def admin_update_role(user_id: int, body: dict):
    """Change a user's role (admin only)."""
    role = body.get("role", "")
    if role not in ("admin", "operator", "viewer"):
        raise HTTPException(status_code=422, detail="Invalid role")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_users SET role = %s WHERE id = %s"
            " RETURNING id, username, role",
            (role, user_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("Role changed: user_id=%d new_role=%s", user_id, role)
    return dict(row)


# ---------------------------------------------------------------------------
# Admin: update user status
# ---------------------------------------------------------------------------

@router.patch(
    "/admin/users/{user_id}/status",
    dependencies=[Depends(require_role("admin"))],
)
def admin_update_status(user_id: int, body: dict):
    """Activate or deactivate a user (admin only)."""
    is_active = body.get("is_active")
    if not isinstance(is_active, bool):
        raise HTTPException(status_code=422, detail="is_active must be boolean")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_users SET is_active = %s WHERE id = %s"
            " RETURNING id, username, is_active",
            (is_active, user_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    action = "activated" if is_active else "deactivated"
    logger.info("User %s: user_id=%d", action, user_id)
    return dict(row)


# ---------------------------------------------------------------------------
# Admin: delete user
# ---------------------------------------------------------------------------

@router.delete(
    "/admin/users/{user_id}",
    dependencies=[Depends(require_role("admin"))],
)
def admin_delete_user(user_id: int):
    """Permanently delete a user (admin only)."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM fortress_users WHERE id = %s RETURNING username",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    logger.warning("Deleted user: %s (id=%d)", row["username"], user_id)
    return {"deleted": True, "username": row["username"]}


# ---------------------------------------------------------------------------
# Admin: reset user password (Fortune 500 standard)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/users/{user_id}/reset-password",
    dependencies=[Depends(require_role("admin"))],
)
def admin_reset_password(user_id: int, body: PasswordResetRequest,
                         admin=Depends(require_role("admin"))):
    """
    Reset any user's password (admin only).

    The admin provides the new password. It is bcrypt-hashed before storage.
    The plaintext is never logged or stored. A full audit trail is recorded.
    """
    hashed = bcrypt.hash(body.new_password)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_users SET password = %s WHERE id = %s"
            " RETURNING id, username, role",
            (hashed, user_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    logger.warning(
        "PASSWORD RESET: admin=%s reset password for user=%s (id=%d)",
        admin.get("username", "unknown"), row["username"], user_id,
    )

    return {
        "status": "password_reset",
        "user_id": user_id,
        "username": row["username"],
        "message": f"Password for '{row['username']}' has been reset.",
    }


# ---------------------------------------------------------------------------
# Self-service: change own password
# ---------------------------------------------------------------------------

@router.post("/profile/password")
def change_own_password(body: PasswordChangeRequest,
                        user=Depends(require_auth)):
    """Change your own password (must know current password)."""
    user_id = int(user["sub"])

    with get_cursor() as cur:
        cur.execute(
            "SELECT password FROM fortress_users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if not bcrypt.verify(body.current_password, row["password"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    hashed = bcrypt.hash(body.new_password)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_users SET password = %s WHERE id = %s",
            (hashed, user_id),
        )

    logger.info("Password changed: user=%s", user.get("username"))
    return {"status": "password_changed"}


# ---------------------------------------------------------------------------
# Self-service: change own username
# ---------------------------------------------------------------------------

@router.post("/profile/username")
def change_own_username(body: UsernameChangeRequest,
                        user=Depends(require_auth)):
    """Change your own username (must verify current password)."""
    user_id = int(user["sub"])

    with get_cursor() as cur:
        cur.execute(
            "SELECT password FROM fortress_users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if not bcrypt.verify(body.password, row["password"]):
        raise HTTPException(status_code=401, detail="Password is incorrect")

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE fortress_users SET username = %s WHERE id = %s"
                " RETURNING id, username",
                (body.new_username, user_id),
            )
            updated = cur.fetchone()
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Username '{body.new_username}' already taken",
            )
        raise

    logger.info("Username changed: old=%s new=%s", user.get("username"), body.new_username)
    return {"status": "username_changed", "username": updated["username"]}


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

@router.post("/api-keys", dependencies=[Depends(require_role("admin"))])
def create_api_key(body: ApiKeyCreate, user=Depends(require_role("admin"))):
    """Generate a new API key (admin only). Key shown once."""
    raw_key = f"frt_{secrets.token_hex(32)}"
    prefix = raw_key[:12]
    hashed = bcrypt.hash(raw_key)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO fortress_api_keys"
            " (key_prefix, key_hash, name, scopes, owner_id)"
            " VALUES (%s, %s, %s, %s, %s)"
            " RETURNING id, name, key_prefix, scopes,"
            " created_at::text, last_used::text",
            (prefix, hashed, body.name, body.scopes, int(user["sub"])),
        )
        row = cur.fetchone()

    logger.info("Created API key: %s (prefix=%s)", body.name, prefix)
    result = dict(row)
    result["raw_key"] = raw_key
    return result


@router.get("/api-keys", dependencies=[Depends(require_role("admin"))])
def list_api_keys():
    """List all API keys (admin only). Hashes are not returned."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, key_prefix, scopes,"
            " created_at::text, last_used::text"
            " FROM fortress_api_keys"
            " ORDER BY created_at DESC"
        )
        rows = cur.fetchall()

    return [dict(r) for r in rows]


@router.delete(
    "/api-keys/{key_id}",
    dependencies=[Depends(require_role("admin"))],
)
def revoke_api_key(key_id: int):
    """Revoke (deactivate) an API key (admin only)."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE fortress_api_keys SET is_active = FALSE"
            " WHERE id = %s RETURNING name",
            (key_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="API key not found")

    logger.info("Revoked API key: %s", row["name"])
    return {"revoked": True, "name": row["name"]}
