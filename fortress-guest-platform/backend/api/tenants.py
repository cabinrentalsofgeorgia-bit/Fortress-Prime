"""
Tenant management API — onboarding, settings, branding.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.core.database import get_db

router = APIRouter()


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    domain: Optional[str] = None
    timezone: str = "America/New_York"
    plan: str = "starter"


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    timezone: Optional[str] = None
    streamline_api_url: Optional[str] = None
    streamline_api_key: Optional[str] = None
    streamline_api_secret: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    domain: Optional[str]
    logo_url: Optional[str]
    primary_color: str
    timezone: str
    plan: str
    max_properties: int
    max_staff_users: int
    is_active: bool


@router.get("/", response_model=list[TenantResponse])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM tenants WHERE is_active = true ORDER BY name")
    )
    rows = []
    for r in result.fetchall():
        d = dict(r._mapping)
        d["id"] = str(d["id"])
        rows.append(d)
    return rows


@router.post("/", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": body.slug},
    )
    if existing.fetchone():
        raise HTTPException(409, "Tenant slug already exists")

    plan_limits = {
        "starter": (25, 5),
        "professional": (100, 15),
        "enterprise": (500, 50),
    }
    max_props, max_staff = plan_limits.get(body.plan, (25, 5))

    result = await db.execute(
        text("""
            INSERT INTO tenants (name, slug, domain, timezone, plan, max_properties, max_staff_users)
            VALUES (:name, :slug, :domain, :timezone, :plan, :max_props, :max_staff)
            RETURNING *
        """),
        {
            "name": body.name,
            "slug": body.slug,
            "domain": body.domain,
            "timezone": body.timezone,
            "plan": body.plan,
            "max_props": max_props,
            "max_staff": max_staff,
        },
    )
    await db.commit()
    row = result.fetchone()
    d = dict(row._mapping)
    d["id"] = str(d["id"])
    return d


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM tenants WHERE id = :id"),
        {"id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Tenant not found")
    d = dict(row._mapping)
    d["id"] = str(d["id"])
    return d


TENANT_UPDATABLE_COLUMNS = frozenset({
    "name", "domain", "logo_url", "primary_color", "timezone",
    "streamline_api_url", "streamline_api_key", "streamline_api_secret",
    "twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
})


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")

    safe_updates = {k: v for k, v in updates.items() if k in TENANT_UPDATABLE_COLUMNS}
    if not safe_updates:
        raise HTTPException(400, "No valid fields to update")

    set_clauses = ", ".join(f"{col} = :{col}" for col in safe_updates)
    safe_updates["id"] = tenant_id

    result = await db.execute(
        text(f"UPDATE tenants SET {set_clauses}, updated_at = NOW() WHERE id = :id RETURNING *"),
        safe_updates,
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Tenant not found")
    d = dict(row._mapping)
    d["id"] = str(d["id"])
    return d
