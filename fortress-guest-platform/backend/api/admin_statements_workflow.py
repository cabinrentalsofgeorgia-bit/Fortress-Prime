"""
Admin Statement Workflow API — lifecycle management for OwnerBalancePeriods.

Endpoints:
  GET  /api/admin/payouts/accounts                         — list owner payout accounts (OPAs)
  POST /api/admin/payouts/statements/generate              — create/update drafts
  GET  /api/admin/payouts/statements                       — list periods
  GET  /api/admin/payouts/statements/{id}                  — full detail
  POST /api/admin/payouts/statements/{id}/approve          — pending_approval → approved
  POST /api/admin/payouts/statements/{id}/void             — → voided
  POST /api/admin/payouts/statements/{id}/mark-paid        — approved → paid
  POST /api/admin/payouts/statements/{id}/mark-emailed     — approved/paid → emailed
  GET  /api/admin/payouts/statements/{id}/pdf              — download PDF
  POST /api/admin/payouts/statements/{id}/send-test        — F4: manual test send

File choice: a new file rather than extending admin_payouts.py.
admin_payouts.py already handles payout schedules, ledger sweeps, invites,
and the statement send-all stub. The statement lifecycle is a distinct domain
and benefits from its own module.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_manager_or_admin
from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.models.staff import StaffUser
from backend.services.email_service import is_email_configured, send_email
from backend.services.statement_computation import compute_owner_statement
from backend.services.statement_workflow import (
    GenerateStatementsResult,
    StatementWorkflowError,
    approve_statement,
    generate_monthly_statements,
    mark_statement_emailed,
    mark_statement_paid,
    void_statement,
)

logger = structlog.get_logger(service="admin_statements_workflow")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
_UTC = timezone.utc


# ── OPA list (for UI dropdowns) ───────────────────────────────────────────────

@router.get("/accounts")
async def list_owner_payout_accounts(db: AsyncSession = Depends(get_db)):
    """
    Return all owner payout accounts for UI dropdowns.
    Includes property name resolved from properties table.
    """
    import uuid as _uuid

    result = await db.execute(
        select(OwnerPayoutAccount).order_by(OwnerPayoutAccount.owner_name)
    )
    opas = result.scalars().all()

    items = []
    for opa in opas:
        prop_name: Optional[str] = None
        try:
            prop_uuid = _uuid.UUID(opa.property_id)
            prop = await db.get(Property, prop_uuid)
            prop_name = prop.name if prop else None
        except ValueError:
            pass
        items.append({
            "id": opa.id,
            "owner_name": opa.owner_name,
            "owner_email": opa.owner_email,
            "property_id": opa.property_id,
            "property_name": prop_name,
            "commission_rate": str(opa.commission_rate) if opa.commission_rate is not None else None,
            "streamline_owner_id": opa.streamline_owner_id,
            "stripe_account_id": opa.stripe_account_id,
            "account_status": opa.account_status,
        })
    return {"accounts": items, "total": len(items)}


# ── Schemas ───────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    period_start: date
    period_end: date
    dry_run: bool = False


class VoidRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


class MarkPaidRequest(BaseModel):
    payment_reference: str = Field(
        ...,
        min_length=1,
        description="e.g. 'QuickBooks ACH batch 2026-05-15-001'",
    )


class SendTestRequest(BaseModel):
    override_email: str = Field(
        ...,
        description="Email address to receive the test send (real owner is NOT notified).",
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    note: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional note included in the email body for verification context.",
    )


def _period_dict(period: OwnerBalancePeriod) -> dict:
    return {
        "id": period.id,
        "owner_payout_account_id": period.owner_payout_account_id,
        "period_start": period.period_start.isoformat() if period.period_start else None,
        "period_end": period.period_end.isoformat() if period.period_end else None,
        "opening_balance": str(period.opening_balance),
        "closing_balance": str(period.closing_balance),
        "total_revenue": str(period.total_revenue),
        "total_commission": str(period.total_commission),
        "total_charges": str(period.total_charges),
        "total_payments": str(period.total_payments),
        "total_owner_income": str(period.total_owner_income),
        "status": period.status,
        "created_at": period.created_at.isoformat() if period.created_at else None,
        "updated_at": period.updated_at.isoformat() if period.updated_at else None,
        "approved_at": period.approved_at.isoformat() if period.approved_at else None,
        "approved_by": period.approved_by,
        "paid_at": period.paid_at.isoformat() if period.paid_at else None,
        "paid_by": getattr(period, "paid_by", None),
        "emailed_at": period.emailed_at.isoformat() if period.emailed_at else None,
        "voided_at": getattr(period, "voided_at", None),
        "voided_by": getattr(period, "voided_by", None),
        "notes": period.notes,
    }


def _workflow_error_to_http(exc: StatementWorkflowError) -> HTTPException:
    status = 404 if exc.code == "not_found" else 409
    return HTTPException(status_code=status, detail=exc.message)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/statements/generate", response_model=GenerateStatementsResult)
async def generate_statements(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate draft statements for all active enrolled owners for a period.

    Finalized statements (approved/paid/emailed/voided) are never overwritten.
    Set dry_run=true to preview without committing.
    """
    today = date.today()
    if body.period_end <= body.period_start:
        raise HTTPException(422, "period_end must be strictly after period_start")
    if body.period_end > today:
        raise HTTPException(
            422,
            f"period_end ({body.period_end}) is in the future. "
            "Statements can only be generated for completed months.",
        )

    result = await generate_monthly_statements(
        db,
        period_start=body.period_start,
        period_end=body.period_end,
        dry_run=body.dry_run,
    )
    return result


