"""
Staff invite model — secure token-based invitation system.
An admin creates an invite → email is sent → user clicks link → sets password → account created.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Column, String, Boolean, TIMESTAMP, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base

INVITE_EXPIRY_HOURS = 72


class StaffInvite(Base):
    __tablename__ = "staff_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False, default="staff")
    token = Column(String(128), unique=True, nullable=False, index=True)

    invited_by = Column(UUID(as_uuid=True), ForeignKey("staff_users.id"), nullable=False)

    status = Column(String(20), nullable=False, default="pending")
    # pending | accepted | expired | revoked

    expires_at = Column(TIMESTAMP, nullable=False)
    accepted_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at and self.status == "pending"

    @property
    def is_usable(self) -> bool:
        return self.status == "pending" and datetime.utcnow() <= self.expires_at

    def __repr__(self) -> str:
        return f"<StaffInvite {self.email} ({self.status})>"
