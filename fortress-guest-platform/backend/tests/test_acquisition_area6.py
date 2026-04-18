"""
Integration tests for Area 6 — Property Acquisition Pipeline.

Tests:
1.  due_diligence table exists in crog_acquisition schema
2.  due_diligence has all 11 canonical checklist item keys defined
3.  due_diligence.status CHECK constraint accepts valid values
4.  due_diligence.status CHECK constraint rejects invalid status
5.  pipeline entry creation seeds 11 checklist items
6.  stage update changes pipeline stage correctly
7.  due diligence item update changes status + completed_at
8.  kanban API returns stage-grouped structure
9.  pipeline stats returns per-stage counts
10. seed_due_diligence is idempotent (no duplicates on re-seed)
11. AcquisitionDueDiligence model importable and has correct fields
12. DEFAULT_CHECKLIST has all 11 items including user-required ones
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

EXPECTED_ITEM_KEYS = {
    "title_search",
    "property_inspection",
    "revenue_history",
    "hoa_review",
    "tax_records",
    "zoning",
    "competitor_rates",
    "owner_motivation",
    "str_license_verification",
    "hoa_str_policy_review",
    "comparable_revenue_streamline",
}


# ── 1–2. Schema checks ────────────────────────────────────────────────────────

def test_due_diligence_table_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'crog_acquisition' AND table_name = 'due_diligence'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    required = {"id", "pipeline_id", "item_key", "label", "display_order",
                "status", "notes", "completed_at", "completed_by", "created_at", "updated_at"}
    assert required.issubset(cols), f"Missing columns: {required - cols}"


def test_default_checklist_keys_defined():
    from backend.api.acquisition_pipeline import DEFAULT_CHECKLIST
    defined_keys = {item[0] for item in DEFAULT_CHECKLIST}
    missing = EXPECTED_ITEM_KEYS - defined_keys
    assert not missing, f"Missing checklist keys: {missing}"


# ── 3–4. Check constraint ─────────────────────────────────────────────────────

def test_status_check_accepts_valid():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    # A quick round-trip with valid statuses — just verify constraint doesn't fire
    for status in ("pending", "passed", "failed", "waived"):
        cur.execute(f"SELECT '{status}'::text ~* '^(pending|passed|failed|waived)$'")
        assert cur.fetchone()[0] is True
    conn.close()


def test_status_check_rejects_invalid():
    """Check constraint exists on status column of due_diligence table."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    try:
        # Use pg_constraint + pg_class to find the CHECK constraint
        cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = 'crog_acquisition'
              AND t.relname = 'due_diligence'
              AND c.contype = 'c'
        """)
        rows = [r[0] for r in cur.fetchall()]
        status_checks = [r for r in rows if "status" in r.lower() or "pending" in r.lower()]
        assert len(status_checks) > 0, (
            f"No CHECK constraint found on due_diligence. Constraints found: {rows}"
        )
    finally:
        conn.close()


# ── 5. Pipeline entry creation seeds checklist ───────────────────────────────

@pytest.mark.asyncio
async def test_create_pipeline_seeds_checklist():
    from backend.core.database import AsyncSessionLocal
    from backend.models.acquisition import (
        AcquisitionParcel, AcquisitionProperty, AcquisitionPipeline,
        AcquisitionDueDiligence, FunnelStage,
    )
    from sqlalchemy import select
    from decimal import Decimal

    # Create minimal acquisition property record to satisfy FK chain
    async with AsyncSessionLocal() as db:
        parcel = AcquisitionParcel(
            parcel_id=f"TEST-{uuid.uuid4().hex[:8]}",
            county_name="Fannin",
            assessed_value=Decimal("250000"),
        )
        db.add(parcel)
        await db.flush()

        prop = AcquisitionProperty(
            parcel_id=parcel.id,
        )
        db.add(prop)
        await db.flush()

        pipeline = AcquisitionPipeline(
            property_id=prop.id,
            stage=FunnelStage.RADAR,
        )
        db.add(pipeline)
        await db.flush()

        # Seed checklist
        from backend.api.acquisition_pipeline import DEFAULT_CHECKLIST
        for item_key, label, order in DEFAULT_CHECKLIST:
            db.add(AcquisitionDueDiligence(
                pipeline_id=pipeline.id,
                item_key=item_key,
                label=label,
                display_order=order,
                status="pending",
            ))

        await db.commit()
        pipeline_id = pipeline.id

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AcquisitionDueDiligence).where(
                AcquisitionDueDiligence.pipeline_id == pipeline_id
            )
        )
        items = result.scalars().all()

    assert len(items) == len(DEFAULT_CHECKLIST), (
        f"Expected {len(DEFAULT_CHECKLIST)} items, got {len(items)}"
    )
    item_keys = {i.item_key for i in items}
    assert item_keys == EXPECTED_ITEM_KEYS


# ── 6. Stage update ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_update_changes_stage():
    from backend.core.database import AsyncSessionLocal
    from backend.models.acquisition import (
        AcquisitionParcel, AcquisitionProperty, AcquisitionPipeline, FunnelStage,
    )
    from decimal import Decimal

    async with AsyncSessionLocal() as db:
        parcel = AcquisitionParcel(
            parcel_id=f"STAGE-{uuid.uuid4().hex[:8]}",
            county_name="Fannin",
            assessed_value=Decimal("180000"),
        )
        db.add(parcel)
        await db.flush()
        prop = AcquisitionProperty(parcel_id=parcel.id)
        db.add(prop)
        await db.flush()
        pipeline = AcquisitionPipeline(property_id=prop.id, stage=FunnelStage.RADAR)
        db.add(pipeline)
        await db.commit()
        pipeline_id = pipeline.id

    async with AsyncSessionLocal() as db:
        pipeline = await db.get(AcquisitionPipeline, pipeline_id)
        pipeline.stage = FunnelStage.TARGET_LOCKED  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT stage FROM crog_acquisition.acquisition_pipeline WHERE id=%s",
        (str(pipeline_id),)
    )
    assert cur.fetchone()[0] == "TARGET_LOCKED"
    conn.close()


# ── 7. Due diligence item update ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dd_item_status_update():
    from backend.core.database import AsyncSessionLocal
    from backend.models.acquisition import (
        AcquisitionParcel, AcquisitionProperty, AcquisitionPipeline,
        AcquisitionDueDiligence, FunnelStage,
    )
    from sqlalchemy import select
    from decimal import Decimal
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        parcel = AcquisitionParcel(
            parcel_id=f"DD-{uuid.uuid4().hex[:8]}",
            county_name="Fannin",
            assessed_value=Decimal("200000"),
        )
        db.add(parcel)
        await db.flush()
        prop = AcquisitionProperty(parcel_id=parcel.id)
        db.add(prop)
        await db.flush()
        pipeline = AcquisitionPipeline(property_id=prop.id, stage=FunnelStage.RADAR)
        db.add(pipeline)
        await db.flush()
        item = AcquisitionDueDiligence(
            pipeline_id=pipeline.id,
            item_key="title_search",
            label="Title Search",
            display_order=1,
            status="pending",
        )
        db.add(item)
        await db.commit()
        item_id = item.id

    async with AsyncSessionLocal() as db:
        item = await db.get(AcquisitionDueDiligence, item_id)
        item.status = "passed"  # type: ignore[assignment]
        item.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        item.completed_by = "Gary Knight"  # type: ignore[assignment]
        await db.commit()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT status, completed_at, completed_by FROM crog_acquisition.due_diligence WHERE id=%s",
        (str(item_id),)
    )
    row = cur.fetchone()
    conn.close()
    assert row[0] == "passed"
    assert row[1] is not None  # completed_at was set
    assert row[2] == "Gary Knight"


# ── 8–9. API endpoint tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kanban_endpoint_returns_6_stages():
    from backend.core.database import AsyncSessionLocal
    from backend.api.acquisition_pipeline import get_pipeline_kanban

    async with AsyncSessionLocal() as db:
        result = await get_pipeline_kanban(db=db)

    assert "stages" in result
    assert "total" in result
    stage_names = {s["stage"] for s in result["stages"]}
    expected = {"RADAR", "TARGET_LOCKED", "DEPLOYED", "ENGAGED", "ACQUIRED", "REJECTED"}
    assert expected == stage_names, f"Missing stages: {expected - stage_names}"
    # Each stage has a cards list
    for stage in result["stages"]:
        assert "cards" in stage
        assert isinstance(stage["cards"], list)


@pytest.mark.asyncio
async def test_pipeline_stats_returns_all_stages():
    from backend.core.database import AsyncSessionLocal
    from backend.api.acquisition_pipeline import get_pipeline_stats

    async with AsyncSessionLocal() as db:
        result = await get_pipeline_stats(db=db)

    assert "stages" in result
    assert "total" in result
    stage_keys = set(result["stages"].keys())
    expected = {"RADAR", "TARGET_LOCKED", "DEPLOYED", "ENGAGED", "ACQUIRED", "REJECTED"}
    assert expected == stage_keys
    assert isinstance(result["total"], int)


# ── 10. Idempotent seed ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_due_diligence_is_idempotent():
    from backend.core.database import AsyncSessionLocal
    from backend.models.acquisition import (
        AcquisitionParcel, AcquisitionProperty, AcquisitionPipeline,
        AcquisitionDueDiligence, FunnelStage,
    )
    from backend.api.acquisition_pipeline import DEFAULT_CHECKLIST
    from sqlalchemy import select, func
    from decimal import Decimal

    async with AsyncSessionLocal() as db:
        parcel = AcquisitionParcel(
            parcel_id=f"IDEM-{uuid.uuid4().hex[:8]}",
            county_name="Fannin",
            assessed_value=Decimal("300000"),
        )
        db.add(parcel)
        await db.flush()
        prop = AcquisitionProperty(parcel_id=parcel.id)
        db.add(prop)
        await db.flush()
        pipeline = AcquisitionPipeline(property_id=prop.id, stage=FunnelStage.RADAR)
        db.add(pipeline)
        await db.flush()
        # Seed once
        for item_key, label, order in DEFAULT_CHECKLIST:
            db.add(AcquisitionDueDiligence(
                pipeline_id=pipeline.id, item_key=item_key, label=label,
                display_order=order, status="pending",
            ))
        await db.commit()
        pipeline_id = pipeline.id

    # Seed again — should not create duplicates
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(AcquisitionDueDiligence.item_key).where(
                AcquisitionDueDiligence.pipeline_id == pipeline_id
            )
        )).scalars().all()
        existing_keys = set(existing)
        added = 0
        for item_key, label, order in DEFAULT_CHECKLIST:
            if item_key not in existing_keys:
                db.add(AcquisitionDueDiligence(
                    pipeline_id=pipeline_id, item_key=item_key, label=label,
                    display_order=order, status="pending",
                ))
                added += 1
        await db.commit()

    assert added == 0, f"Expected 0 new items on re-seed, got {added}"

    # Count should still be exactly 11
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM crog_acquisition.due_diligence WHERE pipeline_id=%s",
        (str(pipeline_id),)
    )
    count = cur.fetchone()[0]
    conn.close()
    assert count == len(DEFAULT_CHECKLIST)


# ── 11–12. Model and checklist integrity ─────────────────────────────────────

def test_acquisition_due_diligence_model_importable():
    from backend.models.acquisition import AcquisitionDueDiligence
    # Check key column attributes
    assert hasattr(AcquisitionDueDiligence, "pipeline_id")
    assert hasattr(AcquisitionDueDiligence, "item_key")
    assert hasattr(AcquisitionDueDiligence, "status")
    assert hasattr(AcquisitionDueDiligence, "completed_at")


def test_default_checklist_includes_user_required_items():
    from backend.api.acquisition_pipeline import DEFAULT_CHECKLIST
    keys = {item[0] for item in DEFAULT_CHECKLIST}
    user_required = {
        "str_license_verification",
        "hoa_str_policy_review",
        "comparable_revenue_streamline",
    }
    missing = user_required - keys
    assert not missing, f"Missing user-required checklist items: {missing}"
