"""
Storefront Demand Signals — Social proof and urgency data for the
cabin detail and checkout pages.

Provides two signals:
  1. Recent viewer count (from storefront_intent_events, last 60 min)
  2. "Last Available" status for a given weekend category
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.models.property import Property
from backend.models.blocked_day import BlockedDay

logger = structlog.get_logger()
router = APIRouter()


@router.get("/signals/{property_slug}")
async def get_demand_signals(
    property_slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return demand signals for a single property."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)

    viewer_stmt = (
        select(func.count(func.distinct(StorefrontIntentEvent.session_fp)))
        .where(and_(
            StorefrontIntentEvent.property_slug == property_slug,
            StorefrontIntentEvent.event_type == "property_view",
            StorefrontIntentEvent.created_at >= cutoff,
        ))
    )
    viewer_count = (await db.execute(viewer_stmt)).scalar() or 0

    prop_stmt = (
        select(Property.id, Property.bedrooms)
        .where(and_(Property.slug == property_slug, Property.is_active.is_(True)))
    )
    prop_row = (await db.execute(prop_stmt)).first()

    last_available = False
    category_total = 0
    category_available = 0

    if prop_row:
        prop_id, bedrooms = prop_row

        today = datetime.now(timezone.utc).date()
        days_until_friday = (4 - today.weekday()) % 7
        next_friday = today + timedelta(days=days_until_friday if days_until_friday > 0 else 7)
        next_sunday = next_friday + timedelta(days=2)

        peers_stmt = (
            select(Property.id)
            .where(and_(
                Property.bedrooms == bedrooms,
                Property.is_active.is_(True),
            ))
        )
        peer_ids = [row[0] for row in (await db.execute(peers_stmt)).all()]
        category_total = len(peer_ids)

        if peer_ids:
            blocked_stmt = (
                select(func.count(func.distinct(BlockedDay.property_id)))
                .where(and_(
                    BlockedDay.property_id.in_(peer_ids),
                    BlockedDay.start_date <= next_friday,
                    BlockedDay.end_date >= next_sunday,
                ))
            )
            blocked_count = (await db.execute(blocked_stmt)).scalar() or 0
            category_available = category_total - blocked_count
            last_available = category_available <= 1

    return {
        "property_slug": property_slug,
        "viewers_last_hour": viewer_count,
        "high_demand": viewer_count >= 3,
        "last_available_weekend": last_available,
        "category_total": category_total,
        "category_available": category_available,
    }
