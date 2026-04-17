"""
Sovereign tax and fee ledgers for quote-time financial primitives.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.core.time import utc_now


class Tax(Base):
    __tablename__ = "taxes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    percentage_rate = Column(Numeric(6, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property_links = relationship(
        "PropertyTax",
        back_populates="tax",
        cascade="all, delete-orphan",
    )


class Fee(Base):
    __tablename__ = "fees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    flat_amount = Column(Numeric(12, 2), nullable=False, server_default="0")
    fee_type = Column(
        String(20), nullable=False, server_default="flat",
        doc="'flat' = flat_amount is the charge; 'percentage' = percentage_rate applied to pre-processing subtotal (rent + all flat fees)",
    )
    percentage_rate = Column(
        Numeric(6, 3), nullable=True,
        doc="Used when fee_type='percentage'. Rate in whole-number percent (e.g. 3.000 = 3%).",
    )
    is_pet_fee = Column(Boolean, nullable=False, default=False, server_default="false")
    is_optional = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property_links = relationship(
        "PropertyFee",
        back_populates="fee",
        cascade="all, delete-orphan",
    )


class PropertyTax(Base):
    __tablename__ = "property_taxes"
    __table_args__ = (
        UniqueConstraint("property_id", "tax_id", name="uq_property_taxes_property_tax"),
        Index("ix_property_taxes_property_id", "property_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    tax_id = Column(
        UUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property = relationship("Property", back_populates="tax_links")
    tax = relationship("Tax", back_populates="property_links")


class PropertyFee(Base):
    __tablename__ = "property_fees"
    __table_args__ = (
        UniqueConstraint("property_id", "fee_id", name="uq_property_fees_property_fee"),
        Index("ix_property_fees_property_id", "property_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    fee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("fees.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    property = relationship("Property", back_populates="fee_links")
    fee = relationship("Fee", back_populates="property_links")