@router.get("/statements")
async def list_statements(
    status: Optional[StatementPeriodStatus] = Query(None),
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    owner_payout_account_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List OwnerBalancePeriod rows with optional filters."""
    q = select(OwnerBalancePeriod)
    if status is not None:
        q = q.where(OwnerBalancePeriod.status == status.value)
    if period_start is not None:
        q = q.where(OwnerBalancePeriod.period_start >= period_start)
    if period_end is not None:
        q = q.where(OwnerBalancePeriod.period_end <= period_end)
    if owner_payout_account_id is not None:
        q = q.where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id
        )
    q = q.order_by(
        OwnerBalancePeriod.period_start.desc(),
        OwnerBalancePeriod.owner_payout_account_id.asc(),
    ).offset(offset).limit(limit)

    result = await db.execute(q)
    periods = result.scalars().all()
    return {"statements": [_period_dict(p) for p in periods], "total": len(periods)}


@router.get("/statements/{period_id}")
async def get_statement(period_id: int, db: AsyncSession = Depends(get_db)):
    """
    Return a full statement with the persisted balance row AND live line items
    (reservations and owner_charges recomputed from compute_owner_statement).
    """
    period = await db.get(OwnerBalancePeriod, period_id)
    if not period:
        raise HTTPException(404, f"Statement period {period_id} not found")

    # Compute live statement for the line items
    try:
        stmt = await compute_owner_statement(
            db,
            owner_payout_account_id=period.owner_payout_account_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        line_items_data = stmt.model_dump()
    except Exception as exc:
        line_items_data = {"error": str(exc)[:300]}

    return {
        "balance_period": _period_dict(period),
        "statement": line_items_data,
    }


@router.post("/statements/{period_id}/approve")
async def approve(
    period_id: int,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Transition pending_approval → approved."""
    try:
        period = await approve_statement(db, period_id, user.email)
    except StatementWorkflowError as exc:
        raise _workflow_error_to_http(exc)
    return _period_dict(period)


@router.post("/statements/{period_id}/void")
async def void(
    period_id: int,
    body: VoidRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Transition draft / pending_approval / approved → voided."""
    try:
        period = await void_statement(db, period_id, body.reason, user.email)
    except StatementWorkflowError as exc:
        raise _workflow_error_to_http(exc)
    return _period_dict(period)


@router.post("/statements/{period_id}/mark-paid")
async def mark_paid(
    period_id: int,
    body: MarkPaidRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    """Transition approved (or emailed) → paid."""
    try:
        period = await mark_statement_paid(
            db, period_id, body.payment_reference, user.email
        )
    except StatementWorkflowError as exc:
        raise _workflow_error_to_http(exc)
    return _period_dict(period)


@router.post("/statements/{period_id}/mark-emailed")
async def mark_emailed(
    period_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Transition approved / paid → emailed. Usually called by Phase F email cron."""
    try:
        period = await mark_statement_emailed(db, period_id)
    except StatementWorkflowError as exc:
        raise _workflow_error_to_http(exc)
    return _period_dict(period)


# ── Phase E: PDF download ──────────────────────────────────────────────────────

@router.get("/statements/{period_id}/pdf")
async def download_statement_pdf(
    period_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Render and download a PDF owner statement.
    Content-Disposition suggests a filename based on owner name, property, and period.
    """
    import re
    import uuid as _uuid
    from fastapi.responses import Response as FastAPIResponse
    from backend.services.statement_pdf import render_owner_statement_pdf

    # Verify the period exists (OwnerBalancePeriod already imported at module level)
    period = await db.get(OwnerBalancePeriod, period_id)
    if period is None:
        raise HTTPException(404, f"Statement period {period_id} not found")

    # Render
    try:
        pdf_bytes = await render_owner_statement_pdf(db, period_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.error("pdf_render_failed", period_id=period_id, error=str(exc)[:200])
        raise HTTPException(500, f"PDF rendering failed: {str(exc)[:200]}")

    # Build filename from owner name, property name, and period
    opa = await db.get(OwnerPayoutAccount, period.owner_payout_account_id)
    owner_slug = "owner"
    prop_slug = "property"
    if opa:
        name_parts = (opa.owner_name or "owner").lower().split()
        owner_slug = re.sub(r"[^a-z0-9]+", "_", name_parts[-1] if name_parts else "owner")[:20]
        try:
            prop_uuid = _uuid.UUID(opa.property_id)
            prop = await db.get(Property, prop_uuid)
            if prop:
                prop_slug = re.sub(r"[^a-z0-9]+", "_", prop.name.lower())[:30]
        except ValueError:
            pass

    period_str = period.period_start.strftime("%Y-%m")
    filename = f"owner_statement_{owner_slug}_{prop_slug}_{period_str}.pdf"

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Phase F4: Manual test endpoint ────────────────────────────────────────────

@router.post("/statements/{period_id}/send-test")
async def send_test_statement(
    period_id: int,
    body: SendTestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a test copy of this statement to an override email address.

    - Sends to override_email, NOT to the real owner.
    - Subject is prefixed with [TEST].
    - Adds a clear warning banner in the email body.
    - Does NOT transition the statement's status (mark_statement_emailed is NOT called).
    - Works regardless of CROG_STATEMENTS_PARALLEL_MODE.
    """
    import uuid as _uuid
    from backend.services.statement_pdf import render_owner_statement_pdf

    period = await db.get(OwnerBalancePeriod, period_id)
    if period is None:
        raise HTTPException(404, f"Statement period {period_id} not found")

    opa = await db.get(OwnerPayoutAccount, period.owner_payout_account_id)
    owner_name = opa.owner_name if opa else "(unknown)"
    owner_email = opa.owner_email if opa else None

    # Resolve property name
    prop_name = opa.property_id if opa else "(unknown)"
    if opa:
        try:
            prop_uuid = _uuid.UUID(opa.property_id)
            prop = await db.get(Property, prop_uuid)
            if prop:
                prop_name = prop.name
        except (ValueError, Exception):
            pass

    # Render PDF
    try:
        pdf_bytes = await render_owner_statement_pdf(db, period_id)
    except Exception as exc:
        raise HTTPException(500, f"PDF rendering failed: {str(exc)[:200]}")

    # Build filename
    last_slug = re.sub(r"[^a-z0-9]+", "_", (owner_name.split()[0] if owner_name.split() else "owner").lower())[:20]
    prop_slug = re.sub(r"[^a-z0-9]+", "_", prop_name.lower())[:20]
    period_str_file = period.period_start.strftime("%Y-%m")
    filename = f"owner_statement_{last_slug}_{prop_slug}_{period_str_file}.pdf"

    month_year = period.period_start.strftime("%B %Y")
    subject = f"[TEST] Your statement for {month_year} — Cabin Rentals of Georgia"

    note_section = f"\nNote from sender: {body.note}\n" if body.note else ""
    warning = (
        f"*** THIS IS A TEST SEND ***\n"
        f"This statement was sent to {body.override_email} for verification purposes.\n"
        f"The real owner ({owner_name} at {owner_email or 'no email'}) "
        f"did NOT receive this email.\n"
        f"{note_section}"
        f"The statement is attached as a PDF."
    )
    text_body = f"{warning}\n\nStatement period: {month_year}\nOwner: {owner_name}\nProperty: {prop_name}"
    html_body = (
        f"<pre style='background:#fef3c7;padding:12px;border:2px solid #d97706;border-radius:4px'>"
        f"{warning}"
        f"</pre>"
        f"<p>Statement period: <strong>{month_year}</strong><br/>"
        f"Owner: {owner_name}<br/>Property: {prop_name}</p>"
    )

    if not is_email_configured():
        raise HTTPException(500, "SMTP is not configured — email cannot be sent")

    ok = send_email(
        to=body.override_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachments=[{"filename": filename, "content": pdf_bytes, "mime_type": "application/pdf"}],
    )

    if not ok:
        raise HTTPException(500, "SMTP send returned failure — check server logs")

    logger.info(
        "statement_test_sent",
        period_id=period_id,
        override_email=body.override_email,
        owner=owner_name,
    )
    return {
        "success": True,
        "sent_to": body.override_email,
        "statement_status_unchanged": True,
        "pdf_size_bytes": len(pdf_bytes),
        "message": (
            f"Test statement for {month_year} sent to {body.override_email}. "
            f"The real owner ({owner_name}) was NOT notified. "
            f"Statement status remains '{period.status}'."
        ),
    }
