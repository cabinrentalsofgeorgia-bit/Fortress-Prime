"""
Functional node ledger for non-cabin legacy Drupal routes.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class FunctionalNode(Base):
    """Ledger row describing a legacy public page and its sovereign mirror state."""

    __tablename__ = "functional_nodes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    legacy_node_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_path: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    canonical_path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    functional_complexity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    crawl_status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered", index=True)
    mirror_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    cutover_status: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy", index=True)
    priority_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=50, index=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    taxonomy_terms: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    media_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mirror_component_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mirror_route_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<FunctionalNode path={self.canonical_path!r} category={self.content_category}>"
