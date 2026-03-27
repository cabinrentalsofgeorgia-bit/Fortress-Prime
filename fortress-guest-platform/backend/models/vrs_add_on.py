"""
Ancillary revenue ledger for deterministic add-on pricing.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DECIMAL,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    TIMESTAMP,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class VRSAddOnPricingModel(str, enum.Enum):
    FLAT_FEE = "flat_fee"
    PER_NIGHT = "per_night"
    PER_GUEST = "per_guest"


class VRSAddOnScope(str, enum.Enum):
    GLOBAL = "global"
    PROPERTY_SPECIFIC = "property_specific"


class VRSAddOn(Base):
    __tablename__ = "vrs_add_ons"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_vrs_add_ons_price_nonnegative"),
        CheckConstraint(
            "(scope = 'global' AND property_id IS NULL) OR "
            "(scope = 'property_specific' AND property_id IS NOT NULL)",
            name="ck_vrs_add_ons_scope_property_consistency",
        ),
        Index("ix_vrs_add_ons_is_active", "is_active"),
        Index("ix_vrs_add_ons_scope", "scope"),
        Index("ix_vrs_add_ons_property_id", "property_id"),
        Index(
            "ix_vrs_add_ons_active_scope_property",
            "is_active",
            "scope",
            "property_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    price = Column(DECIMAL(12, 2), nullable=False, default=Decimal("0.00"))
    pricing_model = Column(
        SQLEnum(
            VRSAddOnPricingModel,
            name="vrs_add_on_pricing_model",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    scope = Column(
        SQLEnum(
            VRSAddOnScope,
            name="vrs_add_on_scope",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        TIMESTAMP,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    property = relationship("Property", foreign_keys=[property_id])

    def __repr__(self) -> str:
        return f"<VRSAddOn id={self.id} name={self.name} scope={self.scope}>"
