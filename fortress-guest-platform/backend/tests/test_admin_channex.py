from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
import backend.api.admin_channex as admin_channex_api
import backend.services.channex_sync as channex_sync
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.services.channex_sync import (
    ChannexSyncInventoryRequest,
    ChannexSyncInventoryResponse,
    ChannexSyncResult,
    _PropertyMetadataHint,
    build_property_shell_payload,
    _parse_address,
    sync_inventory_to_channex,
)
from backend.services.channex_remediation import ChannexRemediationResponse


def _prop(
    *,
    name: str,
    slug: str,
    listing_id: str | None = None,
):
    ota_metadata = {"channex_listing_id": listing_id} if listing_id else {}
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        slug=slug,
        ota_metadata=ota_metadata,
        address="123 Ridge Rd, Blue Ridge, GA 30513",
    )


def test_parse_address_keeps_single_line_street_and_default_city() -> None:
    parsed = _parse_address("638 Bell Camp Ridge")

    assert parsed["address"] == "638 Bell Camp Ridge"
    assert parsed["city"] == "Blue Ridge"
    assert parsed["state"] == "GA"
    assert parsed["zip_code"] == "30513"


def test_build_property_shell_payload_prefers_metadata_hint() -> None:
    prop = _prop(name="Skyfall", slug="skyfall")
    prop.address = "269 Big Valley Overlook"
    prop.latitude = "34.89351570"
    prop.longitude = "-84.13282070"

    payload = build_property_shell_payload(
        prop,
        metadata_hint=_PropertyMetadataHint(city="Morganton", state="GA", zip_code="30560"),
    )

    assert payload["property"]["title"] == "Skyfall"
    assert payload["property"]["address"] == "269 Big Valley Overlook"
    assert payload["property"]["city"] == "Morganton"
    assert payload["property"]["state"] == "GA"
    assert payload["property"]["zip_code"] == "30560"
    assert payload["property"]["latitude"] == "34.89351570"
    assert payload["property"]["longitude"] == "-84.13282070"


