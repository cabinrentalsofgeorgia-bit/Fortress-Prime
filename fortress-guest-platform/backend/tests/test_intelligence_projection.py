from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.intelligence_projection import router as intelligence_projection_router
from backend.core.database import get_db
from backend.services.intelligence_projection import load_scout_alpha_metrics


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(intelligence_projection_router, prefix="/api/intelligence/projection")
    return app


class DummyScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalars(self) -> "DummyScalarResult":
        return self

    def all(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_property_context_projection_returns_targeted_findings() -> None:
    app = build_test_app()
    property_id = uuid4()
    property_record = SimpleNamespace(
        id=property_id,
        slug="ridge-line-lodge",
        name="Ridge Line Lodge",
        is_active=True,
    )
    entries = [
        SimpleNamespace(
            id=uuid4(),
            category="market_shift",
            title="Fly Fishing Festival draws spring demand",
            summary="Angler traffic is spiking along the Toccoa corridor this weekend.",
            market="Blue Ridge, Georgia",
            locality="Blue Ridge",
            confidence_score=0.91,
            query_topic="market_shift",
            source_urls=["https://example.com/festival"],
            target_tags=["fishing-nearby", "river-access"],
            discovered_at=datetime(2026, 3, 24, 17, 26, tzinfo=timezone.utc),
        )
    ]

    class DummySession:
        def __init__(self) -> None:
            self._results = iter(
                [
                    DummyScalarResult(property_record),
                    DummyScalarResult(entries),
                ]
            )

        async def execute(self, _query):
            return next(self._results)

    async def override_get_db():
        yield DummySession()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/intelligence/projection/property/ridge-line-lodge")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["property_slug"] == "ridge-line-lodge"
    assert payload["items"][0]["title"] == "Fly Fishing Festival draws spring demand"
    assert payload["items"][0]["target_tags"] == ["fishing-nearby", "river-access"]


@pytest.mark.asyncio
async def test_load_scout_alpha_metrics_counts_insight_impressions() -> None:
    property_id = uuid4()
    scout_entry_id = uuid4()
    now = datetime.now(timezone.utc)
    scout_patch = SimpleNamespace(
        property_id=property_id,
        source_intelligence_id=scout_entry_id,
        deploy_status="succeeded",
        status="pending_human",
        godhead_score=92.0,
        created_at=now,
    )
    recent_entry = SimpleNamespace(
        id=scout_entry_id,
        category="market_shift",
        target_property_ids=[str(property_id)],
        discovered_at=now,
    )
    property_row = SimpleNamespace(id=property_id, slug="ridge-line-lodge")
    event_rows = [
        SimpleNamespace(property_slug="ridge-line-lodge", event_type="insight_impression"),
        SimpleNamespace(property_slug="ridge-line-lodge", event_type="funnel_hold_started"),
        SimpleNamespace(property_slug="ridge-line-lodge", event_type="quote_open"),
    ]
    scout_entry = SimpleNamespace(id=scout_entry_id, category="market_shift")

    class DummySession:
        def __init__(self) -> None:
            self._results = iter(
                [
                    DummyScalarResult([scout_patch]),
                    DummyScalarResult([recent_entry]),
                    DummyScalarResult([property_row]),
                    DummyScalarResult(event_rows),
                    DummyScalarResult([scout_entry]),
                ]
            )

        async def execute(self, _query):
            return next(self._results)

    metrics = await load_scout_alpha_metrics(DummySession())

    assert metrics["scout_patch_count"] == 1
    assert metrics["scout_hold_started_count"] == 1
    assert metrics["scout_insight_impression_count"] == 1
