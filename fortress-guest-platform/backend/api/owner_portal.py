"""
Owner Portal API — property owners can view their revenue, reservations,
work orders, statements, and documents.

Data sources:
  - Local DB for aggregates (reservations, work_orders, trust_balance)
  - Streamline VRS for live owner balances and monthly statements
  - Yield Loss Engine for real-time revenue impact analysis
"""

import io
import json
import time
import structlog
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.core.database import get_db
from backend.core.config import settings
from backend.services.inventory_events import publish_inventory_availability_changed
from backend.services.knowledge_retriever import (
    semantic_search,
    legal_library_search,
    format_legal_context,
    format_context as format_kb_context,
)

logger = structlog.get_logger(service="owner_portal")

router = APIRouter()

TWO_PLACES = Decimal("0.01")
DEFAULT_TAX_RATE = Decimal("0.13")

PEAK_MONTHS = {6, 7, 10, 11, 12}
WEEKEND_DAYS = {4, 5}


# ============================================================================
# Models
# ============================================================================

class OwnerDashboard(BaseModel):
    total_properties: int
    active_reservations: int
    revenue_mtd: float
    revenue_ytd: float
    occupancy_rate: float
    open_work_orders: int
    upcoming_reservations: int


class OwnerStatement(BaseModel):
    id: str
    period_start: str
    period_end: str
    gross_revenue: float
    management_fee: float
    cleaning_fees: float
    maintenance_costs: float
    net_payout: float
    status: str
    generated_at: str


class OwnerDocument(BaseModel):
    id: str
    name: str
    category: str
    file_url: str
    uploaded_at: str


# ============================================================================
# Owner Dashboard
# ============================================================================

def _et_today():
    import pytz
    from datetime import datetime as _dt
    return _dt.now(pytz.timezone("America/New_York")).date()


@router.get("/dashboard/{owner_id}", response_model=OwnerDashboard)
async def owner_dashboard(owner_id: str, db: AsyncSession = Depends(get_db)):
    """Get owner's high-level dashboard metrics."""
    today = _et_today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    props = await db.execute(
        text("SELECT COUNT(*) FROM properties WHERE is_active = true"),
    )
    total_properties = props.scalar() or 0

    active = await db.execute(
        text("""
            SELECT COUNT(*) FROM reservations 
            WHERE status IN ('confirmed', 'checked_in')
            AND check_in_date <= :today AND check_out_date >= :today
        """),
        {"today": today},
    )
    active_reservations = active.scalar() or 0

    rev_mtd = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_amount), 0) FROM reservations
            WHERE check_in_date >= :start AND status != 'cancelled'
        """),
        {"start": month_start},
    )
    revenue_mtd = float(rev_mtd.scalar() or 0)

    rev_ytd = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_amount), 0) FROM reservations
            WHERE check_in_date >= :start AND status != 'cancelled'
        """),
        {"start": year_start},
    )
    revenue_ytd = float(rev_ytd.scalar() or 0)

    occ = await db.execute(
        text("""
            SELECT COUNT(DISTINCT property_id) FROM reservations
            WHERE status IN ('confirmed', 'checked_in')
            AND check_in_date <= :today AND check_out_date >= :today
        """),
        {"today": today},
    )
    occupied = occ.scalar() or 0
    occupancy_rate = (occupied / total_properties * 100) if total_properties > 0 else 0

    wo = await db.execute(
        text("SELECT COUNT(*) FROM work_orders WHERE status = 'open'"),
    )
    open_work_orders = wo.scalar() or 0

    upcoming = await db.execute(
        text("""
            SELECT COUNT(*) FROM reservations
            WHERE check_in_date > :today AND check_in_date <= :future
            AND status != 'cancelled'
        """),
        {"today": today, "future": today + timedelta(days=30)},
    )

    return OwnerDashboard(
        total_properties=total_properties,
        active_reservations=active_reservations,
        revenue_mtd=revenue_mtd,
        revenue_ytd=revenue_ytd,
        occupancy_rate=occupancy_rate,
        open_work_orders=open_work_orders,
        upcoming_reservations=upcoming.scalar() or 0,
    )


# ============================================================================
# Owner Reservations Calendar
# ============================================================================

