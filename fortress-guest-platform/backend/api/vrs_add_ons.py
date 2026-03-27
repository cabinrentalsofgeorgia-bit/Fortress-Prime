"""
Ancillary revenue catalog endpoints for deterministic quote composition.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.vrs_add_on import VRSAddOn, VRSAddOnPricingModel, VRSAddOnScope

router = APIRouter()


class VRSAddOnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    price: Decimal
    pricing_model: VRSAddOnPricingModel
    is_active: bool
    scope: VRSAddOnScope
    property_id: UUID | None


@router.get("/add-ons", response_model=list[VRSAddOnResponse])
async def list_vrs_add_ons(
    property_id: UUID | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    query = select(VRSAddOn)

    if not include_inactive:
        query = query.where(VRSAddOn.is_active.is_(True))

    if property_id is not None:
        query = query.where(
            or_(
                VRSAddOn.scope == VRSAddOnScope.GLOBAL,
                VRSAddOn.property_id == property_id,
            )
        )
    else:
        query = query.where(VRSAddOn.scope == VRSAddOnScope.GLOBAL)

    query = query.order_by(VRSAddOn.scope.asc(), VRSAddOn.name.asc())
    result = await db.execute(query)
    return list(result.scalars().all())
