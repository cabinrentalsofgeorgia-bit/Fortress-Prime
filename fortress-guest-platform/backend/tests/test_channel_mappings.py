"""
Integration tests for channel_mappings API and channel_adapters facade fix.

Tests:
1. channel_mappings table exists and is populated from migration backfill
2. CRUD endpoints: create, read, update, delete
3. AirbnbAdapter.push_availability raises NotImplementedError (no silent facade)
4. VrboAdapter.push_availability raises NotImplementedError
5. BookingComAdapter.push_availability raises NotImplementedError
6. ICalAdapter.generate_ical_feed still works (not a facade)
7. Channex credentials now available in settings
"""
from __future__ import annotations

import uuid
import pytest
import psycopg2
from decimal import Decimal
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()


# ── 1. DB: channel_mappings populated ────────────────────────────────────────

def test_channel_mappings_table_exists_and_populated():
    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM channel_mappings WHERE channel = 'channex'")
        count = cur.fetchone()[0]
        assert count == 14, (
            f"Expected 14 Channex mappings (one per active property), got {count}. "
            "Run: alembic upgrade d07f15298db8"
        )
        cur.execute(
            "SELECT COUNT(DISTINCT property_id) FROM channel_mappings WHERE sync_status = 'active'"
        )
        active = cur.fetchone()[0]
        assert active == 14, f"Expected 14 active mappings, got {active}"
    finally:
        conn.close()


def test_channel_mappings_all_have_real_uuids():
    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT slug, cm.external_listing_id "
            "FROM channel_mappings cm JOIN properties p ON p.id = cm.property_id "
            "WHERE cm.channel = 'channex'"
        )
        rows = cur.fetchall()
        for slug, ext_id in rows:
            assert ext_id and len(ext_id) == 36, (
                f"{slug}: external_listing_id {ext_id!r} is not a UUID"
            )
    finally:
        conn.close()


# ── 2. Facade adapters raise NotImplementedError ──────────────────────────────

@pytest.mark.asyncio
async def test_airbnb_adapter_push_availability_raises():
    from backend.integrations.channel_adapters import AirbnbAdapter
    adapter = AirbnbAdapter()
    with pytest.raises(NotImplementedError, match="(?i)airbnb"):
        await adapter.push_availability("prop-1", "listing-1", [{"date": "2026-06-01"}])


@pytest.mark.asyncio
async def test_airbnb_adapter_push_rates_raises():
    from backend.integrations.channel_adapters import AirbnbAdapter
    adapter = AirbnbAdapter()
    with pytest.raises(NotImplementedError, match="(?i)airbnb"):
        await adapter.push_rates("prop-1", "listing-1", [{"date": "2026-06-01", "rate": 199}])


@pytest.mark.asyncio
async def test_vrbo_adapter_push_availability_raises():
    from backend.integrations.channel_adapters import VrboAdapter
    adapter = VrboAdapter()
    with pytest.raises(NotImplementedError, match="(?i)vrbo"):
        await adapter.push_availability("prop-1", "listing-1", [{"date": "2026-06-01"}])


@pytest.mark.asyncio
async def test_booking_com_adapter_push_availability_raises():
    from backend.integrations.channel_adapters import BookingComAdapter
    adapter = BookingComAdapter()
    with pytest.raises(NotImplementedError, match="(?i)booking"):
        await adapter.push_availability("prop-1", "listing-1", [{"date": "2026-06-01"}])


# ── 3. iCal adapter still works ───────────────────────────────────────────────

def test_ical_adapter_generates_valid_feed():
    from backend.integrations.channel_adapters import ICalAdapter
    adapter = ICalAdapter()
    feed = adapter.generate_ical_feed(
        "Test Cabin",
        [{"check_in_date": "2026-06-01", "check_out_date": "2026-06-05",
          "confirmation_code": "TEST-001", "guest_name": "Jane Doe"}],
    )
    assert "BEGIN:VCALENDAR" in feed
    assert "BEGIN:VEVENT" in feed
    assert "TEST-001" in feed


# ── 4. Channex credentials now in settings ───────────────────────────────────

def test_channex_credentials_loaded_in_settings():
    import importlib, sys
    # Force reload to pick up freshly added .env values
    for mod in list(sys.modules.keys()):
        if "backend.core.config" in mod:
            del sys.modules[mod]
    from backend.core.config import settings
    assert settings.channex_api_base_url, "CHANNEX_API_BASE_URL must be set in .env"
    assert settings.channex_api_key, "CHANNEX_API_KEY must be set in .env"
    assert settings.channex_api_base_url.startswith("https://"), (
        f"CHANNEX_API_BASE_URL should start with https://, got: {settings.channex_api_base_url}"
    )


# ── 5. CRUD API: create → read → update → delete ─────────────────────────────

@pytest.mark.asyncio
async def test_channel_mapping_crud():
    from backend.core.database import AsyncSessionLocal
    from backend.models.channel_mapping import ChannelMapping
    from sqlalchemy import select

    # Use a real property_id from the DB
    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active = true LIMIT 1")
    property_id = cur.fetchone()[0]
    conn.close()

    test_channel = "ical"
    test_listing_id = f"test-ical-{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        # Create
        mapping = ChannelMapping(
            property_id=property_id,
            channel=test_channel,
            external_listing_id=test_listing_id,
            sync_status="pending",
        )
        db.add(mapping)
        await db.commit()
        mapping_id = mapping.id

        # Read
        fetched = (await db.execute(
            select(ChannelMapping).where(ChannelMapping.id == mapping_id)
        )).scalar_one()
        assert fetched.channel == test_channel
        assert fetched.external_listing_id == test_listing_id
        assert fetched.sync_status == "pending"

        # Update
        fetched.sync_status = "active"
        await db.commit()

        updated = await db.get(ChannelMapping, mapping_id)
        assert updated.sync_status == "active"

        # Delete
        await db.delete(updated)
        await db.commit()

        gone = await db.get(ChannelMapping, mapping_id)
        assert gone is None
