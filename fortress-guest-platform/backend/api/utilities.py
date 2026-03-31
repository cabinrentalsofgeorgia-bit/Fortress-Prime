"""
Property Utilities & Services API
CRUD for utility accounts (ISP, electric, water, gas, etc.),
daily cost readings, and cost analytics.
"""
from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

import structlog
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.encryption import get_fernet, encrypt as _shared_encrypt, decrypt as _shared_decrypt
from backend.core.security import require_operator_manager_admin, require_manager_or_admin
from backend.models.property_utility import PropertyUtility, UtilityReading, SERVICE_TYPES
from backend.models.staff import StaffUser

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


def _get_fernet() -> Fernet:
    return get_fernet(settings.secret_key)


def _encrypt(plaintext: str) -> str:
    return _shared_encrypt(plaintext, settings.secret_key)


def _decrypt(ciphertext: str) -> str:
    result = _shared_decrypt(ciphertext, settings.secret_key)
    return result if result else "********"


class UtilityCreate(BaseModel):
    property_id: UUID
    service_type: str
    provider_name: str
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    portal_url: Optional[str] = None
    portal_username: Optional[str] = None
    portal_password: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    monthly_budget: Optional[float] = None


class UtilityUpdate(BaseModel):
    service_type: Optional[str] = None
    provider_name: Optional[str] = None
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    portal_url: Optional[str] = None
    portal_username: Optional[str] = None
    portal_password: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    monthly_budget: Optional[float] = None
    is_active: Optional[bool] = None


class UtilityResponse(BaseModel):
    id: UUID
    property_id: UUID
    service_type: str
    provider_name: str
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    portal_url: Optional[str] = None
    portal_username: Optional[str] = None
    has_portal_password: bool = False
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    monthly_budget: Optional[float] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    total_cost_mtd: Optional[float] = None
    total_cost_ytd: Optional[float] = None
    latest_reading_date: Optional[str] = None

    class Config:
        from_attributes = True


class ReadingCreate(BaseModel):
    reading_date: date = Field(default_factory=date.today)
    cost: float
    usage_amount: Optional[float] = None
    usage_unit: Optional[str] = None
    notes: Optional[str] = None


class ReadingResponse(BaseModel):
    id: UUID
    utility_id: UUID
    reading_date: date
    cost: float
    usage_amount: Optional[float] = None
    usage_unit: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CostSummary(BaseModel):
    property_id: UUID
    property_name: Optional[str] = None
    period: str
    by_service: dict
    total: float
    daily_breakdown: Optional[list] = None


@router.get("/types")
async def list_service_types():
    return SERVICE_TYPES