@router.get("/reservations/{owner_id}")
async def owner_reservations(
    owner_id: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get owner's property reservations within a date range."""
    start_date = date.fromisoformat(start) if start else _et_today() - timedelta(days=30)
    end_date = date.fromisoformat(end) if end else _et_today() + timedelta(days=90)

    result = await db.execute(
        text("""
            SELECT r.*, p.name as property_name, 
                   g.first_name, g.last_name
            FROM reservations r
            JOIN properties p ON r.property_id = p.id
            LEFT JOIN guests g ON r.guest_id = g.id
            WHERE r.check_in_date <= :end AND r.check_out_date >= :start
            AND r.status != 'cancelled'
            ORDER BY r.check_in_date
        """),
        {"start": start_date, "end": end_date},
    )
    return [dict(row._mapping) for row in result.fetchall()]


# ============================================================================
# Owner Work Orders
# ============================================================================

@router.get("/work-orders/{owner_id}")
async def owner_work_orders(
    owner_id: str,
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get work orders for owner's properties."""
    query = """
        SELECT wo.*, p.name as property_name
        FROM work_orders wo
        LEFT JOIN properties p ON wo.property_id = p.id
    """
    params = {}
    if status:
        query += " WHERE wo.status = :status"
        params["status"] = status
    query += " ORDER BY wo.created_at DESC LIMIT 50"

    result = await db.execute(text(query), params)
    return [dict(row._mapping) for row in result.fetchall()]


# ============================================================================
# Owner Statements
# ============================================================================

@router.get("/statements/{owner_id}")
async def owner_statements(
    owner_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get owner financial statements.
    Tries DB owner_statements first, falls back to reservation-based calc."""
    db_stmts = await db.execute(
        text("""
            SELECT * FROM owner_statements
            ORDER BY period_start DESC LIMIT 12
        """)
    )
    rows = db_stmts.fetchall()

    if rows:
        return [
            {
                "id": str(r.id),
                "period_start": r.period_start.isoformat() if r.period_start else "",
                "period_end": r.period_end.isoformat() if r.period_end else "",
                "gross_revenue": float(r.gross_revenue or 0),
                "management_fee": float(r.management_fee or 0),
                "cleaning_fees": float(r.cleaning_revenue or 0),
                "maintenance_costs": float(r.maintenance_expenses or 0),
                "net_payout": float(r.net_to_owner or 0),
                "status": r.payout_status or "pending",
                "generated_at": r.generated_at.isoformat() if r.generated_at else "",
            }
            for r in rows
        ]

    today = _et_today()
    statements = []
    for months_back in range(6):
        period_end = today.replace(day=1) - timedelta(days=1 + months_back * 30)
        period_start = period_end.replace(day=1)

        rev = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount), 0) FROM reservations
                WHERE check_in_date >= :start AND check_in_date <= :end
                AND status != 'cancelled'
            """),
            {"start": period_start, "end": period_end},
        )
        gross = float(rev.scalar() or 0)
        mgmt_fee = gross * 0.20
        cleaning = gross * 0.08
        maintenance = gross * 0.05
        net = gross - mgmt_fee - cleaning - maintenance

        statements.append({
            "id": f"stmt-{period_start.isoformat()}",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "gross_revenue": round(gross, 2),
            "management_fee": round(mgmt_fee, 2),
            "cleaning_fees": round(cleaning, 2),
            "maintenance_costs": round(maintenance, 2),
            "net_payout": round(net, 2),
            "status": "paid" if months_back > 0 else "pending",
            "generated_at": period_end.isoformat(),
        })

    return statements


# ============================================================================
# Owner Documents
# ============================================================================

@router.get("/documents/{owner_id}")
async def owner_documents(owner_id: str, db: AsyncSession = Depends(get_db)):
    """Get owner documents (leases, insurance, tax docs)."""
    return [
        {
            "id": "doc-1",
            "name": "Property Management Agreement",
            "category": "legal",
            "file_url": "/documents/pma.pdf",
            "uploaded_at": "2025-01-15",
        },
        {
            "id": "doc-2",
            "name": "Insurance Certificate 2026",
            "category": "insurance",
            "file_url": "/documents/insurance-2026.pdf",
            "uploaded_at": "2025-12-01",
        },
        {
            "id": "doc-3",
            "name": "1099 Tax Form 2025",
            "category": "tax",
            "file_url": "/documents/1099-2025.pdf",
            "uploaded_at": "2026-01-31",
        },
    ]


# ============================================================================
# Property Balances (from Streamline sync)
# ============================================================================

@router.get("/balances/{owner_id}")
async def owner_balances(owner_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return per-property owner balances from the trust_balance table
    and from the cached owner_balance JSONB on properties.
    """
    tb_result = await db.execute(
        text("SELECT * FROM trust_balance_cache ORDER BY last_updated DESC")
    )
    trust_rows = tb_result.fetchall()

    prop_result = await db.execute(
        text("""
            SELECT name, streamline_property_id, owner_id, owner_name,
                   owner_balance
            FROM properties
            WHERE owner_balance IS NOT NULL
            ORDER BY name
        """)
    )
    prop_rows = prop_result.fetchall()

    return {
        "trust_balances": [
            {
                "property_id": r.property_id,
                "owner_funds": float(r.owner_funds or 0),
                "operating_funds": float(r.operating_funds or 0),
                "escrow_funds": float(r.escrow_funds or 0),
                "security_deposits": float(r.security_deps or 0),
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in trust_rows
        ],
        "property_balances": [
            {
                "name": r.name,
                "streamline_property_id": r.streamline_property_id,
                "owner_id": r.owner_id,
                "owner_name": r.owner_name,
                "balance_detail": r.owner_balance,
            }
            for r in prop_rows
        ],
    }


@router.get("/balances/{owner_id}/live")
async def owner_balance_live(owner_id: str, unit_id: Optional[int] = Query(None)):
    """Fetch live owner balance from Streamline for a specific unit."""
    if not unit_id:
        raise HTTPException(status_code=400, detail="unit_id query parameter is required")

    from backend.integrations.streamline_vrs import StreamlineVRS
    vrs = StreamlineVRS()
    try:
        data = await vrs.fetch_unit_owner_balance(unit_id)
        if not data:
            raise HTTPException(status_code=404, detail="No balance data returned")
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await vrs.close()


@router.get("/balances/{owner_id}/statement")
async def owner_statement_live(
    owner_id: str,
    unit_id: Optional[int] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Fetch a live monthly statement from Streamline."""
    from backend.integrations.streamline_vrs import StreamlineVRS
    vrs = StreamlineVRS()
    try:
        start_date = date.fromisoformat(start) if start else None
        end_date = date.fromisoformat(end) if end else None
        data = await vrs.fetch_owner_statement(
            owner_id=int(owner_id),
            unit_id=unit_id,
            start_date=start_date,
            end_date=end_date,
            include_pdf=False,
        )
        return data if data else {"message": "No statement data"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await vrs.close()


# ============================================================================
# Strangler Facade — Legacy Streamline Statement Proxy
# ============================================================================

@router.get("/{property_id}/statements/legacy")
async def get_legacy_statements_list(property_id: str):
    """Proxy to Streamline for historical owner statement PDFs.

    The Next.js UI renders these alongside new Iron Dome statements,
    creating a seamless unified timeline while the legacy system is
    gradually decommissioned.
    """
    from backend.integrations.streamline_vrs import StreamlineVRS

    vrs = StreamlineVRS()
    try:
        today = date.today()
        statements = []
        for months_back in range(1, 13):
            end_dt = today.replace(day=1) - timedelta(days=1 + (months_back - 1) * 30)
            start_dt = end_dt.replace(day=1)
            stmt_id = f"stmt_{start_dt.year}_{start_dt.month:02d}"
            statements.append({
                "id": stmt_id,
                "month": start_dt.strftime("%B %Y"),
                "period_start": start_dt.isoformat(),
                "period_end": end_dt.isoformat(),
                "source": "streamline",
                "download_url": f"/api/owner/{property_id}/statements/legacy/{stmt_id}/download",
            })
        return {"statements": statements}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Legacy archive unreachable: {e}")
    finally:
        await vrs.close()


@router.get("/{property_id}/statements/legacy/{statement_id}/download")
async def download_legacy_statement(property_id: str, statement_id: str):
    """Stream a Streamline owner statement PDF directly to the browser."""
    from backend.integrations.streamline_vrs import StreamlineVRS

    vrs = StreamlineVRS()
    try:
        parts = statement_id.replace("stmt_", "").split("_")
        year, month = int(parts[0]), int(parts[1])
        start_dt = date(year, month, 1)
        if month == 12:
            end_dt = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_dt = date(year, month + 1, 1) - timedelta(days=1)

        data = await vrs.fetch_owner_statement(
            owner_id=0,
            start_date=start_dt,
            end_date=end_dt,
            include_pdf=True,
        )
        pdf_bytes = data.get("pdf_data", b"") if data else b""

        if not pdf_bytes:
            raise HTTPException(status_code=404, detail="Statement PDF not available")

        return StreamingResponse(
            io.BytesIO(pdf_bytes if isinstance(pdf_bytes, bytes) else pdf_bytes.encode()),
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=CROG_Statement_{statement_id}.pdf"
                )
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail="Failed to retrieve legacy document.")
    finally:
        await vrs.close()


# ============================================================================
# Iron Dome — Secure Owner-Facing Journal Activity
# ============================================================================
# INFORMATION WALL: Only surfaces the total deduction from account 2000
# (Trust Liability — Owners). The vendor payable (2100) and PM overhead
# revenue (4100) lines are strictly excluded. Owners see the fully burdened
# cost; the margin split remains internal.

@router.get("/{property_id}/iron-dome/activity")
async def get_iron_dome_activity(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Owner-facing journal activity showing total charges only."""
    result = await db.execute(
        text("""
            SELECT je.id, je.entry_date, je.description,
                   jli.debit AS total_owner_charge
            FROM journal_entries je
            JOIN journal_line_items jli ON je.id = jli.journal_entry_id
            WHERE je.property_id = :pid
              AND je.is_void = FALSE
              AND jli.account_id = (SELECT id FROM accounts WHERE code = '2000')
              AND jli.debit > 0
            ORDER BY je.entry_date DESC
            LIMIT 50
        """),
        {"pid": property_id},
    )

    return {
        "transactions": [
            {
                "id": row.id,
                "date": row.entry_date.isoformat(),
                "description": row.description,
                "amount": float(row.total_owner_charge),
            }
            for row in result.fetchall()
        ]
    }


# ============================================================================
# YIELD LOSS ENGINE — Revenue Impact Calculator for Owner Blocks
# ============================================================================
# When an owner requests to block dates for personal use, the engine
# calculates the real-time revenue impact using the property's Streamline
# rate_card and historical ADR. The result is surfaced as psychological
# friction on the Glass before the block is confirmed.

class BlockRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = "owner_stay"


class YieldLossEstimate(BaseModel):
    property_id: str
    property_name: str
    requested_nights: int
    projected_adr: float
    gross_revenue_loss: float
    cleaning_fee: float
    tax_estimate: float
    total_estimated_loss: float
    demand_alert: bool
    peak_nights: int
    warning_message: str
    nightly_breakdown: List[Dict[str, Any]]


def _parse_streamline_date(ds: Optional[str]) -> Optional[date]:
    if not ds:
        return None
    try:
        parts = ds.split("/")
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _nightly_from_rate_card(rate_card: dict, stay_date: date) -> Optional[Decimal]:
    for entry in rate_card.get("rates", []):
        start = _parse_streamline_date(entry.get("start_date"))
        end = _parse_streamline_date(entry.get("end_date"))
        if start and end and start <= stay_date <= end:
            nightly = entry.get("nightly")
            if nightly is not None:
                return Decimal(str(nightly)).quantize(TWO_PLACES, ROUND_HALF_UP)
    return None


def _fees_from_rate_card(rate_card: dict) -> Decimal:
    total = Decimal("0")
    for fee in rate_card.get("fees", []):
        amount = fee.get("amount")
        if amount is not None:
            total += Decimal(str(amount)).quantize(TWO_PLACES, ROUND_HALF_UP)
    return total


def _tax_rate_from_rate_card(rate_card: dict) -> Decimal:
    total = Decimal("0")
    for tax in rate_card.get("taxes", []):
        rate = tax.get("rate")
        ttype = (tax.get("type") or "").lower()
        if rate is not None and "percent" in ttype:
            total += Decimal(str(rate))
    return total if total > 0 else DEFAULT_TAX_RATE


@router.post("/{property_id}/blocks/calculate-yield-loss", response_model=YieldLossEstimate)
async def calculate_yield_loss(
    property_id: str,
    request: BlockRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    YIELD LOSS ENGINE: Intercepts an owner block request and calculates
    the real-time revenue impact using the property's Streamline rate_card
    and historical ADR from actual reservation data.

    This is a read-only estimate — no block is created.
    """
    delta = (request.end_date - request.start_date).days
    if delta <= 0:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    prop_result = await db.execute(
        text("SELECT id, name, rate_card, bedrooms FROM properties WHERE id = :pid"),
        {"pid": property_id},
    )
    prop = prop_result.fetchone()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    rate_card = prop.rate_card or {}
    has_rate_card = isinstance(rate_card, dict) and len(rate_card.get("rates", [])) > 0

    hist_adr_result = await db.execute(
        text("""
            SELECT COALESCE(
                SUM(total_amount) / NULLIF(SUM(nights_count), 0),
                0
            ) AS historical_adr
            FROM reservations
            WHERE property_id = :pid
              AND status != 'cancelled'
              AND nights_count > 0
              AND total_amount > 0
              AND check_in_date >= :lookback_start
        """),
        {
            "pid": property_id,
            "lookback_start": request.start_date - timedelta(days=365),
        },
    )
    historical_adr = Decimal(str(hist_adr_result.scalar() or 0)).quantize(TWO_PLACES)

    BEDROOM_FALLBACK = {
        1: Decimal("149"), 2: Decimal("199"), 3: Decimal("269"),
        4: Decimal("329"), 5: Decimal("399"), 6: Decimal("449"),
        7: Decimal("549"), 8: Decimal("649"),
    }
    bedroom_base = BEDROOM_FALLBACK.get(prop.bedrooms or 3, Decimal("299"))

    nightly_breakdown = []
    base_rent = Decimal("0")
    peak_nights = 0
    current = request.start_date

    while current < request.end_date:
        rate_card_rate = _nightly_from_rate_card(rate_card, current) if has_rate_card else None

        if rate_card_rate and historical_adr > 0:
            nightly_rate = max(rate_card_rate, historical_adr)
        elif rate_card_rate:
            nightly_rate = rate_card_rate
        elif historical_adr > 0:
            nightly_rate = historical_adr
        else:
            nightly_rate = bedroom_base
            if current.weekday() in WEEKEND_DAYS:
                nightly_rate = (nightly_rate * Decimal("1.20")).quantize(TWO_PLACES)
            if current.month in PEAK_MONTHS:
                nightly_rate = (nightly_rate * Decimal("1.15")).quantize(TWO_PLACES)

        is_peak = current.month in PEAK_MONTHS
        if is_peak:
            peak_nights += 1

        nightly_breakdown.append({
            "date": current.isoformat(),
            "rate": float(nightly_rate),
            "source": "rate_card" if rate_card_rate else ("historical_adr" if historical_adr > 0 else "bedroom_fallback"),
            "is_peak": is_peak,
        })
        base_rent += nightly_rate
        current += timedelta(days=1)

    cleaning_fee = _fees_from_rate_card(rate_card) if has_rate_card else Decimal("250")
    tax_rate = _tax_rate_from_rate_card(rate_card)
    taxable = base_rent + cleaning_fee
    tax_estimate = (taxable * tax_rate).quantize(TWO_PLACES)
    total_loss = base_rent + cleaning_fee + tax_estimate
    projected_adr = (base_rent / Decimal(str(delta))).quantize(TWO_PLACES) if delta > 0 else Decimal("0")
    demand_alert = peak_nights > (delta / 2)

    logger.info(
        "yield_loss_calculated",
        property_id=property_id,
        nights=delta,
        projected_adr=float(projected_adr),
        gross_loss=float(base_rent),
        total_loss=float(total_loss),
        demand_alert=demand_alert,
    )

    return YieldLossEstimate(
        property_id=property_id,
        property_name=prop.name or "Unknown",
        requested_nights=delta,
        projected_adr=float(projected_adr),
        gross_revenue_loss=float(base_rent),
        cleaning_fee=float(cleaning_fee),
        tax_estimate=float(tax_estimate),
        total_estimated_loss=float(total_loss),
        demand_alert=demand_alert,
        peak_nights=peak_nights,
        warning_message=(
            f"Blocking these {delta} nights will result in an estimated "
            f"${float(total_loss):,.2f} loss in Gross Rental Revenue "
            f"based on current market pacing."
        ),
        nightly_breakdown=nightly_breakdown,
    )


# ============================================================================
# OWNER BLOCK CRUD — Create, List, Delete Owner Holds
# ============================================================================

@router.get("/{property_id}/blocks")
async def list_owner_blocks(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all owner hold blocks for a property."""
    result = await db.execute(
        text("""
            SELECT id, start_date, end_date, block_type, source, created_at
            FROM blocked_days
            WHERE property_id = :pid AND block_type = 'owner_hold'
            ORDER BY start_date
        """),
        {"pid": property_id},
    )
    return {
        "blocks": [
            {
                "id": str(row.id),
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "block_type": row.block_type,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]
    }


@router.post("/{property_id}/blocks")
async def create_owner_block(
    property_id: str,
    request: BlockRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create an owner hold block after the yield loss intercept.
    Validates no overlap with existing reservations.
    """
    delta = (request.end_date - request.start_date).days
    if delta <= 0:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    conflict = await db.execute(
        text("""
            SELECT COUNT(*) FROM reservations
            WHERE property_id = :pid
              AND status IN ('confirmed', 'checked_in')
              AND check_in_date < :end_date
              AND check_out_date > :start_date
        """),
        {"pid": property_id, "start_date": request.start_date, "end_date": request.end_date},
    )
    if (conflict.scalar() or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot block dates that overlap with confirmed reservations.",
        )

    await db.execute(
        text("""
            INSERT INTO blocked_days (id, property_id, start_date, end_date, block_type, source, created_at)
            VALUES (gen_random_uuid(), :pid, :start, :end, 'owner_hold', 'owner_portal', NOW())
            ON CONFLICT (property_id, start_date, end_date, block_type) DO NOTHING
        """),
        {"pid": property_id, "start": request.start_date, "end": request.end_date},
    )
    await db.commit()

    logger.info(
        "owner_block_created",
        property_id=property_id,
        start=request.start_date.isoformat(),
        end=request.end_date.isoformat(),
        reason=request.reason,
    )

    await publish_inventory_availability_changed(
        str(property_id),
        reason="owner_calendar_block",
        source="owner_portal",
        extra={
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        },
    )

    return {
        "status": "blocked",
        "property_id": property_id,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "nights": delta,
    }


@router.delete("/{property_id}/blocks/{block_id}")
async def delete_owner_block(
    property_id: str,
    block_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Remove an owner hold. Only owner_hold blocks can be deleted via this endpoint."""
    result = await db.execute(
        text("""
            DELETE FROM blocked_days
            WHERE id = :bid AND property_id = :pid AND block_type = 'owner_hold'
            RETURNING id
        """),
        {"bid": block_id, "pid": property_id},
    )
    deleted = result.fetchone()
    await db.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Owner block not found")

    logger.info("owner_block_deleted", property_id=property_id, block_id=block_id)

    await publish_inventory_availability_changed(
        str(property_id),
        reason="owner_calendar_unblock",
        source="owner_portal",
        extra={"block_id": block_id},
    )

    return {"status": "unblocked", "block_id": block_id}


# ============================================================================
# ENHANCED CALENDAR — Merged reservations + blocks + nightly rates
# ============================================================================

@router.get("/{property_id}/calendar")
async def owner_calendar(
    property_id: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Merged calendar returning reservations, owner holds, and per-day
    nightly rates from rate_card so the Glass can render a full-context
    interactive calendar.
    """
    today = _et_today()
    start_date = date.fromisoformat(start) if start else today - timedelta(days=7)
    end_date = date.fromisoformat(end) if end else today + timedelta(days=90)

    prop_result = await db.execute(
        text("SELECT id, name, rate_card, bedrooms FROM properties WHERE id = :pid"),
        {"pid": property_id},
    )
    prop = prop_result.fetchone()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    rate_card = prop.rate_card or {}
    has_rate_card = isinstance(rate_card, dict) and len(rate_card.get("rates", [])) > 0

    BEDROOM_FALLBACK = {
        1: Decimal("149"), 2: Decimal("199"), 3: Decimal("269"),
        4: Decimal("329"), 5: Decimal("399"), 6: Decimal("449"),
        7: Decimal("549"), 8: Decimal("649"),
    }
    bedroom_base = BEDROOM_FALLBACK.get(prop.bedrooms or 3, Decimal("299"))

    res_result = await db.execute(
        text("""
            SELECT id, confirmation_code, guest_id, check_in_date, check_out_date,
                   status, total_amount, nightly_rate, nights_count
            FROM reservations
            WHERE property_id = :pid
              AND status != 'cancelled'
              AND check_in_date <= :end AND check_out_date >= :start
            ORDER BY check_in_date
        """),
        {"pid": property_id, "start": start_date, "end": end_date},
    )
    reservations = res_result.fetchall()

    block_result = await db.execute(
        text("""
            SELECT id, start_date, end_date, block_type, source
            FROM blocked_days
            WHERE property_id = :pid
              AND start_date <= :end AND end_date >= :start
            ORDER BY start_date
        """),
        {"pid": property_id, "start": start_date, "end": end_date},
    )
    blocks = block_result.fetchall()

    booked_map: Dict[date, dict] = {}
    for r in reservations:
        cursor = max(r.check_in_date, start_date)
        r_end = min(r.check_out_date, end_date + timedelta(days=1))
        while cursor < r_end:
            booked_map[cursor] = {
                "reservation_id": str(r.id),
                "confirmation_code": r.confirmation_code,
                "status": r.status,
            }
            cursor += timedelta(days=1)

    blocked_map: Dict[date, dict] = {}
    for b in blocks:
        cursor = max(b.start_date, start_date)
        b_end = min(b.end_date, end_date + timedelta(days=1))
        while cursor < b_end:
            blocked_map[cursor] = {
                "block_id": str(b.id),
                "block_type": b.block_type,
                "source": b.source,
            }
            cursor += timedelta(days=1)

    days: Dict[str, dict] = {}
    cursor = start_date
    while cursor <= end_date:
        iso = cursor.isoformat()

        rate_card_rate = _nightly_from_rate_card(rate_card, cursor) if has_rate_card else None
        if rate_card_rate is None:
            rate_card_rate = bedroom_base
            if cursor.weekday() in WEEKEND_DAYS:
                rate_card_rate = (rate_card_rate * Decimal("1.20")).quantize(TWO_PLACES)
            if cursor.month in PEAK_MONTHS:
                rate_card_rate = (rate_card_rate * Decimal("1.15")).quantize(TWO_PLACES)

        if cursor in booked_map:
            days[iso] = {
                "status": "booked",
                "nightly_rate": float(rate_card_rate),
                "is_peak": cursor.month in PEAK_MONTHS,
                **booked_map[cursor],
            }
        elif cursor in blocked_map:
            days[iso] = {
                "status": "blocked",
                "nightly_rate": float(rate_card_rate),
                "is_peak": cursor.month in PEAK_MONTHS,
                **blocked_map[cursor],
            }
        else:
            days[iso] = {
                "status": "available",
                "nightly_rate": float(rate_card_rate),
                "is_peak": cursor.month in PEAK_MONTHS,
            }

        cursor += timedelta(days=1)

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": days,
        "reservations": [
            {
                "id": str(r.id),
                "confirmation_code": r.confirmation_code,
                "check_in_date": r.check_in_date.isoformat(),
                "check_out_date": r.check_out_date.isoformat(),
                "status": r.status,
                "total_amount": float(r.total_amount or 0),
            }
            for r in reservations
        ],
        "blocks": [
            {
                "id": str(b.id),
                "start_date": b.start_date.isoformat(),
                "end_date": b.end_date.isoformat(),
                "block_type": b.block_type,
                "source": b.source,
            }
            for b in blocks
        ],
    }


# ============================================================================
# CAPEX APPROVAL GATE — High-ticket invoice staging for owner authorization
# ============================================================================

@router.get("/{property_id}/capex/pending")
async def list_pending_capex(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all pending CapEx invoices awaiting owner approval."""
    result = await db.execute(
        text("""
            SELECT id, property_id, vendor, amount, total_owner_charge,
                   description, journal_lines, audit_trail, created_at
            FROM capex_staging
            WHERE property_id = :pid AND compliance_status = 'PENDING_CAPEX_APPROVAL'
            ORDER BY created_at DESC
        """),
        {"pid": property_id},
    )
    return {
        "pending": [
            {
                "id": row.id,
                "property_id": row.property_id,
                "vendor": row.vendor,
                "amount": float(row.amount),
                "total_owner_charge": float(row.total_owner_charge),
                "description": row.description,
                "journal_lines": row.journal_lines,
                "audit_trail": row.audit_trail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]
    }


@router.post("/{property_id}/capex/{staging_id}/approve")
async def approve_capex(
    property_id: str,
    staging_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Owner approves a staged CapEx invoice.
    Moves the pre-computed journal lines into the Iron Dome ledger.
    """
    row = await db.execute(
        text("""
            SELECT id, property_id, vendor, amount, total_owner_charge,
                   description, journal_lines, compliance_status
            FROM capex_staging
            WHERE id = :sid AND property_id = :pid
        """),
        {"sid": staging_id, "pid": property_id},
    )
    staging = row.fetchone()

    if not staging:
        raise HTTPException(status_code=404, detail="CapEx staging record not found")
    if staging.compliance_status != "PENDING_CAPEX_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve — current status is '{staging.compliance_status}'",
        )

    journal_lines = staging.journal_lines
    if not journal_lines or not isinstance(journal_lines, list):
        raise HTTPException(status_code=422, detail="No valid journal lines to commit")

    je_result = await db.execute(
        text("""
            INSERT INTO journal_entries
                (property_id, entry_date, description, reference_type, reference_id, is_void)
            VALUES (:pid, CURRENT_DATE, :desc, 'capex_approval', :ref, FALSE)
            RETURNING id
        """),
        {
            "pid": property_id,
            "desc": f"CAPEX APPROVED: {staging.vendor} — ${float(staging.total_owner_charge):.2f}",
            "ref": str(staging_id),
        },
    )
    je_id = je_result.scalar()

    for line in journal_lines:
        code = str(line.get("code", ""))
        line_type = (line.get("type") or "").lower()
        amount = Decimal(str(line.get("amount", 0))).quantize(TWO_PLACES)

        acct_result = await db.execute(
            text("SELECT id FROM accounts WHERE code = :code"),
            {"code": code},
        )
        acct_id = acct_result.scalar()
        if not acct_id:
            logger.warning("capex_approve_unknown_account", code=code)
            continue

        await db.execute(
            text("""
                INSERT INTO journal_line_items
                    (journal_entry_id, account_id, debit, credit)
                VALUES (:je_id, :acct_id, :debit, :credit)
            """),
            {
                "je_id": je_id,
                "acct_id": acct_id,
                "debit": float(amount) if line_type == "debit" else 0,
                "credit": float(amount) if line_type == "credit" else 0,
            },
        )

    await db.execute(
        text("""
            UPDATE capex_staging
            SET compliance_status = 'APPROVED',
                approved_by = 'owner_portal',
                approved_at = NOW()
            WHERE id = :sid
        """),
        {"sid": staging_id},
    )
    await db.commit()

    logger.info(
        "capex_approved",
        staging_id=staging_id,
        property_id=property_id,
        vendor=staging.vendor,
        amount=float(staging.total_owner_charge),
    )

    return {
        "status": "approved",
        "staging_id": staging_id,
        "journal_entry_id": je_id,
        "vendor": staging.vendor,
        "amount": float(staging.total_owner_charge),
    }


@router.post("/{property_id}/capex/{staging_id}/reject")
async def reject_capex(
    property_id: str,
    staging_id: int,
    reason: str = Query("Owner declined"),
    db: AsyncSession = Depends(get_db),
):
    """Owner rejects a staged CapEx invoice. No journal entry is created."""
    result = await db.execute(
        text("""
            UPDATE capex_staging
            SET compliance_status = 'REJECTED',
                rejected_by = 'owner_portal',
                rejected_at = NOW(),
                rejection_reason = :reason
            WHERE id = :sid AND property_id = :pid
              AND compliance_status = 'PENDING_CAPEX_APPROVAL'
            RETURNING id, vendor, total_owner_charge
        """),
        {"sid": staging_id, "pid": property_id, "reason": reason},
    )
    rejected = result.fetchone()
    await db.commit()

    if not rejected:
        raise HTTPException(status_code=404, detail="Pending CapEx not found or already processed")

    logger.info(
        "capex_rejected",
        staging_id=staging_id,
        property_id=property_id,
        vendor=rejected.vendor,
        reason=reason,
    )

    return {
        "status": "rejected",
        "staging_id": staging_id,
        "vendor": rejected.vendor,
        "amount": float(rejected.total_owner_charge),
        "reason": reason,
    }


# ============================================================================
# FIDUCIARY CONCIERGE — AI Chat with Information Wall Enforcement
# ============================================================================
# Uses SWARM (qwen2.5:7b) via local Ollama. Financial data stays on-premise.
# The Information Wall hides accounts 2100 (vendor AP) and 4100 (PM overhead).

CONCIERGE_SYSTEM_PROMPT = """\
You are the Fiduciary Concierge for Cabin Rentals of Georgia's Owner Portal.
You answer owner questions about their property finances, reservations,
maintenance, and management contract terms using ONLY the context provided below.

RULES (non-negotiable):
- Answer ONLY from the provided context. Never fabricate data.
- NEVER reveal internal account codes (2100, 4100) or their purposes.
- NEVER mention "markup", "overhead", "PM commission", or "management fee percentage".
- All maintenance charges shown to owners are the TOTAL cost to the owner.
  Do not break them down into vendor cost vs. markup.
- Be polite, precise with dollar amounts, and concise.
- If you don't know the answer from the context, say so honestly.
- Format currency as $X,XXX.XX. Use bullet points for lists.
- When referencing management contracts or legal documents, cite the source
  file name, e.g. [Source: filename.pdf].
- Contract clauses take precedence over general knowledge for owner-specific questions.
"""


class UpgradeAuthorization(BaseModel):
    project_name: str
    estimated_cost: float
    projected_adr_lift: float


@router.get("/{property_id}/roi-simulator")
async def get_roi_simulations(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    SOTA WEALTH MULTIPLIER: Identifies missing high-yield amenities,
    calculates the Blue Ridge market ADR lift, and projects a 5-year ROI.

    Phase 1 uses curated Blue Ridge market intelligence. Phase 2 will
    pipe live amenity gap analysis from the DGX Swarm.
    """
    TWO_PLACES = Decimal("0.01")

    prop_result = await db.execute(
        text("SELECT bedrooms, amenities, rate_card FROM properties WHERE id = :pid"),
        {"pid": property_id},
    )
    prop_row = prop_result.first()
    bedrooms = int(prop_row.bedrooms) if prop_row and prop_row.bedrooms else 3
    amenities_raw = prop_row.amenities if prop_row else None
    existing_amenities_lower: set = set()
    if amenities_raw and isinstance(amenities_raw, list):
        for a in amenities_raw:
            name = ""
            if isinstance(a, dict):
                name = (a.get("amenity_name") or a.get("name") or "").strip()
            elif isinstance(a, str):
                name = a.strip()
            if name:
                existing_amenities_lower.add(name.lower())

    lookback = date.today() - timedelta(days=365)
    perf = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(total_amount), 0) AS annual_revenue,
                COALESCE(SUM(nights_count), 0)  AS annual_nights,
                COALESCE(
                    SUM(total_amount) / NULLIF(SUM(nights_count), 0), 0
                ) AS hist_adr
            FROM reservations
            WHERE property_id = :pid
              AND status != 'cancelled'
              AND nights_count > 0
              AND total_amount > 0
              AND check_in_date >= :lb
        """),
        {"pid": property_id, "lb": lookback},
    )
    perf_row = perf.first()
    annual_revenue = float(perf_row.annual_revenue) if perf_row else 0
    annual_nights = int(perf_row.annual_nights) if perf_row else 0
    current_adr = float(perf_row.hist_adr) if perf_row else 0

    bedroom_fallback = {
        1: 149, 2: 199, 3: 269, 4: 329, 5: 399, 6: 449, 7: 549,
    }
    if current_adr <= 0:
        current_adr = bedroom_fallback.get(bedrooms, 329)
    if annual_nights <= 0:
        annual_nights = 210

    occupancy_pct = round(annual_nights / 365 * 100, 1)

    market_benchmarks = {
        1: {"avg_rate": 160, "occupancy": 58},
        2: {"avg_rate": 215, "occupancy": 62},
        3: {"avg_rate": 290, "occupancy": 65},
        4: {"avg_rate": 375, "occupancy": 60},
        5: {"avg_rate": 480, "occupancy": 55},
        6: {"avg_rate": 580, "occupancy": 50},
        7: {"avg_rate": 700, "occupancy": 45},
    }
    bench = market_benchmarks.get(bedrooms, market_benchmarks[3])
    market_adr = bench["avg_rate"]
    adr_vs_market = round((current_adr - market_adr) / market_adr * 100, 1) if market_adr else 0

    upgrade_catalog = [
        {
            "id": "upg_firepit_01",
            "project_name": "Flagstone Fire Pit & Seating Area",
            "category": "outdoor",
            "icon": "flame",
            "description": (
                "High-demand fall/winter amenity. Market data shows properties "
                "in Blue Ridge with fire pits capture a 12% ADR premium."
            ),
            "estimated_cost": 4500.00,
            "adr_impact": 42.00,
            "occupancy_impact_pct": 3.0,
            "keywords": ["fire pit", "firepit", "fire-pit"],
        },
        {
            "id": "upg_hottub_02",
            "project_name": "Premium 6-Person Hot Tub Installation",
            "category": "amenity",
            "icon": "waves",
            "description": (
                "The #1 requested cabin amenity. Increases winter occupancy "
                "by an estimated 18% and lifts base ADR."
            ),
            "estimated_cost": 8200.00,
            "adr_impact": 65.00,
            "occupancy_impact_pct": 5.0,
            "keywords": ["hot tub", "hottub", "jacuzzi", "spa"],
        },
        {
            "id": "upg_gameroom_03",
            "project_name": "Basement Arcade & Billiards Conversion",
            "category": "amenity",
            "icon": "gamepad-2",
            "description": (
                "Converts unused square footage into a family-friendly draw. "
                "Crucial for maximizing summer yields."
            ),
            "estimated_cost": 12500.00,
            "adr_impact": 85.00,
            "occupancy_impact_pct": 4.0,
            "keywords": ["game room", "pool table", "arcade", "billiards"],
        },
        {
            "id": "upg_theater_04",
            "project_name": "Home Theater / Media Room",
            "category": "luxury",
            "icon": "monitor-play",
            "description": (
                "Premium entertainment upgrade. Properties with dedicated theater "
                "rooms see 15% higher repeat booking rates."
            ),
            "estimated_cost": 8500.00,
            "adr_impact": 45.00,
            "occupancy_impact_pct": 3.0,
            "keywords": ["theater", "theatre", "media room", "home theater"],
        },
        {
            "id": "upg_ev_05",
            "project_name": "EV Charging Station (Level 2)",
            "category": "technology",
            "icon": "zap",
            "description": (
                "EV ownership is surging. A Level 2 charger unlocks a growing "
                "demographic of high-income guests."
            ),
            "estimated_cost": 2200.00,
            "adr_impact": 15.00,
            "occupancy_impact_pct": 2.0,
            "keywords": ["ev charger", "ev charging", "tesla", "electric vehicle"],
        },
        {
            "id": "upg_sauna_06",
            "project_name": "Barrel Sauna Installation",
            "category": "luxury",
            "icon": "thermometer",
            "description": (
                "Luxury wellness amenity with high social media shareability. "
                "Barrel saunas are the fastest-growing cabin amenity in North GA."
            ),
            "estimated_cost": 6500.00,
            "adr_impact": 50.00,
            "occupancy_impact_pct": 2.0,
            "keywords": ["sauna", "steam room", "barrel sauna"],
        },
    ]

    opportunities = []
    for upg in upgrade_catalog:
        has_already = any(
            kw in am for kw in upg["keywords"] for am in existing_amenities_lower
        )
        if has_already:
            continue

        proj_adr = current_adr + upg["adr_impact"]
        proj_occ = min(occupancy_pct + upg["occupancy_impact_pct"], 95.0)
        proj_nights = round(proj_occ / 100 * 365)
        added_annual = round(proj_adr * proj_nights - current_adr * annual_nights, 2)
        if added_annual <= 0:
            added_annual = round(upg["adr_impact"] * annual_nights, 2)
        monthly_add = added_annual / 12
        payback = round(upg["estimated_cost"] / monthly_add, 1) if monthly_add > 0 else 99.9
        roi_5y = round((5 * added_annual - upg["estimated_cost"]) / upg["estimated_cost"] * 100, 1)

        opportunities.append({
            "id": upg["id"],
            "project_name": upg["project_name"],
            "category": upg["category"],
            "icon": upg["icon"],
            "description": upg["description"],
            "estimated_cost": upg["estimated_cost"],
            "projected_adr_lift": round(upg["adr_impact"], 2),
            "added_annual_revenue": added_annual,
            "payback_period_months": payback,
            "five_year_roi_pct": roi_5y,
        })

    opportunities.sort(key=lambda x: x["payback_period_months"])

    return {
        "property_id": property_id,
        "current_adr": round(current_adr, 2),
        "current_occupancy_pct": occupancy_pct,
        "annual_occupancy_days": annual_nights,
        "annual_revenue": round(annual_revenue, 2),
        "market_adr": market_adr,
        "adr_vs_market_pct": adr_vs_market,
        "bedrooms": bedrooms,
        "opportunities": opportunities,
    }


@router.post("/{property_id}/capex/authorize-upgrade")
async def authorize_strategic_upgrade(
    property_id: str,
    req: UpgradeAuthorization,
    db: AsyncSession = Depends(get_db),
):
    """
    THE KILLSHOT: The owner clicks 'Authorize'. This writes to capex_staging
    as APPROVED, alerting CROG Development to begin the project.
    """
    journal_lines = json.dumps([
        {"code": "5010", "type": "debit", "amount": req.estimated_cost},
        {"code": "1000", "type": "credit", "amount": req.estimated_cost},
    ])
    audit_trail = json.dumps([
        f"Owner authorized strategic upgrade: {req.project_name}",
        f"Estimated cost: ${req.estimated_cost:,.2f}",
        f"Projected ADR lift: +${req.projected_adr_lift}/night",
    ])

    result = await db.execute(
        text("""
            INSERT INTO capex_staging
                (property_id, vendor, amount, total_owner_charge,
                 description, journal_lines, compliance_status,
                 audit_trail, approved_by, approved_at)
            VALUES
                (:pid, 'CROG Development (Internal)', :amt, :amt,
                 :desc, CAST(:jl AS jsonb), 'APPROVED',
                 CAST(:audit AS jsonb), 'owner', NOW())
            RETURNING id
        """),
        {
            "pid": property_id,
            "amt": req.estimated_cost,
            "desc": f"STRATEGIC UPGRADE: {req.project_name} (Projected Lift: +${req.projected_adr_lift}/night)",
            "jl": journal_lines,
            "audit": audit_trail,
        },
    )
    await db.commit()
    capex_id = result.scalar()

    logger.info(
        "strategic_upgrade_authorized",
        property_id=property_id,
        project=req.project_name,
        cost=req.estimated_cost,
        capex_id=capex_id,
    )

    return {
        "status": "authorized",
        "capex_id": capex_id,
        "project_name": req.project_name,
        "estimated_cost": req.estimated_cost,
        "message": f"CROG Development has been dispatched for: {req.project_name}",
    }


@router.get("/{property_id}/iot/status")
async def get_iot_telemetry(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    SOTA DIGITAL TWIN: Exposes real-time cabin telemetry to the Owner Glass.
    Strictly read-only — owners observe, only the Swarm/Admin can command.
    """
    devices_result = await db.execute(
        text("""
            SELECT device_id, device_type, device_name,
                   state_json, battery_level, is_online, last_event_ts
            FROM iot_schema.digital_twins
            WHERE property_id = :pid
            ORDER BY device_type, device_name
        """),
        {"pid": property_id},
    )
    devices = devices_result.fetchall()

    events_result = await db.execute(
        text("""
            SELECT e.device_id, e.event_type, e.payload, e.created_at
            FROM iot_schema.device_events e
            JOIN iot_schema.digital_twins d ON d.device_id = e.device_id
            WHERE d.property_id = :pid
            ORDER BY e.created_at DESC
            LIMIT 20
        """),
        {"pid": property_id},
    )
    events = events_result.fetchall()

    if not devices:
        return {
            "property_id": property_id,
            "total_devices": 4,
            "online_count": 4,
            "critical_battery": 0,
            "thermostat": {
                "device_name": "Main Floor Thermostat",
                "current_temp": 72,
                "target_temp": 70,
                "mode": "heat",
                "hvac_state": "idle",
                "humidity": 45,
                "is_online": True,
            },
            "locks": [
                {"device_name": "Front Door (Yale Assure)", "lock_state": "LOCKED", "battery": 88, "is_online": True},
                {"device_name": "Garage Entry (Yale)", "lock_state": "LOCKED", "battery": 72, "is_online": True},
            ],
            "sensors": [
                {"device_name": "Water Heater Sensor", "sensor_type": "leak", "status": "dry", "is_online": True},
            ],
            "cameras": [
                {"device_name": "Driveway Camera", "status": "active", "is_online": True},
            ],
            "recent_events": [],
            "simulated": True,
        }

    thermostat = None
    locks: list = []
    sensors: list = []
    cameras: list = []
    total = len(devices)
    online_count = 0
    critical_battery = 0

    for d in devices:
        state = d.state_json if isinstance(d.state_json, dict) else {}
        if d.is_online:
            online_count += 1
        if d.battery_level is not None and d.battery_level < 20:
            critical_battery += 1

        if d.device_type == "thermostat":
            thermostat = {
                "device_name": d.device_name or "Thermostat",
                "current_temp": state.get("current_temp") or state.get("temp"),
                "target_temp": state.get("target_temp") or state.get("target"),
                "mode": state.get("mode", "auto"),
                "hvac_state": state.get("hvac_state", "idle"),
                "humidity": state.get("humidity"),
                "is_online": d.is_online,
            }
        elif d.device_type == "smart_lock":
            locks.append({
                "device_name": d.device_name or "Lock",
                "lock_state": state.get("lock_state", "UNKNOWN"),
                "battery": d.battery_level,
                "is_online": d.is_online,
                "last_user": state.get("last_user"),
            })
        elif d.device_type in ("leak_sensor", "moisture_sensor", "noise_monitor"):
            sensors.append({
                "device_name": d.device_name or "Sensor",
                "sensor_type": d.device_type,
                "status": state.get("status", "nominal"),
                "is_online": d.is_online,
            })
        elif d.device_type == "camera":
            cameras.append({
                "device_name": d.device_name or "Camera",
                "status": state.get("status", "active"),
                "is_online": d.is_online,
            })

    recent_events = []
    for e in events:
        recent_events.append({
            "device_id": e.device_id,
            "event_type": e.event_type,
            "payload": e.payload if isinstance(e.payload, dict) else {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })

    return {
        "property_id": property_id,
        "total_devices": total,
        "online_count": online_count,
        "critical_battery": critical_battery,
        "thermostat": thermostat,
        "locks": locks,
        "sensors": sensors,
        "cameras": cameras,
        "recent_events": recent_events,
        "simulated": False,
    }


class PayoutSetupRequest(BaseModel):
    owner_email: str


@router.post("/{property_id}/payouts/setup")
async def setup_payout_account(
    property_id: str,
    req: PayoutSetupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    CONTINUOUS LIQUIDITY: Initiate Stripe Connect onboarding for the property owner.
    Creates a connected account and returns the onboarding URL.
    """
    from backend.services.payout_service import (
        create_connect_account,
        create_onboarding_link,
    )

    prop_result = await db.execute(
        text("SELECT owner_name FROM properties WHERE id = :pid"),
        {"pid": property_id},
    )
    prop_row = prop_result.first()
    owner_name = prop_row.owner_name if prop_row else "Property Owner"

    existing = await db.execute(
        text("SELECT stripe_account_id, account_status FROM owner_payout_accounts WHERE property_id = :pid"),
        {"pid": property_id},
    )
    existing_row = existing.first()

    if existing_row and existing_row.stripe_account_id:
        onboarding_url = await create_onboarding_link(
            existing_row.stripe_account_id,
            f"{settings.frontend_url}/owner",
        )
        return {
            "status": existing_row.account_status,
            "onboarding_url": onboarding_url,
            "message": "Account already exists. Complete onboarding at the link.",
        }

    result = await create_connect_account(owner_name, req.owner_email)
    if not result:
        return {
            "status": "not_configured",
            "message": "Stripe is not configured. Payouts will use the legacy end-of-month ACH batch.",
        }

    await db.execute(
        text("""
            INSERT INTO owner_payout_accounts
                (property_id, owner_name, owner_email, stripe_account_id, account_status)
            VALUES (:pid, :name, :email, :acct_id, 'onboarding')
            ON CONFLICT (property_id) DO UPDATE SET
                stripe_account_id = EXCLUDED.stripe_account_id,
                account_status = 'onboarding',
                updated_at = NOW()
        """),
        {
            "pid": property_id,
            "name": owner_name,
            "email": req.owner_email,
            "acct_id": result["account_id"],
        },
    )
    await db.commit()

    onboarding_url = await create_onboarding_link(
        result["account_id"],
        f"{settings.frontend_url}/owner",
    )

    return {
        "status": "onboarding",
        "onboarding_url": onboarding_url,
        "message": "Stripe Connect account created. Complete onboarding to enable instant payouts.",
    }


@router.get("/{property_id}/payouts/account-status")
async def get_payout_account_status(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Check the Stripe Connect account status for this property."""
    result = await db.execute(
        text("""
            SELECT stripe_account_id, account_status, owner_email, instant_payout, created_at
            FROM owner_payout_accounts
            WHERE property_id = :pid
        """),
        {"pid": property_id},
    )
    row = result.first()
    if not row or not row.stripe_account_id:
        return {
            "has_account": False,
            "account_status": "none",
            "instant_payout": False,
            "message": "No payout account configured. Enable Continuous Liquidity to get paid instantly.",
        }

    from backend.services.payout_service import check_account_status

    live_status = await check_account_status(row.stripe_account_id)

    if live_status.get("status") == "active" and row.account_status != "active":
        await db.execute(
            text("UPDATE owner_payout_accounts SET account_status = 'active', updated_at = NOW() WHERE property_id = :pid"),
            {"pid": property_id},
        )
        await db.commit()

    return {
        "has_account": True,
        "account_status": live_status.get("status", row.account_status),
        "instant_payout": row.instant_payout,
        "owner_email": row.owner_email,
        "charges_enabled": live_status.get("charges_enabled", False),
        "payouts_enabled": live_status.get("payouts_enabled", False),
    }


@router.get("/{property_id}/payouts")
async def get_payout_history(
    property_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List payout history for this property."""
    result = await db.execute(
        text("""
            SELECT id, confirmation_code, gross_amount, owner_amount,
                   stripe_transfer_id, status, initiated_at, completed_at,
                   failure_reason, created_at
            FROM payout_ledger
            WHERE property_id = :pid
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"pid": property_id},
    )
    rows = result.fetchall()

    total_paid = 0.0
    pending_count = 0
    payouts = []
    for r in rows:
        payout = {
            "id": r.id,
            "confirmation_code": r.confirmation_code,
            "gross_amount": float(r.gross_amount),
            "owner_amount": float(r.owner_amount),
            "status": r.status,
            "stripe_transfer_id": r.stripe_transfer_id,
            "initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        payouts.append(payout)
        if r.status == "completed":
            total_paid += float(r.owner_amount)
        elif r.status in ("staged", "processing"):
            pending_count += 1

    return {
        "property_id": property_id,
        "total_paid_out": round(total_paid, 2),
        "pending_count": pending_count,
        "payout_count": len(payouts),
        "payouts": payouts,
    }


class ConciergeRequest(BaseModel):
    question: str
    messages: Optional[List[Dict[str, str]]] = None


@router.post("/{property_id}/concierge")
async def fiduciary_concierge(
    property_id: str,
    req: ConciergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE-streaming AI concierge for owner queries.
    Gathers context from the Iron Dome (account 2000 only), trust balances,
    recent reservations, and work orders, then streams the LLM response.
    """
    today = _et_today()

    try:
        iron_dome = await db.execute(
            text("""
                SELECT je.entry_date, je.description, jli.debit AS total_charge
                FROM journal_entries je
                JOIN journal_line_items jli ON je.id = jli.journal_entry_id
                WHERE je.property_id = :pid
                  AND je.is_void = FALSE
                  AND jli.account_id = (SELECT id FROM accounts WHERE code = '2000')
                  AND jli.debit > 0
                ORDER BY je.entry_date DESC
                LIMIT 20
            """),
            {"pid": property_id},
        )
        iron_dome_lines = [
            f"  {r.entry_date.isoformat()} | {r.description} | ${float(r.total_charge):.2f}"
            for r in iron_dome.fetchall()
        ]
    except Exception:
        iron_dome_lines = []

    try:
        trust_result = await db.execute(
            text("SELECT * FROM trust_balance_cache WHERE property_id = :pid"),
            {"pid": property_id},
        )
        trust_row = trust_result.fetchone()
        trust_ctx = ""
        if trust_row:
            trust_ctx = (
                f"  Owner Funds: ${float(trust_row.owner_funds or 0):,.2f}\n"
                f"  Operating Funds: ${float(trust_row.operating_funds or 0):,.2f}\n"
                f"  Escrow: ${float(trust_row.escrow_funds or 0):,.2f}\n"
                f"  Security Deposits: ${float(trust_row.security_deps or 0):,.2f}"
            )
    except Exception:
        trust_ctx = ""

    try:
        res_result = await db.execute(
            text("""
                SELECT confirmation_code, check_in_date, check_out_date,
                       total_amount, status
                FROM reservations
                WHERE property_id = :pid AND check_in_date >= :since
                  AND status != 'cancelled'
                ORDER BY check_in_date DESC
                LIMIT 15
            """),
            {"pid": property_id, "since": today - timedelta(days=90)},
        )
        res_lines = [
            f"  {r.confirmation_code} | {r.check_in_date} - {r.check_out_date} | "
            f"${float(r.total_amount or 0):,.2f} | {r.status}"
            for r in res_result.fetchall()
        ]
    except Exception:
        res_lines = []

    try:
        wo_result = await db.execute(
            text("""
                SELECT title, status, created_at
                FROM work_orders
                WHERE property_id = :pid
                ORDER BY created_at DESC
                LIMIT 10
            """),
            {"pid": property_id},
        )
        wo_lines = [
            f"  {r.title} | {r.status} | {r.created_at.strftime('%Y-%m-%d') if r.created_at else 'N/A'}"
            for r in wo_result.fetchall()
        ]
    except Exception:
        wo_lines = []

    try:
        capex_result = await db.execute(
            text("""
                SELECT vendor, total_owner_charge, description, compliance_status, created_at
                FROM capex_staging
                WHERE property_id = :pid
                ORDER BY created_at DESC
                LIMIT 5
            """),
            {"pid": property_id},
        )
        capex_lines = [
            f"  {r.vendor} | ${float(r.total_owner_charge):,.2f} | {r.description} | {r.compliance_status}"
            for r in capex_result.fetchall()
        ]
    except Exception:
        capex_lines = []

    # ── RAG: Retrieve management contract context + KB context ──
    owner_id = None
    try:
        owner_row = await db.execute(
            text("SELECT owner_id FROM properties WHERE id::text = :pid OR streamline_property_id = :pid LIMIT 1"),
            {"pid": property_id},
        )
        owner_id = owner_row.scalar()
    except Exception:
        pass

    legal_ctx = ""
    kb_ctx = ""
    try:
        legal_hits = await legal_library_search(
            req.question, owner_id=str(owner_id) if owner_id else None, top_k=5
        )
        legal_ctx = format_legal_context(legal_hits)
    except Exception as e:
        logger.warning("concierge_legal_rag_failed", error=str(e)[:200])

    try:
        kb_hits = await semantic_search(req.question, db, property_id=None, top_k=3)
        kb_ctx = format_kb_context(kb_hits)
    except Exception as e:
        logger.warning("concierge_kb_rag_failed", error=str(e)[:200])

    context = (
        f"PROPERTY: {property_id}\n"
        f"DATE: {today.isoformat()}\n\n"
        f"TRUST ACCOUNT BALANCES:\n{trust_ctx or '  No trust data available.'}\n\n"
        f"RECENT MAINTENANCE CHARGES (total owner cost):\n"
        + ("\n".join(iron_dome_lines) or "  No recent charges.") + "\n\n"
        f"RECENT RESERVATIONS (last 90 days):\n"
        + ("\n".join(res_lines) or "  No recent reservations.") + "\n\n"
        f"WORK ORDERS:\n"
        + ("\n".join(wo_lines) or "  No work orders.") + "\n\n"
        f"PENDING CAPEX APPROVALS:\n"
        + ("\n".join(capex_lines) or "  No pending approvals.") + "\n"
    )
    if legal_ctx:
        context += f"\nMANAGEMENT CONTRACT CONTEXT:\n{legal_ctx}\n"
    if kb_ctx:
        context += f"\nKNOWLEDGE BASE CONTEXT:\n{kb_ctx}\n"

    conversation = [{"role": "system", "content": CONCIERGE_SYSTEM_PROMPT + "\n\nCONTEXT:\n" + context}]
    if req.messages:
        conversation.extend(req.messages[-10:])
    conversation.append({"role": "user", "content": req.question})

    async def generate_sse():
        import httpx

        t0 = time.time()
        yield f"data: {json.dumps({'type': 'status', 'agent': 'Fiduciary Concierge', 'message': 'Gathering financial context...'})}\n\n"

        try:
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                async with http_client.stream(
                    "POST",
                    f"{settings.ollama_base_url}/api/chat",
                    json={
                        "model": settings.ollama_fast_model,
                        "messages": conversation,
                        "stream": True,
                        "options": {"temperature": 0.3, "num_predict": 1024},
                    },
                    timeout=120.0,
                ) as resp:
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'type': 'token', 'content': 'The AI service is temporarily unavailable. Please try again shortly.'})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'model': settings.ollama_fast_model, 'model_id': 'swarm', 'tokens': 0, 'latency_ms': 0, 'tok_per_sec': 0})}\n\n"
                        return

                    yield f"data: {json.dumps({'type': 'status', 'agent': 'Fiduciary Concierge', 'message': 'Analyzing your question...'})}\n\n"

                    total_tokens = 0
                    reasoning_buffer = ""
                    in_think = False

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        content = chunk.get("message", {}).get("content", "")
                        if not content:
                            if chunk.get("done"):
                                break
                            continue

                        total_tokens += 1

                        if "<think>" in content:
                            in_think = True
                            content = content.split("<think>", 1)[1]
                        if "</think>" in content:
                            reasoning_buffer += content.split("</think>", 1)[0]
                            in_think = False
                            if reasoning_buffer:
                                yield f"data: {json.dumps({'type': 'thought', 'content': reasoning_buffer})}\n\n"
                                reasoning_buffer = ""
                            remainder = content.split("</think>", 1)[1]
                            if remainder.strip():
                                yield f"data: {json.dumps({'type': 'token', 'content': remainder})}\n\n"
                            continue

                        if in_think:
                            reasoning_buffer += content
                        else:
                            yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                    elapsed = int((time.time() - t0) * 1000)
                    tps = round(total_tokens / max((time.time() - t0), 0.001), 1)
                    yield f"data: {json.dumps({'type': 'done', 'model': settings.ollama_fast_model, 'model_id': 'swarm-concierge', 'tokens': total_tokens, 'latency_ms': elapsed, 'tok_per_sec': tps})}\n\n"

        except Exception as e:
            logger.error("concierge_stream_error", error=str(e), property_id=property_id)
            yield f"data: {json.dumps({'type': 'token', 'content': 'I encountered an error processing your request. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'model': 'error', 'model_id': '', 'tokens': 0, 'latency_ms': 0, 'tok_per_sec': 0})}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


# ============================================================================
# Marketing Syndicate — Direct Booking Growth Engine
# ============================================================================

class MarketingPreferencesRequest(BaseModel):
    marketing_pct: float
    enabled: bool = True


@router.get("/{property_id}/marketing/preferences")
async def get_marketing_preferences(
    property_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the current marketing allocation and escrow balance for a property."""
    try:
        pref_result = await db.execute(
            text("""
                SELECT marketing_pct, enabled, updated_at, updated_by
                FROM owner_marketing_preferences
                WHERE property_id = :pid
            """),
            {"pid": property_id},
        )
        pref_row = pref_result.mappings().first()

        escrow_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(jli.credit) - SUM(jli.debit), 0) AS escrow_balance
                FROM journal_line_items jli
                JOIN accounts a ON a.id = jli.account_id
                JOIN journal_entries je ON je.id = jli.journal_entry_id
                WHERE a.code = '2400'
                  AND je.property_id = :pid
            """),
            {"pid": property_id},
        )
        escrow_row = escrow_result.mappings().first()

        return {
            "property_id": property_id,
            "marketing_pct": float(pref_row["marketing_pct"]) if pref_row else 0.0,
            "enabled": bool(pref_row["enabled"]) if pref_row else False,
            "updated_at": str(pref_row["updated_at"]) if pref_row else None,
            "updated_by": pref_row["updated_by"] if pref_row else None,
            "escrow_balance": float(escrow_row["escrow_balance"]) if escrow_row else 0.0,
        }
    except Exception as e:
        logger.error("marketing_preferences_get_error", property_id=property_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch marketing preferences")


@router.post("/{property_id}/marketing/preferences")
async def update_marketing_preferences(
    property_id: str,
    req: MarketingPreferencesRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Upsert marketing allocation % for a property (0-25 range enforced)."""
    if req.marketing_pct < 0 or req.marketing_pct > 25:
        raise HTTPException(
            status_code=422,
            detail="marketing_pct must be between 0 and 25",
        )

    try:
        await db.execute(
            text("""
                INSERT INTO owner_marketing_preferences (property_id, marketing_pct, enabled, updated_at, updated_by)
                VALUES (:pid, :pct, :enabled, CURRENT_TIMESTAMP, 'owner')
                ON CONFLICT (property_id)
                DO UPDATE SET
                    marketing_pct = EXCLUDED.marketing_pct,
                    enabled = EXCLUDED.enabled,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = 'owner'
            """),
            {"pid": property_id, "pct": req.marketing_pct, "enabled": req.enabled},
        )
        await db.commit()

        logger.info(
            "marketing_preferences_updated",
            property_id=property_id,
            marketing_pct=req.marketing_pct,
            enabled=req.enabled,
        )

        return {
            "status": "ok",
            "property_id": property_id,
            "marketing_pct": req.marketing_pct,
            "enabled": req.enabled,
        }
    except Exception as e:
        await db.rollback()
        logger.error("marketing_preferences_update_error", property_id=property_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update marketing preferences")


@router.get("/{property_id}/marketing/attribution")
async def get_marketing_attribution(
    property_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return campaign attribution data for a property (last 12 months)."""
    try:
        result = await db.execute(
            text("""
                SELECT id, property_id, period_start, period_end,
                       ad_spend, impressions, clicks, direct_bookings,
                       gross_revenue, roas, campaign_notes, entered_by, created_at
                FROM marketing_attribution
                WHERE property_id = :pid
                  AND period_start >= CURRENT_DATE - INTERVAL '12 months'
                ORDER BY period_start DESC
            """),
            {"pid": property_id},
        )
        rows = result.mappings().all()

        totals_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(ad_spend), 0) AS total_spend,
                    COALESCE(SUM(impressions), 0) AS total_impressions,
                    COALESCE(SUM(clicks), 0) AS total_clicks,
                    COALESCE(SUM(direct_bookings), 0) AS total_bookings,
                    COALESCE(SUM(gross_revenue), 0) AS total_revenue
                FROM marketing_attribution
                WHERE property_id = :pid
                  AND period_start >= CURRENT_DATE - INTERVAL '12 months'
            """),
            {"pid": property_id},
        )
        totals = totals_result.mappings().first()

        total_spend = float(totals["total_spend"]) if totals else 0.0
        total_revenue = float(totals["total_revenue"]) if totals else 0.0

        return {
            "property_id": property_id,
            "periods": [
                {
                    "id": row["id"],
                    "period_start": str(row["period_start"]),
                    "period_end": str(row["period_end"]),
                    "ad_spend": float(row["ad_spend"]),
                    "impressions": int(row["impressions"]),
                    "clicks": int(row["clicks"]),
                    "direct_bookings": int(row["direct_bookings"]),
                    "gross_revenue": float(row["gross_revenue"]),
                    "roas": float(row["roas"]),
                    "campaign_notes": row["campaign_notes"],
                    "entered_by": row["entered_by"],
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ],
            "totals": {
                "ad_spend": total_spend,
                "impressions": int(totals["total_impressions"]) if totals else 0,
                "clicks": int(totals["total_clicks"]) if totals else 0,
                "direct_bookings": int(totals["total_bookings"]) if totals else 0,
                "gross_revenue": total_revenue,
                "roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0,
            },
        }
    except Exception as e:
        logger.error("marketing_attribution_get_error", property_id=property_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch attribution data")
