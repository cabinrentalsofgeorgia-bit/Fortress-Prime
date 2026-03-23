"""Pydantic contracts for the sovereign Fast Quote pipeline."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


TWO_PLACES = Decimal("0.01")


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    check_in: date
    check_out: date
    adults: int = Field(ge=1)
    children: int = Field(ge=0)
    pets: int = Field(ge=0)


class QuoteLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    amount: Decimal
    type: Literal["rent", "fee", "tax", "discount"]

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> float:
        return float(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


class QuoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    currency: str = "USD"
    line_items: list[QuoteLineItem]
    total_amount: Decimal
    is_bookable: bool

    @field_serializer("total_amount")
    def serialize_total_amount(self, value: Decimal) -> float:
        return float(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))
