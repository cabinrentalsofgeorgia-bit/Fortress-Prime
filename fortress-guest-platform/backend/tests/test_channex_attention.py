from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.channex_attention import (
    build_attention_fingerprint,
    build_attention_reasons,
    emit_channex_attention_signal_if_needed,
    get_latest_channex_attention_summary,
)
from backend.services.channex_health import ChannexHealthResponse


def _snapshot(**overrides) -> ChannexHealthResponse:
    base = {
        "property_count": 14,
        "healthy_count": 14,
        "shell_ready_count": 14,
        "catalog_ready_count": 14,
        "ari_ready_count": 14,
        "duplicate_rate_plan_count": 0,
        "properties": [],
    }
    base.update(overrides)
    return ChannexHealthResponse(**base)


def test_build_attention_reasons_empty_when_healthy() -> None:
    assert build_attention_reasons(_snapshot()) == []


@pytest.mark.asyncio
async def test_emit_attention_signal_publishes_when_snapshot_unhealthy() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])))
    snapshot = _snapshot(healthy_count=12, ari_ready_count=13, duplicate_rate_plan_count=2)

    with patch("backend.services.channex_attention.EventPublisher.publish", AsyncMock()) as publish_mock, patch(
        "backend.services.channex_attention.record_audit_event",
        AsyncMock(),
    ) as audit_mock, patch(
        "backend.services.channex_attention._notify_urgent_staff_of_channex_attention",
        AsyncMock(),
    ) as notify_mock:
        emitted = await emit_channex_attention_signal_if_needed(
            db,
            actor_id="admin-1",
            actor_email="admin@example.com",
            request_id="req-1",
            snapshot=snapshot,
        )

    assert emitted is True
    publish_mock.assert_awaited_once()
    audit_mock.assert_awaited_once()
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_attention_signal_skips_duplicate_fingerprint() -> None:
    fingerprint = build_attention_fingerprint(_snapshot(healthy_count=12))
    row = SimpleNamespace(metadata_json={"fingerprint": fingerprint})
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row])))

    with patch("backend.services.channex_attention.EventPublisher.publish", AsyncMock()) as publish_mock, patch(
        "backend.services.channex_attention.record_audit_event",
        AsyncMock(),
    ) as audit_mock, patch(
        "backend.services.channex_attention._notify_urgent_staff_of_channex_attention",
        AsyncMock(),
    ) as notify_mock:
        emitted = await emit_channex_attention_signal_if_needed(
            db,
            actor_id="admin-1",
            actor_email="admin@example.com",
            request_id="req-1",
            snapshot=_snapshot(healthy_count=12),
        )

    assert emitted is False
    publish_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()
    notify_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_latest_channex_attention_summary_returns_recent_event() -> None:
    row = SimpleNamespace(
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        request_id="req-1",
        metadata_json={
            "property_count": 14,
            "healthy_count": 12,
            "catalog_ready_count": 14,
            "ari_ready_count": 13,
            "duplicate_rate_plan_count": 2,
            "reasons": ["2 properties are not healthy", "2 duplicate rate plans detected"],
        },
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row)))

    summary = await get_latest_channex_attention_summary(db)

    assert summary is not None
    assert summary.recent is True
    assert summary.request_id == "req-1"
    assert summary.healthy_count == 12
    assert summary.duplicate_rate_plan_count == 2
