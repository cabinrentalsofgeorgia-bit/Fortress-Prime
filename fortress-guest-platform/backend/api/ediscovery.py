"""
E-Discovery API — POST /api/internal/legal/discovery/extract
====================================================
Accepts a list of entity keywords, runs the e-discovery pipeline against
the legacy Command Center database (fortress_db), and returns a unified
chronological evidence timeline plus synthesized brief injection text.

Hooked into:
    public.email_archive      (36K+ emails)
    public.finance_invoices   (financial records)
    public.sender_registry    (sender profiles)
    legal.case_evidence       (pre-indexed evidence)
    legal.correspondence      (legal communications)
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.core.security import require_manager_or_admin
from backend.services.ediscovery_agent import run_discovery

logger = structlog.get_logger()

router = APIRouter()


class DiscoveryRequest(BaseModel):
    entities: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of entity keywords to search for (e.g., 'Generali', 'Brian Wollover')",
    )
    max_per_table: int = Field(
        default=200,
        ge=10,
        le=500,
        description="Maximum results per data source per entity",
    )

    @field_validator("entities")
    @classmethod
    def validate_entities(cls, v: list[str]) -> list[str]:
        cleaned = []
        for entity in v:
            stripped = entity.strip()
            if len(stripped) < 2:
                raise ValueError(f"Entity too short: '{stripped}' (minimum 2 characters)")
            if len(stripped) > 200:
                raise ValueError(f"Entity too long: '{stripped[:20]}...' (maximum 200 characters)")
            cleaned.append(stripped)
        return cleaned


class DiscoveryResponse(BaseModel):
    entities: list[str]
    total_hits: int
    source_stats: dict[str, int]
    elapsed_seconds: float
    errors: list[str]
    timeline: list[dict]
    brief_injection: str


@router.post(
    "/discovery/extract",
    response_model=DiscoveryResponse,
    summary="Run automated e-discovery extraction",
    description="Search all legacy databases for entity mentions and return a unified evidence timeline.",
)
async def extract_discovery(
    request: DiscoveryRequest,
    _user=Depends(require_manager_or_admin),
) -> DiscoveryResponse:
    logger.info(
        "ediscovery_api_request",
        entities=request.entities,
        max_per_table=request.max_per_table,
    )
    try:
        result = await run_discovery(
            entities=request.entities,
            max_per_table=request.max_per_table,
        )
        return DiscoveryResponse(**result)
    except Exception as exc:
        logger.error("ediscovery_api_error", error=str(exc)[:500], exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "type": "https://fortress/errors/ediscovery",
                "title": "E-Discovery Pipeline Error",
                "status": 502,
                "detail": f"Discovery pipeline failed: {str(exc)[:200]}",
            },
        )
