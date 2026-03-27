from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.sql.sqltypes import DateTime, Numeric

from backend.models.treasury import CompetitorListing, OTAProvider


def test_competitor_listing_uses_uuid_fk_and_dense_fee_columns() -> None:
    columns = CompetitorListing.__table__.c

    assert isinstance(columns.property_id.type, PostgresUUID)
    assert any(fk.ondelete == "CASCADE" for fk in columns.property_id.foreign_keys)
    assert isinstance(columns.snapshot_payload.type, JSONB)
    assert isinstance(columns.observed_nightly_rate.type, Numeric)
    assert isinstance(columns.observed_total_before_tax.type, Numeric)
    assert isinstance(columns.platform_fee.type, Numeric)
    assert isinstance(columns.cleaning_fee.type, Numeric)
    assert isinstance(columns.total_after_tax.type, Numeric)
    assert isinstance(columns.last_observed.type, DateTime)
    assert columns.last_observed.type.timezone is True


def test_competitor_listing_has_dedupe_constraint_and_repr() -> None:
    constraint_names = {constraint.name for constraint in CompetitorListing.__table__.constraints}
    assert "uq_competitor_listings_dedupe_hash" in constraint_names

    listing = CompetitorListing(
        property_id="00000000-0000-0000-0000-000000000001",
        platform=OTAProvider.AIRBNB,
        dedupe_hash="abc123",
        observed_nightly_rate=199.0,
        observed_total_before_tax=299.0,
        platform_fee=25.0,
        cleaning_fee=50.0,
        total_after_tax=335.0,
    )

    assert "airbnb" in repr(listing)
