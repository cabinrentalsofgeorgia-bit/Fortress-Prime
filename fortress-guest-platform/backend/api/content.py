from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.models.content import MarketingArticle, TaxonomyCategory

router = APIRouter()

CONTENT_CACHE_CONTROL = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


class ContentCategorySummary(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    meta_title: str | None
    meta_description: str | None
    article_count: int


class RelatedCabinSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    property_type: str
    max_guests: int


class ContentArticleSummary(BaseModel):
    id: UUID
    title: str
    slug: str
    author: str | None
    published_date: datetime | None


class ContentCategoryDetail(ContentCategorySummary):
    articles: list[ContentArticleSummary]
    related_cabins: list[RelatedCabinSummary]


class ContentArticleDetail(BaseModel):
    id: UUID
    title: str
    slug: str
    content_body_html: str
    author: str | None
    published_date: datetime | None
    category: ContentCategorySummary


def _set_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = CONTENT_CACHE_CONTROL


def _serialize_category_summary(category: TaxonomyCategory) -> ContentCategorySummary:
    return ContentCategorySummary(
        id=category.id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        meta_title=category.meta_title,
        meta_description=category.meta_description,
        article_count=len(category.articles),
    )


def _serialize_article_summary(article: MarketingArticle) -> ContentArticleSummary:
    return ContentArticleSummary(
        id=article.id,
        title=article.title,
        slug=article.slug,
        author=article.author,
        published_date=article.published_date,
    )


@router.get("/categories", response_model=list[ContentCategorySummary])
async def list_content_categories(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> list[ContentCategorySummary]:
    _set_cache_headers(response)
    categories = (
        await db.execute(
            select(TaxonomyCategory)
            .options(selectinload(TaxonomyCategory.articles))
            .order_by(TaxonomyCategory.name.asc())
        )
    ).scalars().unique().all()

    return [_serialize_category_summary(category) for category in categories]


@router.get("/categories/{slug}", response_model=ContentCategoryDetail)
async def get_content_category(
    slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ContentCategoryDetail:
    _set_cache_headers(response)
    category = (
        await db.execute(
            select(TaxonomyCategory)
            .options(selectinload(TaxonomyCategory.articles))
            .where(TaxonomyCategory.slug == slug)
        )
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="Content category not found")

    return ContentCategoryDetail(
        **_serialize_category_summary(category).model_dump(),
        articles=[_serialize_article_summary(article) for article in category.articles],
        related_cabins=[],
    )


@router.get("/articles/{slug}", response_model=ContentArticleDetail)
async def get_marketing_article(
    slug: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ContentArticleDetail:
    _set_cache_headers(response)
    article = (
        await db.execute(
            select(MarketingArticle)
            .options(
                selectinload(MarketingArticle.category).selectinload(TaxonomyCategory.articles)
            )
            .where(MarketingArticle.slug == slug)
        )
    ).scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Marketing article not found")

    return ContentArticleDetail(
        id=article.id,
        title=article.title,
        slug=article.slug,
        content_body_html=article.content_body_html,
        author=article.author,
        published_date=article.published_date,
        category=_serialize_category_summary(article.category),
    )
