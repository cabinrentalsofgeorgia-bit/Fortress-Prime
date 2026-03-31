"""Reactivation Hunter API contract tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


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

import backend.api.hunter as hunter_api
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.core.security import require_operator_manager_admin


def build_hunter_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hunter_api.router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    app = build_hunter_test_app()
    session = AsyncMock()
    session.add = MagicMock()

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
    app.dependency_overrides[require_manager_or_admin] = override_user
    app.state.test_session = session
    return app


@pytest.mark.asyncio
async def test_get_reactivation_targets_returns_strict_payload(app: FastAPI) -> None:
    today = date.today()
    valid_guest = SimpleNamespace(
        id=uuid4(),
        full_name="Ada Lovelace",
        email="ada@example.com",
        lifetime_revenue=Decimal("12500.00"),
        last_stay_date=today - timedelta(days=420),
        lifetime_stays=4,
        total_stays=4,
        is_vip=True,
        opt_in_marketing=True,
    )
    blank_email_guest = SimpleNamespace(
        id=uuid4(),
        full_name="No Email",
        email="   ",
        lifetime_revenue=Decimal("9000.00"),
        last_stay_date=today - timedelta(days=400),
        lifetime_stays=2,
        total_stays=2,
        is_vip=False,
        opt_in_marketing=True,
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [valid_guest, blank_email_guest]
    app.state.test_session.execute = AsyncMock(return_value=result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/vrs/hunter/targets")

    body = response.json()
    assert response.status_code == 200
    assert len(body) == 1
    assert body[0]["guest_id"] == str(valid_guest.id)
    assert body[0]["full_name"] == "Ada Lovelace"
    assert body[0]["email"] == "ada@example.com"
    assert body[0]["lifetime_value"] == 12500.0
    assert body[0]["days_dormant"] == 420
    assert isinstance(body[0]["target_score"], int)
    assert body[0]["target_score"] > 0


def test_target_score_caps_at_100_for_extreme_profiles() -> None:
    guest = SimpleNamespace(
        is_vip=True,
        lifetime_stays=50,
        total_stays=50,
        opt_in_marketing=True,
    )

    score = hunter_api._target_score(guest, revenue=200000.0, days_dormant=1200)

    assert score == 100


@pytest.mark.asyncio
async def test_dispatch_reactivation_agent_queues_event(app: FastAPI) -> None:
    with (
        patch("backend.api.hunter.publish_vrs_event", new=AsyncMock(return_value=True)),
        patch("backend.api.hunter.queue_depth", new=AsyncMock(return_value=7)),
        patch("backend.api.hunter.record_audit_event", new=AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/vrs/hunter/dispatch",
                json={
                    "guest_id": str(uuid4()),
                    "full_name": "Ada Lovelace",
                    "target_score": 91,
                },
            )

    body = response.json()
    assert response.status_code == 202
    assert body["status"] == "queued"
    assert body["message"] == "Agent dispatched for Ada Lovelace"
    assert body["queue_depth"] == 7
    assert body["queue_key"] == "fortress:events:streamline"
    assert body["event_id"].startswith("hunter:")


@pytest.mark.asyncio
async def test_hunter_queue_stats_returns_status_counts(app: FastAPI) -> None:
    def _count(value: int) -> MagicMock:
        result = MagicMock()
        result.scalar.return_value = value
        return result

    app.state.test_session.execute = AsyncMock(
        side_effect=[
            _count(2),
            _count(3),
            _count(1),
            _count(4),
            _count(0),
            _count(0),
            _count(1),
        ]
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/vrs/hunter/queue/stats")

    body = response.json()
    assert response.status_code == 200
    assert body["pending_review"] == 2
    assert body["approved"] == 3
    assert body["edited"] == 1
    assert body["rejected"] == 4
    assert body["failed"] == 1
    assert body["total"] == 11


@pytest.mark.asyncio
async def test_edit_hunter_queue_entry_updates_status_and_message(app: FastAPI) -> None:
    queue_entry = SimpleNamespace(
        id=uuid4(),
        status="pending_review",
        final_human_message=None,
        original_ai_draft="Original Hunter draft.",
        guest=SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        prop=SimpleNamespace(name="Fallen Timber"),
        error_log=None,
    )
    app.state.test_session.commit = AsyncMock(return_value=None)

    with (
        patch("backend.api.hunter._load_agent_queue_entry", new=AsyncMock(return_value=queue_entry)),
        patch("backend.api.hunter._deliver_hunter_message", new=AsyncMock(return_value=(True, None))),
        patch("backend.api.hunter.record_audit_event", new=AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/hunter/queue/{queue_entry.id}/edit",
                json={"final_human_message": "Edited draft copy."},
            )

    body = response.json()
    assert response.status_code == 200
    assert queue_entry.status == "delivered"
    assert queue_entry.final_human_message == "Edited draft copy."
    assert body["status"] == "delivered"
    assert body["delivery_status"] == "sent"


@pytest.mark.asyncio
async def test_approve_hunter_queue_entry_marks_failed_when_delivery_fails(app: FastAPI) -> None:
    queue_entry = SimpleNamespace(
        id=uuid4(),
        status="pending_review",
        final_human_message=None,
        original_ai_draft="Original Hunter draft.",
        guest=SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        prop=SimpleNamespace(name="Fallen Timber"),
        error_log=None,
    )
    app.state.test_session.commit = AsyncMock(return_value=None)

    with (
        patch("backend.api.hunter._load_agent_queue_entry", new=AsyncMock(return_value=queue_entry)),
        patch(
            "backend.api.hunter._deliver_hunter_message",
            new=AsyncMock(return_value=(False, "SMTP is not configured.")),
        ),
        patch("backend.api.hunter.record_audit_event", new=AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/hunter/queue/{queue_entry.id}/approve",
                json={},
            )

    body = response.json()
    assert response.status_code == 200
    assert queue_entry.status == "failed"
    assert queue_entry.error_log == "SMTP is not configured."
    assert body["status"] == "failed"
    assert body["delivery_status"] == "failed"


@pytest.mark.asyncio
async def test_retry_hunter_queue_entry_retries_failed_delivery(app: FastAPI) -> None:
    queue_entry = SimpleNamespace(
        id=uuid4(),
        status="failed",
        final_human_message="Retry this Hunter message.",
        original_ai_draft="Original Hunter draft.",
        guest=SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        prop=SimpleNamespace(name="Fallen Timber"),
        error_log="SMTP is not configured.",
    )
    app.state.test_session.commit = AsyncMock(return_value=None)

    with (
        patch("backend.api.hunter._load_agent_queue_entry", new=AsyncMock(return_value=queue_entry)),
        patch("backend.api.hunter._deliver_hunter_message", new=AsyncMock(return_value=(True, None))),
        patch("backend.api.hunter.record_audit_event", new=AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/hunter/queue/{queue_entry.id}/retry",
                json={},
            )

    body = response.json()
    assert response.status_code == 200
    assert queue_entry.status == "delivered"
    assert body["status"] == "delivered"
    assert body["delivery_status"] == "sent"


@pytest.mark.asyncio
async def test_approve_hunter_queue_entry_can_send_via_sms(app: FastAPI) -> None:
    queue_entry = SimpleNamespace(
        id=uuid4(),
        status="pending_review",
        final_human_message=None,
        original_ai_draft="Original Hunter draft.",
        guest=SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        prop=SimpleNamespace(name="Fallen Timber"),
        error_log=None,
    )
    app.state.test_session.commit = AsyncMock(return_value=None)
    deliver_mock = AsyncMock(return_value=(True, None))

    with (
        patch("backend.api.hunter._load_agent_queue_entry", new=AsyncMock(return_value=queue_entry)),
        patch("backend.api.hunter._deliver_hunter_message", new=deliver_mock),
        patch("backend.api.hunter.record_audit_event", new=AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/hunter/queue/{queue_entry.id}/approve",
                json={"channel": "sms"},
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "delivered"
    assert body["delivery_channel"] == "sms"
    assert deliver_mock.await_args.args[3] == "sms"


@pytest.mark.asyncio
async def test_audit_hunter_console_event_returns_accepted(app: FastAPI) -> None:
    audit_mock = AsyncMock(return_value=None)
    with patch("backend.api.hunter.record_audit_event", new=audit_mock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/vrs/hunter/audit",
                json={
                    "event_name": "hunter.export.targets.csv",
                    "metadata_json": {"row_count": 12},
                },
            )

    body = response.json()
    assert response.status_code == 202
    assert body["status"] == "accepted"
    assert audit_mock.await_count == 1


@pytest.mark.asyncio
async def test_approve_hunter_queue_entry_emits_audit(app: FastAPI) -> None:
    queue_entry = SimpleNamespace(
        id=uuid4(),
        status="pending_review",
        guest_id=uuid4(),
        final_human_message=None,
        original_ai_draft="Original Hunter draft.",
        guest=SimpleNamespace(full_name="Ada Lovelace", email="ada@example.com"),
        prop=SimpleNamespace(name="Fallen Timber"),
        error_log=None,
    )
    app.state.test_session.commit = AsyncMock(return_value=None)
    audit_mock = AsyncMock(return_value=None)

    with (
        patch("backend.api.hunter._load_agent_queue_entry", new=AsyncMock(return_value=queue_entry)),
        patch("backend.api.hunter._deliver_hunter_message", new=AsyncMock(return_value=(True, None))),
        patch("backend.api.hunter.record_audit_event", new=audit_mock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/vrs/hunter/queue/{queue_entry.id}/approve",
                json={"channel": "email"},
            )

    assert response.status_code == 200
    assert audit_mock.await_count == 1
    assert audit_mock.await_args.kwargs["action"] == "hunter.queue.approve"
    assert audit_mock.await_args.kwargs["resource_id"] == str(queue_entry.id)
