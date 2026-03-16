"""
Verses in Bloom ORM Model — Isolated e-commerce product catalog.

Tables live in ``verses_schema``, created by
``database/migrations/005_verses_ecommerce.sql``.

Read/write path: FGP backend API (``backend/api/verses.py``).
SEO enrichment: Standalone ``src/verses_seo_daemon.py`` writes via raw SQL.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.database import Base


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model
# ---------------------------------------------------------------------------

class VersesProduct(Base):
    """A single product in the Verses in Bloom watercolor card catalog."""

    __tablename__ = "products"
    __table_args__ = {"schema": "verses_schema"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    seo_description = Column(Text, nullable=True)
    typography_metadata = Column(JSONB, nullable=False, server_default="{}")
    image_metadata = Column(JSONB, nullable=False, server_default="{}")
    stock_level = Column(Integer, default=0)
    status = Column(String(30), default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ProductCreateRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    typography_metadata: Dict[str, Any] = Field(default_factory=dict)
    image_metadata: Dict[str, Any] = Field(default_factory=dict)
    stock_level: int = Field(default=0, ge=0)


class VersesProductResponse(BaseModel):
    id: str
    sku: str
    title: str
    seo_description: Optional[str] = None
    typography_metadata: Dict[str, Any] = Field(default_factory=dict)
    image_metadata: Dict[str, Any] = Field(default_factory=dict)
    stock_level: int = 0
    status: str = "draft"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
