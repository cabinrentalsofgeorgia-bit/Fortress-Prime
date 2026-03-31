from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api import admin_acquisition_foia
from backend.core.database import get_db
from backend.core.security import require_admin


def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_acquisition_foia.router)
    app.state.arq_pool = AsyncMock()
    return app


@pytest.fixture
def app() -> FastAPI:
    app = build_app()

    async def override_get_db():
        yield AsyncMock()

    async def override_require_admin():
        return SimpleNamespace(id="user-1", email="admin@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = override_require_admin
    return app


@pytest.mark.asyncio
async def test_enqueue_fannin_foia_ingest_returns_async_job(app: FastAPI) -> None:
    fake_job = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        job_name="foia_fannin_str_ingest",
        queue_name="fortress:arq",
        status="queued",
        requested_by="admin@example.com",
        tenant_id=None,
        request_id="req-123",
        arq_job_id="11111111-1111-1111-1111-111111111111",
        attempts=0,
        payload_json={"filename": "fannin.csv"},
        result_json={},
        error_text=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )

    with (
        patch(
            "backend.api.admin_acquisition_foia.enqueue_async_job",
            new=AsyncMock(return_value=fake_job),
        ),
        patch(
            "backend.api.admin_acquisition_foia.record_audit_event",
            new=AsyncMock(return_value=None),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingest/foia/fannin-str",
                data={"dry_run": "true", "county_name": "Fannin"},
                files={"upload": ("fannin.csv", b"parcel_id,owner\n001,Owner One\n", "text/csv")},
            )

    body = response.json()
    assert response.status_code == 202
    assert body["job_name"] == "foia_fannin_str_ingest"
    assert body["status"] == "queued"
