from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.admin_insights import router as admin_insights_router
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_insights_router, prefix="/api/admin")
    return app


class DummyScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar(self):
        return self._value

    def all(self):
        return self._value


@pytest.mark.asyncio
async def test_admin_insights_returns_replacement_contract() -> None:
    app = build_test_app()

    class DummySession:
        def __init__(self) -> None:
            self._results = iter(
                [
                    DummyScalarResult(5),  # total_properties
                    DummyScalarResult(3),  # active_reservations
                    DummyScalarResult(18450.25),  # revenue_mtd
                    DummyScalarResult(4),  # open_work_orders
                    DummyScalarResult(7),  # unread_messages
                    DummyScalarResult(22),  # outbound_messages_7d
                    DummyScalarResult(11),  # auto_outbound_messages_7d
                    DummyScalarResult(1),  # urgent_work_orders
                    DummyScalarResult(
                        [
                            ("2026-03", 11250.0, 9),
                            ("2026-02", 9800.0, 7),
                        ]
                    ),
                    DummyScalarResult(
                        [
                            ("hvac", 2),
                            ("plumbing", 1),
                        ]
                    ),
                ]
            )

        async def execute(self, _query):
            return next(self._results)

    async def override_get_db():
        yield DummySession()

    async def override_user():
        return object()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_manager_or_admin] = override_user
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/insights", params={"limit": 7})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["X-Fortress-Admin-Insights-Contract"] == "derived"

    payload = response.json()
    assert payload["count"] == 4
    assert payload["requested_limit"] == 7
    assert payload["source_table_present"] is False
    assert payload["live_data_supported"] is True
    assert payload["status"] == "derived_snapshot"
    assert payload["items"][0] == {
        "id": "operational_overview",
        "title": "Operational overview",
        "summary": "3 active stays across 5 active properties, 4 open work orders, and 7 unread inbound messages.",
        "metrics": {
            "active_properties": 5,
            "active_reservations": 3,
            "occupancy_rate": 60.0,
            "open_work_orders": 4,
            "urgent_work_orders": 1,
            "unread_messages": 7,
            "revenue_mtd": 18450.25,
        },
    }
    assert payload["items"][1]["metrics"]["months"] == [
        {
            "month": "2026-03",
            "revenue": 11250.0,
            "reservation_count": 9,
        },
        {
            "month": "2026-02",
            "revenue": 9800.0,
            "reservation_count": 7,
        },
    ]
    assert payload["items"][2]["metrics"] == {
        "outbound_messages_7d": 22,
        "auto_outbound_messages_7d": 11,
        "automation_rate_7d": 50.0,
        "unread_inbound_messages": 7,
    }
    assert payload["items"][3]["metrics"]["top_open_categories"] == [
        {"category": "hvac", "count": 2},
        {"category": "plumbing", "count": 1},
    ]
    assert payload["replacement_contract"]["type"] == "derived_core_tables"
    assert payload["replacement_contract"]["supported_endpoints"] == [
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
    assert payload["replacement_contract"]["dashboard_routes"] == ["/analytics/insights"]
    assert payload["replacement_contract"]["source_tables"] == [
        "properties",
        "reservations",
        "messages",
        "work_orders",
    ]
    assert payload["replacement_contract"]["notes"] == [
        "No checked-in ai_insights table exists in backend models or Alembic migrations.",
        "Insights are derived from existing operational tables instead of a dedicated ai_insights ledger.",
        "Use the listed AI capability endpoints for supported live behavior.",
    ]


@pytest.mark.asyncio
async def test_admin_insights_requires_manager_or_admin() -> None:
    app = build_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/insights")

    assert response.status_code == 401
