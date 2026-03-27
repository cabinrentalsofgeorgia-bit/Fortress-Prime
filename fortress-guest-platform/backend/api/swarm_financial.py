"""
Swarm Financial API — read-only yield analysis over the sovereign ledger.
"""
from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.financial_agent import FinancialYieldAgent, YieldAnalysis
from backend.core.database import get_db
from backend.core.security_swarm import verify_swarm_token
from backend.services.yield_extraction_service import extract_financial_context

router = APIRouter()


class FinancialAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    days_back: int = Field(default=7, ge=1, le=90)
    window_days: int = Field(default=30, ge=1, le=180)


@router.post(
    "/analyze",
    response_model=YieldAnalysis,
    status_code=status.HTTP_200_OK,
)
async def analyze_yield(
    body: FinancialAnalyzeRequest,
    _swarm_token: str = Depends(verify_swarm_token),
    db: AsyncSession = Depends(get_db),
) -> YieldAnalysis:
    try:
        context = await extract_financial_context(
            db,
            body.property_id,
            days_back=body.days_back,
            window_days=body.window_days,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    agent = FinancialYieldAgent()
    try:
        return await agent.analyze(context)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "DGX yield analysis returned an invalid payload.",
                "errors": exc.errors(),
            },
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DGX yield analysis request failed: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
