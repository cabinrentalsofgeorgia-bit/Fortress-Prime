"""Activity model — migrated Drupal 'activity' nodes for the storefront."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.core.database import Base


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    activity_slug: Mapped[str | None] = mapped_column(
        String(500), unique=True, index=True
    )
    body: Mapped[str | None] = mapped_column(Text)
    body_summary: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)

    activity_type: Mapped[str | None] = mapped_column(String(255))
    activity_type_tid: Mapped[int | None] = mapped_column(Integer)
    area: Mapped[str | None] = mapped_column(String(255))
    area_tid: Mapped[int | None] = mapped_column(Integer)
    people: Mapped[str | None] = mapped_column(String(255))
    people_tid: Mapped[int | None] = mapped_column(Integer)
    difficulty_level: Mapped[str | None] = mapped_column(String(255))
    difficulty_level_tid: Mapped[int | None] = mapped_column(Integer)
    season: Mapped[str | None] = mapped_column(String(255))
    season_tid: Mapped[int | None] = mapped_column(Integer)

    featured_image_url: Mapped[str | None] = mapped_column(Text)
    featured_image_alt: Mapped[str | None] = mapped_column(String(500))
    featured_image_title: Mapped[str | None] = mapped_column(String(500))
    video_urls: Mapped[list | None] = mapped_column(JSONB)

    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()

    status: Mapped[str] = mapped_column(String(50), default="published")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    drupal_nid: Mapped[int | None] = mapped_column(Integer)
    drupal_vid: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Activity slug={self.slug!r}>"
