"""
Verses in Bloom API — Isolated e-commerce product catalog.

Endpoints for managing watercolor card products and triggering
automated SEO copywriting via the Redpanda event bus.
"""

import structlog
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.event_publisher import EventPublisher
from backend.models.verses import (
    ProductCreateRequest,
    VersesProduct,
    VersesProductResponse,
)

logger = structlog.get_logger()
router = APIRouter()


@router.post("/products", response_model=VersesProductResponse, status_code=201)
async def create_product(
    body: ProductCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new watercolor card product and queue SEO generation."""
    existing = await db.execute(
        select(VersesProduct).where(VersesProduct.sku == body.sku)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"SKU '{body.sku}' already exists")

    product = VersesProduct(
        sku=body.sku,
        title=body.title,
        typography_metadata=body.typography_metadata,
        image_metadata=body.image_metadata,
        stock_level=body.stock_level,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    await EventPublisher.publish(
        topic="ecommerce.seo.generation_requested",
        payload={
            "product_id": str(product.id),
            "sku": product.sku,
            "title": product.title,
            "typography": product.typography_metadata or {},
            "visuals": product.image_metadata or {},
        },
        key=product.sku,
    )
    logger.info("verses_product_created", sku=product.sku, product_id=str(product.id))

    return _to_response(product)


@router.get("/products", response_model=List[VersesProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all Verses in Bloom products."""
    stmt = select(VersesProduct).order_by(VersesProduct.created_at.desc())
    if status:
        stmt = stmt.where(VersesProduct.status == status)
    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    products = result.scalars().all()
    return [_to_response(p) for p in products]


@router.get("/products/{sku}", response_model=VersesProductResponse)
async def get_product(sku: str, db: AsyncSession = Depends(get_db)):
    """Retrieve a single product by SKU."""
    result = await db.execute(
        select(VersesProduct).where(VersesProduct.sku == sku)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product SKU '{sku}' not found")
    return _to_response(product)


def _to_response(p: VersesProduct) -> VersesProductResponse:
    return VersesProductResponse(
        id=str(p.id),
        sku=p.sku,
        title=p.title,
        seo_description=p.seo_description,
        typography_metadata=p.typography_metadata or {},
        image_metadata=p.image_metadata or {},
        stock_level=p.stock_level or 0,
        status=p.status or "draft",
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
