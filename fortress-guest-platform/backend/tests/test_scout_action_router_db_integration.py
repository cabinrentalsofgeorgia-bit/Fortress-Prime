from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.config import settings
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.property import Property
from backend.models.property_knowledge import PropertyKnowledge
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.models.staff import StaffUser
from backend.services import scout_action_router as scout_action_router_module
from backend.services.scout_action_router import ScoutActionRouter

_INTEGRATION_TABLES = [
    StaffUser.__table__,
    Property.__table__,
    PropertyKnowledge.__table__,
    IntelligenceLedgerEntry.__table__,
    SEORubric.__table__,
    SEOPatch.__table__,
]


@pytest_asyncio.fixture
async def isolated_session_maker(monkeypatch) -> async_sessionmaker[AsyncSession]:
    if not settings.postgres_api_uri:
        pytest.skip("POSTGRES_API_URI is not configured for isolated router integration tests.")

    schema_name = f"test_scout_router_{uuid.uuid4().hex}"
    base_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    translated_engine = base_engine.execution_options(schema_translate_map={None: schema_name})

    async with base_engine.begin() as conn:
        can_create_schema = (
            await conn.execute(
                text(
                    "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
                )
            )
        ).scalar_one()
        if not can_create_schema:
            pytest.skip("POSTGRES_API_URI user lacks CREATE privilege for isolated schema tests.")

    try:
        async with base_engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    except ProgrammingError as exc:
        await base_engine.dispose()
        if "permission denied" in str(exc).lower():
            pytest.skip("POSTGRES_API_URI user lacks CREATE privilege for isolated schema tests.")
        raise

    async with translated_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_INTEGRATION_TABLES))

    session_maker = async_sessionmaker(
        translated_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(scout_action_router_module, "async_session_maker", session_maker)

    try:
        yield session_maker
    finally:
        async with base_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await base_engine.dispose()


async def _seeded_seo_dispatch(
    db: AsyncSession,
    *,
    entry: IntelligenceLedgerEntry,
    property_ids: list[uuid.UUID],
    target_tags: list[str],
) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(Property.id, Property.slug).where(Property.id.in_(property_ids))
        )
    ).all()
    properties_by_id = {row.id: row.slug for row in rows}

    results: list[dict[str, str]] = []
    for property_id in property_ids:
        slug = properties_by_id.get(property_id)
        if slug is None:
            raise RuntimeError("synthetic missing property for router integration test")
        patch = SEOPatch(
            property_id=property_id,
            source_intelligence_id=entry.id,
            source_agent="integration_test",
            page_path=f"/cabins/{slug}",
            status="drafted",
            title=entry.title,
            meta_description=entry.summary,
            final_payload={
                "target_tags": target_tags,
            },
        )
        db.add(patch)
        await db.flush()
        results.append(
            {
                "property_id": str(property_id),
                "patch_id": str(patch.id),
                "status": patch.status,
            }
        )
    return results


