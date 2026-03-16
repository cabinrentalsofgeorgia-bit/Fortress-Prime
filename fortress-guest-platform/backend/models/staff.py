"""
Staff user model - Admin access
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.core.database import Base


class StaffUser(Base):
    """Staff/Admin User model"""
    
    __tablename__ = "staff_users"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Auth
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    
    # Profile
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False, default="staff", index=True)
    # admin, manager, staff, maintenance
    
    # Permissions
    permissions = Column(JSONB)  # {'can_send_messages': true, 'can_edit_properties': false}
    
    # Status
    is_active = Column(Boolean, default=True)
    last_login_at = Column(TIMESTAMP)
    
    # Notifications
    notification_phone = Column(String(20))
    notification_email = Column(String(255))
    notify_urgent = Column(Boolean, default=True)
    notify_workorders = Column(Boolean, default=True)
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def full_name(self) -> str:
        """Get staff member's full name"""
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self) -> str:
        return f"<StaffUser {self.full_name} ({self.role})>"
