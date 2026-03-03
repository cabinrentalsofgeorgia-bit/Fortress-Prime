"""
LEGAL CASES CRUD API — Queries legal.* schema in fortress_db
=============================================================

Provides GET endpoints for the Next.js Legal Command Center dashboard:
    GET  /cases                          — List all cases
    GET  /cases/{slug}                   — Case detail + actions/evidence/watchdog
    GET  /cases/{slug}/deadlines         — Case deadlines with computed fields
    GET  /cases/{slug}/correspondence    — Case correspondence
    GET  /cases/{slug}/timeline          — Unified timeline
    PUT  /deadlines/{deadline_id}        — Update deadline review status
    POST /cases/{slug}/correspondence    — Create correspondence
    POST /cases/{slug}/extract           — Trigger extraction (stub)

Database: fortress_db (read via shared async engine from ediscovery_agent)
"""

import json
import os
import structlog
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.services.ediscovery_agent import LegacySession

logger = structlog.get_logger()

router = APIRouter()


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy Row to a plain dict, serializing dates/datetimes."""
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


def _compute_days_remaining(critical_date_str: str | None) -> int | None:
    if not critical_date_str:
        return None
    try:
        cd = date.fromisoformat(critical_date_str) if isinstance(critical_date_str, str) else critical_date_str
        return (cd - date.today()).days
    except (ValueError, TypeError):
        return None


def _compute_deadline_fields(d: dict) -> dict:
    """Add computed fields that the frontend expects: days_remaining, effective_date, urgency."""
    due = d.get("due_date")
    extended = d.get("extended_to")
    effective = extended or due

    if isinstance(effective, str):
        try:
            eff_date = date.fromisoformat(effective)
        except ValueError:
            eff_date = None
    elif isinstance(effective, date):
        eff_date = effective
    else:
        eff_date = None

    days_remaining = (eff_date - date.today()).days if eff_date else None

    if days_remaining is None:
        urgency = "unknown"
    elif days_remaining < 0:
        urgency = "overdue"
    elif days_remaining <= 3:
        urgency = "critical"
    elif days_remaining <= 7:
        urgency = "urgent"
    elif days_remaining <= 14:
        urgency = "warning"
    else:
        urgency = "normal"

    d["days_remaining"] = days_remaining
    d["effective_date"] = effective.isoformat() if isinstance(effective, date) else effective
    d["urgency"] = urgency
    return d


# ── Cases ────────────────────────────────────────────────────────────

@router.get("/cases", summary="List all legal cases")
async def list_cases():
    async with LegacySession() as session:
        result = await session.execute(text("""
            SELECT c.*,
                   d.consensus_signal  AS live_ai_status,
                   d.trigger_type      AS latest_action,
                   d.timestamp         AS last_ai_review
            FROM legal.cases c
            LEFT JOIN LATERAL (
                SELECT consensus_signal, trigger_type, timestamp
                FROM legal_cmd.deliberation_events
                WHERE case_slug = c.case_slug
                ORDER BY timestamp DESC
                LIMIT 1
            ) d ON true
            ORDER BY c.critical_date ASC NULLS LAST, c.id
        """))
        rows = result.fetchall()

    cases = []
    for row in rows:
        d = _row_to_dict(row)
        d["days_remaining"] = _compute_days_remaining(d.get("critical_date"))
        if isinstance(d.get("extracted_entities"), str):
            try:
                d["extracted_entities"] = json.loads(d["extracted_entities"])
            except (json.JSONDecodeError, TypeError):
                d["extracted_entities"] = {}
        cases.append(d)

    return {"cases": cases}


@router.get("/cases/{slug}", summary="Get case detail")
async def get_case(slug: str):
    async with LegacySession() as session:
        result = await session.execute(
            text("SELECT * FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        case = _row_to_dict(row)
        case["days_remaining"] = _compute_days_remaining(case.get("critical_date"))
        if isinstance(case.get("extracted_entities"), str):
            try:
                case["extracted_entities"] = json.loads(case["extracted_entities"])
            except (json.JSONDecodeError, TypeError):
                case["extracted_entities"] = {}

        actions_r = await session.execute(
            text("SELECT * FROM legal.case_actions WHERE case_id = :cid ORDER BY action_date DESC"),
            {"cid": case["id"]},
        )
        actions = [_row_to_dict(r) for r in actions_r.fetchall()]

        evidence_r = await session.execute(
            text("SELECT * FROM legal.case_evidence WHERE case_id = :cid ORDER BY discovered_at DESC"),
            {"cid": case["id"]},
        )
        evidence = [_row_to_dict(r) for r in evidence_r.fetchall()]

        watchdog_r = await session.execute(
            text("SELECT * FROM legal.case_watchdog WHERE case_id = :cid ORDER BY priority"),
            {"cid": case["id"]},
        )
        watchdog = [_row_to_dict(r) for r in watchdog_r.fetchall()]

    return {
        "case": case,
        "actions": actions,
        "evidence": evidence,
        "watchdog": watchdog,
    }


# ── Deadlines ────────────────────────────────────────────────────────

@router.get("/cases/{slug}/deadlines", summary="List deadlines for a case")
async def list_deadlines(slug: str):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        result = await session.execute(
            text("SELECT * FROM legal.deadlines WHERE case_id = :cid ORDER BY due_date ASC"),
            {"cid": case_row.id},
        )
        rows = result.fetchall()

    deadlines = [_compute_deadline_fields(_row_to_dict(r)) for r in rows]
    return {"deadlines": deadlines}


class DeadlineUpdate(BaseModel):
    review_status: str = Field(..., pattern="^(approved|rejected|pending_review)$")


@router.put("/deadlines/{deadline_id}", summary="Update deadline review status")
async def update_deadline(deadline_id: int, body: DeadlineUpdate):
    async with LegacySession() as session:
        result = await session.execute(
            text("UPDATE legal.deadlines SET review_status = :status WHERE id = :did RETURNING id"),
            {"status": body.review_status, "did": deadline_id},
        )
        row = result.fetchone()
        await session.commit()
        if not row:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
    return {"updated": True}


# ── Correspondence ───────────────────────────────────────────────────

@router.get("/cases/{slug}/correspondence", summary="List correspondence for a case")
async def list_correspondence(slug: str):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        result = await session.execute(
            text("SELECT * FROM legal.correspondence WHERE case_id = :cid ORDER BY created_at DESC"),
            {"cid": case_row.id},
        )
        rows = result.fetchall()

    correspondence = []
    for r in rows:
        d = _row_to_dict(r)
        if isinstance(d.get("extracted_entities"), str):
            try:
                d["extracted_entities"] = json.loads(d["extracted_entities"])
            except (json.JSONDecodeError, TypeError):
                d["extracted_entities"] = {}
        correspondence.append(d)

    return {"correspondence": correspondence, "total": len(correspondence)}


class CorrespondenceCreate(BaseModel):
    subject: str = Field(..., min_length=1)
    body: Optional[str] = None
    direction: str = "outbound"
    comm_type: str = "email"
    recipient: Optional[str] = None
    recipient_email: Optional[str] = None


@router.post("/cases/{slug}/correspondence", summary="Create correspondence")
async def create_correspondence(slug: str, body: CorrespondenceCreate):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        result = await session.execute(
            text("""
                INSERT INTO legal.correspondence
                    (case_id, subject, body, direction, comm_type, recipient, recipient_email, status)
                VALUES (:cid, :subject, :body, :direction, :comm_type, :recipient, :email, 'draft')
                RETURNING id
            """),
            {
                "cid": case_row.id,
                "subject": body.subject,
                "body": body.body,
                "direction": body.direction,
                "comm_type": body.comm_type,
                "recipient": body.recipient,
                "email": body.recipient_email,
            },
        )
        new_row = result.fetchone()
        await session.commit()

    return {"created": True, "correspondence_id": new_row.id}


# ── Correspondence Vault (download / status / content) ───────────────

MIME_MAP = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"


@router.get("/correspondence/{corr_id}/download", summary="Download correspondence file from NAS")
async def download_correspondence(corr_id: int):
    async with LegacySession() as session:
        result = await session.execute(
            text("SELECT id, file_path, subject FROM legal.correspondence WHERE id = :cid"),
            {"cid": corr_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Correspondence {corr_id} not found")

    file_path = row.file_path
    if not file_path:
        raise HTTPException(status_code=404, detail="No file attached to this correspondence")

    if not os.path.isfile(file_path):
        logger.error("correspondence_file_missing", corr_id=corr_id, path=file_path)
        raise HTTPException(status_code=404, detail="File not found on NAS")

    if not file_path.startswith(NAS_LEGAL_ROOT) and not file_path.startswith("/home/admin/Fortress-Prime"):
        raise HTTPException(status_code=403, detail="Access denied — file outside legal vault")

    ext = Path(file_path).suffix.lower()
    media_type = MIME_MAP.get(ext, "application/octet-stream")
    filename = Path(file_path).name

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )


class CorrespondenceStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|approved|sent|cancelled)$")


@router.put("/correspondence/{corr_id}/status", summary="Update correspondence status")
async def update_correspondence_status(corr_id: int, body: CorrespondenceStatusUpdate):
    async with LegacySession() as session:
        row_check = await session.execute(
            text("SELECT id, case_id, status as old_status, subject FROM legal.correspondence WHERE id = :cid"),
            {"cid": corr_id},
        )
        existing = row_check.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Correspondence {corr_id} not found")

        sent_clause = ", sent_at = NOW()" if body.status == "sent" else ""
        approved_clause = ", approved_at = NOW(), approved_by = 'operator'" if body.status == "approved" else ""

        result = await session.execute(
            text(f"""
                UPDATE legal.correspondence
                SET status = :status {sent_clause} {approved_clause}
                WHERE id = :cid
                RETURNING id, status, sent_at
            """),
            {"status": body.status, "cid": corr_id},
        )
        updated = result.fetchone()

        await session.execute(
            text("""
                INSERT INTO legal.case_actions (case_id, action_type, description, status)
                VALUES (:case_id, 'status_change',
                        :desc,
                        :new_status)
            """),
            {
                "case_id": existing.case_id,
                "desc": f"Correspondence #{corr_id} status changed: {existing.old_status} -> {body.status} ({existing.subject})",
                "new_status": body.status,
            },
        )
        await session.commit()

    logger.info("correspondence_status_updated", corr_id=corr_id, new_status=body.status)
    return {
        "updated": True,
        "id": updated.id,
        "status": updated.status,
        "sent_at": updated.sent_at.isoformat() if updated.sent_at else None,
    }


@router.get("/correspondence/{corr_id}/content", summary="Get file content as text for clipboard copy")
async def get_correspondence_content(corr_id: int):
    async with LegacySession() as session:
        result = await session.execute(
            text("SELECT id, file_path, body, subject FROM legal.correspondence WHERE id = :cid"),
            {"cid": corr_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Correspondence {corr_id} not found")

    file_path = row.file_path
    filename = None

    if file_path and os.path.isfile(file_path):
        ext = Path(file_path).suffix.lower()
        if ext in (".txt", ".md", ".csv"):
            try:
                content = Path(file_path).read_text(encoding="utf-8")
                filename = Path(file_path).name
                return {"content": content, "filename": filename}
            except Exception as e:
                logger.error("correspondence_file_read_error", corr_id=corr_id, error=str(e))

    if row.body:
        return {"content": row.body, "filename": f"correspondence_{corr_id}.txt"}

    raise HTTPException(status_code=404, detail="No readable content available")


# ── Case File Download (NAS) ──────────────────────────────────────────

_CASE_SUBDIRS = ("certified_mail", "correspondence", "evidence", "receipts", "filings/incoming", "filings/outgoing")


@router.get("/cases/{slug}/download/{filename}", summary="Download a file from a case's NAS vault")
async def download_case_file(slug: str, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        if not case_r.fetchone():
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

    case_root = Path(NAS_LEGAL_ROOT) / slug
    for subdir in _CASE_SUBDIRS:
        candidate = case_root / subdir / filename
        if candidate.is_file():
            resolved = candidate.resolve()
            if not str(resolved).startswith(NAS_LEGAL_ROOT):
                raise HTTPException(status_code=403, detail="Access denied")
            ext = candidate.suffix.lower()
            media_type = MIME_MAP.get(ext, "application/octet-stream")
            logger.info("legal_file_download", slug=slug, filename=filename, subdir=subdir)
            return FileResponse(path=str(resolved), media_type=media_type, filename=filename)

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found in case vault")


@router.get("/cases/{slug}/files", summary="List all files in a case's NAS vault")
async def list_case_files(slug: str):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        if not case_r.fetchone():
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

    case_root = Path(NAS_LEGAL_ROOT) / slug
    files: list[dict[str, Any]] = []
    for subdir in _CASE_SUBDIRS:
        d = case_root / subdir
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "subdir": subdir,
                    "size_bytes": f.stat().st_size,
                    "download_url": f"/api/legal/cases/{slug}/download/{f.name}",
                })
    return {"case_slug": slug, "files": files, "total": len(files)}


# ── Timeline ─────────────────────────────────────────────────────────

@router.get("/cases/{slug}/timeline", summary="Unified case timeline")
async def get_timeline(slug: str):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        cid = case_row.id

        actions_r = await session.execute(
            text("""
                SELECT 'action' as event_type, description as summary,
                       COALESCE(notes, '') as detail, status,
                       action_date as event_time, id as ref_id
                FROM legal.case_actions WHERE case_id = :cid
            """),
            {"cid": cid},
        )

        corr_r = await session.execute(
            text("""
                SELECT 'correspondence' as event_type,
                       subject as summary,
                       COALESCE(LEFT(body, 200), '') as detail,
                       status,
                       created_at as event_time, id as ref_id
                FROM legal.correspondence WHERE case_id = :cid
            """),
            {"cid": cid},
        )

        deadlines_r = await session.execute(
            text("""
                SELECT 'deadline' as event_type,
                       description as summary,
                       COALESCE(extension_reason, '') as detail,
                       status,
                       due_date::timestamp as event_time, id as ref_id
                FROM legal.deadlines WHERE case_id = :cid
            """),
            {"cid": cid},
        )

        evidence_r = await session.execute(
            text("""
                SELECT 'evidence' as event_type,
                       COALESCE(description, evidence_type) as summary,
                       '' as detail,
                       CASE WHEN is_critical THEN 'critical' ELSE 'normal' END as status,
                       discovered_at as event_time, id as ref_id
                FROM legal.case_evidence WHERE case_id = :cid
            """),
            {"cid": cid},
        )

    events = []
    for result_set in [actions_r, corr_r, deadlines_r, evidence_r]:
        for row in result_set.fetchall():
            events.append(_row_to_dict(row))

    events.sort(key=lambda e: e.get("event_time", "") or "", reverse=True)
    return events


# ── Extraction Stub ──────────────────────────────────────────────────

class WarRoomStateUpdate(BaseModel):
    active_brief: Optional[str] = None
    active_consensus: Optional[dict] = None


@router.get("/cases/{slug}/state", summary="Get war room persistent state")
async def get_war_room_state(slug: str):
    async with LegacySession() as session:
        result = await session.execute(
            text("SELECT active_brief, active_consensus FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        d = dict(row._mapping)
        if isinstance(d.get("active_consensus"), str):
            try:
                d["active_consensus"] = json.loads(d["active_consensus"])
            except (json.JSONDecodeError, TypeError):
                d["active_consensus"] = None

    return {"active_brief": d.get("active_brief"), "active_consensus": d.get("active_consensus")}


@router.patch("/cases/{slug}/state", summary="Save war room persistent state")
async def patch_war_room_state(slug: str, body: WarRoomStateUpdate):
    sets: list[str] = []
    params: dict[str, Any] = {"slug": slug}

    if body.active_brief is not None:
        sets.append("active_brief = :brief")
        params["brief"] = body.active_brief

    if body.active_consensus is not None:
        sets.append("active_consensus = :consensus")
        params["consensus"] = json.dumps(body.active_consensus)

    if not sets:
        raise HTTPException(status_code=422, detail="No fields provided to update")

    sets.append("updated_at = now()")
    query = f"UPDATE legal.cases SET {', '.join(sets)} WHERE case_slug = :slug RETURNING id"

    async with LegacySession() as session:
        result = await session.execute(text(query), params)
        row = result.fetchone()
        await session.commit()
        if not row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

    logger.info("war_room_state_saved", slug=slug,
                has_brief=body.active_brief is not None,
                has_consensus=body.active_consensus is not None)
    return {"saved": True, "case_slug": slug}


# ── Extraction Stub ──────────────────────────────────────────────────

class ExtractionRequest(BaseModel):
    target: str
    text: Optional[str] = None
    correspondence_id: Optional[int] = None


@router.post("/cases/{slug}/extract", summary="Queue entity extraction")
async def trigger_extraction(slug: str, body: ExtractionRequest):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

    logger.info("legal_extraction_queued", slug=slug, target=body.target)
    return {
        "extraction": "queued",
        "target": body.target,
        "id": case_row.id,
    }