@pytest.mark.asyncio
async def test_router_nested_transaction_continuity_in_isolated_schema(
    isolated_session_maker: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    async def fake_ensure_pricing_signal(_db, *, entry, property_ids, target_tags):
        return {"id": f"pricing-{entry.id}", "status": "queued"}

    monkeypatch.setattr(
        scout_action_router_module.research_scout_action_router,
        "_ensure_seo_drafts",
        _seeded_seo_dispatch,
    )
    monkeypatch.setattr(
        scout_action_router_module.research_scout_action_router,
        "_ensure_pricing_signal",
        fake_ensure_pricing_signal,
    )

    f1_id = uuid.uuid4()
    f2_id = uuid.uuid4()

    async with isolated_session_maker() as db:
        prop = Property(
            slug="nested-success-cabin",
            name="Success Cabin",
            property_type="cabin",
            bedrooms=3,
            bathrooms=2,
            max_guests=6,
        )
        db.add_all(
            [
                IntelligenceLedgerEntry(
                    id=f1_id,
                    category="local_event",
                    confidence_score=0.9,
                    title="Fail Row",
                    summary="Integrity failure target",
                    market="Blue Ridge, Georgia",
                    target_property_ids=[str(uuid.uuid4())],
                    finding_payload={},
                    dedupe_hash="fail_nested_1",
                ),
                prop,
            ]
        )
        await db.flush()
        db.add(
            IntelligenceLedgerEntry(
                id=f2_id,
                category="market_shift",
                confidence_score=0.9,
                title="Success Row",
                summary="Should survive the batch",
                market="Blue Ridge, Georgia",
                target_property_ids=[str(prop.id)],
                finding_payload={},
                dedupe_hash="success_nested_1",
            )
        )
        await db.commit()

    await ScoutActionRouter.route_findings([f1_id, f2_id])

    async with isolated_session_maker() as verify_db:
        f2 = (
            await verify_db.execute(
                select(IntelligenceLedgerEntry).where(IntelligenceLedgerEntry.id == f2_id)
            )
        ).scalar_one()
        assert f2.finding_payload.get("action_routed") is True
        assert "routed_at" in f2.finding_payload

        f1 = (
            await verify_db.execute(
                select(IntelligenceLedgerEntry).where(IntelligenceLedgerEntry.id == f1_id)
            )
        ).scalar_one()
        assert f1.finding_payload.get("action_routed") is None
        assert "routed_at" not in f1.finding_payload


@pytest.mark.asyncio
async def test_router_preserves_seeded_targets_in_isolated_schema(
    isolated_session_maker: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    async def fake_ensure_pricing_signal(_db, *, entry, property_ids, target_tags):
        return {"id": f"pricing-{entry.id}", "status": "queued"}

    monkeypatch.setattr(
        scout_action_router_module.research_scout_action_router,
        "_ensure_seo_drafts",
        _seeded_seo_dispatch,
    )
    monkeypatch.setattr(
        scout_action_router_module.research_scout_action_router,
        "_ensure_pricing_signal",
        fake_ensure_pricing_signal,
    )
    # Route findings opens its own session via async_session_maker; redirect it to
    # the isolated schema so patches are visible in the verify session below.
    monkeypatch.setattr(
        scout_action_router_module,
        "async_session_maker",
        isolated_session_maker,
    )

    fid = uuid.uuid4()
    seeded_property_id: uuid.UUID | None = None

    async with isolated_session_maker() as db:
        prop_seeded = Property(
            slug="seeded-cabin",
            name="Seeded Cabin",
            property_type="cabin",
            bedrooms=2,
            bathrooms=2,
            max_guests=4,
        )
        prop_unrelated = Property(
            slug="unrelated-cabin",
            name="Unrelated Cabin",
            property_type="cabin",
            bedrooms=4,
            bathrooms=3,
            max_guests=10,
        )
        db.add_all([prop_seeded, prop_unrelated])
        await db.flush()
        seeded_property_id = prop_seeded.id
        db.add(
            IntelligenceLedgerEntry(
                id=fid,
                # Use "content_gap" so _should_create_seo() returns True
                # (LOCAL_EVENT_TERMS don't match "Strict Target Test" title/summary)
                category="content_gap",
                confidence_score=0.9,
                title="Strict Target Test",
                summary="Only target the seeded ID",
                market="Blue Ridge, Georgia",
                target_property_ids=[str(prop_seeded.id)],
                finding_payload={},
                dedupe_hash="strict_target_1",
            )
        )
        await db.commit()

    await ScoutActionRouter.route_findings([fid])

    async with isolated_session_maker() as verify_db:
        patches = (
            await verify_db.execute(select(SEOPatch).where(SEOPatch.source_intelligence_id == fid))
        ).scalars().all()
        assert len(patches) == 1
        assert patches[0].property_id == seeded_property_id

        ledger_row = (
            await verify_db.execute(
                select(IntelligenceLedgerEntry).where(IntelligenceLedgerEntry.id == fid)
            )
        ).scalar_one()
        assert ledger_row.finding_payload.get("action_routed") is True
        assert "routed_at" in ledger_row.finding_payload
        assert ledger_row.target_property_ids == [str(seeded_property_id)]