@pytest.mark.asyncio
async def test_admin_channex_sync_blocks_manager_role(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(admin_channex_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return SimpleNamespace(id=uuid4(), email="manager@example.com", role="manager")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    monkeypatch.setattr(
        admin_channex_api,
        "sync_inventory_to_channex",
        AsyncMock(
            return_value=ChannexSyncInventoryResponse(
                dry_run=True,
                scanned_count=0,
                created_count=0,
                mapped_count=0,
                failed_count=0,
                results=[],
            )
        ),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/admin/channex/sync-inventory", json={"dry_run": True})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_channex_health_returns_snapshot_for_admin(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(admin_channex_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return SimpleNamespace(id=uuid4(), email="admin@example.com", role="admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    monkeypatch.setattr(
        admin_channex_api,
        "channex_health_snapshot",
        AsyncMock(
            return_value={
                "property_count": 14,
                "healthy_count": 14,
                "shell_ready_count": 14,
                "catalog_ready_count": 14,
                "ari_ready_count": 14,
                "duplicate_rate_plan_count": 0,
                "properties": [],
            }
        ),
    )
    monkeypatch.setattr(
        admin_channex_api,
        "emit_channex_attention_signal_if_needed",
        AsyncMock(return_value=False),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/channex/health")

    assert response.status_code == 200
    assert response.json()["healthy_count"] == 14


@pytest.mark.asyncio
async def test_admin_channex_history_returns_items_for_admin(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(admin_channex_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return SimpleNamespace(id=uuid4(), email="admin@example.com", role="admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    monkeypatch.setattr(
        admin_channex_api,
        "get_channex_remediation_history",
        AsyncMock(
            return_value={
                "count": 1,
                "recent_success_count": 1,
                "recent_partial_failure_count": 0,
                "recent_remediated_property_count": 14,
                "recent_failed_property_count": 0,
                "last_run_at": "2026-03-30T00:00:00",
                "last_success_at": "2026-03-30T00:00:00",
                "items": [
                    {
                        "id": "hist-1",
                        "action": "admin.channex.remediate",
                        "outcome": "success",
                        "actor_email": "admin@example.com",
                        "created_at": "2026-03-30T00:00:00",
                        "request_id": "req-1",
                        "property_count": 14,
                        "remediated_count": 14,
                        "failed_count": 0,
                        "ari_window_days": 30,
                        "results": [],
                    }
                ],
            }
        ),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/channex/history?limit=5")

    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.asyncio
async def test_admin_channex_remediate_returns_snapshot_for_admin(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(admin_channex_api.router, prefix="/api/admin")
    session = AsyncMock()

    async def override_get_db():
        yield session

    async def override_current_user():
        return SimpleNamespace(id=uuid4(), email="admin@example.com", role="admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    monkeypatch.setattr(
        admin_channex_api,
        "remediate_channex_fleet",
        AsyncMock(
            return_value=ChannexRemediationResponse(
                property_count=14,
                remediated_count=14,
                failed_count=0,
                results=[],
            )
        ),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/admin/channex/remediate", json={"ari_window_days": 30})

    assert response.status_code == 200
    assert response.json()["remediated_count"] == 14


@pytest.mark.asyncio
async def test_sync_inventory_matches_existing_without_create_in_dry_run(monkeypatch) -> None:
    prop = _prop(name="Fallen Timber Lodge", slug="fallen-timber-lodge")
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.rollback = AsyncMock()

    monkeypatch.setattr(channex_sync, "_list_candidate_properties", AsyncMock(return_value=[prop]))
    monkeypatch.setattr(
        channex_sync,
        "_fetch_upstream_properties",
        AsyncMock(
            return_value=[
                channex_sync._UpstreamProperty(
                    listing_id="upstream-123",
                    title="Fallen Timber Lodge",
                    normalized_title=channex_sync.normalize_name("Fallen Timber Lodge"),
                )
            ]
        ),
    )
    create_mock = AsyncMock(return_value="created-should-not-run")
    persist_mock = AsyncMock()
    monkeypatch.setattr(channex_sync, "_create_upstream_property_shell", create_mock)
    monkeypatch.setattr(channex_sync, "_persist_channex_listing_id", persist_mock)

    response = await sync_inventory_to_channex(
        db,
        ChannexSyncInventoryRequest(dry_run=True),
    )

    assert response.mapped_count == 1
    assert response.created_count == 0
    assert response.failed_count == 0
    assert response.results[0].action == "would_map_existing"
    assert response.results[0].channex_listing_id == "upstream-123"
    create_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_inventory_creates_property_when_no_match(monkeypatch) -> None:
    prop = _prop(name="New Ridge Cabin", slug="new-ridge-cabin")
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.rollback = AsyncMock()

    monkeypatch.setattr(channex_sync, "_list_candidate_properties", AsyncMock(return_value=[prop]))
    monkeypatch.setattr(channex_sync, "_fetch_upstream_properties", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        channex_sync,
        "_create_upstream_property_shell",
        AsyncMock(return_value="created-456"),
    )
    persist_mock = AsyncMock()
    monkeypatch.setattr(channex_sync, "_persist_channex_listing_id", persist_mock)

    response = await sync_inventory_to_channex(
        db,
        ChannexSyncInventoryRequest(dry_run=False),
    )

    assert response.created_count == 1
    assert response.mapped_count == 0
    assert response.failed_count == 0
    assert response.results[0].action == "created_property"
    assert response.results[0].channex_listing_id == "created-456"
    persist_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_inventory_skips_already_mapped_property(monkeypatch) -> None:
    prop = _prop(
        name="Mapped Cabin",
        slug="mapped-cabin",
        listing_id="existing-789",
    )
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.rollback = AsyncMock()

    monkeypatch.setattr(channex_sync, "_list_candidate_properties", AsyncMock(return_value=[prop]))
    monkeypatch.setattr(channex_sync, "_fetch_upstream_properties", AsyncMock(return_value=[]))
    create_mock = AsyncMock()
    persist_mock = AsyncMock()
    monkeypatch.setattr(channex_sync, "_create_upstream_property_shell", create_mock)
    monkeypatch.setattr(channex_sync, "_persist_channex_listing_id", persist_mock)

    response = await sync_inventory_to_channex(
        db,
        ChannexSyncInventoryRequest(dry_run=False, property_ids=[str(prop.id)]),
    )

    assert response.scanned_count == 1
    assert response.created_count == 0
    assert response.mapped_count == 0
    assert response.failed_count == 0
    assert response.results[0] == ChannexSyncResult(
        property_id=str(prop.id),
        slug="mapped-cabin",
        property_name="Mapped Cabin",
        action="skipped_existing_mapping",
        channex_listing_id="existing-789",
        match_strategy="local_existing",
        error=None,
    )
    create_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()
