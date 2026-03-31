from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.api.ai_superpowers as ai_superpowers_api
from backend.core.security import get_current_user


def _user(role: str = "operator") -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": f"{role}@fortress.local",
        "role": role,
        "is_active": True,
    }


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ai_superpowers_api.router, prefix="/api/ai")

    async def override_current_user():
        return type("User", (), _user())()

    app.dependency_overrides[get_current_user] = override_current_user
    return app


@pytest.mark.asyncio
async def test_ask_endpoint_accepts_query_alias_and_returns_response_alias(monkeypatch) -> None:
    app = build_test_app()

    class FakeAnalytics:
        async def ask(self, question: str, context: dict | None):
            return {
                "question": question,
                "answer": f"Answer for {question}",
                "context": context,
            }

    monkeypatch.setattr(ai_superpowers_api, "analytics", FakeAnalytics())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/ai/ask",
            json={"query": "What changed?", "context": {"scope": "portfolio"}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "What changed?"
    assert payload["answer"] == "Answer for What changed?"
    assert payload["response"] == "Answer for What changed?"
    assert payload["context"] == {"scope": "portfolio"}


@pytest.mark.asyncio
async def test_optimize_listing_returns_suggestions_alias(monkeypatch) -> None:
    app = build_test_app()

    class FakeOptimizer:
        async def generate_description(
            self,
            property_name: str,
            bedrooms: int,
            bathrooms: float,
            max_guests: int,
            amenities: list[str],
            location: str,
        ):
            return {
                "property_name": property_name,
                "generated_description": f"{property_name} in {location}",
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "max_guests": max_guests,
                "amenities": amenities,
            }

    monkeypatch.setattr(ai_superpowers_api, "optimizer", FakeOptimizer())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/ai/optimize-listing",
            json={
                "property_name": "Sky Ridge",
                "bedrooms": 3,
                "bathrooms": 2.5,
                "max_guests": 8,
                "amenities": ["hot tub"],
                "location": "Blue Ridge, GA",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_description"] == "Sky Ridge in Blue Ridge, GA"
    assert payload["suggestions"] == "Sky Ridge in Blue Ridge, GA"


@pytest.mark.asyncio
async def test_predict_maintenance_returns_alerts_alias(monkeypatch) -> None:
    app = build_test_app()

    class FakeMaintenance:
        async def analyze_patterns(self, work_orders: list[dict], messages: list[dict]):
            return {
                "analysis": f"Reviewed {len(work_orders)} work orders and {len(messages)} messages",
                "work_orders_analyzed": len(work_orders),
            }

    monkeypatch.setattr(ai_superpowers_api, "maintenance", FakeMaintenance())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/ai/predict-maintenance",
            json={
                "work_orders": [{"id": 1}],
                "messages": [{"id": "m-1"}],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"] == "Reviewed 1 work orders and 1 messages"
    assert payload["alerts"] == ["Reviewed 1 work orders and 1 messages"]
