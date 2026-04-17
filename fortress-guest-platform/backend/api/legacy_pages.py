from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.content import LegacyPage

router = APIRouter()

CACHE_CONTROL = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


class PageContentResponse(BaseModel):
    entity_type: str
    bundle: str
    entity_id: int
    revision_id: int | None
    language: str
    delta: int
    title: str | None
    slug: str | None
    body_value: str | None
    body_summary: str | None
    body_format: str | None


@router.get("/slug/{slug}", response_model=PageContentResponse)
async def get_page_by_slug(
    slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> PageContentResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL

    page = (
        await db.execute(
            select(LegacyPage).where(LegacyPage.slug == slug)
        )
    ).scalar_one_or_none()

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    return PageContentResponse(
        entity_type=page.entity_type,
        bundle=page.bundle,
        entity_id=0,
        revision_id=None,
        language=page.language,
        delta=0,
        title=page.title,
        slug=page.slug,
        body_value=page.body_value,
        body_summary=page.body_summary,
        body_format=page.body_format,
    )


@router.get("/title/{title}", response_model=PageContentResponse)
async def get_page_by_title(
    title: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> PageContentResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL

    page = (
        await db.execute(
            select(LegacyPage).where(LegacyPage.title.ilike(f"%{title}%"))
        )
    ).scalar_one_or_none()

    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found by title: {title}")

    return PageContentResponse(
        entity_type=page.entity_type,
        bundle=page.bundle,
        entity_id=0,
        revision_id=None,
        language=page.language,
        delta=0,
        title=page.title,
        slug=page.slug,
        body_value=page.body_value,
        body_summary=page.body_summary,
        body_format=page.body_format,
    )
