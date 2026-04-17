"""Public + admin activity endpoints consumed by the Next.js storefront."""
from __future__ import annotations

from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.activity import Activity

router = APIRouter()
CACHE_CONTROL = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


class ActivityResponse(BaseModel):
    id: str
    title: str
    slug: str
    activity_slug: str | None = None
    body: str | None = None
    body_summary: str | None = None
    address: str | None = None
    activity_type: str | None = None
    activity_type_tid: int | None = None
    area: str | None = None
    area_tid: int | None = None
    people: str | None = None
    people_tid: int | None = None
    difficulty_level: str | None = None
    difficulty_level_tid: int | None = None
    season: str | None = None
    season_tid: int | None = None
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    featured_image_title: str | None = None
    video_urls: list[str] | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str = "published"
    is_featured: bool = False
    display_order: int = 0
    drupal_nid: int | None = None
    drupal_vid: int | None = None
    created_at: str
    updated_at: str | None = None
    published_at: str | None = None


class ActivityListResponse(BaseModel):
    activities: list[ActivityResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


def _to_response(a: Activity) -> ActivityResponse:
    return ActivityResponse(
        id=str(a.id),
        title=a.title,
        slug=a.slug,
        activity_slug=a.activity_slug,
        body=a.body,
        body_summary=a.body_summary,
        address=a.address,
        activity_type=a.activity_type,
        activity_type_tid=a.activity_type_tid,
        area=a.area,
        area_tid=a.area_tid,
        people=a.people,
        people_tid=a.people_tid,
        difficulty_level=a.difficulty_level,
        difficulty_level_tid=a.difficulty_level_tid,
        season=a.season,
        season_tid=a.season_tid,
        featured_image_url=a.featured_image_url,
        featured_image_alt=a.featured_image_alt,
        featured_image_title=a.featured_image_title,
        video_urls=a.video_urls,
        latitude=a.latitude,
        longitude=a.longitude,
        status=a.status,
        is_featured=a.is_featured,
        display_order=a.display_order,
        drupal_nid=a.drupal_nid,
        drupal_vid=a.drupal_vid,
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else None,
        published_at=a.published_at.isoformat() if a.published_at else None,
    )


# ── Public list ───────────────────────────────────────────────────────────

@router.get("", response_model=ActivityListResponse)
async def list_activities(
    response: Response,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    activity_type_tid: int | None = Query(None),
    search: str | None = Query(None),
) -> ActivityListResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    q = select(Activity).where(Activity.status == "published")

    if activity_type_tid is not None:
        q = q.where(Activity.activity_type_tid == activity_type_tid)
    if search:
        q = q.where(Activity.title.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    rows = (
        await db.execute(
            q.order_by(Activity.display_order, Activity.title)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ActivityListResponse(
        activities=[_to_response(a) for a in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── Public single-item lookups ────────────────────────────────────────────

@router.get("/slug/{slug}", response_model=ActivityResponse)
async def get_activity_by_slug(
    slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ActivityResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    a = (
        await db.execute(
            select(Activity)
            .where(Activity.slug == slug, Activity.status == "published")
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, f"Activity not found: {slug}")
    return _to_response(a)


@router.get("/activity-slug/{activity_slug:path}", response_model=ActivityResponse)
async def get_activity_by_activity_slug(
    activity_slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ActivityResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    decoded = unquote(activity_slug)
    a = (
        await db.execute(
            select(Activity)
            .where(Activity.activity_slug == decoded, Activity.status == "published")
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, f"Activity not found: {decoded}")
    return _to_response(a)


@router.get("/{activity_id}", response_model=ActivityResponse)
async def get_activity_by_id(
    activity_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ActivityResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    try:
        uid = UUID(activity_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    a = (
        await db.execute(
            select(Activity)
            .where(Activity.id == uid, Activity.status == "published")
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, f"Activity not found: {activity_id}")
    return _to_response(a)
