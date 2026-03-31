"""
Admin API — Payment verification queue, operator controls, God Mode aggregation,
Fortress Prime real-time telemetry, and CapEx exception management.

Endpoints (auth required — admin/operator only):
  GET  /api/admin/payments/pending               — List quotes awaiting manual payment verification
  POST /api/admin/payments/{quote_id}/verify     — Verify funds received, trigger post-payment automation
  GET  /api/admin/god-mode/financials            — Iron Dome bypass: total PM overhead, AP, capital calls
  GET  /api/admin/prime/stream                   — SSE: live Redpanda telemetry (4 topics)
  GET  /api/admin/prime/snapshot                 — Treasury KPIs, revenue timeline, recent journals
  GET  /api/admin/fleet-status                   — Fleet Matrix aggregation for Admin Operations Glass
  POST /api/admin/splits/{property_id}           — Upsert commission split
  POST /api/admin/markups/{property_id}          — Upsert CapEx markup percentage
  GET  /api/admin/capex/{property_id}/pending    — Pending CapEx items for a property
  POST /api/admin/capex/{staging_id}/approve     — Approve CapEx item (commit journal lines)
  POST /api/admin/capex/{staging_id}/reject      — Reject CapEx item with reason
  POST /api/admin/capex/{staging_id}/dispatch-capital-call — Create Stripe Payment Link + email owner
  POST /api/admin/reconcile-revenue   — Fiduciary Sweep: find enriched reservations missing from Iron Dome
  POST /api/admin/onboard-owner       — Monolithic owner onboarding transaction
"""
import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.checkout import _build_quote_data_for_docs
from backend.core.database import get_db
from backend.core.event_publisher import EventPublisher
from backend.core.security import require_admin, require_manager_or_admin
from backend.models.lead import Lead
from backend.models.quote import Quote, QuoteOption
from backend.models.staff import StaffUser
from backend.services.channex_attention import get_latest_channex_attention_summary

logger = structlog.get_logger(service="admin_api")

router = APIRouter()


def _missing_runtime_table(exc: ProgrammingError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "does not exist" in message or "undefinedtable" in message


class PendingPaymentItem(BaseModel):
    quote_id: str
    guest_name: str
    property_name: str
    total: str
    payment_method: str
    created_at: Optional[str] = None


class PendingPaymentsResponse(BaseModel):
    payments: List[PendingPaymentItem]
    count: int


class VerifyResponse(BaseModel):
    success: bool
    quote_id: str
    status: str
    message: str


@router.get("/payments/pending", response_model=PendingPaymentsResponse)
async def list_pending_payments(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_manager_or_admin),
):
    """List all quotes with status 'pending_verification' for the admin queue."""
    result = await db.execute(
        select(Quote)
        .where(Quote.status == "pending_verification")
        .options(
            selectinload(Quote.options).selectinload(QuoteOption.property),
        )
        .order_by(Quote.created_at.desc())
    )
    quotes = result.scalars().all()

    items: list[PendingPaymentItem] = []
    for q in quotes:
        lead_result = await db.execute(select(Lead).where(Lead.id == q.lead_id))
        lead = lead_result.scalar_one_or_none()

        first_opt = q.options[0] if q.options else None
        prop_name = first_opt.property.name if first_opt and first_opt.property else "—"
        grand_total = str(sum(
            (opt.total_price or Decimal("0")) for opt in q.options
        ))

        items.append(PendingPaymentItem(
            quote_id=str(q.id),
            guest_name=lead.guest_name if lead else "Unknown",
            property_name=prop_name,
            total=grand_total,
            payment_method=q.payment_method or "—",
            created_at=q.created_at.isoformat() if q.created_at else None,
        ))

    logger.info("pending_payments_listed", count=len(items))
    return PendingPaymentsResponse(payments=items, count=len(items))


@router.post("/payments/{quote_id}/verify", response_model=VerifyResponse)
async def verify_payment(
    quote_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_manager_or_admin),
):
    """
    Verify that manual funds (Zelle/Crypto) have been received.

    Transitions quote to 'paid', lead to 'converted', and queues
    the same post-payment automation (PDF receipt + agreement + email)
    that the Stripe path uses.
    """
    result = await db.execute(
        select(Quote)
        .where(Quote.id == quote_id)
        .options(selectinload(Quote.options).selectinload(QuoteOption.property))
    )
    quote = result.scalar_one_or_none()

    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if quote.status != "pending_verification":
        raise HTTPException(
            status_code=400,
            detail=f"Quote status is '{quote.status}', expected 'pending_verification'",
        )

    lead_result = await db.execute(select(Lead).where(Lead.id == quote.lead_id))
    lead = lead_result.scalar_one_or_none()

    quote.status = "paid"
    if lead:
        lead.status = "converted"

    grand_total = str(sum(
        (opt.total_price or Decimal("0")) for opt in quote.options
    ))

    guest_email = lead.email if lead else None
    post_payment_job_id = None
    if guest_email:
        quote_data = _build_quote_data_for_docs(
            quote, lead, list(quote.options), grand_total,
        )
        post_payment_job = await enqueue_async_job(
            db,
            worker_name="dispatch_post_payment_docs_job",
            job_name="dispatch_post_payment_docs",
            payload={
                "guest_email": guest_email,
                "quote_data": quote_data,
            },
            requested_by=extract_request_actor(
                request.headers.get("x-user-id"),
                request.headers.get("x-user-email"),
            ),
            tenant_id=getattr(request.state, "tenant_id", None),
            request_id=request.headers.get("x-request-id"),
            redis=arq_redis,
        )
        post_payment_job_id = str(post_payment_job.id)
        logger.info(
            "verify_post_payment_docs_queued",
            quote_id=str(quote_id),
            to=guest_email,
            job_id=post_payment_job_id,
        )
    else:
        logger.warning("verify_no_email_for_docs", quote_id=str(quote_id))

    await db.commit()

    logger.info(
        "payment_verified",
        quote_id=str(quote_id),
        payment_method=quote.payment_method,
    )

    return VerifyResponse(
        success=True,
        quote_id=str(quote_id),
        status="paid",
        message=(
            "Funds verified. Receipt and agreement dispatched to guest."
            if post_payment_job_id
            else "Funds verified. No guest email was available for document dispatch."
        ),
    )


# ============================================================================
# God Mode — Iron Dome Bypass for Operator Aggregation
# ============================================================================

