"""
Legal Email Intake API
======================
CRUD endpoints for the legal.email_intake_queue table.

Mounted at /api/internal/legal (INTERNAL_LEGAL_API_PREFIX) alongside all
other legal API routers.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from backend.core.security import require_manager_or_admin
from backend.services.ediscovery_agent import LegacySession

logger = structlog.get_logger(service="legal_email_intake_api")

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy RowMapping or Row to a plain dict."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if hasattr(row, "_asdict"):
        return row._asdict()
    return dict(row)


# ── List intake queue ─────────────────────────────────────────────────────────

@router.get("/email-intake", summary="List legal email intake queue")
async def list_email_intake(
    status: Optional[str] = Query(default=None, description="Filter by intake_status: pending|linked|unlinked|rejected"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    async with LegacySession() as session:
        where_clause = "WHERE intake_status = :status" if status else ""
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        result = await session.execute(
            text(f"""
                SELECT id, message_uid, sender_email, sender_name, subject,
                       case_slug, triage_result, intake_status, attachment_count,
                       correspondence_id, received_at, processed_at
                FROM legal.email_intake_queue
                {where_clause}
                ORDER BY received_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM legal.email_intake_queue {where_clause}"),
            {"status": status} if status else {},
        )
        total = count_result.scalar() or 0

    items = []
    for r in rows:
        d = _row_to_dict(r)
        if isinstance(d.get("triage_result"), str):
            try:
                d["triage_result"] = json.loads(d["triage_result"])
            except (json.JSONDecodeError, TypeError):
                pass
        # Serialize datetimes
        for k in ("received_at", "processed_at"):
            if d.get(k) and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ── Single intake record (includes body_text) ─────────────────────────────────

@router.get("/email-intake/{intake_id}", summary="Get full email intake record")
async def get_email_intake(intake_id: int):
    async with LegacySession() as session:
        result = await session.execute(
            text("SELECT * FROM legal.email_intake_queue WHERE id = :id"),
            {"id": intake_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Intake record {intake_id} not found")

    d = _row_to_dict(row)
    if isinstance(d.get("triage_result"), str):
        try:
            d["triage_result"] = json.loads(d["triage_result"])
        except (json.JSONDecodeError, TypeError):
            pass
    for k in ("received_at", "processed_at", "created_at"):
        if d.get(k) and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


# ── Manual case link ──────────────────────────────────────────────────────────

class LinkRequest(BaseModel):
    case_slug: str


@router.post("/email-intake/{intake_id}/link", summary="Manually link email to a case")
async def link_email_to_case(intake_id: int, body: LinkRequest):
    case_slug = body.case_slug.strip()
    if not case_slug:
        raise HTTPException(status_code=422, detail="case_slug is required")

    async with LegacySession() as session:
        # Verify case exists
        case_row = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug LIMIT 1"),
            {"slug": case_slug},
        )
        if not case_row.fetchone():
            raise HTTPException(status_code=404, detail=f"Case '{case_slug}' not found")

        # Fetch existing intake record
        intake_result = await session.execute(
            text("SELECT * FROM legal.email_intake_queue WHERE id = :id"),
            {"id": intake_id},
        )
        intake = intake_result.fetchone()
        if not intake:
            raise HTTPException(status_code=404, detail=f"Intake record {intake_id} not found")

        intake_dict = _row_to_dict(intake)

        # Create correspondence row if not already linked
        correspondence_id = intake_dict.get("correspondence_id")
        if not correspondence_id:
            from backend.services.legal_email_intake import _record_correspondence, _record_timeline_event
            correspondence_id = await _record_correspondence(
                case_slug=case_slug,
                subject=intake_dict.get("subject", ""),
                body=intake_dict.get("body_text", ""),
                sender_email=intake_dict.get("sender_email", ""),
                sender_name=intake_dict.get("sender_name", "") or "",
                category="correspondence",
                session=session,
            )
            await _record_timeline_event(
                case_slug=case_slug,
                subject=intake_dict.get("subject", ""),
                sender_email=intake_dict.get("sender_email", ""),
                session=session,
            )

        # Update intake queue record
        await session.execute(
            text("""
                UPDATE legal.email_intake_queue
                SET case_slug        = :slug,
                    intake_status    = 'linked',
                    correspondence_id = :cid,
                    processed_at     = now()
                WHERE id = :id
            """),
            {"slug": case_slug, "cid": correspondence_id, "id": intake_id},
        )
        await session.commit()

    logger.info("legal_intake_manual_link", intake_id=intake_id, case_slug=case_slug)
    return {"linked": True, "case_slug": case_slug, "correspondence_id": correspondence_id}


# ── Reject ────────────────────────────────────────────────────────────────────

@router.post("/email-intake/{intake_id}/reject", summary="Reject intake email as non-legal")
async def reject_email_intake(intake_id: int):
    async with LegacySession() as session:
        result = await session.execute(
            text("""
                UPDATE legal.email_intake_queue
                SET intake_status = 'rejected',
                    processed_at  = now()
                WHERE id = :id
                RETURNING id
            """),
            {"id": intake_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Intake record {intake_id} not found")
        await session.commit()

    return {"rejected": True, "id": intake_id}


# ── Manual trigger ────────────────────────────────────────────────────────────

@router.post("/email-intake/trigger", summary="Trigger a manual email intake patrol cycle")
async def trigger_email_intake(background_tasks: BackgroundTasks):
    async def _run() -> None:
        from backend.services.legal_email_intake import run_legal_intake_patrol
        try:
            result = await run_legal_intake_patrol()
            logger.info("legal_intake_manual_trigger_complete", **result)
        except Exception as exc:
            logger.error("legal_intake_manual_trigger_error", error=str(exc)[:200])

    background_tasks.add_task(_run)
    return {"triggered": True}
