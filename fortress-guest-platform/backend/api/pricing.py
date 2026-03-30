"""
Admin pricing override API for human-approved yield actions.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.pricing_override import PricingOverride
from backend.models.property import Property
from backend.models.staff import StaffRole, StaffUser

router = APIRouter()
TWO_PLACES = Decimal("0.01")


class PricingOverrideCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    start_date: date
    end_date: date
    adjustment_percentage: Decimal = Field(ge=Decimal("-100.00"), le=Decimal("100.00"))
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_date_order(self) -> "PricingOverrideCreateRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        self.adjustment_percentage = self.adjustment_percentage.quantize(
            TWO_PLACES,
            rounding=ROUND_HALF_UP,
        )
        return self


class PricingOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    property_id: UUID
    start_date: date
    end_date: date
    adjustment_percentage: Decimal
    reason: str
    approved_by: str

    @field_serializer("adjustment_percentage")
    def serialize_adjustment_percentage(self, value: Decimal) -> float:
        return float(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


@router.post(
    "/overrides",
    response_model=PricingOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pricing_override(
    body: PricingOverrideCreateRequest,
    db: AsyncSession = Depends(get_db),
    approver: StaffUser = Depends(RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])),
) -> PricingOverrideResponse:
    property_record = await db.get(Property, body.property_id)
    if property_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    overlap_stmt = (
        select(PricingOverride.id)
        .where(PricingOverride.property_id == body.property_id)
        .where(PricingOverride.start_date <= body.end_date)
        .where(PricingOverride.end_date >= body.start_date)
        .limit(1)
    )
    existing_overlap = (await db.execute(overlap_stmt)).scalar_one_or_none()
    if existing_overlap is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An overlapping pricing override already exists for this property.",
        )

    override = PricingOverride(
        property_id=body.property_id,
        start_date=body.start_date,
        end_date=body.end_date,
        adjustment_percentage=body.adjustment_percentage,
        reason=body.reason.strip(),
        approved_by=approver.email,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return PricingOverrideResponse.model_validate(override)
