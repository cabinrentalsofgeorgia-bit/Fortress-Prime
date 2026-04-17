"""
FinancialApproval — Sovereign AI queue for parity discrepancy triage.

When the Hermes parity auditor or the daily continuous auditor detects a
difference between the local ledger and Streamline's GetReservationPrice,
a FinancialApproval row is created.  Small variances (≤ $10) are
auto-resolved; larger discrepancies require 1-click commander approval.

Status lifecycle:
  pending       → Commander reviews and approves/rejects
  auto_resolved → System variance ≤ $10.00, automatically reconciled
  approved      → Commander accepted the discrepancy
  rejected      → Commander flagged for investigation

Resolution strategies (set at approval time):
  absorb  → Balance internal variance account; guest is not billed
  invoice → Create a Stripe Invoice to collect the delta from the guest
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class FinancialApproval(Base):
    __tablename__ = "financial_approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id = Column(String(100), nullable=False, index=True)
    status = Column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    discrepancy_type = Column(String(100), nullable=False, default="parity_drift")
    local_total_cents = Column(Integer, nullable=False)
    streamline_total_cents = Column(Integer, nullable=False)
    delta_cents = Column(Integer, nullable=False)
    context_payload = Column(JSONB, nullable=False, server_default="{}")
    resolution_strategy = Column(
        String(30),
        nullable=True,
        index=True,
    )
    stripe_invoice_id = Column(String(255), nullable=True)
    resolved_by = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<FinancialApproval {self.status} "
            f"Δ{self.delta_cents}¢ res={self.reservation_id} "
            f"strategy={self.resolution_strategy}>"
        )
