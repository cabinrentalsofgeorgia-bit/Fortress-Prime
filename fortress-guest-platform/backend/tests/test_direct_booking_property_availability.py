from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.direct_booking import router as direct_booking_router
from backend.core.database import get_db
from backend.services.property_availability_cache import build_property_availability_snapshot


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(direct_booking_router, prefix="/api/direct-booking")
    return app


class DummyResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_get_booking_property_includes_cached_availability() -> None:
    app = build_test_app()
    property_id = uuid.uuid4()
    availability = build_property_availability_snapshot(
        property_id=str(property_id),
        property_slug="ridge-line-lodge",
        blocked_ranges=[{"start_date": date(2026, 3, 10), "end_date": date(2026, 3, 12)}],
        generated_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        anchor_date=date(2026, 3, 24),
    )
    property_record = SimpleNamespace(
        id=property_id,
        name="Ridge Line Lodge",
        slug="ridge-line-lodge",
        property_type="cabin",
        bedrooms=3,
        bathrooms=2.5,
        max_guests=8,
        address="Blue Ridge, Georgia",
        parking_instructions="Use the upper gravel pad.",
        streamline_property_id="42",
        availability=availability,
        images=[],
        is_active=True,
    )

    class DummySession:
        async def execute(self, _query):
            return DummyResult(property_record)

    async def override_get_db():
        yield DummySession()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/direct-booking/property/ridge-line-lodge")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["property_id"] == str(property_id)
    assert payload["availability"]["property_slug"] == "ridge-line-lodge"
    assert payload["availability"]["blocked_dates"] == ["2026-03-10", "2026-03-11"]