@router.get("/god-mode/financials")
async def get_god_mode_financials(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    FORTRESS PROTOCOL: God Mode Aggregation.
    Bypasses the Information Wall to aggregate total PM overhead,
    active accounts payable, and portfolio overdrafts across the
    entire Iron Dome ledger.

    This endpoint is operator-only (auth enforced by GlobalAuthMiddleware).
    """
    try:
        overhead_result = await db.execute(text("""
            SELECT COALESCE(SUM(credit - debit), 0) AS total_overhead
            FROM journal_line_items
            WHERE account_id = (SELECT id FROM accounts WHERE code = '4100')
        """))
        total_overhead = overhead_result.scalar() or 0

        ap_result = await db.execute(text("""
            SELECT COALESCE(SUM(credit - debit), 0) AS total_ap
            FROM journal_line_items
            WHERE account_id = (SELECT id FROM accounts WHERE code = '2100')
        """))
        total_ap = ap_result.scalar() or 0

        cc_result = await db.execute(text("""
            SELECT property_id, operating_funds
            FROM trust_balance
            WHERE operating_funds <= 0
        """))
        capital_calls = [
            {"property_id": row.property_id, "deficit": float(row.operating_funds)}
            for row in cc_result.fetchall()
        ]

        margin_result = await db.execute(text("""
            SELECT je.property_id, je.entry_date, je.description,
                   jli.credit AS margin_captured
            FROM journal_entries je
            JOIN journal_line_items jli ON je.id = jli.journal_entry_id
            WHERE jli.account_id = (SELECT id FROM accounts WHERE code = '4100')
              AND jli.credit > 0
              AND je.is_void = FALSE
            ORDER BY je.entry_date DESC
            LIMIT 25
        """))
        recent_margins = [
            {
                "property_id": row.property_id,
                "date": row.entry_date.isoformat() if row.entry_date else None,
                "description": row.description,
                "amount": float(row.margin_captured),
            }
            for row in margin_result.fetchall()
        ]

        markup_result = await db.execute(text("""
            SELECT omr.property_id, omr.expense_category, omr.markup_percentage,
                   tb.owner_funds, tb.operating_funds
            FROM owner_markup_rules omr
            LEFT JOIN trust_balance tb ON omr.property_id = tb.property_id
            ORDER BY omr.property_id
        """))
        markup_rules = [
            {
                "property_id": row.property_id,
                "expense_category": row.expense_category,
                "markup_pct": float(row.markup_percentage),
                "owner_funds": float(row.owner_funds or 0),
                "operating_funds": float(row.operating_funds or 0),
            }
            for row in markup_result.fetchall()
        ]

        ledger_result = await db.execute(text("""
            SELECT COUNT(*) AS entries FROM journal_entries WHERE is_void = FALSE
        """))
        total_entries = ledger_result.scalar() or 0

        line_result = await db.execute(text("""
            SELECT COUNT(*) AS lines FROM journal_line_items
        """))
        total_lines = line_result.scalar() or 0

        trigger_result = await db.execute(text("""
            SELECT trigger_name, event_manipulation
            FROM information_schema.triggers
            WHERE event_object_table = 'journal_line_items'
            ORDER BY trigger_name
        """))
        active_triggers = [
            {"name": row.trigger_name, "event": row.event_manipulation}
            for row in trigger_result.fetchall()
        ]

        logger.info(
            "god_mode_financials_accessed",
            total_overhead=float(total_overhead),
            total_ap=float(total_ap),
            capital_calls=len(capital_calls),
        )

        return {
            "global_metrics": {
                "total_overhead_revenue_captured": float(total_overhead),
                "total_vendor_accounts_payable": float(total_ap),
                "properties_in_overdraft": len(capital_calls),
            },
            "capital_calls_required": capital_calls,
            "recent_margin_captures": recent_margins,
            "markup_rules": markup_rules,
            "iron_dome_health": {
                "journal_entries": total_entries,
                "journal_line_items": total_lines,
                "active_triggers": active_triggers,
                "balance_enforcement": "trg_verify_balance" in [t["name"] for t in active_triggers],
                "append_only_enforcement": "trg_immutable_line_items" in [t["name"] for t in active_triggers],
            },
        }
    except Exception as e:
        logger.error("god_mode_aggregation_failed", error=str(e)[:500])
        raise HTTPException(
            status_code=500,
            detail=f"God Mode aggregation failed: {str(e)[:200]}",
        )


# ============================================================================
# Fortress Prime — Real-Time Telemetry & Treasury Dashboard
# ============================================================================

PRIME_TOPICS = [
    "enterprise.inbox.raw",
    "trust.accounting.staged",
    "trust.revenue.staged",
    "trust.payout.staged",
]

KAFKA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")


@router.get("/prime/stream")
async def prime_telemetry_stream(
    request: Request,
    _user: StaffUser = Depends(require_manager_or_admin),
):
    """
    FORTRESS PRIME: Live SSE stream of the Redpanda event bus.

    Tails enterprise.inbox.raw, trust.accounting.staged, trust.revenue.staged,
    and trust.payout.staged with a dedicated consumer group so production
    consumers are unaffected. Emits heartbeats every 5 seconds.

    Graceful degradation: if Kafka/Redpanda is unreachable, falls back to
    a heartbeat-only stream so the dashboard stays connected.
    """
    async def event_generator():
        from aiokafka import AIOKafkaConsumer

        consumer: AIOKafkaConsumer | None = None
        try:
            consumer = AIOKafkaConsumer(
                *PRIME_TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                group_id="fortress-prime-glass",
                auto_offset_reset="latest",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=4000,
            )
            await asyncio.wait_for(consumer.start(), timeout=8.0)
            logger.info("prime_sse_stream_started", topics=PRIME_TOPICS)
        except Exception as exc:
            logger.warning("prime_sse_kafka_unavailable", error=str(exc)[:200])
            consumer = None

        try:
            while True:
                if await request.is_disconnected():
                    break

                if consumer is None:
                    heartbeat = json.dumps({
                        "type": "heartbeat",
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "kafka": "unavailable",
                    })
                    yield f"data: {heartbeat}\n\n"
                    await asyncio.sleep(5)
                    continue

                batch = await consumer.getmany(timeout_ms=4000, max_records=50)

                if not batch:
                    heartbeat = json.dumps({
                        "type": "heartbeat",
                        "ts": datetime.utcnow().isoformat() + "Z",
                    })
                    yield f"data: {heartbeat}\n\n"
                    continue

                for tp, messages in batch.items():
                    for msg in messages:
                        payload = {
                            "type": "event",
                            "topic": msg.topic,
                            "partition": msg.partition,
                            "offset": msg.offset,
                            "ts": datetime.utcfromtimestamp(
                                msg.timestamp / 1000
                            ).isoformat() + "Z" if msg.timestamp else datetime.utcnow().isoformat() + "Z",
                            "event": msg.value,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            if consumer:
                await consumer.stop()
            logger.info("prime_sse_stream_stopped")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/prime/snapshot")
async def prime_snapshot(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_manager_or_admin),
) -> Dict[str, Any]:
    """
    FORTRESS PRIME: Treasury snapshot for the God Mode dashboard.

    Returns current Iron Dome balances, 30-day revenue timeline,
    recent journal entries, payout summary, and system pulse.
    """
    try:
        acct_result = await db.execute(text("""
            SELECT a.code, a.name,
                   COALESCE(SUM(jli.debit), 0) AS total_debit,
                   COALESCE(SUM(jli.credit), 0) AS total_credit
            FROM accounts a
            LEFT JOIN journal_line_items jli ON jli.account_id = a.id
            WHERE a.code IN ('1010', '2000', '2100', '4000', '4010', '4100', '2200')
            GROUP BY a.code, a.name
            ORDER BY a.code
        """))
        accounts = {}
        for row in acct_result.fetchall():
            balance = float(row.total_credit - row.total_debit) if row.code[0] in ('2', '4') else float(row.total_debit - row.total_credit)
            accounts[row.code] = {
                "name": row.name,
                "balance": round(balance, 2),
                "total_debit": round(float(row.total_debit), 2),
                "total_credit": round(float(row.total_credit), 2),
            }

        timeline_result = await db.execute(text("""
            SELECT DATE(je.entry_date) AS day,
                   COALESCE(SUM(CASE WHEN a.code = '4100' THEN jli.credit ELSE 0 END), 0) AS pm_commission,
                   COALESCE(SUM(CASE WHEN a.code IN ('4000', '4010') THEN jli.credit ELSE 0 END), 0) AS rental_revenue,
                   COALESCE(SUM(CASE WHEN a.code = '1010' THEN jli.debit ELSE 0 END), 0) AS cash_inflow
            FROM journal_entries je
            JOIN journal_line_items jli ON je.id = jli.journal_entry_id
            JOIN accounts a ON jli.account_id = a.id
            WHERE je.entry_date >= CURRENT_DATE - INTERVAL '30 days'
              AND je.is_void = FALSE
              AND a.code IN ('4100', '4000', '4010', '1010')
            GROUP BY DATE(je.entry_date)
            ORDER BY day
        """))
        revenue_timeline = [
            {
                "day": row.day.isoformat() if row.day else None,
                "pm_commission": round(float(row.pm_commission), 2),
                "rental_revenue": round(float(row.rental_revenue), 2),
                "cash_inflow": round(float(row.cash_inflow), 2),
            }
            for row in timeline_result.fetchall()
        ]

        recent_result = await db.execute(text("""
            SELECT je.id, je.entry_date, je.description, je.reference_type,
                   je.property_id, je.posted_by,
                   json_agg(json_build_object(
                       'account_code', a.code,
                       'account_name', a.name,
                       'debit', jli.debit,
                       'credit', jli.credit
                   )) AS lines
            FROM journal_entries je
            JOIN journal_line_items jli ON je.id = jli.journal_entry_id
            JOIN accounts a ON jli.account_id = a.id
            WHERE je.is_void = FALSE
            GROUP BY je.id, je.entry_date, je.description,
                     je.reference_type, je.property_id, je.posted_by
            ORDER BY je.created_at DESC
            LIMIT 30
        """))
        recent_journals = [
            {
                "id": row.id,
                "date": row.entry_date.isoformat() if row.entry_date else None,
                "description": row.description,
                "reference_type": row.reference_type,
                "property_id": row.property_id,
                "posted_by": row.posted_by,
                "lines": row.lines if isinstance(row.lines, list) else [],
            }
            for row in recent_result.fetchall()
        ]

        try:
            payout_result = await db.execute(text("""
                SELECT status,
                       COUNT(*) AS cnt,
                       COALESCE(SUM(owner_amount), 0) AS total
                FROM payout_ledger
                GROUP BY status
            """))
            payout_summary = {
                row.status: {"count": row.cnt, "total": round(float(row.total), 2)}
                for row in payout_result.fetchall()
            }
        except ProgrammingError as exc:
            if not _missing_runtime_table(exc):
                raise
            await db.rollback()
            payout_summary = {}
            logger.warning("prime_snapshot_payout_ledger_missing")

        today_je_result = await db.execute(text("""
            SELECT COUNT(*) FROM journal_entries
            WHERE entry_date = CURRENT_DATE AND is_void = FALSE
        """))
        today_entries = today_je_result.scalar() or 0

        prop_result = await db.execute(text("SELECT COUNT(*) FROM properties"))
        total_properties = prop_result.scalar() or 0

        res_result = await db.execute(text("""
            SELECT COUNT(*) FROM reservations
            WHERE status IN ('confirmed', 'checked_in')
        """))
        active_reservations = res_result.scalar() or 0

        try:
            channex_attention = await get_latest_channex_attention_summary(db)
        except Exception as exc:
            logger.warning("prime_snapshot_channex_attention_unavailable", error=str(exc)[:300])
            channex_attention = None

        logger.info("prime_snapshot_served")

        return {
            "accounts": accounts,
            "revenue_timeline": revenue_timeline,
            "recent_journals": recent_journals,
            "payout_summary": payout_summary,
            "channex_attention": channex_attention.model_dump() if channex_attention else None,
            "system_pulse": {
                "journal_entries_today": today_entries,
                "total_properties": total_properties,
                "active_reservations": active_reservations,
            },
        }

    except Exception as e:
        logger.error("prime_snapshot_failed", error=str(e)[:500])
        raise HTTPException(status_code=500, detail=f"Prime snapshot failed: {str(e)[:200]}")


# ============================================================================
# Admin Operations Glass — Fleet Management & Financial Rules
# ============================================================================

class SplitUpdateRequest(BaseModel):
    owner_pct: float
    pm_pct: float


class MarkupUpdateRequest(BaseModel):
    markup_pct: float
    expense_category: str = "ALL"


@router.get("/fleet-status")
async def get_fleet_status(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Fleet Matrix aggregation for the Admin Operations Glass.

    Joins properties, owner_property_map, management_splits, trust_balance,
    owner_markup_rules, capex_staging, and MTD journal revenue into a single
    payload for the fleet grid and global KPI strip.
    """
    try:
        query = text("""
            WITH capex_summary AS (
                SELECT property_id,
                       COUNT(*) AS pending_count,
                       COALESCE(SUM(amount), 0) AS pending_total
                FROM capex_staging
                WHERE compliance_status = 'PENDING_CAPEX_APPROVAL'
                GROUP BY property_id
            ),
            mtd_revenue AS (
                SELECT je.property_id,
                       COALESCE(SUM(jli.credit), 0) AS mtd_pm_revenue,
                       COUNT(DISTINCT je.id) AS mtd_reservations
                FROM journal_entries je
                JOIN journal_line_items jli ON je.id = jli.journal_entry_id
                JOIN accounts a ON jli.account_id = a.id
                WHERE a.code = '4100'
                  AND je.reference_type = 'reservation_revenue'
                  AND je.is_void = FALSE
                  AND date_trunc('month', je.entry_date) = date_trunc('month', CURRENT_DATE)
                GROUP BY je.property_id
            )
            SELECT
                p.streamline_property_id AS property_id,
                p.name,
                opm.owner_name,
                opm.email AS owner_email,
                ms.owner_pct,
                ms.pm_pct,
                ms.effective_date AS split_effective_date,
                COALESCE(omr.markup_percentage, 23.00) AS markup_pct,
                COALESCE(tb.owner_funds, 0) AS trust_owner_funds,
                COALESCE(tb.operating_funds, 0) AS trust_operating_funds,
                COALESCE(tb.escrow_funds, 0) AS trust_escrow,
                COALESCE(tb.security_deps, 0) AS trust_security_deps,
                COALESCE(cs.pending_count, 0) AS pending_capex_count,
                COALESCE(cs.pending_total, 0) AS pending_capex_total,
                COALESCE(mr.mtd_pm_revenue, 0) AS mtd_pm_revenue,
                COALESCE(mr.mtd_reservations, 0) AS mtd_reservations
            FROM properties p
            JOIN owner_property_map opm
                ON p.streamline_property_id = opm.unit_id
            LEFT JOIN management_splits ms
                ON p.streamline_property_id = ms.property_id
            LEFT JOIN trust_balance tb
                ON p.streamline_property_id = tb.property_id
            LEFT JOIN owner_markup_rules omr
                ON p.streamline_property_id = omr.property_id
                AND omr.expense_category = 'ALL'
            LEFT JOIN capex_summary cs
                ON p.streamline_property_id = cs.property_id
            LEFT JOIN mtd_revenue mr
                ON p.streamline_property_id = mr.property_id
            WHERE p.streamline_property_id IS NOT NULL
            ORDER BY p.name
        """)

        result = await db.execute(query)
        rows = result.fetchall()

        fleet = []
        for row in rows:
            r = dict(row._mapping)
            for k in ("owner_pct", "pm_pct", "markup_pct", "trust_owner_funds",
                       "trust_operating_funds", "trust_escrow", "trust_security_deps",
                       "pending_capex_total", "mtd_pm_revenue"):
                if r.get(k) is not None:
                    r[k] = round(float(r[k]), 2)
            for k in ("pending_capex_count", "mtd_reservations"):
                if r.get(k) is not None:
                    r[k] = int(r[k])
            if r.get("split_effective_date"):
                r["split_effective_date"] = r["split_effective_date"].isoformat()

            trust_owner = r.get("trust_owner_funds", 0)
            pending_capex = r.get("pending_capex_total", 0)
            if trust_owner < 0:
                r["health"] = "overdraft"
            elif trust_owner < pending_capex:
                r["health"] = "warning"
            else:
                r["health"] = "healthy"

            fleet.append(r)

        global_totals = {
            "total_owner_funds": round(sum(f.get("trust_owner_funds", 0) for f in fleet), 2),
            "total_operating_funds": round(sum(f.get("trust_operating_funds", 0) for f in fleet), 2),
            "total_pm_revenue_mtd": round(sum(f.get("mtd_pm_revenue", 0) for f in fleet), 2),
            "properties_in_overdraft": sum(1 for f in fleet if f.get("trust_owner_funds", 0) < 0),
            "pending_capex_items": sum(f.get("pending_capex_count", 0) for f in fleet),
        }

        logger.info("fleet_status_served", property_count=len(fleet))
        return {"fleet": fleet, "global_totals": global_totals}

    except Exception as e:
        logger.error("fleet_status_failed", error=str(e)[:500])
        raise HTTPException(
            status_code=500,
            detail=f"Fleet status aggregation failed: {str(e)[:200]}",
        )


@router.post("/splits/{property_id}")
async def update_commission_split(
    property_id: str,
    payload: SplitUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Upsert a management commission split for a property.

    The management_splits table has a UNIQUE constraint on property_id,
    so this overwrites the current split. The effective_date is set to today
    to mark when the change was applied.
    """
    if round(payload.owner_pct + payload.pm_pct, 2) != 100.00:
        raise HTTPException(
            status_code=400,
            detail=f"owner_pct ({payload.owner_pct}) + pm_pct ({payload.pm_pct}) must equal 100.00",
        )

    old_result = await db.execute(
        text("SELECT owner_pct, pm_pct FROM management_splits WHERE property_id = :pid"),
        {"pid": property_id},
    )
    old = old_result.fetchone()

    await db.execute(text("""
        INSERT INTO management_splits (property_id, owner_pct, pm_pct, effective_date)
        VALUES (:pid, :opct, :ppct, CURRENT_DATE)
        ON CONFLICT (property_id) DO UPDATE SET
            owner_pct = EXCLUDED.owner_pct,
            pm_pct = EXCLUDED.pm_pct,
            effective_date = CURRENT_DATE
    """), {"pid": property_id, "opct": payload.owner_pct, "ppct": payload.pm_pct})
    await db.commit()

    logger.info(
        "commission_split_updated",
        property_id=property_id,
        old_split=f"{old.owner_pct}/{old.pm_pct}" if old else "none",
        new_split=f"{payload.owner_pct}/{payload.pm_pct}",
    )
    return {
        "status": "success",
        "property_id": property_id,
        "owner_pct": payload.owner_pct,
        "pm_pct": payload.pm_pct,
    }


@router.post("/markups/{property_id}")
async def update_capex_markup(
    property_id: str,
    payload: MarkupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Upsert a CapEx markup percentage for a property.

    ON CONFLICT on (property_id, expense_category) updates the existing row.
    """
    old_result = await db.execute(
        text("""
            SELECT markup_percentage FROM owner_markup_rules
            WHERE property_id = :pid AND expense_category = :cat
        """),
        {"pid": property_id, "cat": payload.expense_category},
    )
    old = old_result.scalar()

    await db.execute(text("""
        INSERT INTO owner_markup_rules (property_id, expense_category, markup_percentage)
        VALUES (:pid, :cat, :pct)
        ON CONFLICT (property_id, expense_category)
        DO UPDATE SET markup_percentage = EXCLUDED.markup_percentage,
                      updated_at = CURRENT_TIMESTAMP
    """), {"pid": property_id, "cat": payload.expense_category, "pct": payload.markup_pct})
    await db.commit()

    logger.info(
        "capex_markup_updated",
        property_id=property_id,
        expense_category=payload.expense_category,
        old_markup=float(old) if old else None,
        new_markup=payload.markup_pct,
    )
    return {
        "status": "success",
        "property_id": property_id,
        "expense_category": payload.expense_category,
        "markup_pct": payload.markup_pct,
    }


# ============================================================================
# CapEx Exception Management — Approve / Reject / Dispatch Capital Call
# ============================================================================

class CapexRejectRequest(BaseModel):
    reason: str


@router.get("/capex/{property_id}/pending")
async def get_pending_capex(
    property_id: str,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Returns all PENDING_CAPEX_APPROVAL items for a given property.
    Used by the Admin Operations Glass CapEx Review section.
    """
    try:
        result = await db.execute(text("""
            SELECT id, property_id, vendor, amount, total_owner_charge,
                   description, audit_trail, created_at
            FROM capex_staging
            WHERE property_id = :pid
              AND compliance_status = 'PENDING_CAPEX_APPROVAL'
            ORDER BY created_at DESC
        """), {"pid": property_id})
        rows = result.fetchall()

        items = []
        for row in rows:
            r = dict(row._mapping)
            r["amount"] = round(float(r["amount"]), 2)
            r["total_owner_charge"] = round(float(r["total_owner_charge"]), 2)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            items.append(r)

        return {"items": items, "count": len(items)}

    except Exception as e:
        logger.error("capex_pending_query_failed", property_id=property_id, error=str(e)[:500])
        raise HTTPException(status_code=500, detail=f"Failed to query pending CapEx: {str(e)[:200]}")


@router.post("/capex/{staging_id}/approve")
async def approve_capex(
    staging_id: int,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Approve a CapEx staging item: commits pre-computed journal_lines
    to the Iron Dome ledger and marks the item as APPROVED.
    """
    try:
        row_result = await db.execute(text("""
            SELECT id, property_id, vendor, amount, total_owner_charge,
                   journal_lines, compliance_status, audit_trail
            FROM capex_staging WHERE id = :sid
        """), {"sid": staging_id})
        item = row_result.fetchone()

        if not item:
            raise HTTPException(status_code=404, detail=f"CapEx staging item {staging_id} not found")

        if item.compliance_status != "PENDING_CAPEX_APPROVAL":
            raise HTTPException(
                status_code=409,
                detail=f"Item status is '{item.compliance_status}', expected 'PENDING_CAPEX_APPROVAL'",
            )

        journal_lines = item.journal_lines if isinstance(item.journal_lines, list) else []
        if not journal_lines:
            raise HTTPException(status_code=422, detail="No journal_lines to commit for this staging item")

        je_result = await db.execute(text("""
            INSERT INTO journal_entries (property_id, entry_date, description, reference_type, reference_id)
            VALUES (:pid, CURRENT_DATE, :desc, 'capex_expense', :ref)
            RETURNING id
        """), {
            "pid": item.property_id,
            "desc": f"CapEx Approved: {item.vendor} (${float(item.amount):,.2f})",
            "ref": f"CAPEX-{staging_id}",
        })
        je_id = je_result.scalar()

        for line in journal_lines:
            await db.execute(text("""
                INSERT INTO journal_line_items (journal_entry_id, account_id, debit, credit)
                VALUES (
                    :je_id,
                    (SELECT id FROM accounts WHERE code = :acct_code),
                    :debit,
                    :credit
                )
            """), {
                "je_id": je_id,
                "acct_code": line["account_code"],
                "debit": float(line.get("debit", 0)),
                "credit": float(line.get("credit", 0)),
            })

        audit = item.audit_trail or {}
        audit["approved_at"] = datetime.utcnow().isoformat() + "Z"
        audit["journal_entry_id"] = je_id
        audit["approved_via"] = "admin_glass"

        await db.execute(text("""
            UPDATE capex_staging
            SET compliance_status = 'APPROVED',
                approved_at = CURRENT_TIMESTAMP,
                approved_by = 'admin',
                audit_trail = :trail
            WHERE id = :sid
        """), {"sid": staging_id, "trail": json.dumps(audit)})
        await db.commit()

        logger.info(
            "capex_approved",
            staging_id=staging_id,
            journal_entry_id=je_id,
            vendor=item.vendor,
            amount=float(item.amount),
        )
        return {
            "status": "approved",
            "staging_id": staging_id,
            "journal_entry_id": je_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("capex_approve_failed", staging_id=staging_id, error=str(e)[:500])
        raise HTTPException(status_code=500, detail=f"CapEx approval failed: {str(e)[:200]}")


@router.post("/capex/{staging_id}/reject")
async def reject_capex(
    staging_id: int,
    payload: CapexRejectRequest,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Reject a CapEx staging item with a reason. No journal lines are committed."""
    try:
        row_result = await db.execute(text("""
            SELECT id, compliance_status, audit_trail FROM capex_staging WHERE id = :sid
        """), {"sid": staging_id})
        item = row_result.fetchone()

        if not item:
            raise HTTPException(status_code=404, detail=f"CapEx staging item {staging_id} not found")

        if item.compliance_status != "PENDING_CAPEX_APPROVAL":
            raise HTTPException(
                status_code=409,
                detail=f"Item status is '{item.compliance_status}', expected 'PENDING_CAPEX_APPROVAL'",
            )

        audit = item.audit_trail or {}
        audit["rejected_at"] = datetime.utcnow().isoformat() + "Z"
        audit["rejection_reason"] = payload.reason
        audit["rejected_via"] = "admin_glass"

        await db.execute(text("""
            UPDATE capex_staging
            SET compliance_status = 'REJECTED',
                rejected_at = CURRENT_TIMESTAMP,
                rejected_by = 'admin',
                rejection_reason = :reason,
                audit_trail = :trail
            WHERE id = :sid
        """), {"sid": staging_id, "reason": payload.reason, "trail": json.dumps(audit)})
        await db.commit()

        logger.info("capex_rejected", staging_id=staging_id, reason=payload.reason)
        return {
            "status": "rejected",
            "staging_id": staging_id,
            "reason": payload.reason,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("capex_reject_failed", staging_id=staging_id, error=str(e)[:500])
        raise HTTPException(status_code=500, detail=f"CapEx rejection failed: {str(e)[:200]}")


@router.post("/capex/{staging_id}/dispatch-capital-call")
async def dispatch_capital_call(
    staging_id: int,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Dispatch a Capital Call: create a Stripe Payment Link for the total
    owner charge, then email it to the property owner.

    1. Read capex_staging row (vendor, amount, total_owner_charge).
    2. Join owner_property_map for owner email/name.
    3. Create Stripe Payment Link via ad-hoc Product + Price + PaymentLink.
    4. Send email to owner with the link and invoice details.
    5. Update audit_trail with dispatch metadata.
    """
    try:
        row_result = await db.execute(text("""
            SELECT cs.id, cs.property_id, cs.vendor, cs.amount,
                   cs.total_owner_charge, cs.description,
                   cs.compliance_status, cs.audit_trail,
                   opm.owner_name, opm.email AS owner_email,
                   p.name AS property_name
            FROM capex_staging cs
            JOIN owner_property_map opm ON cs.property_id = opm.unit_id
            JOIN properties p ON cs.property_id = p.streamline_property_id
            WHERE cs.id = :sid
        """), {"sid": staging_id})
        item = row_result.fetchone()

        if not item:
            raise HTTPException(status_code=404, detail=f"CapEx staging item {staging_id} not found")

        if item.compliance_status != "PENDING_CAPEX_APPROVAL":
            raise HTTPException(
                status_code=409,
                detail=f"Item status is '{item.compliance_status}', expected 'PENDING_CAPEX_APPROVAL'",
            )

        if not item.owner_email:
            raise HTTPException(
                status_code=422,
                detail=f"No email on file for owner of property {item.property_id}",
            )

        from backend.integrations.stripe_payments import StripePayments

        stripe_client = StripePayments()
        amount_cents = int(round(float(item.total_owner_charge) * 100))
        markup_amount = round(float(item.total_owner_charge) - float(item.amount), 2)

        link_result = await stripe_client.create_payment_link(
            amount_cents=amount_cents,
            description=(
                f"Capital Call: {item.vendor} — {item.description or 'Maintenance'} "
                f"at {item.property_name}"
            ),
            property_name=item.property_name,
            property_id=item.property_id,
            staging_id=staging_id,
            owner_name=item.owner_name,
        )

        from backend.services.email_service import send_email

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #111;">Capital Call — {item.property_name}</h2>
            <p>Dear {item.owner_name},</p>
            <p>A maintenance expense requires owner funding for your property <strong>{item.property_name}</strong>.</p>
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr style="background: #f8f8f8;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Vendor</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{item.vendor}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Invoice Amount</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">${float(item.amount):,.2f}</td>
                </tr>
                <tr style="background: #f8f8f8;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>PM Markup</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">${markup_amount:,.2f}</td>
                </tr>
                <tr style="background: #e8f5e9;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Due</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">${float(item.total_owner_charge):,.2f}</td>
                </tr>
            </table>
            <p style="margin: 20px 0;">
                <a href="{link_result['payment_link_url']}"
                   style="display: inline-block; background: #16a34a; color: white; padding: 14px 28px;
                          text-decoration: none; border-radius: 6px; font-weight: 600;">
                    Pay ${float(item.total_owner_charge):,.2f} Now
                </a>
            </p>
            <p style="color: #666; font-size: 13px;">
                This is a secure Stripe-hosted payment link. Your card details are handled
                entirely by Stripe and never touch our systems.
            </p>
            <p style="color: #999; font-size: 12px; margin-top: 30px;">
                Cabin Rentals of Georgia, LLC — Property Management
            </p>
        </div>
        """

        email_sent = send_email(
            to=item.owner_email,
            subject=f"Capital Call — {item.property_name}: {item.vendor} (${float(item.total_owner_charge):,.2f})",
            html_body=html_body,
            text_body=(
                f"Capital Call for {item.property_name}\n\n"
                f"Vendor: {item.vendor}\n"
                f"Invoice: ${float(item.amount):,.2f}\n"
                f"Total Due (with markup): ${float(item.total_owner_charge):,.2f}\n\n"
                f"Pay here: {link_result['payment_link_url']}"
            ),
        )

        audit = item.audit_trail or {}
        audit["capital_call_dispatched_at"] = datetime.utcnow().isoformat() + "Z"
        audit["stripe_payment_link_url"] = link_result["payment_link_url"]
        audit["stripe_payment_link_id"] = link_result["payment_link_id"]
        audit["email_sent_to"] = item.owner_email
        audit["email_delivered"] = email_sent

        await db.execute(text("""
            UPDATE capex_staging
            SET audit_trail = :trail
            WHERE id = :sid
        """), {"sid": staging_id, "trail": json.dumps(audit)})
        await db.commit()

        logger.info(
            "capital_call_dispatched",
            staging_id=staging_id,
            property_id=item.property_id,
            owner_email=item.owner_email[:8] + "...",
            amount=float(item.total_owner_charge),
            stripe_link_id=link_result["payment_link_id"],
            email_sent=email_sent,
        )

        return {
            "status": "dispatched",
            "staging_id": staging_id,
            "payment_link_url": link_result["payment_link_url"],
            "email_sent_to": item.owner_email,
            "email_delivered": email_sent,
            "total_owner_charge": float(item.total_owner_charge),
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("capital_call_dispatch_failed", staging_id=staging_id, error=str(e)[:500])
        raise HTTPException(
            status_code=500,
            detail=f"Capital call dispatch failed: {str(e)[:200]}",
        )


# ============================================================================
# Revenue Reconciliation — The Fiduciary Sweep
# ============================================================================

@router.post("/reconcile-revenue")
async def reconcile_revenue(
    execute: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Revenue Reconciliation Sweep.

    Finds enriched paid reservations that have no matching journal entry in
    the Iron Dome. Returns a gap report with confirmation codes and total
    unrealized revenue. When ``execute=true``, publishes revenue events to
    trust.revenue.staged for each missing reservation so the Revenue Consumer
    Daemon can journal them.
    """
    try:
        gap_query = text("""
            SELECT r.confirmation_code,
                   p.streamline_property_id AS unit_id,
                   p.name AS property_name,
                   r.total_amount,
                   r.tax_amount,
                   r.cleaning_fee,
                   r.nightly_rate,
                   r.nights_count,
                   r.check_in_date,
                   r.status
            FROM reservations r
            JOIN properties p ON p.id = r.property_id
            LEFT JOIN journal_entries je
                ON je.reference_id = r.confirmation_code
                AND je.reference_type = 'reservation_revenue'
            WHERE r.paid_amount > 0
              AND r.streamline_financial_detail IS NOT NULL
              AND r.total_amount > 0
              AND r.status NOT IN ('cancelled')
              AND je.id IS NULL
            ORDER BY r.check_in_date DESC
        """)

        result = await db.execute(gap_query)
        missing = result.fetchall()

        report: Dict[str, Any] = {
            "missing_count": len(missing),
            "total_gap_value": round(sum(float(row.total_amount) for row in missing), 2),
            "execute": execute,
            "staged_events": [],
            "missing_reservations": [
                {
                    "confirmation_code": row.confirmation_code,
                    "property": row.property_name,
                    "unit_id": row.unit_id,
                    "total_amount": round(float(row.total_amount), 2),
                    "check_in": row.check_in_date.isoformat() if row.check_in_date else None,
                }
                for row in missing[:50]
            ],
        }

        if execute and missing:
            for row in missing:
                payload = {
                    "property_id": str(row.unit_id),
                    "confirmation_code": row.confirmation_code,
                    "total_amount": float(row.total_amount),
                    "cleaning_fee": float(row.cleaning_fee or 0),
                    "tax_amount": float(row.tax_amount or 0),
                    "nightly_rate": float(row.nightly_rate or 0),
                    "nights_count": int(row.nights_count or 0),
                    "is_historical": False,
                }
                await EventPublisher.publish(
                    "trust.revenue.staged", payload,
                    key=row.confirmation_code,
                )
                report["staged_events"].append(row.confirmation_code)

            logger.info(
                "revenue_reconciliation_executed",
                staged=len(report["staged_events"]),
                total_value=report["total_gap_value"],
            )
        else:
            logger.info(
                "revenue_reconciliation_report",
                missing=len(missing),
                total_value=report["total_gap_value"],
            )

        return report

    except Exception as e:
        logger.error("revenue_reconciliation_failed", error=str(e)[:500])
        raise HTTPException(
            status_code=500,
            detail=f"Revenue reconciliation failed: {str(e)[:200]}",
        )


# =============================================================================
# OWNER ONBOARDING — Monolithic Transaction
# =============================================================================


class OnboardOwnerRequest(BaseModel):
    owner_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=254)
    phone: Optional[str] = None
    sl_owner_id: str = Field(..., min_length=1, max_length=50)
    property_ids: List[str] = Field(..., min_length=1)
    owner_pct: float = Field(65.00, ge=0, le=100)
    pm_pct: float = Field(35.00, ge=0, le=100)
    markup_pct: float = Field(23.00, ge=0, le=100)
    contract_nas_path: Optional[str] = None


def _run_contract_ingestion(nas_path: str, owner_id: str):
    """Background task: ingest management contract into legal_library Qdrant collection."""
    try:
        import sys as _sys
        _project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        _sys.path.insert(0, _project_root)
        from Modules.CF03_CounselorCRM_loader import ingest_file
        ingest_file(
            nas_path,
            category="management_contract",
            extra_metadata={"owner_id": owner_id},
        )
        logger.info("contract_ingestion_complete", path=nas_path, owner_id=owner_id)
    except ImportError:
        try:
            import importlib.util
            _project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            spec = importlib.util.spec_from_file_location(
                "ingest_docs",
                os.path.join(_project_root, "Modules", "CF-03_CounselorCRM", "ingest_docs.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.ingest_file(
                nas_path,
                category="management_contract",
                extra_metadata={"owner_id": owner_id},
            )
            logger.info("contract_ingestion_complete", path=nas_path, owner_id=owner_id)
        except Exception as e:
            logger.error("contract_ingestion_failed", path=nas_path, error=str(e)[:500])
    except Exception as e:
        logger.error("contract_ingestion_failed", path=nas_path, error=str(e)[:500])


@router.post("/onboard-owner")
async def onboard_owner(
    req: OnboardOwnerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Monolithic owner onboarding transaction.

    Seeds all five ledger tables in a single atomic commit, generates a
    magic-link login URL, and optionally triggers background contract
    ingestion into the legal_library Qdrant collection.
    """
    split_sum = round(req.owner_pct + req.pm_pct, 2)
    if split_sum != 100.00:
        raise HTTPException(
            status_code=422,
            detail=f"owner_pct ({req.owner_pct}) + pm_pct ({req.pm_pct}) must equal 100.00, got {split_sum}",
        )

    if req.contract_nas_path and not os.path.isfile(req.contract_nas_path):
        raise HTTPException(
            status_code=422,
            detail=f"Contract file not found on NAS: {req.contract_nas_path}",
        )

    properties_seeded: List[str] = []
    sub_ledger_accounts: List[str] = []

    try:
        # ── 1. owner_property_map ────────────────────────────────
        for pid in req.property_ids:
            prop_result = await db.execute(text("""
                SELECT name FROM properties WHERE streamline_property_id = :pid
            """), {"pid": pid})
            prop_row = prop_result.fetchone()
            prop_name = prop_row.name if prop_row else f"Property {pid}"

            await db.execute(text("""
                INSERT INTO owner_property_map
                    (sl_owner_id, unit_id, owner_name, email, phone, property_name, live_balance)
                VALUES
                    (:owner_id, :unit_id, :name, :email, :phone, :prop_name, 0.00)
                ON CONFLICT (sl_owner_id, unit_id)
                DO UPDATE SET
                    owner_name = EXCLUDED.owner_name,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    property_name = EXCLUDED.property_name,
                    synced_at = CURRENT_TIMESTAMP
            """), {
                "owner_id": req.sl_owner_id,
                "unit_id": pid,
                "name": req.owner_name,
                "email": req.email,
                "phone": req.phone,
                "prop_name": prop_name,
            })

        # ── 2. management_splits ─────────────────────────────────
        for pid in req.property_ids:
            await db.execute(text("""
                INSERT INTO management_splits (property_id, owner_pct, pm_pct, effective_date)
                VALUES (:pid, :owner_pct, :pm_pct, CURRENT_DATE)
                ON CONFLICT (property_id)
                DO UPDATE SET
                    owner_pct = EXCLUDED.owner_pct,
                    pm_pct = EXCLUDED.pm_pct,
                    effective_date = CURRENT_DATE
            """), {
                "pid": pid,
                "owner_pct": req.owner_pct,
                "pm_pct": req.pm_pct,
            })

        # ── 3. owner_markup_rules ────────────────────────────────
        for pid in req.property_ids:
            await db.execute(text("""
                INSERT INTO owner_markup_rules (property_id, expense_category, markup_percentage)
                VALUES (:pid, 'ALL', :markup)
                ON CONFLICT (property_id, expense_category)
                DO UPDATE SET
                    markup_percentage = EXCLUDED.markup_percentage,
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "pid": pid,
                "markup": req.markup_pct,
            })

        # ── 4. trust_balance ─────────────────────────────────────
        for pid in req.property_ids:
            await db.execute(text("""
                INSERT INTO trust_balance (property_id, owner_funds, operating_funds, escrow_funds, security_deps)
                VALUES (:pid, 0, 0, 0, 0)
                ON CONFLICT (property_id) DO NOTHING
            """), {"pid": pid})
            properties_seeded.append(pid)

        # ── 5. accounts — per-property 2000 sub-ledger ──────────
        parent_result = await db.execute(text(
            "SELECT id FROM accounts WHERE code = '2000' LIMIT 1"
        ))
        parent_row = parent_result.fetchone()
        parent_id = parent_row.id if parent_row else None

        for pid in req.property_ids:
            sub_code = f"2000-{pid}"
            await db.execute(text("""
                INSERT INTO accounts
                    (code, name, account_type, sub_type, normal_balance,
                     parent_id, property_id, is_active, description)
                VALUES
                    (:code, :name, 'Liability', 'Trust', 'credit',
                     :parent_id, :pid, TRUE, :desc)
                ON CONFLICT (code)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    property_id = EXCLUDED.property_id,
                    is_active = TRUE
            """), {
                "code": sub_code,
                "name": f"Trust Liability — {req.owner_name} ({pid})",
                "parent_id": parent_id,
                "pid": pid,
                "desc": f"Owner trust sub-ledger for {req.owner_name}, property {pid}",
            })
            sub_ledger_accounts.append(sub_code)

        # ── 6. Magic Link ────────────────────────────────────────
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(hours=24)

        await db.execute(text("""
            INSERT INTO owner_magic_tokens (token_hash, owner_email, sl_owner_id, expires_at)
            VALUES (:hash, :email, :owner_id, :expires)
        """), {
            "hash": token_hash,
            "email": req.email,
            "owner_id": req.sl_owner_id,
            "expires": expires_at,
        })

        login_url = f"https://crog-ai.com/owner-login?token={raw_token}"

        await db.commit()

        logger.info(
            "owner_onboarded",
            owner_id=req.sl_owner_id,
            owner_name=req.owner_name,
            properties=req.property_ids,
            splits=f"{req.owner_pct}/{req.pm_pct}",
            markup=req.markup_pct,
        )

        # ── 7. Background: contract ingestion ────────────────────
        contract_ingested = False
        contract_ingestion_job_id = None
        if req.contract_nas_path:
            contract_job = await enqueue_async_job(
                db,
                worker_name="run_contract_ingestion_job",
                job_name="run_contract_ingestion",
                payload={
                    "nas_path": req.contract_nas_path,
                    "owner_id": req.sl_owner_id,
                },
                requested_by=extract_request_actor(
                    request.headers.get("x-user-id"),
                    request.headers.get("x-user-email"),
                ),
                tenant_id=getattr(request.state, "tenant_id", None),
                request_id=request.headers.get("x-request-id"),
                redis=arq_redis,
            )
            contract_ingested = True
            contract_ingestion_job_id = str(contract_job.id)

        return {
            "status": "onboarded",
            "owner_id": req.sl_owner_id,
            "owner_name": req.owner_name,
            "properties_seeded": properties_seeded,
            "splits": {"owner_pct": req.owner_pct, "pm_pct": req.pm_pct},
            "markup_pct": req.markup_pct,
            "trust_accounts_created": len(properties_seeded),
            "sub_ledger_accounts": sub_ledger_accounts,
            "contract_ingested": contract_ingested,
            "contract_ingestion_job_id": contract_ingestion_job_id,
            "magic_link_url": login_url,
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            "owner_onboarding_failed",
            owner_id=req.sl_owner_id,
            error=str(e)[:500],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Owner onboarding failed: {str(e)[:200]}",
        )


# ============================================================================
# Marketing Budgets — Fleet-Wide Escrow & Attribution Report
# ============================================================================

@router.get("/marketing-budgets")
async def get_marketing_budgets(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Fleet-wide marketing escrow balances and latest attribution metrics."""
    try:
        prefs_result = await db.execute(text("""
            SELECT
                omp.property_id,
                omp.marketing_pct,
                omp.enabled,
                p.name AS property_name,
                COALESCE(
                    (SELECT SUM(jli.credit) - SUM(jli.debit)
                     FROM journal_line_items jli
                     JOIN accounts a ON a.id = jli.account_id
                     JOIN journal_entries je ON je.id = jli.journal_entry_id
                     WHERE a.code = '2400' AND je.property_id = omp.property_id),
                    0
                ) AS escrow_balance
            FROM owner_marketing_preferences omp
            LEFT JOIN properties p ON p.streamline_property_id = omp.property_id
            ORDER BY omp.property_id
        """))
        prefs_rows = prefs_result.mappings().all()

        attr_result = await db.execute(text("""
            SELECT DISTINCT ON (property_id)
                property_id, period_start, period_end,
                ad_spend, impressions, clicks, direct_bookings,
                gross_revenue, roas
            FROM marketing_attribution
            ORDER BY property_id, period_end DESC
        """))
        attr_map = {
            row["property_id"]: dict(row)
            for row in attr_result.mappings().all()
        }

        properties = []
        total_escrow = 0.0
        total_ad_spend = 0.0
        for row in prefs_rows:
            pid = row["property_id"]
            escrow = float(row["escrow_balance"])
            total_escrow += escrow
            attr = attr_map.get(pid, {})
            ad_spend = float(attr.get("ad_spend", 0))
            total_ad_spend += ad_spend
            properties.append({
                "property_id": pid,
                "property_name": row["property_name"],
                "marketing_pct": float(row["marketing_pct"]),
                "enabled": bool(row["enabled"]),
                "escrow_balance": escrow,
                "latest_attribution": {
                    "period_start": str(attr["period_start"]) if attr.get("period_start") else None,
                    "period_end": str(attr["period_end"]) if attr.get("period_end") else None,
                    "ad_spend": ad_spend,
                    "impressions": int(attr.get("impressions", 0)),
                    "clicks": int(attr.get("clicks", 0)),
                    "direct_bookings": int(attr.get("direct_bookings", 0)),
                    "gross_revenue": float(attr.get("gross_revenue", 0)),
                    "roas": float(attr.get("roas", 0)),
                } if attr else None,
            })

        return {
            "fleet_totals": {
                "total_escrow": round(total_escrow, 2),
                "total_ad_spend": round(total_ad_spend, 2),
                "properties_enrolled": sum(1 for p in properties if p["enabled"]),
                "properties_total": len(properties),
            },
            "properties": properties,
        }
    except Exception as e:
        logger.error("marketing_budgets_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch marketing budgets")


class MarketingAttributionEntry(BaseModel):
    period_start: str = Field(..., description="ISO date YYYY-MM-DD")
    period_end: str = Field(..., description="ISO date YYYY-MM-DD")
    ad_spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    direct_bookings: int = 0
    gross_revenue: float = 0.0
    campaign_notes: Optional[str] = None


@router.post("/marketing-attribution/{property_id}")
async def post_marketing_attribution(
    property_id: str,
    entry: MarketingAttributionEntry,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Admin enters campaign performance data for a property/period. ROAS auto-computed."""
    roas = round(entry.gross_revenue / entry.ad_spend, 2) if entry.ad_spend > 0 else 0.0
    try:
        result = await db.execute(
            text("""
                INSERT INTO marketing_attribution
                    (property_id, period_start, period_end, ad_spend, impressions,
                     clicks, direct_bookings, gross_revenue, roas, campaign_notes, entered_by)
                VALUES (:pid, :ps, :pe, :spend, :imp, :clk, :bk, :rev, :roas, :notes, 'admin')
                ON CONFLICT (property_id, period_start, period_end)
                DO UPDATE SET
                    ad_spend = EXCLUDED.ad_spend,
                    impressions = EXCLUDED.impressions,
                    clicks = EXCLUDED.clicks,
                    direct_bookings = EXCLUDED.direct_bookings,
                    gross_revenue = EXCLUDED.gross_revenue,
                    roas = EXCLUDED.roas,
                    campaign_notes = EXCLUDED.campaign_notes,
                    entered_by = 'admin'
                RETURNING id
            """),
            {
                "pid": property_id,
                "ps": entry.period_start,
                "pe": entry.period_end,
                "spend": entry.ad_spend,
                "imp": entry.impressions,
                "clk": entry.clicks,
                "bk": entry.direct_bookings,
                "rev": entry.gross_revenue,
                "roas": roas,
                "notes": entry.campaign_notes,
            },
        )
        await db.commit()
        row = result.first()

        logger.info(
            "marketing_attribution_entered",
            property_id=property_id,
            period=f"{entry.period_start} to {entry.period_end}",
            roas=roas,
        )

        return {
            "status": "ok",
            "id": row[0] if row else None,
            "property_id": property_id,
            "roas": roas,
        }
    except Exception as e:
        await db.rollback()
        logger.error("marketing_attribution_post_error", property_id=property_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save attribution data")