@router.get("/property/{property_id}", response_model=List[UtilityResponse])
async def list_property_utilities(
    property_id: UUID,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(PropertyUtility).where(PropertyUtility.property_id == property_id)
    if is_active is not None:
        q = q.where(PropertyUtility.is_active == is_active)
    q = q.order_by(PropertyUtility.service_type)

    result = await db.execute(q)
    utilities = result.scalars().all()

    now = datetime.utcnow()
    month_start = date(now.year, now.month, 1)
    year_start = date(now.year, 1, 1)

    responses = []
    for u in utilities:
        mtd_result = await db.execute(
            select(func.coalesce(func.sum(UtilityReading.cost), 0))
            .where(UtilityReading.utility_id == u.id)
            .where(UtilityReading.reading_date >= month_start)
        )
        mtd_val = float(mtd_result.scalar_one())

        ytd_result = await db.execute(
            select(func.coalesce(func.sum(UtilityReading.cost), 0))
            .where(UtilityReading.utility_id == u.id)
            .where(UtilityReading.reading_date >= year_start)
        )
        ytd_val = float(ytd_result.scalar_one())

        latest_result = await db.execute(
            select(func.max(UtilityReading.reading_date))
            .where(UtilityReading.utility_id == u.id)
        )
        latest_val = latest_result.scalar_one()

        responses.append(UtilityResponse(
            id=u.id,
            property_id=u.property_id,
            service_type=u.service_type,
            provider_name=u.provider_name,
            account_number=u.account_number,
            account_holder=u.account_holder,
            portal_url=u.portal_url,
            portal_username=u.portal_username,
            has_portal_password=bool(u.portal_password_enc),
            contact_phone=u.contact_phone,
            contact_email=u.contact_email,
            notes=u.notes,
            monthly_budget=float(u.monthly_budget) if u.monthly_budget else None,
            is_active=u.is_active,
            created_at=u.created_at,
            updated_at=u.updated_at,
            total_cost_mtd=mtd_val,
            total_cost_ytd=ytd_val,
            latest_reading_date=str(latest_val) if latest_val else None,
        ))

    return responses


@router.post("/", response_model=UtilityResponse, status_code=201)
async def create_utility(data: UtilityCreate, db: AsyncSession = Depends(get_db), _user: StaffUser = Depends(require_manager_or_admin)):
    u = PropertyUtility(
        property_id=data.property_id,
        service_type=data.service_type,
        provider_name=data.provider_name,
        account_number=data.account_number,
        account_holder=data.account_holder,
        portal_url=data.portal_url,
        portal_username=data.portal_username,
        portal_password_enc=_encrypt(data.portal_password) if data.portal_password else None,
        contact_phone=data.contact_phone,
        contact_email=data.contact_email,
        notes=data.notes,
        monthly_budget=data.monthly_budget,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    logger.info("utility_created", id=str(u.id), property_id=str(u.property_id), service=u.service_type)
    return UtilityResponse(
        id=u.id, property_id=u.property_id, service_type=u.service_type,
        provider_name=u.provider_name, account_number=u.account_number,
        account_holder=u.account_holder, portal_url=u.portal_url,
        portal_username=u.portal_username, has_portal_password=bool(u.portal_password_enc),
        contact_phone=u.contact_phone, contact_email=u.contact_email,
        notes=u.notes, monthly_budget=float(u.monthly_budget) if u.monthly_budget else None,
        is_active=u.is_active, created_at=u.created_at, updated_at=u.updated_at,
        total_cost_mtd=0, total_cost_ytd=0,
    )


@router.patch("/{utility_id}", response_model=UtilityResponse)
async def update_utility(utility_id: UUID, body: UtilityUpdate, db: AsyncSession = Depends(get_db), _user: StaffUser = Depends(require_manager_or_admin)):
    u = await db.get(PropertyUtility, utility_id)
    if not u:
        raise HTTPException(status_code=404, detail="Utility account not found")

    updates = body.model_dump(exclude_unset=True)
    if "portal_password" in updates:
        pw = updates.pop("portal_password")
        u.portal_password_enc = _encrypt(pw) if pw else None

    for field, value in updates.items():
        setattr(u, field, value)

    u.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(u)
    logger.info("utility_updated", id=str(utility_id))
    return UtilityResponse(
        id=u.id, property_id=u.property_id, service_type=u.service_type,
        provider_name=u.provider_name, account_number=u.account_number,
        account_holder=u.account_holder, portal_url=u.portal_url,
        portal_username=u.portal_username, has_portal_password=bool(u.portal_password_enc),
        contact_phone=u.contact_phone, contact_email=u.contact_email,
        notes=u.notes, monthly_budget=float(u.monthly_budget) if u.monthly_budget else None,
        is_active=u.is_active, created_at=u.created_at, updated_at=u.updated_at,
    )


@router.delete("/{utility_id}")
async def delete_utility(utility_id: UUID, db: AsyncSession = Depends(get_db), _user: StaffUser = Depends(require_manager_or_admin)):
    u = await db.get(PropertyUtility, utility_id)
    if not u:
        raise HTTPException(status_code=404, detail="Utility account not found")
    await db.delete(u)
    await db.commit()
    logger.info("utility_deleted", id=str(utility_id))
    return {"status": "deleted"}


@router.get("/{utility_id}/password")
async def reveal_password(utility_id: UUID, db: AsyncSession = Depends(get_db), user: StaffUser = Depends(require_manager_or_admin)):
    """Decrypt and return the portal password (audit logged)."""
    u = await db.get(PropertyUtility, utility_id)
    if not u:
        raise HTTPException(status_code=404, detail="Utility account not found")
    logger.warning("utility_password_revealed", utility_id=str(utility_id), service=u.service_type, revealed_by=str(user.id))
    return {"password": _decrypt(u.portal_password_enc) if u.portal_password_enc else None}


@router.post("/{utility_id}/readings", response_model=ReadingResponse, status_code=201)
async def add_reading(utility_id: UUID, data: ReadingCreate, db: AsyncSession = Depends(get_db)):
    u = await db.get(PropertyUtility, utility_id)
    if not u:
        raise HTTPException(status_code=404, detail="Utility account not found")

    reading = UtilityReading(
        utility_id=utility_id,
        reading_date=data.reading_date,
        cost=data.cost,
        usage_amount=data.usage_amount,
        usage_unit=data.usage_unit,
        notes=data.notes,
    )
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    logger.info("utility_reading_added", utility_id=str(utility_id), date=str(data.reading_date), cost=data.cost)
    return ReadingResponse.model_validate(reading)


@router.get("/{utility_id}/readings", response_model=List[ReadingResponse])
async def list_readings(
    utility_id: UUID,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = Query(365, le=3650),
    db: AsyncSession = Depends(get_db),
):
    q = select(UtilityReading).where(UtilityReading.utility_id == utility_id)
    if start:
        q = q.where(UtilityReading.reading_date >= start)
    if end:
        q = q.where(UtilityReading.reading_date <= end)
    q = q.order_by(UtilityReading.reading_date.desc()).limit(limit)
    result = await db.execute(q)
    return [ReadingResponse.model_validate(r) for r in result.scalars().all()]


@router.delete("/readings/{reading_id}")
async def delete_reading(reading_id: UUID, db: AsyncSession = Depends(get_db), _user: StaffUser = Depends(require_manager_or_admin)):
    r = await db.get(UtilityReading, reading_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reading not found")
    await db.delete(r)
    await db.commit()
    return {"status": "deleted"}


@router.get("/analytics/{property_id}", response_model=CostSummary)
async def utility_cost_analytics(
    property_id: UUID,
    period: str = Query("mtd", pattern="^(mtd|ytd|last30|last90|last365)$"),
    db: AsyncSession = Depends(get_db),
):
    now = date.today()
    if period == "mtd":
        start_date = date(now.year, now.month, 1)
    elif period == "ytd":
        start_date = date(now.year, 1, 1)
    elif period == "last30":
        start_date = now - timedelta(days=30)
    elif period == "last90":
        start_date = now - timedelta(days=90)
    else:
        start_date = now - timedelta(days=365)

    by_service_q = (
        select(
            PropertyUtility.service_type,
            func.coalesce(func.sum(UtilityReading.cost), 0).label("total"),
        )
        .join(UtilityReading, UtilityReading.utility_id == PropertyUtility.id)
        .where(PropertyUtility.property_id == property_id)
        .where(UtilityReading.reading_date >= start_date)
        .group_by(PropertyUtility.service_type)
    )
    result = await db.execute(by_service_q)
    by_service = {row.service_type: float(row.total) for row in result}
    total = sum(by_service.values())

    daily_q = (
        select(
            UtilityReading.reading_date,
            PropertyUtility.service_type,
            func.sum(UtilityReading.cost).label("cost"),
        )
        .join(PropertyUtility, PropertyUtility.id == UtilityReading.utility_id)
        .where(PropertyUtility.property_id == property_id)
        .where(UtilityReading.reading_date >= start_date)
        .group_by(UtilityReading.reading_date, PropertyUtility.service_type)
        .order_by(UtilityReading.reading_date)
    )
    result = await db.execute(daily_q)
    daily = [
        {"date": str(row.reading_date), "service": row.service_type, "cost": float(row.cost)}
        for row in result
    ]

    from backend.models import Property
    prop = await db.get(Property, property_id)

    return CostSummary(
        property_id=property_id,
        property_name=prop.name if prop else None,
        period=period,
        by_service=by_service,
        total=total,
        daily_breakdown=daily,
    )


@router.get("/analytics/portfolio/summary")
async def portfolio_cost_summary(
    period: str = Query("mtd", pattern="^(mtd|ytd|last30|last90|last365)$"),
    db: AsyncSession = Depends(get_db),
):
    """Cross-property utility cost summary for the whole portfolio."""
    now = date.today()
    if period == "mtd":
        start_date = date(now.year, now.month, 1)
    elif period == "ytd":
        start_date = date(now.year, 1, 1)
    elif period == "last30":
        start_date = now - timedelta(days=30)
    elif period == "last90":
        start_date = now - timedelta(days=90)
    else:
        start_date = now - timedelta(days=365)

    from backend.models import Property
    q = (
        select(
            Property.id,
            Property.name,
            PropertyUtility.service_type,
            func.coalesce(func.sum(UtilityReading.cost), 0).label("total"),
        )
        .join(PropertyUtility, PropertyUtility.property_id == Property.id)
        .join(UtilityReading, UtilityReading.utility_id == PropertyUtility.id)
        .where(UtilityReading.reading_date >= start_date)
        .group_by(Property.id, Property.name, PropertyUtility.service_type)
        .order_by(Property.name)
    )
    result = await db.execute(q)

    properties: dict = {}
    for row in result:
        pid = str(row.id)
        if pid not in properties:
            properties[pid] = {"property_id": pid, "property_name": row.name, "by_service": {}, "total": 0.0}
        properties[pid]["by_service"][row.service_type] = float(row.total)
        properties[pid]["total"] += float(row.total)

    return {
        "period": period,
        "properties": list(properties.values()),
        "grand_total": sum(p["total"] for p in properties.values()),
    }
