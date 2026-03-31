"""
Acquisition intelligence models for the CROG property acquisition division.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import UserDefinedType

from backend.core.database import Base

ACQUISITION_SCHEMA = "crog_acquisition"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeometryPolygon(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "GEOMETRY(POLYGON,4326)"


class MarketState(str, Enum):
    UNMANAGED = "UNMANAGED"
    CROG_MANAGED = "CROG_MANAGED"
    COMPETITOR_MANAGED = "COMPETITOR_MANAGED"
    FOR_SALE = "FOR_SALE"


class FunnelStage(str, Enum):
    RADAR = "RADAR"
    TARGET_LOCKED = "TARGET_LOCKED"
    DEPLOYED = "DEPLOYED"
    ENGAGED = "ENGAGED"
    ACQUIRED = "ACQUIRED"
    REJECTED = "REJECTED"


class SignalSource(str, Enum):
    FOIA_CSV = "foia_csv"
    OTA_FIRECRAWL_HEURISTIC = "ota_firecrawl_heuristic"
    AGGREGATOR_API = "aggregator_api"


market_state_enum = SqlEnum(
    MarketState,
    name="market_state",
    schema=ACQUISITION_SCHEMA,
)
funnel_stage_enum = SqlEnum(
    FunnelStage,
    name="funnel_stage",
    schema=ACQUISITION_SCHEMA,
)
signal_source_enum = SqlEnum(
    SignalSource,
    name="signal_source",
    schema=ACQUISITION_SCHEMA,
)


class AcquisitionParcel(Base):
    __tablename__ = "parcels"
    __table_args__ = (
        UniqueConstraint("parcel_id", name="uq_acquisition_parcels_parcel_id"),
        Index("idx_acquisition_parcels_geom", "geom", postgresql_using="gist"),
        Index("idx_acquisition_parcels_assessed", "assessed_value"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    county_name = Column(String(100), nullable=False, default="Fannin", server_default=text("'Fannin'"))
    parcel_id = Column(String(100), nullable=False)
    geom = Column(GeometryPolygon(), nullable=True)
    assessed_value = Column(Numeric(12, 2), nullable=False)
    zoning_code = Column(String(50), nullable=True)
    is_waterfront = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_ridgeline = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    properties = relationship("AcquisitionProperty", back_populates="parcel")


class AcquisitionOwner(Base):
    __tablename__ = "owners"
    __table_args__ = (
        Index("idx_acquisition_owners_legal_name", "legal_name"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    legal_name = Column(String(255), nullable=False)
    tax_mailing_address = Column(Text, nullable=False)
    primary_residence_state = Column(String(2), nullable=True)
    psychological_profile = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    contacts = relationship("AcquisitionOwnerContact", back_populates="owner", cascade="all, delete-orphan")
    properties = relationship("AcquisitionProperty", back_populates="owner")


class AcquisitionOwnerContact(Base):
    __tablename__ = "owner_contacts"
    __table_args__ = (
        UniqueConstraint("owner_id", "contact_value", name="uq_acquisition_owner_contacts_owner_value"),
        CheckConstraint(
            "contact_type IN ('CELL', 'LANDLINE', 'EMAIL')",
            name="ck_acquisition_owner_contacts_contact_type",
        ),
        CheckConstraint(
            "confidence_score >= 0.00 AND confidence_score <= 1.00",
            name="ck_acquisition_owner_contacts_confidence_score",
        ),
        Index("idx_acquisition_owner_contacts_owner", "owner_id"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.owners.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_type = Column(String(50), nullable=True)
    contact_value = Column(String(255), nullable=False)
    source = Column(String(100), nullable=True)
    confidence_score = Column(Numeric(3, 2), nullable=True)
    is_dnc = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    owner = relationship("AcquisitionOwner", back_populates="contacts")


class AcquisitionProperty(Base):
    __tablename__ = "properties"
    __table_args__ = (
        Index("idx_acquisition_properties_status", "status"),
        Index("idx_acquisition_properties_mgmt", "management_company"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    parcel_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.parcels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.owners.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    fannin_str_cert_id = Column(String(100), nullable=True, unique=True)
    blue_ridge_str_permit = Column(String(100), nullable=True, unique=True)
    zillow_zpid = Column(String(100), nullable=True, unique=True)
    google_place_id = Column(String(255), nullable=True, unique=True)
    airbnb_listing_id = Column(String(100), nullable=True, unique=True)
    vrbo_listing_id = Column(String(100), nullable=True, unique=True)

    status = Column(
        market_state_enum,
        nullable=False,
        default=MarketState.UNMANAGED,
        server_default=text(f"'{MarketState.UNMANAGED.value}'"),
    )
    management_company = Column(String(255), nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Numeric(3, 1), nullable=True)
    projected_adr = Column(Numeric(8, 2), nullable=True)
    projected_annual_revenue = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    parcel = relationship("AcquisitionParcel", back_populates="properties")
    owner = relationship("AcquisitionOwner", back_populates="properties")
    pipeline = relationship("AcquisitionPipeline", back_populates="property", uselist=False, cascade="all, delete-orphan")
    intel_events = relationship("AcquisitionIntelEvent", back_populates="property", cascade="all, delete-orphan")
    str_signals = relationship("AcquisitionSTRSignal", back_populates="property", cascade="all, delete-orphan")


class AcquisitionPipeline(Base):
    __tablename__ = "acquisition_pipeline"
    __table_args__ = (
        UniqueConstraint("property_id", name="uq_acquisition_pipeline_property_id"),
        Index("idx_acquisition_pipeline_stage", "stage"),
        Index("idx_acquisition_pipeline_next_action_date", "next_action_date"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage = Column(
        funnel_stage_enum,
        nullable=False,
        default=FunnelStage.RADAR,
        server_default=text(f"'{FunnelStage.RADAR.value}'"),
    )
    llm_viability_score = Column(Numeric(3, 2), nullable=True)
    lob_mail_sent_at = Column(DateTime(timezone=True), nullable=True)
    instantly_campaign_id = Column(String(255), nullable=True)
    vapi_call_status = Column(String(100), nullable=True)
    next_action_date = Column(Date, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    property = relationship("AcquisitionProperty", back_populates="pipeline")


class AcquisitionIntelEvent(Base):
    __tablename__ = "intel_events"
    __table_args__ = (
        Index("idx_acquisition_intel_property_time", "property_id", "detected_at"),
        Index("idx_acquisition_intel_event_type", "event_type"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(100), nullable=False)
    event_description = Column(Text, nullable=False)
    raw_source_data = Column(JSONB, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    property = relationship("AcquisitionProperty", back_populates="intel_events")


class AcquisitionSTRSignal(Base):
    __tablename__ = "str_signals"
    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0.00 AND confidence_score <= 1.00",
            name="ck_acquisition_str_signals_confidence_score",
        ),
        Index("idx_acquisition_str_signals_property", "property_id"),
        Index("idx_acquisition_str_signals_source", "signal_source"),
        Index("idx_acquisition_str_signals_detected_at", "detected_at"),
        {"schema": ACQUISITION_SCHEMA},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{ACQUISITION_SCHEMA}.properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_source = Column(signal_source_enum, nullable=False)
    confidence_score = Column(Numeric(3, 2), nullable=False)
    raw_payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    detected_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    property = relationship("AcquisitionProperty", back_populates="str_signals")


__all__ = [
    "ACQUISITION_SCHEMA",
    "AcquisitionIntelEvent",
    "AcquisitionOwner",
    "AcquisitionOwnerContact",
    "AcquisitionParcel",
    "AcquisitionPipeline",
    "AcquisitionProperty",
    "AcquisitionSTRSignal",
    "FunnelStage",
    "MarketState",
    "SignalSource",
]
