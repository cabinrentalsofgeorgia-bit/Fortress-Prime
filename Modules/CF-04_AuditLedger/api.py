"""
MODULE CF-04: AUDIT LEDGER — FastAPI Endpoints
================================================
Fortress Prime | Cabin Rentals of Georgia

Exposes the Audit Ledger engine as REST endpoints for the Command Center
and external integrations.

Base URL: api.crog-ai.com/v1/ledger/
"""

from datetime import date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .ledger_engine import AuditLedger

router = APIRouter(tags=["CF-04 Audit Ledger"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class PostTransactionRequest(BaseModel):
    debit_acct: str = Field(..., description="Account code to debit (e.g., '1000')")
    credit_acct: str = Field(..., description="Account code to credit (e.g., '4000')")
    amount: float = Field(..., gt=0, description="Transaction amount (positive)")
    description: str = Field(..., min_length=1, description="Transaction description")
    property_id: Optional[str] = Field(None, description="Cabin/property identifier")
    reference_id: Optional[str] = Field(None, description="External reference number")
    reference_type: Optional[str] = Field(None, description="Reference type")
    entry_date: Optional[date] = Field(None, description="Transaction date (default: today)")
    posted_by: str = Field("api_user", description="Who is posting this transaction")
    memo: Optional[str] = Field(None, description="Additional memo")


class CompoundLineItem(BaseModel):
    account_code: str
    debit: float = Field(0, ge=0)
    credit: float = Field(0, ge=0)
    memo: Optional[str] = None


class PostCompoundRequest(BaseModel):
    line_items: List[CompoundLineItem] = Field(..., min_length=2)
    description: str = Field(..., min_length=1)
    property_id: Optional[str] = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    entry_date: Optional[date] = None
    posted_by: str = "api_user"


class VoidEntryRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Reason for voiding")
    voided_by: str = Field("api_user", description="Who is voiding this entry")


class ReviewAnomalyRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1)
    notes: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/transaction", summary="Post a double-entry transaction")
async def post_transaction(req: PostTransactionRequest):
    """
    Post a strict double-entry transaction.
    The Iron Dome constraint ensures debits == credits at the database level.
    """
    try:
        with AuditLedger() as ledger:
            result = ledger.post_transaction(
                debit_acct=req.debit_acct,
                credit_acct=req.credit_acct,
                amount=req.amount,
                description=req.description,
                property_id=req.property_id,
                reference_id=req.reference_id,
                reference_type=req.reference_type,
                entry_date=req.entry_date,
                posted_by=req.posted_by,
                memo=req.memo,
            )
            return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transaction failed: {e}")


@router.post("/transaction/compound", summary="Post a compound multi-leg transaction")
async def post_compound_transaction(req: PostCompoundRequest):
    """
    Post a compound transaction with multiple debit/credit legs.
    All legs must balance (total debits == total credits).
    """
    try:
        with AuditLedger() as ledger:
            result = ledger.post_compound_transaction(
                line_items=[li.model_dump() for li in req.line_items],
                description=req.description,
                property_id=req.property_id,
                reference_id=req.reference_id,
                reference_type=req.reference_type,
                entry_date=req.entry_date,
                posted_by=req.posted_by,
            )
            return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compound transaction failed: {e}")


@router.get("/trial-balance", summary="Get the current trial balance")
async def get_trial_balance():
    """Returns the trial balance across all active accounts."""
    try:
        with AuditLedger() as ledger:
            rows = ledger.get_trial_balance()
            total_dr = sum(Decimal(str(r["total_debits"])) for r in rows)
            total_cr = sum(Decimal(str(r["total_credits"])) for r in rows)
            return {
                "trial_balance": rows,
                "total_debits": str(total_dr),
                "total_credits": str(total_cr),
                "is_balanced": total_dr == total_cr,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trust-balance", summary="Get trust fund balance by property")
async def get_trust_balance(property_id: Optional[str] = Query(None)):
    """Returns owner vs. operating fund balance, optionally filtered by property."""
    try:
        with AuditLedger() as ledger:
            return ledger.get_trust_balance(property_id=property_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts", summary="Get chart of accounts")
async def get_accounts(
    account_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
):
    """Returns the full chart of accounts."""
    try:
        with AuditLedger() as ledger:
            return ledger.get_accounts(
                account_type=account_type,
                active_only=active_only,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entries", summary="Query journal entries")
async def get_journal_entries(
    property_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    reference_type: Optional[str] = Query(None),
    include_void: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query journal entries with optional filters."""
    try:
        with AuditLedger() as ledger:
            return ledger.get_journal_entries(
                property_id=property_id,
                start_date=start_date,
                end_date=end_date,
                reference_type=reference_type,
                include_void=include_void,
                limit=limit,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entries/{entry_id}/void", summary="Void a journal entry")
async def void_entry(entry_id: int, req: VoidEntryRequest):
    """
    Void a journal entry. Does NOT delete — preserves full audit trail.
    """
    try:
        with AuditLedger() as ledger:
            return ledger.void_entry(
                entry_id=entry_id,
                reason=req.reason,
                voided_by=req.voided_by,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomalies", summary="Get anomaly flags")
async def get_anomalies(
    reviewed: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Returns AI-flagged financial anomalies."""
    try:
        with AuditLedger() as ledger:
            return ledger.get_anomaly_flags(
                reviewed=reviewed,
                severity=severity,
                limit=limit,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomalies/{flag_id}/review", summary="Review an anomaly flag")
async def review_anomaly(flag_id: int, req: ReviewAnomalyRequest):
    """Mark an anomaly flag as reviewed with notes."""
    try:
        with AuditLedger() as ledger:
            return ledger.review_anomaly(
                flag_id=flag_id,
                reviewed_by=req.reviewed_by,
                notes=req.notes,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", summary="Module health check")
async def health_check():
    """Verify the Audit Ledger module is operational."""
    try:
        with AuditLedger() as ledger:
            accounts = ledger.get_accounts()
            return {
                "module": "CF-04 Audit Ledger",
                "status": "OPERATIONAL",
                "accounts_loaded": len(accounts),
                "version": "1.0.0",
            }
    except Exception as e:
        return {
            "module": "CF-04 Audit Ledger",
            "status": "DEGRADED",
            "error": str(e),
        }
