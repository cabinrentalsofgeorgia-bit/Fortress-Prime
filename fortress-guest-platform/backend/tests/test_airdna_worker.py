from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import backend.core.worker as worker


@pytest.mark.asyncio
async def test_run_airdna_sync_job_delegates_to_service(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_airdna_sync(db, payload):
        assert payload.market == "Fannin County, Georgia"
        assert payload.dry_run is True
        return {"signals_seen": 2, "signals_created": 1}

    async def fake_with_job(job_id, job_try, runner):
        assert job_id == "job-123"
        assert job_try == 2
        return await runner(AsyncMock(), type("Job", (), {"payload_json": {"market": "Fannin County, Georgia", "dry_run": True}})())

    monkeypatch.setattr(worker, "run_airdna_sync", fake_run_airdna_sync)
    monkeypatch.setattr(worker, "_with_job", fake_with_job)

    result = await worker.run_airdna_sync_job({"job_try": 2}, "job-123")

    assert result == {"airdna_sync": {"signals_seen": 2, "signals_created": 1}}
