"""
Phase G.0.7 — Auth regression test for GET /api/v1/admin/statements/{owner_id}.

Before the G.0.7 fix, admin_statements.py used `router = APIRouter()` with no
role dependency, meaning any valid staff JWT (including `staff` and `reviewer`)
could call the endpoint. The fix adds `require_manager_or_admin` at the router
level, consistent with all other Phase A-F statement endpoints.

Tests verify:
  1. No Authorization header        → 401
  2. staff role                     → 403
  3. manager role                   → 200 or 404 (auth passes, handler runs)
  4. super_admin role               → 200 or 404 (auth passes, handler runs)

Pattern: FastAPI test app + dependency_overrides, matching test_route_authorization.py.
No JWT signing, no real DB, no test fixtures needed.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.api.admin_statements as admin_statements_api
from backend.core.database import get_db
from backend.core.security import get_current_user

_TARGET_URL = "/api/v1/admin/statements/nonexistent-owner-99999"


def _user(role: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000099",
        email=f"{role}@fortress.local",
        role=role,
        is_active=True,
    )


def _build_app() -> FastAPI:
    """
    Minimal FastAPI app with only the admin_statements router mounted.

    The DB override returns an empty scalar result for every execute() call,
    which causes the handler to return 404 "No active properties found".
    This is sufficient to prove that auth passed and the handler ran —
    we do not need real owner data in the DB.
    """
    app = FastAPI()
    app.include_router(admin_statements_api.router, prefix="/api/v1/admin")

    async def _empty_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        yield mock_session

    app.dependency_overrides[get_db] = _empty_db
    return app


# ── Test 1: No Authorization header → 401 ────────────────────────────────────

@pytest.mark.asyncio
async def test_no_auth_header_returns_401() -> None:
    """
    No Authorization header → get_current_user raises 401 immediately.
    The role gate is never reached.
    """
    app = _build_app()
    # Intentionally do NOT override get_current_user.
    # bearer_scheme returns None when no Authorization header is present,
    # and get_current_user raises HTTP 401 in that case.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_TARGET_URL)

    assert response.status_code == 401, (
        f"Expected 401 for missing Authorization header, got {response.status_code}: {response.text}"
    )


# ── Test 2: staff role → 403 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_staff_role_returns_403() -> None:
    """
    staff role is not in require_manager_or_admin's allow-list
    (super_admin, admin, manager). Must return 403.
    """
    app = _build_app()

    async def _staff():
        return _user("staff")

    app.dependency_overrides[get_current_user] = _staff

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_TARGET_URL)

    assert response.status_code == 403, (
        f"Expected 403 for staff role, got {response.status_code}: {response.text}"
    )


# ── Test 3: manager role → 404 (auth passes, handler runs) ───────────────────

@pytest.mark.asyncio
async def test_manager_role_passes_auth() -> None:
    """
    manager role is in require_manager_or_admin's allow-list.
    Auth passes → handler runs → 404 because no properties exist for the owner.
    Either 200 or 404 proves the auth gate was cleared.
    """
    app = _build_app()

    async def _manager():
        return _user("manager")

    app.dependency_overrides[get_current_user] = _manager

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_TARGET_URL)

    assert response.status_code in (200, 404), (
        f"Expected 200 or 404 for manager role (auth pass), got {response.status_code}: {response.text}"
    )
    # Specifically not 403 — that would mean the role gate still fired.
    assert response.status_code != 403, "manager role must not receive 403"


# ── Test 4: super_admin role → 404 (auth passes, handler runs) ───────────────

@pytest.mark.asyncio
async def test_super_admin_role_passes_auth() -> None:
    """
    super_admin role is in require_manager_or_admin's allow-list.
    Auth passes → handler runs → 404 because no properties exist for the owner.
    """
    app = _build_app()

    async def _admin():
        return _user("super_admin")

    app.dependency_overrides[get_current_user] = _admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_TARGET_URL)

    assert response.status_code in (200, 404), (
        f"Expected 200 or 404 for super_admin role (auth pass), got {response.status_code}: {response.text}"
    )
    assert response.status_code != 403, "super_admin role must not receive 403"
