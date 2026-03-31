"""Owner magic-link cookie policy regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
import backend.api.auth as auth_api
from backend.core.database import get_db


def _result(first=None, rows=None):
    result = MagicMock()
    result.fetchone.return_value = first
    result.fetchall.return_value = rows or []
    return result


def _build_app(session: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api/auth")

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_owner_verify_magic_link_uses_non_secure_cookie_on_localhost() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result(
                first=SimpleNamespace(
                    id=1,
                    sl_owner_id="146514",
                    owner_email="gary@cabin-rentals-of-georgia.com",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    used_at=None,
                )
            ),
            _result(),
            _result(rows=[SimpleNamespace(unit_id="70209", property_name="Fallen Timber Lodge")]),
        ]
    )
    app = _build_app(session)

    with patch.object(auth_api, "create_access_token", return_value="owner-token"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1:3001") as client:
            response = await client.post(
                "/api/auth/owner/verify-magic-link",
                json={"token": "raw-token"},
            )

    assert response.status_code == 200
    assert "fgp_owner_token=owner-token" in response.headers["set-cookie"]
    assert "Secure" not in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_owner_verify_magic_link_keeps_secure_cookie_on_non_local_host() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result(
                first=SimpleNamespace(
                    id=1,
                    sl_owner_id="146514",
                    owner_email="gary@cabin-rentals-of-georgia.com",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    used_at=None,
                )
            ),
            _result(),
            _result(rows=[SimpleNamespace(unit_id="70209", property_name="Fallen Timber Lodge")]),
        ]
    )
    app = _build_app(session)

    with (
        patch.object(auth_api, "create_access_token", return_value="owner-token"),
        patch.object(auth_api.settings, "environment", "production"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://crog-ai.com") as client:
            response = await client.post(
                "/api/auth/owner/verify-magic-link",
                json={"token": "raw-token"},
            )

    assert response.status_code == 200
    assert "fgp_owner_token=owner-token" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
