"""Authorization coverage for elevated backend routes."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ProgrammingError


def _install_stub_module(module_name: str, *class_names: str) -> None:
    module = types.ModuleType(module_name)
    for class_name in class_names:
        setattr(module, class_name, type(class_name, (), {}))
    sys.modules.setdefault(module_name, module)


_install_stub_module(
    "backend.models.financial_primitives",
    "Fee",
    "Tax",
    "PropertyTax",
    "PropertyFee",
)
_install_stub_module("backend.models.media", "PropertyImage")
_install_stub_module("backend.models.property_stay_restriction", "PropertyStayRestriction")
_install_stub_module("backend.models.pricing_override", "PricingOverride")
_install_stub_module("backend.models.openshell_audit", "OpenShellAuditLog")
_install_stub_module("backend.models.seo_redirect", "SeoRedirect")
_install_stub_module("backend.models.seo_redirect_remap", "SeoRedirectRemapQueue")
_install_stub_module("backend.models.async_job", "AsyncJobRun")
_install_stub_module(
    "backend.models.vrs_add_on",
    "VRSAddOn",
    "VRSAddOnPricingModel",
    "VRSAddOnScope",
)

import run  # noqa: F401
import backend.api.admin as admin_api
import backend.api.admin_insights as admin_insights_api
import backend.api.ai_superpowers as ai_superpowers_api
import backend.api.booking as booking_api
import backend.api.channel_mgr as channel_mgr_api
import backend.api.channels as channels_api
import backend.api.copilot_queue as copilot_queue_api
import backend.api.damage_claims as damage_claims_api
import backend.api.ediscovery as ediscovery_api
import backend.api.guests as guests_api
import backend.api.intelligence as intelligence_api
import backend.api.integrations as integrations_api
import backend.api.iot as iot_api
import backend.api.legal_hold as legal_hold_api
import backend.api.legal_cases as legal_cases_api
import backend.api.legal_council as legal_council_api
import backend.api.legal_counsel_dispatch as legal_counsel_dispatch_api
import backend.api.legal_discovery as legal_discovery_api
import backend.api.legal_docgen as legal_docgen_api
import backend.api.legal_graph as legal_graph_api
import backend.api.legal_strategy as legal_strategy_api
import backend.api.legal_sanctions as legal_sanctions_api
import backend.api.legal_tactical as legal_tactical_api
import backend.api.legal_deposition as legal_deposition_api
import backend.api.legal_agent as legal_agent_api
import backend.api.messages as messages_api
import backend.api.payments as payments_api
import backend.api.properties as properties_api
import backend.api.workorders as workorders_api
import backend.api.reservations as reservations_api
import backend.api.rule_engine as rule_engine_api
import backend.api.review_queue as review_queue_api
import backend.api.tenants as tenants_api
import backend.api.vault as vault_api
import backend.api.agent as agent_api
import backend.api.leads as leads_api
import backend.api.analytics as analytics_api
import backend.api.housekeeping as housekeeping_api
import backend.api.inspections as inspections_api
import backend.api.search as search_api
import backend.api.templates as templates_api
import backend.api.utilities as utilities_api
import backend.api.quotes as quotes_api
import backend.api.agreements as agreements_api
from backend.core.database import get_db
from backend.core.security import (
    get_current_user,
    require_admin,
    require_manager_or_admin,
)


def _user(role: str):
    return SimpleNamespace(
        id=uuid4(),
        email=f"{role}@fortress.local",
        role=role,
        is_active=True,
    )


def build_security_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin-only")
    async def admin_only(_user=Depends(require_admin)):
        return {"ok": True}

    @app.get("/manager-or-admin")
    async def manager_or_admin_only(_user=Depends(require_manager_or_admin)):
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_require_admin_allows_super_admin() -> None:
    app = build_security_test_app()

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-only")

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_require_manager_or_admin_allows_super_admin() -> None:
    app = build_security_test_app()

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/manager-or-admin")

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_require_admin_blocks_manager() -> None:
    app = build_security_test_app()

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-only")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_fleet_status_blocks_manager_role() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/fleet-status")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_god_mode_financials_allows_super_admin() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    def _result(value):
        result = MagicMock()
        result.scalar.return_value = value
        if isinstance(value, list):
            result.fetchall.return_value = value
        else:
            result.fetchall.return_value = []
        return result

    capital_call_row = SimpleNamespace(property_id="70224", operating_funds=-125.50)
    margin_row = SimpleNamespace(
        property_id="70224",
        entry_date=None,
        description="Margin capture",
        margin_captured=25.0,
    )
    trigger_row = SimpleNamespace(trigger_name="trg_verify_balance", event_manipulation="INSERT")
    markup_row = SimpleNamespace(
        property_id="70224",
        expense_category="ALL",
        markup_percentage=23.0,
        owner_funds=50.0,
        operating_funds=-125.50,
    )

    session.execute = AsyncMock(
        side_effect=[
            _result(125.0),               # total_overhead
            _result(75.0),                # total_ap
            _result([capital_call_row]),  # capital calls from trust_balance
            _result([margin_row]),        # recent margins
            _result([markup_row]),        # markup rules
            _result(12),                  # journal entry count
            _result(48),                  # journal line count
            _result([trigger_row]),       # trigger metadata
        ]
    )

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/god-mode/financials")

    assert response.status_code == 200
    payload = response.json()
    assert payload["global_metrics"]["properties_in_overdraft"] == 1
    assert payload["capital_calls_required"][0]["property_id"] == "70224"
    assert payload["iron_dome_health"]["balance_enforcement"] is True


@pytest.mark.asyncio
async def test_admin_insights_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(admin_insights_api.router, prefix="/api/admin")
    session = AsyncMock()

    def _scalar_result(value):
        result = MagicMock()
        result.scalar.return_value = value
        return result

    def _rows_result(rows):
        result = MagicMock()
        result.all.return_value = rows
        return result

    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(5),   # total_properties
            _scalar_result(2),   # active_reservations
            _scalar_result(1200),  # total_revenue_mtd
            _scalar_result(3),   # open_work_orders
            _scalar_result(4),   # unread_messages
            _scalar_result(10),  # outbound_messages_7d
            _scalar_result(6),   # auto_outbound_messages_7d
            _scalar_result(1),   # urgent_work_orders
            _rows_result([("2026-03", 3200, 8)]),  # revenue_rows
            _rows_result([("plumbing", 2)]),       # maintenance_rows
        ]
    )

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "derived_snapshot"
    assert payload["items"][1]["metrics"]["months"][0]["month"] == "2026-03"


@pytest.mark.asyncio
async def test_admin_pending_payments_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    class _FakeLoad:
        def selectinload(self, *_args, **_kwargs):
            return self

    class _FakeQuery:
        def where(self, *_args, **_kwargs):
            return self

        def options(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

    transport = ASGITransport(app=app)
    with (
        patch.object(admin_api, "selectinload", return_value=_FakeLoad()),
        patch.object(admin_api, "select", return_value=_FakeQuery()),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/admin/payments/pending")

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.asyncio
async def test_properties_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(properties_api.router, prefix="/api/properties")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/properties/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_guests_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(guests_api.router, prefix="/api/guests")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/guests/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_hold_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_hold_api.router, prefix="/api")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/legal-hold")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_cases_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_case_detail_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/demo-case")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_crm_overview_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/crm/overview")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenants_list_blocks_manager_role() -> None:
    app = FastAPI()
    app.include_router(tenants_api.router, prefix="/api/tenants")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tenants/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenants_list_allows_super_admin() -> None:
    app = FastAPI()
    app.include_router(tenants_api.router, prefix="/api/tenants")
    session = AsyncMock()
    row = MagicMock()
    row._mapping = {
        "id": uuid4(),
        "name": "Fortress Prime",
        "slug": "fortress-prime",
        "domain": "prime.example.com",
        "logo_url": None,
        "primary_color": "#111827",
        "timezone": "America/New_York",
        "plan": "starter",
        "max_properties": 25,
        "max_staff_users": 5,
        "is_active": True,
    }
    result = MagicMock()
    result.fetchall.return_value = [row]
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tenants/")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "fortress-prime"


@pytest.mark.asyncio
async def test_tenants_create_allows_super_admin() -> None:
    app = FastAPI()
    app.include_router(tenants_api.router, prefix="/api/tenants")
    session = AsyncMock()
    row = MagicMock()
    row._mapping = {
        "id": uuid4(),
        "name": "Fortress Prime",
        "slug": "fortress-prime",
        "domain": "prime.example.com",
        "logo_url": None,
        "primary_color": "#111827",
        "timezone": "America/New_York",
        "plan": "starter",
        "max_properties": 25,
        "max_staff_users": 5,
        "is_active": True,
    }
    existing = MagicMock()
    existing.fetchone.return_value = None
    inserted = MagicMock()
    inserted.fetchone.return_value = row
    session.execute = AsyncMock(side_effect=[existing, inserted])
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/tenants/",
            json={
                "name": "Fortress Prime",
                "slug": "fortress-prime",
                "domain": "prime.example.com",
                "timezone": "America/New_York",
                "plan": "starter",
            },
        )

    assert response.status_code == 201
    assert response.json()["slug"] == "fortress-prime"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reservations_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(reservations_api.router, prefix="/api/reservations")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/reservations/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_agent_stats_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(agent_api.router, prefix="/api/agent")
    session = AsyncMock()
    orchestrator_result = {"runs": 0, "success_rate": 0}

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    with patch.object(agent_api.orchestrator, "get_agent_stats", AsyncMock(return_value=orchestrator_result)):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agent/stats")

    assert response.status_code == 200
    assert response.json() == orchestrator_result


@pytest.mark.asyncio
async def test_review_queue_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(review_queue_api.router, prefix="/api/review-queue")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/review-queue/queue")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_copilot_queue_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(copilot_queue_api.router, prefix="/api/copilot-queue")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/copilot-queue/pending")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leads_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(leads_api.router, prefix="/api/leads")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/leads/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_workorders_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(workorders_api.router, prefix="/api/work-orders")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/work-orders/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_analytics_dashboard_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(analytics_api.router, prefix="/api/analytics")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/analytics/dashboard")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_housekeeping_today_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(housekeeping_api.router, prefix="/api/housekeeping")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/housekeeping/today")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_search_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(search_api.router, prefix="/api/search")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/search/", params={"q": "Blue"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_payments_search_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(payments_api.router, prefix="/api/payments")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/payments/search-reservations", params={"q": "AB"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_iot_twins_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(iot_api.router, prefix="/api/iot")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/iot/twins")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_channel_manager_status_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(channel_mgr_api.router, prefix="/api/channel-manager")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/channel-manager/status")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_channel_manager_mappings_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(channel_mgr_api.router, prefix="/api/channel-manager")
    session = AsyncMock()
    row = MagicMock()
    row._mapping = {
        "property_id": "prop-1",
        "channel": "airbnb",
        "listing_id": "listing-123",
        "is_active": True,
        "property_name": "Blue Ridge Lodge",
    }
    result = MagicMock()
    result.fetchall.return_value = [row]
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/channel-manager/mappings")

    assert response.status_code == 200
    assert response.json()[0]["channel"] == "airbnb"


@pytest.mark.asyncio
async def test_channel_manager_create_mapping_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(channel_mgr_api.router, prefix="/api/channel-manager")
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/channel-manager/mappings",
            json={
                "property_id": "prop-1",
                "channel": "vrbo",
                "listing_id": "listing-456",
                "is_active": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "created"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_channels_status_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(channels_api.router, prefix="/api/channels")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/channels/status/{uuid4()}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_booking_search_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(booking_api.router, prefix="/api/booking")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/booking/search",
            params={"check_in": "2026-04-10", "check_out": "2026-04-13", "guests": 2},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_damage_claims_stats_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(damage_claims_api.router, prefix="/api/damage-claims")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/damage-claims/stats")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_utilities_types_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(utilities_api.router, prefix="/api/utilities")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/utilities/types")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_quotes_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(quotes_api.router, prefix="/api/quotes")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/quotes/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_templates_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(templates_api.router, prefix="/api/templates")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/templates/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_inspections_summary_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(inspections_api.router, prefix="/api/inspections")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/inspections/summary")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_agreements_dashboard_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(agreements_api.router, prefix="/api/agreements")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/agreements/dashboard")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_vault_audit_log_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(vault_api.router, prefix="/api/vault")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/vault/audit-log")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ediscovery_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(ediscovery_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/discovery/extract",
            json={"entities": ["Generali"], "max_per_table": 10},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_integrations_status_blocks_manager_role() -> None:
    app = FastAPI()
    app.include_router(integrations_api.router, prefix="/api/integrations")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/integrations/streamline/status")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_rule_engine_list_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(rule_engine_api.router, prefix="/api/rules")
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/rules/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_messages_list_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(messages_api.router, prefix="/api/messages")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/messages/")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ai_superpowers_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(ai_superpowers_api.router, prefix="/api/ai")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/ai/ask", json={"question": "Revenue?"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_council_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_council_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/council/personas")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_intelligence_models_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(intelligence_api.router, prefix="/api/intelligence")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/intelligence/models")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_intelligence_shadow_board_approve_allows_manager_role() -> None:
    app = FastAPI()
    app.include_router(intelligence_api.router, prefix="/api/intelligence")
    session = AsyncMock()

    def _first_row(*values):
        result = MagicMock()
        result.first.return_value = values
        return result

    def _no_row():
        result = MagicMock()
        result.first.return_value = None
        return result

    session.execute = AsyncMock(
        side_effect=[
            _first_row("11111111-1111-1111-1111-111111111111"),  # property lookup
            _no_row(),                                           # base rate update miss
            _first_row("base-rate-id"),                          # base rate insert
            _no_row(),                                           # vrbo channel lookup miss
            _first_row("channel-vrbo"),                          # vrbo channel insert
            _no_row(),                                           # vrbo adjustment update miss
            _first_row("adj-vrbo"),                              # vrbo adjustment insert
            _no_row(),                                           # direct channel lookup miss
            _first_row("channel-direct"),                        # direct channel insert
            _no_row(),                                           # direct adjustment update miss
            _first_row("adj-direct"),                            # direct adjustment insert
        ]
    )
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    shadow_board = {
        "entries": [
            {
                "id": "entry-1",
                "status": "pending_review",
                "recommendation_json": {
                    "underperformers": [
                        {
                            "property_id": "prop-1",
                            "property_name": "Blue Ridge Lodge",
                            "recommended_base_rate": 250.0,
                            "date_start": "2026-04-01",
                            "date_end": "2026-04-03",
                        }
                    ]
                },
            }
        ]
    }

    async def _run_test():
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        transport = ASGITransport(app=app)
        with patch.object(intelligence_api, "_read_shadow_board", return_value=shadow_board), patch.object(
            intelligence_api, "_write_shadow_board"
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/intelligence/market-snapshot/shadow-board/entry-1/approve",
                    json={"actor": "manager@fortress.local"},
                )
        return response

    response = await _run_test()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["actuation"]["base_rate_count"] == 1
    assert payload["actuation"]["channel_adjustment_count"] == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_legal_tactical_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_tactical_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/demo-case/omni-search",
            json={"query": "Generali"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_graph_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_graph_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/demo-case/graph/snapshot")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_discovery_pack_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_discovery_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/demo-case/discovery/draft-pack",
            json={"local_rules_cap": 10},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_docgen_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_docgen_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/document/draft",
            json={"case_brief": "Example case brief for testing.", "consensus": {"consensus_signal": "TEST"}},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_strategy_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_strategy_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/strategy/chat",
            json={"message": "Analyze this", "case_brief": "Example case brief for testing."},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_counsel_dispatch_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_counsel_dispatch_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/counsel/dispatch/draft",
            json={"case_brief": "Example case brief for testing.", "consensus": {"consensus_signal": "TEST"}},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_sanctions_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_sanctions_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/internal/legal/cases/demo-case/sanctions/sweep")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_sanctions_batch_blocks_manager_role() -> None:
    app = FastAPI()
    app.include_router(legal_sanctions_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/internal/legal/sanctions/sweep/all")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_deposition_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_deposition_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/demo-case/deposition/kill-sheet",
            json={"deponent_entity": "Opposing Party"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_agent_blocks_owner_role() -> None:
    app = FastAPI()
    app.include_router(legal_agent_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("owner")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/demo-case/agent/mission",
            json={"strategic_objective": "Run a focused legal mission against this case."},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_prime_snapshot_blocks_operator_role() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("operator")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/prime/snapshot")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_prime_snapshot_allows_super_admin() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    def _result(value):
        result = MagicMock()
        result.scalar.return_value = value
        result.fetchall.return_value = []
        return result

    session.execute = AsyncMock(
        side_effect=[
            _result([]),   # accounts
            _result([]),   # timeline
            _result([]),   # recent journals
            _result([]),   # payout summary
            _result(0),    # today journal entries
            _result(0),    # total properties
            _result(0),    # active reservations
        ]
    )

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/prime/snapshot")

    assert response.status_code == 200
    assert response.json()["system_pulse"]["total_properties"] == 0


@pytest.mark.asyncio
async def test_admin_prime_snapshot_tolerates_missing_payout_ledger() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    def _result(value):
        result = MagicMock()
        result.scalar.return_value = value
        result.fetchall.return_value = []
        return result

    session.execute = AsyncMock(
        side_effect=[
            _result([]),   # accounts
            _result([]),   # timeline
            _result([]),   # recent journals
            ProgrammingError("stmt", {}, Exception("undefinedtable payout_ledger")),  # payout summary
            _result(0),    # today journal entries
            _result(0),    # total properties
            _result(0),    # active reservations
        ]
    )
    session.rollback = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("super_admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/prime/snapshot")

    assert response.status_code == 200
    assert response.json()["payout_summary"] == {}
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_onboard_owner_blocks_manager_role() -> None:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/onboard-owner",
            json={
                "owner_name": "Owner Example",
                "email": "owner@example.com",
                "sl_owner_id": "123",
                "property_ids": ["P1"],
                "owner_pct": 65,
                "pm_pct": 35,
                "markup_pct": 23,
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_extract_blocks_operator_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("operator")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/demo-case/extract",
            json={"target": "case", "text": "Example body for extraction."},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_deadline_review_blocks_reviewer_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("reviewer")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/internal/legal/deadlines/42",
            json={"review_status": "approved"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legal_deliberate_blocks_operator_role() -> None:
    app = FastAPI()
    app.include_router(legal_cases_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("operator")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/internal/legal/cases/demo-case/deliberate")

    assert response.status_code == 403
