from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.services import scout_action_router as scout_action_router_module
from backend.services.scout_action_router import ResearchScoutActionRouter, ScoutActionRouter


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _DummySession:
    def __init__(self, rows):
        self._rows = rows
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def execute(self, _stmt):
        return _ScalarResult(self._rows)

    def begin_nested(self):
        @asynccontextmanager
        async def _ctx():
            yield

        return _ctx()


@pytest.mark.asyncio
async def test_route_inserted_findings_continues_after_entry_failure(monkeypatch) -> None:
    router = ResearchScoutActionRouter()
    property_id = uuid4()
    failing_entry = IntelligenceLedgerEntry(
        id=uuid4(),
        category="local_event",
        title="Blue Ridge rodeo event",
        summary="The event should fail during SEO draft creation.",
        market="Blue Ridge, Georgia",
        dedupe_hash="fail-entry",
        confidence_score=0.9,
        finding_payload={},
    )
    succeeding_entry = IntelligenceLedgerEntry(
        id=uuid4(),
        category="market_shift",
        title="Blue Ridge fishing demand shift",
        summary="The second entry should still route.",
        market="Blue Ridge, Georgia",
        dedupe_hash="success-entry",
        confidence_score=0.9,
        finding_payload={},
    )
    db = _DummySession([failing_entry, succeeding_entry])

    async def fake_load_property_context(_db):
        return [
            {
                "id": property_id,
                "name": "River Cabin",
                "slug": "river-cabin",
                "address": "Blue Ridge, Georgia",
                "max_guests": 8,
                "searchable_terms": {"blue ridge, georgia", "blue-ridge,-georgia", "fishing-nearby"},
            }
        ]

    async def fake_ensure_seo_drafts(_db, *, entry, property_ids, target_tags):
        if entry.id == failing_entry.id:
            raise RuntimeError("synthetic dispatch failure")
        return [{"property_id": str(property_ids[0]), "patch_id": "patch-1", "status": "drafted"}]

    async def fake_ensure_pricing_signal(_db, *, entry, property_ids, target_tags):
        return {"id": "queue-1", "status": "queued"}

    monkeypatch.setattr(router, "_load_property_context", fake_load_property_context)
    monkeypatch.setattr(router, "_ensure_seo_drafts", fake_ensure_seo_drafts)
    monkeypatch.setattr(router, "_ensure_pricing_signal", fake_ensure_pricing_signal)

    result = await router.route_inserted_findings(
        db,
        inserted_entry_ids=[str(failing_entry.id), str(succeeding_entry.id)],
    )

    assert result["routed_count"] == 1
    assert result["seo_draft_count"] == 1
    assert result["pricing_signal_count"] == 1
    assert result["items"][0]["entry_id"] == str(succeeding_entry.id)
    assert failing_entry.finding_payload.get("action_routed") is not True
    assert "routed_at" not in failing_entry.finding_payload
    assert succeeding_entry.finding_payload.get("action_routed") is True
    assert isinstance(succeeding_entry.finding_payload.get("routed_at"), str)
    assert succeeding_entry.target_property_ids == [str(property_id)]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_inserted_findings_preserves_seeded_target_property_ids(monkeypatch) -> None:
    router = ResearchScoutActionRouter()
    seeded_property_id = uuid4()
    fallback_property_id = uuid4()
    entry = IntelligenceLedgerEntry(
        id=uuid4(),
        category="local_event",
        title="Targeted cabin event",
        summary="Seeded property IDs must be preserved.",
        market="Blue Ridge, Georgia",
        dedupe_hash="seeded-entry",
        confidence_score=0.9,
        target_property_ids=[str(seeded_property_id)],
        finding_payload={},
    )
    db = _DummySession([entry])

    async def fake_load_property_context(_db):
        return [
            {
                "id": fallback_property_id,
                "name": "Fallback Cabin",
                "slug": "fallback-cabin",
                "address": "Blue Ridge, Georgia",
                "max_guests": 6,
                "searchable_terms": {"blue ridge, georgia", "event"},
            }
        ]

    async def fake_ensure_seo_drafts(_db, *, entry, property_ids, target_tags):
        return [{"property_id": str(property_ids[0]), "patch_id": "patch-seeded", "status": "drafted"}]

    match_properties = Mock(return_value=[fallback_property_id])

    monkeypatch.setattr(router, "_load_property_context", fake_load_property_context)
    monkeypatch.setattr(router, "_ensure_seo_drafts", fake_ensure_seo_drafts)
    monkeypatch.setattr(router, "_match_properties", match_properties)

    result = await router.route_inserted_findings(db, inserted_entry_ids=[str(entry.id)])

    assert result["routed_count"] == 1
    assert result["items"][0]["target_property_ids"] == [str(seeded_property_id)]
    assert entry.finding_payload.get("action_routed") is True
    assert isinstance(entry.finding_payload.get("routed_at"), str)
    assert entry.target_property_ids == [str(seeded_property_id)]
    match_properties.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_scout_action_router_delegates_to_instance_router(monkeypatch) -> None:
    finding_id = uuid4()
    route_inserted_findings = AsyncMock(return_value={"routed_count": 1})

    class _RouterSession:
        async def __aenter__(self):
            return "db-session"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        scout_action_router_module.research_scout_action_router,
        "route_inserted_findings",
        route_inserted_findings,
    )
    monkeypatch.setattr(
        scout_action_router_module,
        "async_session_maker",
        lambda: _RouterSession(),
    )

    result = await ScoutActionRouter.route_findings([finding_id])

    assert result == {"routed_count": 1}
    route_inserted_findings.assert_awaited_once_with(
        "db-session",
        inserted_entry_ids=[str(finding_id)],
    )

