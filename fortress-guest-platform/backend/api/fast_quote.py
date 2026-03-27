"""Sovereign Fast Quote API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.pricing import QuoteRequest, QuoteResponse
from backend.services.pricing_service import PricingError, calculate_fast_quote

router = APIRouter()


@router.post("/api/quote", response_model=QuoteResponse)
@router.post("/api/quotes/calculate", response_model=QuoteResponse, include_in_schema=False)
async def quote_property(
    body: QuoteRequest,
    db: AsyncSession = Depends(get_db),
) -> QuoteResponse:
    try:
        return await calculate_fast_quote(body, db)
    except PricingError as exc:
        detail = str(exc)
        if detail == "Property not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
