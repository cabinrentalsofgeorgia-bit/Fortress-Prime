from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.models.acquisition import (
    AcquisitionIntelEvent,
    AcquisitionOwner,
    AcquisitionParcel,
    AcquisitionPipeline,
    AcquisitionProperty,
    AcquisitionSTRSignal,
    FunnelStage,
    MarketState,
    SignalSource,
)
from backend.services.acquisition_advisory import _serialize_property_context


def test_serialize_property_context_includes_recent_str_signals() -> None:
    prop = AcquisitionProperty(
        id=uuid4(),
        status=MarketState.UNMANAGED,
        management_company=None,
        bedrooms=2,
        bathrooms=Decimal("1.5"),
        projected_adr=Decimal("250.00"),
        projected_annual_revenue=Decimal("80000.00"),
    )
    prop.parcel = AcquisitionParcel(
        id=uuid4(),
        parcel_id="0036 011C",
        county_name="Fannin",
        assessed_value=Decimal("1042878.00"),
        is_waterfront=False,
        is_ridgeline=False,
    )
    prop.owner = AcquisitionOwner(
        id=uuid4(),
        legal_name="Owner One",
        tax_mailing_address="123 Main St, Blue Ridge, GA 30513",
        primary_residence_state="GA",
        psychological_profile={"angle": "Property Pride"},
    )
    prop.pipeline = AcquisitionPipeline(
        id=uuid4(),
        stage=FunnelStage.TARGET_LOCKED,
        llm_viability_score=Decimal("0.88"),
        next_action_date=date(2026, 4, 1),
        rejection_reason=None,
    )
    prop.intel_events = [
        AcquisitionIntelEvent(
            id=uuid4(),
            event_type="QPUBLIC_SYNC",
            event_description="Parcel synced",
            raw_source_data={},
            detected_at=datetime.now(timezone.utc),
        )
    ]
    prop.str_signals = [
        AcquisitionSTRSignal(
            id=uuid4(),
            signal_source=SignalSource.FOIA_CSV,
            confidence_score=Decimal("1.00"),
            raw_payload={"source": "foia"},
            detected_at=datetime.now(timezone.utc),
        )
    ]

    payload = _serialize_property_context(prop)

    assert payload["recent_str_signals"][0]["signal_source"] == "foia_csv"
    assert payload["recent_str_signals"][0]["confidence_score"] == 1.0
