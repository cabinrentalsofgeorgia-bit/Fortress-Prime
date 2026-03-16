"""
Vault E-Discovery Audit Log — Chain of Custody for legal searches.

Every search executed against the email vault is logged here for
compliance and defensibility under Rules of Evidence.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Text, Integer, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.core.database import Base


class VaultAuditLog(Base):
    __tablename__ = "vault_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False, default="search", index=True)
    query_text = Column(Text, nullable=False)
    filters_applied = Column(JSONB, nullable=False, default=dict)
    result_count = Column(Integer, nullable=False, default=0)
    top_score = Column(String(10), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<VaultAuditLog {self.action} by={self.user_id} q={self.query_text[:40]}>"
