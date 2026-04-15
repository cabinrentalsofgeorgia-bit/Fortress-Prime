"""
Integration tests for Area 3 — Housekeeping Cleaner Management.

Tests:
1.  cleaners table exists and has expected columns
2.  housekeeping_tasks has assigned_cleaner_id FK column
3.  housekeeping_tasks has legacy_assigned_to column
4.  create a cleaner via API model (direct DB insert)
5.  list cleaners filters active_only correctly
6.  get cleaner by id
7.  update cleaner (patch name, per_clean_rate)
8.  deactivate cleaner (soft delete)
9.  list cleaners by property_id (JSONB contains)
10. assign_cleaner sets assigned_cleaner_id FK on task
11. assign_cleaner keeps legacy assigned_to in sync
12. CRUD round-trip: create → update → deactivate
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── 1. Schema checks ─────────────────────────────────────────────────────────

def test_cleaners_table_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'cleaners'
        ORDER BY ordinal_position
    """)
    rows = cur.fetchall()
    conn.close()
    col_names = {r[0] for r in rows}
    required = {"id", "name", "phone", "email", "active", "per_clean_rate",
                "hourly_rate", "property_ids", "regions", "notes", "created_at", "updated_at"}
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"

def test_housekeeping_tasks_has_assigned_cleaner_id():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'housekeeping_tasks' AND column_name = 'assigned_cleaner_id'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "assigned_cleaner_id column missing from housekeeping_tasks"

def test_housekeeping_tasks_has_legacy_assigned_to():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'housekeeping_tasks' AND column_name = 'legacy_assigned_to'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "legacy_assigned_to column missing from housekeeping_tasks"

def test_assigned_cleaner_id_has_fk():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_name = 'housekeeping_tasks'
          AND kcu.column_name = 'assigned_cleaner_id'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "No FK constraint on housekeeping_tasks.assigned_cleaner_id"

# ── 2. Cleaner CRUD (direct DB + service layer) ───────────────────────────────

@pytest.mark.asyncio
async def test_create_cleaner_direct():
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner

    name = f"Test Cleaner {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        c = Cleaner(
            name=name,
            phone="706-555-0001",
            email="cleaner@example.com",
            active=True,
            per_clean_rate=Decimal("125.00"),
            hourly_rate=Decimal("18.00"),
            property_ids=[],
            regions=["blue_ridge"],
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        cleaner_id = c.id

    # Verify in DB
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT name, active, per_clean_rate FROM cleaners WHERE id=%s", (str(cleaner_id),))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == name
    assert row[1] is True
    assert float(row[2]) == 125.00

@pytest.mark.asyncio
async def test_list_cleaners_active_only():
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c_active = Cleaner(name=f"Active_{uid}", active=True, property_ids=[], regions=[])
        c_inactive = Cleaner(name=f"Inactive_{uid}", active=False, property_ids=[], regions=[])
        db.add_all([c_active, c_inactive])
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Cleaner).where(Cleaner.active.is_(True)).where(
                Cleaner.name.like(f"%{uid}%")
            )
        )
        actives = result.scalars().all()
        result2 = await db.execute(
            select(Cleaner).where(Cleaner.active.is_(False)).where(
                Cleaner.name.like(f"%{uid}%")
            )
        )
        inactives = result2.scalars().all()

    assert len(actives) == 1
    assert len(inactives) == 1
    assert actives[0].name == f"Active_{uid}"

@pytest.mark.asyncio
async def test_update_cleaner():
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c = Cleaner(name=f"UpdateMe_{uid}", active=True, per_clean_rate=Decimal("100.00"),
                    property_ids=[], regions=[])
        db.add(c)
        await db.commit()
        cleaner_id = c.id

    async with AsyncSessionLocal() as db:
        c = await db.get(Cleaner, cleaner_id)
        c.name = f"Updated_{uid}"  # type: ignore[assignment]
        c.per_clean_rate = Decimal("150.00")  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT name, per_clean_rate FROM cleaners WHERE id=%s", (str(cleaner_id),))
    row = cur.fetchone()
    conn.close()
    assert row[0] == f"Updated_{uid}"
    assert float(row[1]) == 150.00

