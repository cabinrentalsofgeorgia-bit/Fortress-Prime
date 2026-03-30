"""
Compatibility router for legacy /api/admin/insights consumers.

No checked-in ai_insights schema or Alembic migration exists in this repo.
Instead of depending on an out-of-band table when one happens to exist, this
endpoint exposes a deliberate replacement contract that points callers at the
supported AI capability endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models import Message, Property, Reservation, WorkOrder
from backend.models.staff import StaffUser

router = APIRouter()

SUPPORTED_AI_ENDPOINTS: list[dict[str, Any]] = [
    {
        "path": "/api/ai/ask",
        "method": "POST",
        "purpose": "Natural-language Q&A against the configured AI engine.",
        "request_shape": {
            "question": "string",
            "context": "object | null",
        },
    },
    {
        "path": "/api/ai/forecast",
        "method": "POST",
        "purpose": "Revenue forecasting summary for the analytics insights page.",
        "request_shape": {
            "historical_data": "array<object>",
            "forecast_months": "integer",
        },
    },
    {
        "path": "/api/ai/predict-maintenance",
        "method": "POST",
        "purpose": "Predictive maintenance suggestions derived from work order history.",
        "request_shape": {
            "work_orders": "array<object>",
            "messages": "array<object>",
        },
    },
    {
        "path": "/api/ai/optimize-listing",
        "method": "POST",
        "purpose": "Listing optimization recommendations for active properties.",
        "request_shape": {
            "property_name": "string",
            "bedrooms": "integer",
            "bathrooms": "number",
            "max_guests": "integer",
            "amenities": "array<string>",
            "location": "string",
        },
    },
]


async def _build_operational_snapshot(db: AsyncSession) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    seven_days_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)
    active_reservation_statuses = ["confirmed", "checked_in"]
    realized_reservation_statuses = ["confirmed", "checked_in", "checked_out", "no_show"]
    open_work_order_statuses = ["open", "in_progress", "waiting_parts"]

    total_properties = (
        await db.execute(select(func.count(Property.id)).where(Property.is_active.is_(True)))
    ).scalar() or 0
    active_reservations = (
        await db.execute(
            select(func.count(Reservation.id)).where(
                Reservation.status.in_(active_reservation_statuses),
                Reservation.check_in_date <= today,
                Reservation.check_out_date >= today,
            )
        )
    ).scalar() or 0
    total_revenue_mtd = (
        await db.execute(
            select(func.coalesce(func.sum(Reservation.total_amount), 0)).where(
                Reservation.check_in_date >= month_start,
                Reservation.check_in_date <= today,
                Reservation.status.in_(realized_reservation_statuses),
            )
        )
    ).scalar() or 0
    open_work_orders = (
        await db.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.status.in_(open_work_order_statuses))
        )
    ).scalar() or 0
    unread_messages = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.direction == "inbound",
                Message.read_at.is_(None),
            )
        )
    ).scalar() or 0
    outbound_messages_7d = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.direction == "outbound",
                func.date(Message.created_at) >= seven_days_ago,
            )
        )
    ).scalar() or 0
    auto_outbound_messages_7d = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.direction == "outbound",
                Message.is_auto_response.is_(True),
                func.date(Message.created_at) >= seven_days_ago,
            )
        )
    ).scalar() or 0
    urgent_work_orders = (
        await db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.status.in_(open_work_order_statuses),
                WorkOrder.priority == "urgent",
            )
        )
    ).scalar() or 0

    occupancy_rate = (
        round((active_reservations / total_properties) * 100, 1) if total_properties else 0.0
    )
    automation_rate_7d = (
        round((auto_outbound_messages_7d / outbound_messages_7d) * 100, 1)
        if outbound_messages_7d
        else 0.0
    )

    month_label = func.to_char(Reservation.check_in_date, "YYYY-MM")

    revenue_rows = (
        await db.execute(
            select(
                month_label,
                func.coalesce(func.sum(Reservation.total_amount), 0),
                func.count(Reservation.id),
            )
            .where(
                Reservation.check_in_date >= today - timedelta(days=180),
                Reservation.status.in_(realized_reservation_statuses),
            )
            .group_by(month_label)
            .order_by(month_label.desc())
            .limit(6)
        )
    ).all()

    maintenance_rows = (
        await db.execute(
            select(WorkOrder.category, func.count(WorkOrder.id))
            .where(WorkOrder.status.in_(open_work_order_statuses))
            .group_by(WorkOrder.category)
            .order_by(func.count(WorkOrder.id).desc(), WorkOrder.category.asc())
            .limit(5)
        )
    ).all()

    items = [
        {
            "id": "operational_overview",
            "title": "Operational overview",
            "summary": (
                f"{active_reservations} active stays across {total_properties} active properties, "
                f"{open_work_orders} open work orders, and {unread_messages} unread inbound messages."
            ),
            "metrics": {
                "active_properties": int(total_properties),
                "active_reservations": int(active_reservations),
                "occupancy_rate": occupancy_rate,
                "open_work_orders": int(open_work_orders),
                "urgent_work_orders": int(urgent_work_orders),
                "unread_messages": int(unread_messages),
                "revenue_mtd": float(total_revenue_mtd),
            },
        },
        {
            "id": "revenue_signal",
            "title": "Revenue signal",
            "summary": "Recent realized reservation revenue by month derived from reservation ledger data.",
            "metrics": {
                "months": [
                    {
                        "month": row[0],
                        "revenue": float(row[1] or 0),
                        "reservation_count": int(row[2] or 0),
                    }
                    for row in revenue_rows
                ],
            },
        },
        {
            "id": "automation_signal",
            "title": "Automation signal",
            "summary": "Seven-day outbound messaging automation rate derived from guest communications.",
            "metrics": {
                "outbound_messages_7d": int(outbound_messages_7d),
                "auto_outbound_messages_7d": int(auto_outbound_messages_7d),
                "automation_rate_7d": automation_rate_7d,
                "unread_inbound_messages": int(unread_messages),
            },
        },
        {
            "id": "maintenance_signal",
            "title": "Maintenance signal",
            "summary": "Open maintenance demand and category hotspots derived from work orders.",
            "metrics": {
                "open_work_orders": int(open_work_orders),
                "urgent_work_orders": int(urgent_work_orders),
                "top_open_categories": [
                    {"category": row[0] or "uncategorized", "count": int(row[1] or 0)}
                    for row in maintenance_rows
                ],
            },
        },
    ]

    return items


@router.get("/insights")
async def list_admin_insights(
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_manager_or_admin),
) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    response.headers["X-Fortress-Admin-Insights-Contract"] = "derived"

    items = await _build_operational_snapshot(db)
    limited_items = items[:limit]

    return {
        "items": limited_items,
        "count": len(limited_items),
        "requested_limit": limit,
        "source_table_present": False,
        "live_data_supported": True,
        "status": "derived_snapshot",
        "message": (
            "No checked-in ai_insights schema exists. This endpoint no longer "
            "relies on an implicit database table and now returns a live "
            "snapshot derived from core operational tables."
        ),
        "replacement_contract": {
            "type": "derived_core_tables",
            "supported_endpoints": SUPPORTED_AI_ENDPOINTS,
            "dashboard_routes": ["/analytics/insights"],
            "source_tables": ["properties", "reservations", "messages", "work_orders"],
            "notes": [
                "No checked-in ai_insights table exists in backend models or Alembic migrations.",
                "Insights are derived from existing operational tables instead of a dedicated ai_insights ledger.",
                "Use the listed AI capability endpoints for supported live behavior.",
            ],
        },
    }
