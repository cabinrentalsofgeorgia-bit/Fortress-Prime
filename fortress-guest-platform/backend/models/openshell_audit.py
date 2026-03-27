"""
OpenShell audit ledger for AI/tool/reservation/SEO activity.

Entries are chained and signed to provide tamper-evident local audit trails.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.core.database import Base


class OpenShellAuditLog(Base):
    __tablename__ = "openshell_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id = Column(String(255), nullable=True, index=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(120), nullable=False, index=True)
    resource_type = Column(String(120), nullable=False, index=True)
    resource_id = Column(String(255), nullable=True)
    purpose = Column(String(255), nullable=True)
    tool_name = Column(String(120), nullable=True, index=True)
    redaction_status = Column(String(50), nullable=False, default="not_applicable", index=True)
    model_route = Column(String(120), nullable=True, index=True)
    outcome = Column(String(50), nullable=False, default="success", index=True)
    request_id = Column(String(100), nullable=True, index=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    payload_hash = Column(String(128), nullable=False, index=True)
    prev_hash = Column(String(128), nullable=True, index=True)
    entry_hash = Column(String(128), nullable=False, unique=True, index=True)
    signature = Column(Text, nullable=False)

    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<OpenShellAuditLog action={self.action} resource={self.resource_type} "
            f"route={self.model_route} outcome={self.outcome}>"
        )
