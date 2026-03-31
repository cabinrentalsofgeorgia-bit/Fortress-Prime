from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
from backend.main import (
    COMMAND_CENTER_INGRESS,
    GlobalAuthMiddleware,
    INTERNAL_INGRESS_HEADER,
    INTERNAL_INGRESS_SIGNATURE_HEADER,
    settings,
)


def _user_payload() -> dict[str, str]:
    return {"sub": str(uuid4()), "role": "admin", "email": "ops@crog-ai.com"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(GlobalAuthMiddleware)

    @app.get("/api/internal/probe")
    async def probe():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_internal_route_rejects_public_storefront_host(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app()
    monkeypatch.setattr(settings, "frontend_url", "https://crog-ai.com")
    monkeypatch.setattr(settings, "command_center_url", "http://localhost:9800")
    monkeypatch.setattr(settings, "storefront_base_url", "https://cabin-rentals-of-georgia.com")
    monkeypatch.setattr(settings, "internal_api_token", "signed-secret")
    monkeypatch.setattr("backend.core.security.decode_token", lambda _token: _user_payload())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/internal/probe",
            headers={
                "Authorization": "Bearer test-token",
                "Host": "api.cabin-rentals-of-georgia.com",
                "X-Forwarded-Host": "api.cabin-rentals-of-georgia.com",
            },
        )

    assert response.status_code == 403
    assert response.json()["title"] == "Ingress Boundary Violation"


@pytest.mark.asyncio
async def test_internal_route_allows_crog_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app()
    monkeypatch.setattr(settings, "frontend_url", "https://crog-ai.com")
    monkeypatch.setattr(settings, "command_center_url", "http://localhost:9800")
    monkeypatch.setattr(settings, "storefront_base_url", "https://cabin-rentals-of-georgia.com")
    monkeypatch.setattr(settings, "internal_api_token", "signed-secret")
    monkeypatch.setattr("backend.core.security.decode_token", lambda _token: _user_payload())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/internal/probe",
            headers={
                "Authorization": "Bearer test-token",
                "Host": "api.crog-ai.com",
                "Origin": "https://crog-ai.com",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_internal_route_allows_signed_command_center_ingress(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app()
    monkeypatch.setattr(settings, "frontend_url", "https://crog-ai.com")
    monkeypatch.setattr(settings, "command_center_url", "http://localhost:9800")
    monkeypatch.setattr(settings, "storefront_base_url", "https://cabin-rentals-of-georgia.com")
    monkeypatch.setattr(settings, "internal_api_token", "signed-secret")
    monkeypatch.setattr("backend.core.security.decode_token", lambda _token: _user_payload())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/internal/probe",
            headers={
                "Authorization": "Bearer test-token",
                "Host": "127.0.0.1:8100",
                "X-Forwarded-Host": "api.crog-ai.com",
                INTERNAL_INGRESS_HEADER: COMMAND_CENTER_INGRESS,
                INTERNAL_INGRESS_SIGNATURE_HEADER: "signed-secret",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
