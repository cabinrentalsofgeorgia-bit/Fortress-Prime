from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.staff import StaffUser

router = APIRouter()


class AdminInsightItem(BaseModel):
    id: str
    title: str
    summary: str
    metrics: dict[str, Any]


class ReplacementContract(BaseModel):
    type: str
    supported_endpoints: list[dict[str, Any]]
    dashboard_routes: list[str]
    source_tables: list[str]
    notes: list[str]


class AdminInsightsResponse(BaseModel):
    items: list[AdminInsightItem]
    count: int
    requested_limit: int
    source_table_present: bool
    live_data_supported: bool
    status: str
    message: str
    replacement_contract: ReplacementContract


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _rollback_if_possible(db: AsyncSession) -> None:
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        await rollback()


async def _scalar(db: AsyncSession, query: str) -> Any:
    try:
        result = await db.execute(text(query))
        return result.scalar()
    except ProgrammingError:
        await _rollback_if_possible(db)
        return 0


async def _rows(db: AsyncSession, query: str) -> list[Any]:
    try:
        result = await db.execute(text(query))
        return list(result.all())
    except ProgrammingError:
        await _rollback_if_possible(db)
        return []


def _replacement_contract() -> ReplacementContract:
    return ReplacementContract(
        type="derived_core_tables",
        supported_endpoints=[
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
        ],
        dashboard_routes=["/analytics/insights"],
        source_tables=["properties", "reservations", "messages", "work_orders"],
        notes=[
            "No checked-in ai_insights table exists in backend models or Alembic migrations.",
            "Insights are derived from existing operational tables instead of a dedicated ai_insights ledger.",
            "Use the listed AI capability endpoints for supported live behavior.",
        ],
    )


@router.get("/insights", response_model=AdminInsightsResponse)
async def get_admin_insights(
    response: Response,
    limit: int = Query(default=4, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_manager_or_admin),
):
    total_properties = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM properties
            WHERE COALESCE(is_active, TRUE) IS TRUE
            """,
        )
        or 0
    )
    active_reservations = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM reservations
            WHERE status IN ('confirmed', 'checked_in', 'pending_payment')
            """,
        )
        or 0
    )
    revenue_mtd = _safe_float(
        await _scalar(
            db,
            """
            SELECT COALESCE(SUM(total_amount), 0)
            FROM reservations
            WHERE created_at >= date_trunc('month', CURRENT_DATE)
            """,
        )
    )
    open_work_orders = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM work_orders
            WHERE status NOT IN ('completed', 'closed', 'resolved', 'cancelled')
            """,
        )
        or 0
    )
    unread_messages = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE direction = 'inbound'
              AND read_at IS NULL
            """,
        )
        or 0
    )
    outbound_messages_7d = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE direction = 'outbound'
              AND created_at >= NOW() - INTERVAL '7 days'
            """,
        )
        or 0
    )
    auto_outbound_messages_7d = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE direction = 'outbound'
              AND COALESCE(is_auto_response, FALSE) IS TRUE
              AND created_at >= NOW() - INTERVAL '7 days'
            """,
        )
        or 0
    )
    urgent_work_orders = int(
        await _scalar(
            db,
            """
            SELECT COUNT(*)
            FROM work_orders
            WHERE priority = 'urgent'
              AND status NOT IN ('completed', 'closed', 'resolved', 'cancelled')
            """,
        )
        or 0
    )
    month_rows = await _rows(
        db,
        """
        SELECT
            to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
            COALESCE(SUM(total_amount), 0) AS revenue,
            COUNT(*) AS reservation_count
        FROM reservations
        WHERE created_at >= date_trunc('month', CURRENT_DATE) - INTERVAL '5 months'
        GROUP BY 1
        ORDER BY 1 DESC
        LIMIT 6
        """,
    )
    category_rows = await _rows(
        db,
        """
        SELECT category, COUNT(*) AS count
        FROM work_orders
        WHERE status NOT IN ('completed', 'closed', 'resolved', 'cancelled')
        GROUP BY category
        ORDER BY count DESC, category ASC
        LIMIT 5
        """,
    )

    occupancy_rate = round((active_reservations / total_properties) * 100, 2) if total_properties else 0.0
    automation_rate = round((auto_outbound_messages_7d / outbound_messages_7d) * 100, 2) if outbound_messages_7d else 0.0
    revenue_months = [
        {
            "month": str(month or ""),
            "revenue": _safe_float(revenue),
            "reservation_count": int(reservation_count or 0),
        }
        for month, revenue, reservation_count in month_rows
    ]
    top_categories = [
        {
            "category": str(category or "unknown"),
            "count": int(count or 0),
        }
        for category, count in category_rows
    ]

    items = [
        AdminInsightItem(
            id="operational_overview",
            title="Operational overview",
            summary=(
                f"{active_reservations} active stays across {total_properties} active properties, "
                f"{open_work_orders} open work orders, and {unread_messages} unread inbound messages."
            ),
            metrics={
                "active_properties": total_properties,
                "active_reservations": active_reservations,
                "occupancy_rate": occupancy_rate,
                "open_work_orders": open_work_orders,
                "urgent_work_orders": urgent_work_orders,
                "unread_messages": unread_messages,
                "revenue_mtd": revenue_mtd,
            },
        ),
        AdminInsightItem(
            id="revenue_signal",
            title="Revenue signal",
            summary=f"${revenue_mtd:,.2f} booked this month across the latest reservation window.",
            metrics={"months": revenue_months},
        ),
        AdminInsightItem(
            id="automation_signal",
            title="Automation signal",
            summary=(
                f"{auto_outbound_messages_7d} automated outbound messages in the last 7 days "
                f"({automation_rate:.1f}% of outbound traffic)."
            ),
            metrics={
                "outbound_messages_7d": outbound_messages_7d,
                "auto_outbound_messages_7d": auto_outbound_messages_7d,
                "automation_rate_7d": automation_rate,
                "unread_inbound_messages": unread_messages,
            },
        ),
        AdminInsightItem(
            id="maintenance_signal",
            title="Maintenance signal",
            summary=(
                f"{open_work_orders} open work orders, including {urgent_work_orders} urgent items."
            ),
            metrics={
                "open_work_orders": open_work_orders,
                "urgent_work_orders": urgent_work_orders,
                "top_open_categories": top_categories,
            },
        ),
    ]

    response.headers["Deprecation"] = "true"
    response.headers["X-Fortress-Admin-Insights-Contract"] = "derived"

    return AdminInsightsResponse(
        items=items[:limit],
        count=min(len(items), limit),
        requested_limit=limit,
        source_table_present=False,
        live_data_supported=True,
        status="derived_snapshot",
        message="Admin insights are served from a derived snapshot over core operational tables.",
        replacement_contract=_replacement_contract(),
    )
