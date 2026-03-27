"""
Dispute Exception Desk — Admin API for chargeback monitoring and manual intervention.

Endpoints:
  GET  /api/admin/disputes/stats          — Telemetry HUD data
  GET  /api/admin/disputes                — Paginated active dispute list
  GET  /api/admin/disputes/{id}/evidence  — Download compiled evidence PDF
  POST /api/admin/disputes/{id}/upload-evidence — Manual photo/doc upload + re-compile
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.core.security import require_admin
from backend.services.async_jobs import enqueue_async_job, extract_request_actor

logger = structlog.get_logger(service="disputes_api")

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_EVIDENCE_DIR = Path(
    os.getenv("EVIDENCE_STORAGE_DIR", str(PROJECT_ROOT / "storage" / "evidence"))
)


@router.get("/stats")
async def dispute_stats(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Telemetry HUD: win rate, funds locked, active ops, recovered YTD."""
    row = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('won', 'lost', 'expired'))       AS total_active,
                COALESCE(SUM(dispute_amount) FILTER (WHERE status NOT IN ('won', 'lost', 'expired')), 0)
                    AS total_disputed_amount,
                COUNT(*) FILTER (WHERE status = 'won')                                 AS win_count,
                COUNT(*) FILTER (WHERE status = 'lost')                                AS loss_count,
                COALESCE(SUM(dispute_amount) FILTER (
                    WHERE status = 'won'
                      AND updated_at >= date_trunc('year', NOW())
                ), 0) AS funds_recovered_ytd,
                COUNT(*) AS total_all_time
            FROM dispute_evidence
        """)
    )
    r = row.first()
    if not r:
        return {
            "total_active": 0, "total_disputed_amount": 0, "win_count": 0,
            "loss_count": 0, "win_rate_pct": 0, "funds_recovered_ytd": 0,
            "by_reason_code": {}, "by_status": {},
        }

    m = r._mapping
    resolved = (m["win_count"] or 0) + (m["loss_count"] or 0)
    win_rate = round(((m["win_count"] or 0) / resolved * 100) if resolved > 0 else 0, 1)

    reason_rows = await db.execute(
        text("""
            SELECT COALESCE(dispute_reason, 'unknown') AS reason, COUNT(*) AS cnt,
                   COALESCE(SUM(dispute_amount), 0) AS amount
            FROM dispute_evidence GROUP BY dispute_reason
        """)
    )
    by_reason = {
        rr.reason: {"count": rr.cnt, "amount": float(rr.amount)}
        for rr in reason_rows.all()
    }

    status_rows = await db.execute(
        text("SELECT status, COUNT(*) AS cnt FROM dispute_evidence GROUP BY status")
    )
    by_status = {sr.status: sr.cnt for sr in status_rows.all()}

    return {
        "total_active": m["total_active"] or 0,
        "total_disputed_amount": float(m["total_disputed_amount"] or 0),
        "win_count": m["win_count"] or 0,
        "loss_count": m["loss_count"] or 0,
        "win_rate_pct": win_rate,
        "funds_recovered_ytd": float(m["funds_recovered_ytd"] or 0),
        "by_reason_code": by_reason,
        "by_status": by_status,
    }


@router.get("/")
async def list_disputes(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Active battlefield — paginated dispute list sorted by urgency."""
    offset = (page - 1) * per_page

    where_clause = ""
    params: dict = {"limit": per_page, "offset": offset}
    if status_filter:
        where_clause = "WHERE de.status = :sf"
        params["sf"] = status_filter

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM dispute_evidence de {where_clause}"),
        params,
    )
    total = count_row.scalar() or 0

    result = await db.execute(
        text(f"""
            SELECT
                de.id,
                de.dispute_id,
                de.dispute_amount,
                de.dispute_reason,
                de.dispute_status,
                de.status AS evidence_status,
                de.iot_events_count,
                de.evidence_pdf_path,
                de.submitted_to_stripe_at,
                de.created_at,
                de.created_at + interval '7 days' AS response_deadline,
                r.confirmation_code,
                r.check_in_date,
                r.check_out_date,
                g.first_name || ' ' || g.last_name AS guest_name,
                g.email AS guest_email,
                p.name AS property_name
            FROM dispute_evidence de
            LEFT JOIN reservations r ON de.reservation_id = r.id
            LEFT JOIN guests g ON de.guest_id = g.id
            LEFT JOIN properties p ON de.property_id = p.id
            {where_clause}
            ORDER BY
                CASE WHEN de.status IN ('pending', 'evidence_compiled') THEN 0 ELSE 1 END,
                de.created_at + interval '7 days' ASC,
                de.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    disputes = []
    for row in result.all():
        m = row._mapping
        deadline = m.get("response_deadline")
        now = datetime.now(timezone.utc)
        days_remaining = None
        if deadline:
            try:
                if hasattr(deadline, "tzinfo") and deadline.tzinfo is None:
                    from datetime import timezone as tz
                    deadline = deadline.replace(tzinfo=tz.utc)
                days_remaining = max(0, (deadline - now).days)
            except Exception:
                pass

        disputes.append({
            "id": str(m["id"]),
            "dispute_id": m["dispute_id"],
            "dispute_amount": float(m["dispute_amount"]) if m["dispute_amount"] else 0,
            "dispute_reason": m["dispute_reason"] or "unknown",
            "dispute_status": m["dispute_status"] or "needs_response",
            "evidence_status": m["evidence_status"],
            "iot_events_count": m["iot_events_count"] or 0,
            "has_evidence_pdf": bool(m["evidence_pdf_path"]),
            "submitted_to_stripe_at": m["submitted_to_stripe_at"].isoformat() if m["submitted_to_stripe_at"] else None,
            "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            "response_deadline": deadline.isoformat() if deadline else None,
            "days_remaining": days_remaining,
            "confirmation_code": m["confirmation_code"],
            "check_in_date": str(m["check_in_date"]) if m["check_in_date"] else None,
            "check_out_date": str(m["check_out_date"]) if m["check_out_date"] else None,
            "guest_name": (m["guest_name"] or "").strip() or "Unknown",
            "guest_email": m["guest_email"],
            "property_name": m["property_name"] or "Unknown Property",
        })

    return {
        "data": disputes,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, -(-total // per_page)),
        },
    }


@router.get("/{dispute_id}/evidence")
async def download_evidence(
    dispute_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Download the compiled evidence PDF for a dispute."""
    result = await db.execute(
        text("SELECT evidence_pdf_path FROM dispute_evidence WHERE dispute_id = :did"),
        {"did": dispute_id},
    )
    row = result.first()
    if not row or not row.evidence_pdf_path:
        raise HTTPException(status_code=404, detail="Evidence PDF not found for this dispute")

    pdf_path = Path(row.evidence_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Evidence PDF file missing from storage")

    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"evidence_packet_{dispute_id}.pdf",
    )


@router.post("/{dispute_id}/upload-evidence")
async def upload_evidence(
    dispute_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
    _user=Depends(require_admin),
):
    """Manually upload additional evidence (photos, docs) and trigger re-compilation."""
    result = await db.execute(
        text("SELECT id, reservation_id FROM dispute_evidence WHERE dispute_id = :did"),
        {"did": dispute_id},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Dispute not found")

    upload_dir = LOCAL_EVIDENCE_DIR / dispute_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename or "upload"
    safe_name = "".join(c if c.isalnum() or c in (".", "-", "_") else "_" for c in safe_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = upload_dir / f"{ts}_{safe_name}"

    content = await file.read()
    dest.write_bytes(content)

    logger.info(
        "manual_evidence_uploaded",
        dispute_id=dispute_id,
        filename=safe_name,
        size_bytes=len(content),
    )

    try:
        nas_dir = Path("/mnt/fortress_nas/sectors/legal/chargeback-evidence") / dispute_id / "uploads"
        if nas_dir.parent.parent.exists():
            nas_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(dest), str(nas_dir / dest.name))
    except Exception as e:
        logger.warning("nas_upload_copy_failed", error=str(e)[:200])

    reservation_id = str(row.reservation_id) if row.reservation_id else ""
    recompile_job = await enqueue_async_job(
        db,
        worker_name="run_dispute_evidence_job",
        job_name="run_dispute_evidence",
        payload={
            "dispute_id": dispute_id,
            "reservation_id": reservation_id,
        },
        requested_by=extract_request_actor(
            request.headers.get("x-user-id"),
            request.headers.get("x-user-email"),
        ),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )

    return {
        "status": "uploaded",
        "dispute_id": dispute_id,
        "filename": safe_name,
        "size_bytes": len(content),
        "recompile_triggered": True,
        "recompile_job_id": str(recompile_job.id),
    }
