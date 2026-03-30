from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api import ops as ops_api
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.staff import StaffRole
from backend.services.async_job_archive import archive_async_job_history


def _sample_row() -> SimpleNamespace:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        job_name="seo_grade",
        queue_name="fortress:arq",
        status="failed",
        requested_by=None,
        tenant_id=None,
        request_id=None,
        arq_job_id="j1",
        attempts=1,
        payload_json={},
        result_json={},
        error_text="boom",
        created_at=now,
        started_at=now,
        finished_at=now,
        updated_at=now,
    )


class DummyScalarResult:
    def __init__(self, value: list) -> None:
        self._value = value

    def scalars(self) -> DummyScalarResult:
        return self

    def all(self) -> list:
        return self._value


@pytest.mark.asyncio
async def test_archive_service_dry_run_rollbacks(tmp_path) -> None:
    row = _sample_row()
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [row]
    mock_db.execute = AsyncMock(return_value=exec_result)

    result = await archive_async_job_history(
        mock_db,
        older_than_minutes=1,
        limit=10,
        apply=False,
        output_path=tmp_path / "never.jsonl",
    )

    assert result.matched_rows == 1
    assert result.apply is False
    assert result.archived_rows == 0
    assert result.archive_path is None
    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_service_apply_writes_and_commits(tmp_path) -> None:
    row = _sample_row()
    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [row]
    mock_db.execute = AsyncMock(return_value=exec_result)
    out = tmp_path / "archive.jsonl"

    result = await archive_async_job_history(
        mock_db,
        older_than_minutes=1,
        limit=10,
        apply=True,
        output_path=out,
    )

    assert result.matched_rows == 1
    assert result.archived_rows == 1
    assert result.archive_path == str(out)
    assert out.exists()
    assert mock_db.execute.await_count == 2
    mock_db.commit.assert_awaited_once()
    mock_db.rollback.assert_not_awaited()


def _build_ops_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ops_api.router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_ops_archive_prune_forbidden_for_reviewer() -> None:
    app = _build_ops_app()

    async def override_get_db():
        class S:
            async def execute(self, _q):
                return DummyScalarResult([])

            async def rollback(self) -> None:
                pass

        yield S()

    async def override_user():
        return SimpleNamespace(
            id=uuid4(),
            email="r@example.com",
            role=StaffRole.REVIEWER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/system/ops/async-jobs/archive-prune",
            json={"apply": False},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ops_archive_prune_dry_run_ok_for_manager() -> None:
    app = _build_ops_app()

    async def override_get_db():
        class S:
            async def execute(self, _q):
                return DummyScalarResult([])

            async def rollback(self) -> None:
                pass

        yield S()

    async def override_user():
        return SimpleNamespace(
            id=uuid4(),
            email="m@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/system/ops/async-jobs/archive-prune",
            json={"older_than_minutes": 60, "limit": 100, "apply": False},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_rows"] == 0
    assert body["apply"] is False
    assert body["preview"] == []


@pytest.mark.asyncio
async def test_ops_archive_prune_validation_rejects_bad_limit() -> None:
    app = _build_ops_app()

    async def override_get_db():
        class S:
            async def execute(self, _q):
                return DummyScalarResult([])

            async def rollback(self) -> None:
                pass

        yield S()

    async def override_user():
        return SimpleNamespace(
            id=uuid4(),
            email="m@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/system/ops/async-jobs/archive-prune",
            json={"limit": 0, "apply": False},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 422
