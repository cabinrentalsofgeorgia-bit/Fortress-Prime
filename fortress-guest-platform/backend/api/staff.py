"""Sovereign staff management API with strict RBAC enforcement."""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import RoleChecker, hash_password
from backend.models.staff import STAFF_ROLE_VALUES, StaffRole, StaffUser

router = APIRouter()
super_admin_only = RoleChecker([StaffRole.SUPER_ADMIN])
PROVISIONABLE_ROLES = (StaffRole.MANAGER, StaffRole.REVIEWER)


class StaffUserResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str


class ProvisionStaffUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)


def _serialize_staff_user(user: StaffUser) -> StaffUserResponse:
    return StaffUserResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


def _derive_name_parts(email: str) -> tuple[str, str]:
    local_part = email.split("@", 1)[0]
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", local_part) if token]
    if not tokens:
        return "Fortress", "Operator"
    first_name = tokens[0].capitalize()
    last_name = " ".join(token.capitalize() for token in tokens[1:]) or "Operator"
    return first_name, last_name


@router.get("/users", response_model=list[StaffUserResponse])
async def list_staff_users(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(super_admin_only),
) -> list[StaffUserResponse]:
    result = await db.execute(
        select(StaffUser).order_by(StaffUser.is_active.desc(), StaffUser.created_at.asc(), StaffUser.email.asc())
    )
    return [_serialize_staff_user(user) for user in result.scalars().all()]


@router.post("/users", response_model=StaffUserResponse, status_code=status.HTTP_201_CREATED)
async def provision_staff_user(
    body: ProvisionStaffUserRequest,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(super_admin_only),
) -> StaffUserResponse:
    email = body.email.lower().strip()
    existing = await db.execute(select(StaffUser).where(StaffUser.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    try:
        requested_role = StaffRole(body.role.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(role.value for role in PROVISIONABLE_ROLES)}",
        ) from exc

    if requested_role not in PROVISIONABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Provisioning is restricted to: {', '.join(role.value for role in PROVISIONABLE_ROLES)}",
        )

    default_first_name, default_last_name = _derive_name_parts(email)
    staff_user = StaffUser(
        email=email,
        password_hash=hash_password(body.password),
        first_name=(body.first_name or default_first_name).strip(),
        last_name=(body.last_name or default_last_name).strip(),
        role=requested_role,
        is_active=True,
    )
    db.add(staff_user)
    await db.commit()
    await db.refresh(staff_user)
    return _serialize_staff_user(staff_user)
