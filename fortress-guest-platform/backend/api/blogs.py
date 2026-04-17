"""Public blog endpoints consumed by the Next.js storefront."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.blog import Blog

router = APIRouter()
CACHE_CONTROL = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


class BlogResponse(BaseModel):
    id: str
    title: str
    slug: str
    body: str | None = None
    author_name: str | None = None
    status: str = "published"
    is_promoted: bool = False
    is_sticky: bool = False
    created_at: str
    updated_at: str | None = None
    published_at: str | None = None


class BlogListResponse(BaseModel):
    blogs: list[BlogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


def _to_response(b: Blog) -> BlogResponse:
    return BlogResponse(
        id=str(b.id),
        title=b.title,
        slug=b.slug,
        body=b.body,
        author_name=b.author_name,
        status=b.status,
        is_promoted=b.is_promoted,
        is_sticky=b.is_sticky,
        created_at=b.created_at.isoformat() if b.created_at else "",
        updated_at=b.updated_at.isoformat() if b.updated_at else None,
        published_at=b.published_at.isoformat() if b.published_at else None,
    )


# ── Public list ───────────────────────────────────────────────────────────

@router.get("", response_model=BlogListResponse)
async def list_blogs(
    response: Response,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
) -> BlogListResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    q = select(Blog).where(Blog.status == "published")

    if search:
        q = q.where(Blog.title.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    rows = (
        await db.execute(
            q.order_by(Blog.published_at.desc().nullslast(), Blog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return BlogListResponse(
        blogs=[_to_response(b) for b in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── Specialty lists ───────────────────────────────────────────────────────

@router.get("/featured", response_model=list[BlogResponse])
async def get_featured_blogs(
    response: Response,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(5, ge=1, le=20),
) -> list[BlogResponse]:
    response.headers["Cache-Control"] = CACHE_CONTROL
    rows = (
        await db.execute(
            select(Blog)
            .where(Blog.status == "published", Blog.is_promoted.is_(True))
            .order_by(Blog.published_at.desc().nullslast())
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        rows = (
            await db.execute(
                select(Blog)
                .where(Blog.status == "published")
                .order_by(Blog.published_at.desc().nullslast())
                .limit(limit)
            )
        ).scalars().all()
    return [_to_response(b) for b in rows]


@router.get("/recent", response_model=list[BlogResponse])
async def get_recent_blogs(
    response: Response,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(5, ge=1, le=20),
) -> list[BlogResponse]:
    response.headers["Cache-Control"] = CACHE_CONTROL
    rows = (
        await db.execute(
            select(Blog)
            .where(Blog.status == "published")
            .order_by(Blog.published_at.desc().nullslast(), Blog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_to_response(b) for b in rows]


# ── Single-item lookups ───────────────────────────────────────────────────

@router.get("/slug/{slug}", response_model=BlogResponse)
async def get_blog_by_slug(
    slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> BlogResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    b = (
        await db.execute(
            select(Blog).where(Blog.slug == slug, Blog.status == "published")
        )
    ).scalar_one_or_none()
    if b is None:
        raise HTTPException(404, f"Blog not found: {slug}")
    return _to_response(b)


@router.get("/{blog_id}", response_model=BlogResponse)
async def get_blog_by_id(
    blog_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> BlogResponse:
    response.headers["Cache-Control"] = CACHE_CONTROL
    try:
        uid = UUID(blog_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    b = (
        await db.execute(
            select(Blog).where(Blog.id == uid, Blog.status == "published")
        )
    ).scalar_one_or_none()
    if b is None:
        raise HTTPException(404, f"Blog not found: {blog_id}")
    return _to_response(b)
