"""VRS C2 adjudication API contract tests."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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

import backend.api.vrs as vrs_api
from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin


def build_vrs_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(vrs_api.router, prefix="/api/vrs")
    return app


@pytest.fixture
def app() -> FastAPI:
    app = build_vrs_test_app()
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_user():
        return SimpleNamespace(
            id=uuid4(),
            email="operator@fortress.local",
            role="operator",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_operator_manager_admin] = override_user
    app.state.test_session = session
    return app


@pytest.mark.asyncio
async def test_list_vrs_queue_returns_held_items(app: FastAPI) -> None:
    fake_log = SimpleNamespace(
        id=uuid4(),
        session_id="sess-1",
        verdict_type="guest_resolve_conflict",
        created_at=None,
    )
    fake_item = {
        "id": str(fake_log.id),
        "session_id": "sess-1",
        "status": "held",
        "hold_reason": "below_send_threshold",
        "consensus_signal": "CAUTION",
        "consensus_conviction": 0.62,
    }

    result = MagicMock()
    result.scalars.return_value.all.return_value = [fake_log]
    app.state.test_session.execute = AsyncMock(return_value=result)

    with (
        patch("backend.api.vrs._dispatched_sessions", new=AsyncMock(return_value=set())),
        patch("backend.api.vrs._queue_item", new=AsyncMock(return_value=fake_item)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/vrs/queue")

    body = response.json()
    assert response.status_code == 200
    assert body["items"][0]["id"] == str(fake_log.id)
    assert body["summary"]["held"] == 1


@pytest.mark.asyncio
async def test_get_vrs_adjudication_returns_detail(app: FastAPI) -> None:
    adjudication_id = uuid4()
    fake_log = SimpleNamespace(id=adjudication_id, verdict_type="guest_resolve_conflict")
    fake_detail = {
        "id": str(adjudication_id),
        "status": "held",
        "draft_reply": "We are reviewing the issue now.",
        "council": {"opinions": []},
    }

    with (
        patch("backend.api.vrs._load_conflict_log", new=AsyncMock(return_value=fake_log)),
        patch("backend.api.vrs._detail_payload", new=AsyncMock(return_value=fake_detail)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/vrs/adjudications/{adjudication_id}")

    assert response.status_code == 200
    assert response.json()["draft_reply"] == "We are reviewing the issue now."


@pytest.mark.asyncio
async def test_override_vrs_dispatch_returns_dispatch_payload(app: FastAPI) -> None:
    adjudication_id = uuid4()
    guest_id = uuid4()
    fake_log = SimpleNamespace(
        id=adjudication_id,
        session_id="sess-override",
        verdict_type="guest_resolve_conflict",
        payload_json={"conflict_resolution": {"consensus_conviction": 0.62}},
    )
    fake_guest = SimpleNamespace(id=guest_id, phone_number="+17065551212")
    fake_dispatch = {"workflow": "guest_send_sms", "dispatched": True}
    fake_detail = {"id": str(adjudication_id), "draft_reply": "Draft override", "status": "held"}

    with (
        patch("backend.api.vrs._load_conflict_log", new=AsyncMock(return_value=fake_log)),
        patch("backend.api.vrs._dispatched_sessions", new=AsyncMock(return_value=set())),
        patch(
            "backend.api.vrs._resolve_context",
            new=AsyncMock(return_value=(fake_guest, None, None, None)),
        ),
        patch("backend.api.vrs._detail_payload", new=AsyncMock(return_value=fake_detail)),
        patch("backend.api.vrs.run_guest_send_sms", new=AsyncMock(return_value=fake_dispatch)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/adjudications/{adjudication_id}/override-dispatch",
                json={"body": "Dispatch this now.", "minimum_conviction": 0},
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dispatched"
    assert body["dispatch"]["workflow"] == "guest_send_sms"


@pytest.mark.asyncio
async def test_resolve_context_backfills_inbound_message_when_log_missing_message_id() -> None:
    guest = SimpleNamespace(id=uuid4())
    reservation = SimpleNamespace(id=uuid4(), guest_id=guest.id, property_id=uuid4())
    prop = SimpleNamespace(id=reservation.property_id)
    message = SimpleNamespace(
        id=uuid4(),
        guest_id=guest.id,
        reservation_id=reservation.id,
        body="The Wi-Fi is still unstable and I want a refund.",
        direction="inbound",
        status="received",
        created_at=None,
    )
    log = SimpleNamespace(
        guest_id=guest.id,
        reservation_id=reservation.id,
        property_id=prop.id,
        message_id=None,
        created_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[guest, reservation, prop])

    with patch("backend.api.vrs._find_anchor_message", new=AsyncMock(return_value=message)):
        resolved_guest, resolved_reservation, resolved_prop, resolved_message = await vrs_api._resolve_context(db, log)

    assert resolved_guest is guest
    assert resolved_reservation is reservation
    assert resolved_prop is prop
    assert resolved_message is message


def test_looks_like_test_artifact_flags_seed_and_e2e_markers() -> None:
    payload = {"seed_metadata": {"source": "cursor_seed"}}
    guest = SimpleNamespace(email="timberline-e2e@fortress-prime.local")
    reservation = SimpleNamespace(special_requests="[TARGETED E2E TEST] session=abc")
    message = SimpleNamespace(body="Verification probe from manage_concierge_pilot.py after arm.")

    assert vrs_api._looks_like_test_artifact(payload, guest, reservation, message) is True


def test_looks_like_test_artifact_allows_normal_guest_data() -> None:
    payload = {}
    guest = SimpleNamespace(email="guest@example.com")
    reservation = SimpleNamespace(special_requests="Please note allergy-friendly snacks.")
    message = SimpleNamespace(body="The Wi-Fi is unstable and I need help before checkout.")

    assert vrs_api._looks_like_test_artifact(payload, guest, reservation, message) is False
