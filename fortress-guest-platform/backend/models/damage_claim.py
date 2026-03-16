"""
DamageClaim model - Post-checkout damage/violation reporting and legal response workflow
"""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, DECIMAL, Date, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class DamageClaim(Base):
    __tablename__ = "damage_claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    claim_number = Column(String(50), unique=True, nullable=False)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)

    damage_description = Column(Text, nullable=False)
    policy_violations = Column(Text)
    damage_areas = Column(ARRAY(Text))
    estimated_cost = Column(DECIMAL(10, 2))
    photo_urls = Column(ARRAY(Text))

    reported_by = Column(String(200), nullable=False, default="staff")
    inspection_date = Column(Date, nullable=False, default=date.today)
    inspection_notes = Column(Text)

    legal_draft = Column(Text)
    legal_draft_model = Column(String(100))
    legal_draft_at = Column(TIMESTAMP)
    rental_agreement_id = Column(UUID(as_uuid=True), ForeignKey("rental_agreements.id", ondelete="SET NULL"))
    agreement_clauses = Column(JSONB)

    status = Column(String(30), nullable=False, default="reported")
    reviewed_by = Column(String(200))
    reviewed_at = Column(TIMESTAMP)
    final_response = Column(Text)
    sent_at = Column(TIMESTAMP)
    sent_via = Column(String(30))
    resolution = Column(Text)
    resolution_amount = Column(DECIMAL(10, 2))
    resolved_at = Column(TIMESTAMP)

    # Vector embedding (stored in Qdrant fgp_golden_claims)
    qdrant_point_id = Column(UUID(as_uuid=True))

    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    reservation = relationship("Reservation", lazy="joined")
    property = relationship("Property", lazy="joined")
    guest = relationship("Guest", lazy="joined")
