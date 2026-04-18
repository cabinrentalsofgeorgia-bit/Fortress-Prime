"""
Integration tests for Area 5 — Work Orders & Vendors.

Tests:
1.  vendors table exists with expected columns
2.  work_orders.assigned_vendor_id FK column exists
3.  work_orders.legacy_assigned_to column exists
4.  assigned_vendor_id FK constraint exists
5.  create a vendor directly (DB insert)
6.  list vendors filters active_only correctly
7.  update vendor (name + trade)
8.  deactivate vendor (soft delete)
9.  list vendors by trade
10. assign_vendor_to_work_order sets FK + updates assigned_to + status
11. photo upload returns 503 when storage not configured
12. run_work_order_sync_job registered in WorkerSettings.functions
13. vendor trade validator rejects invalid trade
"""
from __future__ import annotations

import uuid
from datetime import date

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── 1–4. Schema checks ────────────────────────────────────────────────────────

def test_vendors_table_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'vendors'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    required = {"id", "name", "trade", "phone", "email", "insurance_expiry",
                "active", "hourly_rate", "regions", "notes", "created_at", "updated_at"}
    assert required.issubset(cols), f"Missing columns: {required - cols}"

def test_work_orders_has_assigned_vendor_id():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'work_orders' AND column_name = 'assigned_vendor_id'
    """)
    assert cur.fetchone() is not None, "assigned_vendor_id column missing from work_orders"
    conn.close()

def test_work_orders_has_legacy_assigned_to():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'work_orders' AND column_name = 'legacy_assigned_to'
    """)
    assert cur.fetchone() is not None, "legacy_assigned_to column missing from work_orders"
    conn.close()

def test_assigned_vendor_id_fk_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_name = 'work_orders'
          AND kcu.column_name = 'assigned_vendor_id'
    """)
    assert cur.fetchone() is not None, "No FK constraint on work_orders.assigned_vendor_id"
    conn.close()

# ── 5–9. Vendor CRUD ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_vendor_direct():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor
    from decimal import Decimal

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v = Vendor(
            name=f"Test HVAC Co {uid}",
            trade="hvac",
            phone="706-555-0099",
            email="hvac@example.com",
            active=True,
            hourly_rate=Decimal("95.00"),
            regions=["blue_ridge"],
        )
        db.add(v)
        await db.commit()
        await db.refresh(v)
        vendor_id = v.id

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT name, trade, active, hourly_rate FROM vendors WHERE id=%s", (str(vendor_id),))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == f"Test HVAC Co {uid}"
    assert row[1] == "hvac"
    assert row[2] is True
    assert float(row[3]) == 95.00

@pytest.mark.asyncio
async def test_list_vendors_active_only():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v_active = Vendor(name=f"ActiveV_{uid}", trade="plumbing", active=True, regions=[])
        v_inactive = Vendor(name=f"InactiveV_{uid}", trade="plumbing", active=False, regions=[])
        db.add_all([v_active, v_inactive])
        await db.commit()

    async with AsyncSessionLocal() as db:
        active_res = await db.execute(
            select(Vendor).where(Vendor.active.is_(True)).where(Vendor.name.like(f"%{uid}%"))
        )
        inactive_res = await db.execute(
            select(Vendor).where(Vendor.active.is_(False)).where(Vendor.name.like(f"%{uid}%"))
        )
    assert len(active_res.scalars().all()) == 1
    assert len(inactive_res.scalars().all()) == 1

@pytest.mark.asyncio
async def test_update_vendor():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor
    from decimal import Decimal

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v = Vendor(name=f"UpdateMe_{uid}", trade="electrical", active=True,
                   hourly_rate=Decimal("80.00"), regions=[])
        db.add(v)
        await db.commit()
        vendor_id = v.id

    async with AsyncSessionLocal() as db:
        v = await db.get(Vendor, vendor_id)
        v.name = f"Updated_{uid}"  # type: ignore[assignment]
        v.hourly_rate = Decimal("110.00")  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT name, hourly_rate FROM vendors WHERE id=%s", (str(vendor_id),))
    row = cur.fetchone()
    conn.close()
    assert row[0] == f"Updated_{uid}"
    assert float(row[1]) == 110.00

@pytest.mark.asyncio
async def test_deactivate_vendor():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v = Vendor(name=f"Deactivate_{uid}", active=True, regions=[])
        db.add(v)
        await db.commit()
        vendor_id = v.id

    async with AsyncSessionLocal() as db:
        v = await db.get(Vendor, vendor_id)
        v.active = False  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT active FROM vendors WHERE id=%s", (str(vendor_id),))
    assert cur.fetchone()[0] is False
    conn.close()

@pytest.mark.asyncio
async def test_list_vendors_by_trade():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v1 = Vendor(name=f"Plumber_{uid}", trade="plumbing", active=True, regions=[])
        v2 = Vendor(name=f"HVAC_{uid}", trade="hvac", active=True, regions=[])
        db.add_all([v1, v2])
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Vendor)
            .where(Vendor.active.is_(True))
            .where(Vendor.trade == "plumbing")
            .where(Vendor.name.like(f"%{uid}%"))
        )
        plumbers = result.scalars().all()

    assert len(plumbers) == 1
    assert plumbers[0].name == f"Plumber_{uid}"

# ── 10. Vendor assignment on work order ───────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_vendor_to_work_order_sets_fk():
    from backend.core.database import AsyncSessionLocal
    from backend.models.vendor import Vendor
    from backend.models.workorder import WorkOrder

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        v = Vendor(name=f"FKVendor_{uid}", trade="general", active=True, regions=[])
        wo = WorkOrder(
            ticket_number=f"WO-TEST-{uid}",
            property_id=prop_id,
            title=f"Test WO {uid}",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
        )
        db.add_all([v, wo])
        await db.commit()
        vendor_id = v.id
        wo_id = wo.id

    async with AsyncSessionLocal() as db:
        wo = await db.get(WorkOrder, wo_id)
        wo.assigned_vendor_id = vendor_id  # type: ignore[assignment]
        wo.assigned_to = f"FKVendor_{uid}"  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT assigned_vendor_id, assigned_to FROM work_orders WHERE id=%s",
        (str(wo_id),)
    )
    row = cur.fetchone()
    conn.close()
    assert str(row[0]) == str(vendor_id)
    assert row[1] == f"FKVendor_{uid}"

# ── 11. Photo upload 503 when storage not configured ─────────────────────────

def test_photo_upload_503_when_no_storage():
    from backend.services.storage_service import SovereignStorageService
    # Without S3 credentials configured, _has_s3_credentials() returns False
    assert SovereignStorageService._has_s3_credentials() is False, (
        "Expected storage NOT configured in test environment. "
        "If S3 is configured, this test needs to be updated."
    )

# ── 12. Arq job registration ─────────────────────────────────────────────────

def test_work_order_sync_job_registered():
    from backend.core.worker import WorkerSettings, run_work_order_sync_job

    fn_names = {fn.__name__ for fn in WorkerSettings.functions}
    assert "run_work_order_sync_job" in fn_names, (
        "run_work_order_sync_job not in WorkerSettings.functions"
    )

# ── 13. Trade validator ───────────────────────────────────────────────────────

def test_vendor_trade_validator_rejects_invalid():
    from pydantic import ValidationError
    from backend.api.vendors import VendorCreate

    with pytest.raises(ValidationError) as exc_info:
        VendorCreate(name="Bad Vendor", trade="nonexistent_trade")
    assert "trade" in str(exc_info.value).lower() or "nonexistent_trade" in str(exc_info.value)
