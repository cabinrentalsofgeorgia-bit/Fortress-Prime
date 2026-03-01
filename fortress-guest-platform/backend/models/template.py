"""
EmailTemplate model — Database-driven email templates for the Sovereign Templating Engine.

Each template stores a Jinja2-compatible subject and body that are rendered at
send-time with reservation/guest context variables.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, index=True)
    trigger_event = Column(String(100), nullable=False, index=True)
    subject_template = Column(String(1000), nullable=False, default="")
    body_template = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    requires_human_approval = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<EmailTemplate {self.name!r} trigger={self.trigger_event!r} active={self.is_active}>"
