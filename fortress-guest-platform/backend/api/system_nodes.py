from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.functional_node import FunctionalNode

router = APIRouter()

CONTENT_CACHE_CONTROL = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"
MIRRORED_CONTENT_CATEGORIES = ("area_guide", "blog_article")


class NodeStaticParam(BaseModel):
    canonical_path: str
    slug: list[str]
    title: str
    content_category: str
    updated_at: datetime


class NodeResolvedPayload(BaseModel):
    canonical_path: str
    slug: list[str]
    title: str
    node_type: str
    content_category: str
    raw_html: str
    body_text_preview: str | None
    updated_at: datetime


class NodeResolveResponse(BaseModel):
    node: NodeResolvedPayload | None
    static_params: list[NodeStaticParam] = []


def _set_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = CONTENT_CACHE_CONTROL


def _normalize_path(path: str) -> str:
    cleaned = (path or "").strip()
    if not cleaned:
        return "/"
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned or "/"


def _path_to_slug(path: str) -> list[str]:
    normalized = _normalize_path(path)
    if normalized == "/":
        return []
    return [segment for segment in normalized.split("/") if segment]


def _serialize_static_param(node: FunctionalNode) -> NodeStaticParam:
    return NodeStaticParam(
        canonical_path=node.canonical_path,
        slug=_path_to_slug(node.canonical_path),
        title=node.title,
        content_category=node.content_category,
        updated_at=node.updated_at,
    )


def _serialize_node(node: FunctionalNode) -> NodeResolvedPayload:
    return NodeResolvedPayload(
        canonical_path=node.canonical_path,
        slug=_path_to_slug(node.canonical_path),
        title=node.title,
        node_type=node.node_type,
        content_category=node.content_category,
        raw_html=node.body_html or "",
        body_text_preview=node.body_text_preview,
        updated_at=node.updated_at,
    )


@router.get("/resolve", response_model=NodeResolveResponse)
async def resolve_functional_node(
    response: Response,
    path: str | None = Query(
        default=None,
        description="Canonical public path to resolve, e.g. /blog/2018/blue-ridge-fall-specials",
    ),
    db: AsyncSession = Depends(get_db),
) -> NodeResolveResponse:
    _set_cache_headers(response)

    if path:
        normalized_path = _normalize_path(path)
        node = (
            await db.execute(
                select(FunctionalNode).where(
                    FunctionalNode.canonical_path == normalized_path,
                    FunctionalNode.content_category.in_(MIRRORED_CONTENT_CATEGORIES),
                    FunctionalNode.is_published.is_(True),
                )
            )
        ).scalar_one_or_none()
        if node is None or not (node.body_html or "").strip():
            raise HTTPException(status_code=404, detail="Functional node not found")

        return NodeResolveResponse(node=_serialize_node(node))

    nodes = (
        await db.execute(
            select(FunctionalNode)
            .where(
                FunctionalNode.content_category.in_(MIRRORED_CONTENT_CATEGORIES),
                FunctionalNode.is_published.is_(True),
            )
            .order_by(FunctionalNode.priority_tier.asc(), FunctionalNode.canonical_path.asc())
        )
    ).scalars().all()

    static_params = [
        _serialize_static_param(node)
        for node in nodes
        if (node.body_html or "").strip() and _path_to_slug(node.canonical_path)
    ]

    return NodeResolveResponse(static_params=static_params, node=None)