@pytest.mark.asyncio
async def test_deactivate_cleaner():
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner

    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c = Cleaner(name=f"Deactivate_{uid}", active=True, property_ids=[], regions=[])
        db.add(c)
        await db.commit()
        cleaner_id = c.id

    async with AsyncSessionLocal() as db:
        c = await db.get(Cleaner, cleaner_id)
        c.active = False  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT active FROM cleaners WHERE id=%s", (str(cleaner_id),))
    row = cur.fetchone()
    conn.close()
    assert row[0] is False

@pytest.mark.asyncio
async def test_list_cleaners_by_property_jsonb():
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner
    from sqlalchemy import select

    prop_id = str(uuid.uuid4())
    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c_assigned = Cleaner(
            name=f"Assigned_{uid}", active=True,
            property_ids=[prop_id], regions=[]
        )
        c_other = Cleaner(
            name=f"OtherProp_{uid}", active=True,
            property_ids=[str(uuid.uuid4())], regions=[]
        )
        db.add_all([c_assigned, c_other])
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Cleaner)
            .where(Cleaner.active.is_(True))
            .where(Cleaner.property_ids.contains([prop_id]))  # type: ignore[arg-type]
            .where(Cleaner.name.like(f"%{uid}%"))
        )
        found = result.scalars().all()

    assert len(found) == 1
    assert found[0].name == f"Assigned_{uid}"

# ── 3. HousekeepingService FK assignment ─────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_cleaner_sets_fk():
    """assign_cleaner with a cleaner_id sets assigned_cleaner_id on the task."""
    from backend.core.database import AsyncSessionLocal
    from backend.models.cleaner import Cleaner
    from backend.services.housekeeping_service import HousekeepingService, HousekeepingTask
    from datetime import date

    uid = uuid.uuid4().hex[:6]

    # Need a real property_id
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        # Create a cleaner
        c = Cleaner(name=f"FKCleaner_{uid}", active=True, property_ids=[], regions=[])
        db.add(c)
        # Create a task
        task = HousekeepingTask(
            property_id=prop_id,
            scheduled_date=date(2026, 12, 1),
            status="pending",
            cleaning_type="turnover",
        )
        db.add(task)
        await db.commit()
        cleaner_id = c.id
        task_id = task.id

    async with AsyncSessionLocal() as db:
        svc = HousekeepingService(db)
        updated = await svc.assign_cleaner(
            task_id, f"FKCleaner_{uid}", cleaner_id=cleaner_id
        )
        assert str(updated.assigned_cleaner_id) == str(cleaner_id)
        assert updated.assigned_to == f"FKCleaner_{uid}"
        await db.commit()

    # Verify in DB
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT assigned_cleaner_id, assigned_to FROM housekeeping_tasks WHERE id=%s",
        (str(task_id),)
    )
    row = cur.fetchone()
    conn.close()
    assert str(row[0]) == str(cleaner_id)
    assert row[1] == f"FKCleaner_{uid}"

@pytest.mark.asyncio
async def test_assign_cleaner_legacy_name_without_fk():
    """assign_cleaner without cleaner_id still writes assigned_to (legacy path)."""
    from backend.core.database import AsyncSessionLocal
    from backend.services.housekeeping_service import HousekeepingService, HousekeepingTask
    from datetime import date

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        task = HousekeepingTask(
            property_id=prop_id,
            scheduled_date=date(2026, 12, 2),
            status="pending",
            cleaning_type="turnover",
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    async with AsyncSessionLocal() as db:
        svc = HousekeepingService(db)
        updated = await svc.assign_cleaner(task_id, "Legacy Cleaner Name")
        assert updated.assigned_to == "Legacy Cleaner Name"
        assert updated.assigned_cleaner_id is None
        await db.commit()
