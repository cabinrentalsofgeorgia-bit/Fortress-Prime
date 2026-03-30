"""
OpenShell typed tool endpoints (v1).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.property import Property
from backend.models.seo_redirect import SeoRedirect
from backend.services.history_query_tool import HistoryLibrarian
from backend.services.openshell_audit import record_audit_event
from backend.services.reservation_engine import ReservationEngine

router = APIRouter()
reservation_engine = ReservationEngine()
history_librarian = HistoryLibrarian()


def _extract_actor(request: Request) -> tuple[Optional[str], Optional[str]]:
    token_email = request.headers.get("x-user-email")
    token_sub = request.headers.get("x-user-id")
    return token_sub, token_email


def _normalize_path(path: str) -> str:
    p = path.strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p


class AvailabilityResponseRow(BaseModel):
    property_id: str
    property_name: str
    slug: str
    available: bool
    pricing: Optional[dict[str, Any]] = None


class AvailabilityResponse(BaseModel):
    check_in: str
    check_out: str
    guests: int
    results: list[AvailabilityResponseRow]


class RedirectCreateRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=1024)
    destination_path: str = Field(min_length=1, max_length=1024)
    is_permanent: bool = True
    reason: Optional[str] = Field(default=None, max_length=255)


class RedirectResponse(BaseModel):
    id: str
    source_path: str
    destination_path: str
    status_code: int
    reason: Optional[str]
    is_active: bool


class HistoryLookalikeResponse(BaseModel):
    property_id: str
    stay_date: str
    nightly_rate: float
    total_revenue: float
    guests: int
    nights: int
    booked_at: Optional[str] = None
    lead_days: Optional[int] = None
    addons_total: float = 0.0
    price_resistance: bool = False
    event_hint: Optional[str] = None
    similarity: float
    source_file: str


class HistoryAnalyticsResponse(BaseModel):
    status: str
    property_id: str
    target_date: str
    match_count: int
    comparison_scope: str
    index_backend: Optional[str] = None
    historical_avg: Optional[float] = None
    historical_peak: Optional[float] = None
    last_year_rate: Optional[float] = None
    occupancy_trend: Optional[str] = None
    occupancy_booked_ratio: Optional[float] = None
    sold_out_by_now: Optional[bool] = None
    avg_lead_days: Optional[float] = None
    addon_attach_rate: Optional[float] = None
    price_resistance_rate: Optional[float] = None
    opportunity_gap_suggested: float = 0.0
    lookalikes: list[HistoryLookalikeResponse]


async def get_properties_availability_data(
    *,
    db: AsyncSession,
    check_in: str,
    check_out: str,
    guests: int = 1,
) -> AvailabilityResponse:
    if guests < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guests must be >= 1")

    ci = date.fromisoformat(check_in)
    co = date.fromisoformat(check_out)
    if co <= ci:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="check_out must be after check_in")

    props = (
        await db.execute(
            select(Property)
            .where(Property.is_active.is_(True))
            .where(Property.max_guests >= guests)
            .order_by(Property.name.asc())
        )
    ).scalars().all()

    results: list[AvailabilityResponseRow] = []
    for prop in props:
        is_available = await reservation_engine.get_availability(db, prop.id, ci, co)
        pricing: Optional[dict[str, Any]] = None
        if is_available:
            quote = await reservation_engine.calculate_pricing(db, prop.id, ci, co, guests=guests)
            pricing = {
                "nights": quote["nights"],
                "subtotal": str(quote["subtotal"]),
                "los_discount": str(quote["los_discount"]),
                "extra_guest_fee": str(quote["extra_guest_fee"]),
                "total": str(quote["total"]),
                "nightly_breakdown": quote["nightly_breakdown"],
            }
        results.append(
            AvailabilityResponseRow(
                property_id=str(prop.id),
                property_name=prop.name,
                slug=prop.slug,
                available=is_available,
                pricing=pricing,
            )
        )

    return AvailabilityResponse(
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        results=results,
    )


@router.get("/api/v1/properties/availability", response_model=AvailabilityResponse)
async def properties_availability(
    request: Request,
    check_in: str,
    check_out: str,
    guests: int = 1,
    db: AsyncSession = Depends(get_db),
):
    response = await get_properties_availability_data(
        db=db,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
    )

    actor_id, actor_email = _extract_actor(request)
    await record_audit_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="properties.availability.read",
        resource_type="property",
        purpose="reservation_planning",
        tool_name="get_properties_availability",
        redaction_status="not_applicable",
        model_route="tool",
        outcome="success",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
            "result_count": len(response.results),
        },
        db=db,
    )

    return response


@router.get("/api/v1/history/analytics", response_model=HistoryAnalyticsResponse)
async def history_analytics(
    request: Request,
    property_id: str,
    target_date: str,
    guests: int = 2,
    nights: int = 2,
    event_hint: Optional[str] = None,
    top_k: int = 5,
    db: AsyncSession = Depends(get_db),
):
    if guests < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="guests must be >= 1")
    if nights < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="nights must be >= 1")
    if top_k < 1 or top_k > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="top_k must be between 1 and 20")

    try:
        payload = await history_librarian.get_lookalike_context(
            property_id=property_id,
            target_date=target_date,
            guests=guests,
            nights=nights,
            event_hint=event_hint,
            top_k=top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    actor_id, actor_email = _extract_actor(request)
    await record_audit_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="history.analytics.read",
        resource_type="history_context",
        resource_id=property_id,
        purpose="history_aware_pricing",
        tool_name="get_history_analytics",
        redaction_status="not_applicable",
        model_route="tool",
        outcome="success",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "property_id": property_id,
            "target_date": target_date,
            "guests": guests,
            "nights": nights,
            "event_hint": event_hint,
            "top_k": top_k,
            "match_count": payload.get("match_count", 0),
            "comparison_scope": payload.get("comparison_scope"),
            "opportunity_gap_suggested": payload.get("opportunity_gap_suggested", 0.0),
        },
        db=db,
    )

    return HistoryAnalyticsResponse(**payload)


@router.post("/api/v1/seo/redirects", response_model=RedirectResponse, status_code=status.HTTP_201_CREATED)
async def create_redirect(
    payload: RedirectCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    source_path = _normalize_path(payload.source_path)
    destination_path = _normalize_path(payload.destination_path)
    if source_path == destination_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source and destination cannot match")

    actor_id, actor_email = _extract_actor(request)
    actor = actor_email or actor_id or "system"

    existing = (
        await db.execute(select(SeoRedirect).where(SeoRedirect.source_path == source_path))
    ).scalar_one_or_none()
    if existing is None:
        existing = SeoRedirect(
            source_path=source_path,
            destination_path=destination_path,
            is_permanent=payload.is_permanent,
            reason=payload.reason,
            created_by=actor,
            updated_by=actor,
            is_active=True,
        )
        db.add(existing)
        await db.flush()
    else:
        existing.destination_path = destination_path
        existing.is_permanent = payload.is_permanent
        existing.reason = payload.reason
        existing.updated_by = actor
        existing.is_active = True
        await db.flush()

    await db.commit()
    await db.refresh(existing)

    await record_audit_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="seo.redirect.write",
        resource_type="seo_redirect",
        resource_id=str(existing.id),
        purpose="seo_redirect_management",
        tool_name="create_seo_redirect",
        redaction_status="not_applicable",
        model_route="tool",
        outcome="success",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "source_path": source_path,
            "destination_path": destination_path,
            "status_code": 301 if existing.is_permanent else 302,
            "reason": payload.reason,
        },
    )

    return RedirectResponse(
        id=str(existing.id),
        source_path=existing.source_path,
        destination_path=existing.destination_path,
        status_code=301 if existing.is_permanent else 302,
        reason=existing.reason,
        is_active=existing.is_active,
    )
