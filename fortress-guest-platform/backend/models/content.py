from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.core.database import Base


class TaxonomyCategory(Base):
    """Sovereign taxonomy bucket for storefront marketing content."""

    __tablename__ = "taxonomy_categories"
    __table_args__ = (
        Index("ix_taxonomy_categories_slug", "slug", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    meta_title: Mapped[str | None] = mapped_column(String(255))
    meta_description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    articles: Mapped[list["MarketingArticle"]] = relationship(
        "MarketingArticle",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="desc(MarketingArticle.published_date), MarketingArticle.title.asc()",
    )

    def __repr__(self) -> str:
        return f"<TaxonomyCategory slug={self.slug!r}>"


class MarketingArticle(Base):
    """Migrated article vessel for sovereign category and guide pages."""

    __tablename__ = "marketing_articles"
    __table_args__ = (
        Index("ix_marketing_articles_slug", "slug", unique=True),
        Index("ix_marketing_articles_category_id", "category_id"),
        Index("ix_marketing_articles_published_date", "published_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    content_body_html: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(255))
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomy_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    category: Mapped[TaxonomyCategory] = relationship("TaxonomyCategory", back_populates="articles")

    def __repr__(self) -> str:
        return f"<MarketingArticle slug={self.slug!r}>"
