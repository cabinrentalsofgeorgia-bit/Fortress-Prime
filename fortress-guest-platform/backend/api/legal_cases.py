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

import asyncio
import json
import hashlib
import os
import random
import difflib
import structlog
import uuid
from uuid import UUID

import httpx
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from backend.core.database import AsyncSessionLocal
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_extractor import extract_entities
from backend.services.legal_case_graph import (
    HiveMindFeedback,
    get_case_graph_snapshot,
    trigger_graph_refresh,
)
from backend.services.legal_discovery_engine import generate_discovery_pack, validate_discovery_pack
from backend.services.legal_deposition_engine import (
    DepositionKillSheet,
    build_cross_exam_funnels,
    generate_kill_sheet,
    get_deposition_targets,
    stream_cross_exam_funnels,
)
from backend.schemas.legal_schemas import (
    FunnelUpdateRequest,
    GraphSnapshotResponse,
    TargetStatusUpdateRequest,
)
from backend.models.legal_deposition import CrossExamFunnel, DepositionTarget
from backend.models.legal_graph import LegalCase

logger = structlog.get_logger()

router = APIRouter()


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy Row to a plain dict, serializing dates/datetimes."""
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


async def _legal_case_table_exists(session) -> bool:
    result = await session.execute(text("SELECT to_regclass('legal.cases') IS NOT NULL"))
    return bool(result.scalar())


async def _assert_case_exists_if_supported(session, slug: str) -> None:
    if not await _legal_case_table_exists(session):
        return
    case_r = await session.execute(
        text("SELECT id FROM legal.cases WHERE case_slug = :slug"),
        {"slug": slug},
    )
    if not case_r.fetchone():
        raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")


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
    target: str = Field(..., pattern="^(case|correspondence)$")
    text: Optional[str] = None
    correspondence_id: Optional[int] = None


class DiscoveryDraftPackRequest(BaseModel):
    # New dashboard contract: max discovery items capped by local rules.
    local_rules_cap: int = Field(default=25, ge=1, le=25)
    pack_type: str | None = Field(default=None, pattern="^(interrogatory|rfp|admission)$")
    item_limit: int = Field(default=5, ge=1, le=25)
    # Backward-compatible fields for older callers.
    target_party: str | None = Field(default=None)
    category: str | None = Field(default=None, pattern="^(interrogatory|rfp|admission)$")


class DepositionBuildFunnelRequest(BaseModel):
    target_name: str = Field(..., min_length=1, max_length=255)


class KillSheetRequest(BaseModel):
    deponent_name: str = Field(..., min_length=1, max_length=255)


class FeedbackPayload(BaseModel):
    module_type: str
    original_swarm_text: str
    human_edited_text: str
    accepted: bool


@router.get("/cases/{slug}/graph/snapshot", response_model=GraphSnapshotResponse, summary="Get legal case graph snapshot")
async def get_graph_snapshot(slug: str):
    async with AsyncSessionLocal() as session:
        snapshot = await get_case_graph_snapshot(session, case_slug=slug)
    if not snapshot or not snapshot.get("nodes"):
        raise HTTPException(status_code=404, detail="Case graph not found or empty.")

    nodes = [
        {
            "id": str(node.id),
            "entity_type": node.entity_type,
            "label": node.label,
            "node_metadata": node.node_metadata or {},
        }
        for node in snapshot["nodes"]
    ]
    edges = [
        {
            "id": str(edge.id),
            "source_node_id": str(edge.source_node_id),
            "target_node_id": str(edge.target_node_id),
            "relationship_type": edge.relationship_type,
            "weight": float(edge.weight or 0.0),
            "source_ref": edge.source_ref,
        }
        for edge in snapshot["edges"]
    ]
    return GraphSnapshotResponse(nodes=nodes, edges=edges)


async def _refresh_graph_background(case_slug: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await trigger_graph_refresh(session, case_slug=case_slug)
        except Exception as exc:
            await session.rollback()
            logger.error("legal_graph_refresh_failed", slug=case_slug, error=str(exc)[:280])


@router.post(
    "/cases/{slug}/graph/refresh",
    summary="Queue legal case graph refresh",
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_case_graph(slug: str, background_tasks: BackgroundTasks):
    # Fast-ack pattern: queue refresh so frontend stays responsive.
    background_tasks.add_task(_refresh_graph_background, slug)
    return {"status": "refresh_queued", "case_slug": slug}


@router.post("/cases/{slug}/discovery/draft-pack", summary="Generate discovery draft pack")
async def draft_discovery_pack(slug: str, body: DiscoveryDraftPackRequest):
    async with AsyncSessionLocal() as session:
        try:
            # Compat contract:
            # - New callers provide local_rules_cap only
            # - Legacy callers provide pack_type/category + item_limit
            resolved_pack_type = body.pack_type or body.category or "interrogatory"
            effective_limit = min(
                int(body.local_rules_cap or 25),
                int(body.item_limit or 25),
                25,
            )

            # Ensure there is enough graph context to draft discovery items.
            snapshot = await get_case_graph_snapshot(session, case_slug=slug)
            if not snapshot or not snapshot.get("nodes"):
                raise HTTPException(status_code=400, detail="Cannot draft discovery: Case graph is empty.")

            return await generate_discovery_pack(
                db=session,
                case_slug=slug,
                pack_type=resolved_pack_type,
                item_limit=effective_limit,
            )
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_discovery_draft_failed", slug=slug, error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to generate discovery draft pack")


@router.post("/cases/{slug}/discovery/{pack_id}/validate", summary="Validate Rule 26 proportionality for draft pack")
async def validate_discovery_draft_pack(slug: str, pack_id: UUID):
    async with AsyncSessionLocal() as session:
        try:
            return await validate_discovery_pack(db=session, pack_id=pack_id)
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_discovery_validate_failed", slug=slug, pack_id=str(pack_id), error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to validate discovery draft pack")


@router.post("/cases/{slug}/feedback/telemetry")
async def ingest_hive_mind_telemetry(slug: str, payload: FeedbackPayload):
    """
    Silently catches human edits from the Glass and writes them to the training ledger.
    """
    event_id = str(uuid.uuid4())
    ratio = difflib.SequenceMatcher(
        None,
        payload.original_swarm_text or "",
        payload.human_edited_text or "",
    ).ratio()
    edit_distance_pct = round((1 - ratio) * 100, 4)
    signature_hash = hashlib.sha256(
        f"{payload.original_swarm_text}||{payload.human_edited_text}".encode("utf-8")
    ).hexdigest()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO public.legal_hive_mind_feedback_events
                    (event_id, case_slug, source_route, draft_text, final_text, edit_distance_pct,
                     outcome_label, model_used, source_trace, signature_hash, created_at)
                VALUES
                    (CAST(:event_id AS uuid), :case_slug, :source_route, :draft_text, :final_text, :edit_distance_pct,
                     :outcome_label, :model_used, CAST(:source_trace AS jsonb), :signature_hash, NOW())
                ON CONFLICT (signature_hash) DO UPDATE
                    SET final_text = EXCLUDED.final_text,
                        edit_distance_pct = EXCLUDED.edit_distance_pct,
                        outcome_label = EXCLUDED.outcome_label,
                        model_used = EXCLUDED.model_used,
                        source_trace = EXCLUDED.source_trace,
                        created_at = NOW()
                RETURNING event_id
                """
            ),
            {
                "event_id": event_id,
                "case_slug": slug,
                "source_route": payload.module_type,
                "draft_text": payload.original_swarm_text,
                "final_text": payload.human_edited_text,
                "edit_distance_pct": edit_distance_pct,
                "outcome_label": "accepted" if payload.accepted else "rejected",
                "model_used": "hive-mind-telemetry-v1",
                "source_trace": json.dumps({"module_type": payload.module_type, "accepted": payload.accepted}),
                "signature_hash": signature_hash,
            },
        )
        await session.commit()

    persisted_event_id = str(result.scalar() or event_id)
    return {"status": "telemetry_logged", "event_id": persisted_event_id}


@router.post("/cases/{slug}/deposition/kill-sheet", response_model=DepositionKillSheet)
async def create_deposition_kill_sheet(slug: str, req: KillSheetRequest):
    """
    Commands the Swarm to cross-reference statements and draft an impeachment brief.
    """
    logger.info("[API] Kill-sheet requested for %s in %s", req.deponent_name, slug)
    try:
        kill_sheet = await generate_kill_sheet(slug, req.deponent_name)
        return kill_sheet
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("[API] Kill-sheet engine failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Swarm inference failed during kill-sheet drafting.")


@router.post("/cases/{slug}/deposition/build-funnel", summary="Build graph-driven cross-exam funnels")
async def build_deposition_funnel(slug: str, body: DepositionBuildFunnelRequest):
    async with AsyncSessionLocal() as session:
        try:
            return await build_cross_exam_funnels(
                db=session,
                case_slug=slug,
                target_name=body.target_name,
            )
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_deposition_build_failed", slug=slug, target=body.target_name, error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to build deposition funnel")


@router.get("/cases/{slug}/deposition/targets", summary="Get stored deposition targets and funnels")
async def list_deposition_targets(slug: str):
    async with AsyncSessionLocal() as session:
        try:
            return await get_deposition_targets(db=session, case_slug=slug)
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_deposition_targets_failed", slug=slug, error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to fetch deposition targets")


@router.patch("/cases/{slug}/deposition/funnels/{funnel_id}", summary="Update cross-exam funnel work product")
async def update_deposition_funnel(slug: str, funnel_id: UUID, body: FunnelUpdateRequest):
    async with AsyncSessionLocal() as session:
        try:
            case_res = await session.execute(select(LegalCase).where(LegalCase.slug == slug))
            case = case_res.scalar_one_or_none()
            if not case:
                raise HTTPException(status_code=404, detail=f"Legal case '{slug}' not found")

            funnel_res = await session.execute(select(CrossExamFunnel).where(CrossExamFunnel.id == funnel_id))
            funnel = funnel_res.scalar_one_or_none()
            if not funnel:
                raise HTTPException(status_code=404, detail=f"Funnel '{funnel_id}' not found")

            target_res = await session.execute(select(DepositionTarget).where(DepositionTarget.id == funnel.target_id))
            target = target_res.scalar_one_or_none()
            if not target or target.case_id != case.id:
                raise HTTPException(status_code=404, detail="Funnel not found for case")

            if body.lock_in_questions is not None:
                funnel.lock_in_questions = [str(q).strip() for q in body.lock_in_questions if str(q).strip()]
            if body.strike_script is not None:
                funnel.strike_script = body.strike_script.strip() or None

            await session.commit()
            return {
                "id": str(funnel.id),
                "target_id": str(funnel.target_id),
                "contradiction_edge_id": str(funnel.contradiction_edge_id),
                "topic": funnel.topic,
                "lock_in_questions": funnel.lock_in_questions or [],
                "the_strike_document": funnel.the_strike_document,
                "strike_script": funnel.strike_script,
                "created_at": funnel.created_at.isoformat() if funnel.created_at else None,
            }
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_deposition_funnel_update_failed", slug=slug, funnel_id=str(funnel_id), error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to update deposition funnel")


@router.patch("/cases/{slug}/deposition/targets/{target_id}/status", summary="Update deposition target status")
async def update_deposition_target_status(slug: str, target_id: UUID, body: TargetStatusUpdateRequest):
    async with AsyncSessionLocal() as session:
        try:
            case_res = await session.execute(select(LegalCase).where(LegalCase.slug == slug))
            case = case_res.scalar_one_or_none()
            if not case:
                raise HTTPException(status_code=404, detail=f"Legal case '{slug}' not found")

            target_res = await session.execute(select(DepositionTarget).where(DepositionTarget.id == target_id))
            target = target_res.scalar_one_or_none()
            if not target or target.case_id != case.id:
                raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found for case")

            target.status = body.status
            await session.commit()
            return {
                "id": str(target.id),
                "case_id": str(target.case_id),
                "entity_name": target.entity_name,
                "role": target.role,
                "status": target.status,
                "created_at": target.created_at.isoformat() if target.created_at else None,
            }
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("legal_deposition_target_status_update_failed", slug=slug, target_id=str(target_id), error=str(exc)[:280])
            raise HTTPException(status_code=500, detail="Failed to update deposition target status")


@router.get("/cases/{slug}/deposition/stream-funnel", summary="Stream cross-exam funnel generation")
async def stream_deposition_funnel(slug: str, target_name: str):
    async def event_stream():
        async with AsyncSessionLocal() as session:
            try:
                async for chunk in stream_cross_exam_funnels(
                    db=session,
                    case_slug=slug,
                    target_name=target_name,
                ):
                    yield chunk
            except HTTPException as exc:
                await session.rollback()
                detail = exc.detail if isinstance(exc.detail, str) else "Failed to stream deposition funnel"
                yield f"event: error\ndata: {json.dumps({'detail': detail})}\n\n"
                yield 'event: close\ndata: {"status": "error"}\n\n'
            except Exception as exc:
                await session.rollback()
                logger.error("legal_deposition_stream_failed", slug=slug, target=target_name, error=str(exc)[:280])
                yield 'event: error\ndata: {"detail":"Failed to stream deposition funnel"}\n\n'
                yield 'event: close\ndata: {"status": "error"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_extraction_job(
    *,
    slug: str,
    case_id: int,
    target: str,
    source_text: str,
    correspondence_id: int | None,
) -> None:
    async with LegacySession() as session:
        await session.execute(
            text("""
                UPDATE legal.cases
                SET extraction_status = 'processing', updated_at = now()
                WHERE id = :cid
            """),
            {"cid": case_id},
        )
        await session.commit()

    try:
        entities, model_used = await extract_entities(
            source_text=source_text,
            target=target,
            case_slug=slug,
        )
        entities_json = json.dumps(entities)
        risk_score = int(entities.get("risk_score", 3) or 3)

        async with LegacySession() as session:
            await session.execute(
                text("""
                    UPDATE legal.cases
                    SET extraction_status = 'complete',
                        extracted_entities = CAST(:entities AS jsonb),
                        risk_score = :risk_score,
                        updated_at = now()
                    WHERE id = :cid
                """),
                {
                    "entities": entities_json,
                    "risk_score": max(1, min(5, risk_score)),
                    "cid": case_id,
                },
            )

            if target == "correspondence" and correspondence_id:
                await session.execute(
                    text("""
                        UPDATE legal.correspondence
                        SET extracted_entities = CAST(:entities AS jsonb)
                        WHERE id = :corr_id AND case_id = :cid
                    """),
                    {
                        "entities": entities_json,
                        "corr_id": correspondence_id,
                        "cid": case_id,
                    },
                )

            await session.commit()

        logger.info(
            "legal_extraction_complete",
            slug=slug,
            target=target,
            correspondence_id=correspondence_id,
            model_used=model_used,
        )
    except Exception as exc:
        logger.error(
            "legal_extraction_failed",
            slug=slug,
            target=target,
            correspondence_id=correspondence_id,
            error=str(exc)[:280],
        )
        async with LegacySession() as session:
            await session.execute(
                text("""
                    UPDATE legal.cases
                    SET extraction_status = 'failed', updated_at = now()
                    WHERE id = :cid
                """),
                {"cid": case_id},
            )
            await session.commit()


@router.post("/cases/{slug}/extract", summary="Queue entity extraction")
async def trigger_extraction(slug: str, body: ExtractionRequest, background_tasks: BackgroundTasks):
    async with LegacySession() as session:
        case_r = await session.execute(
            text("SELECT id, notes FROM legal.cases WHERE case_slug = :slug"),
            {"slug": slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        source_candidates: list[str] = []
        if body.text and body.text.strip():
            source_candidates.append(body.text.strip())
        if case_row.notes and str(case_row.notes).strip():
            source_candidates.append(str(case_row.notes).strip())

        # Deterministic fallback so extraction can still run when notes are empty.
        case_context = f"Case Slug: {slug}".strip()
        if case_context:
            source_candidates.append(case_context)

        corr_id = body.correspondence_id

        if body.target == "correspondence":
            if not corr_id:
                raise HTTPException(status_code=422, detail="correspondence_id is required when target=correspondence")
            corr_r = await session.execute(
                text("""
                    SELECT id, body
                    FROM legal.correspondence
                    WHERE id = :corr_id AND case_id = :cid
                """),
                {"corr_id": corr_id, "cid": case_row.id},
            )
            corr_row = corr_r.fetchone()
            if not corr_row:
                raise HTTPException(status_code=404, detail=f"Correspondence {corr_id} not found for case '{slug}'")
            if corr_row.body and str(corr_row.body).strip():
                source_candidates.insert(0, str(corr_row.body).strip())
        else:
            # Case-level extraction fallback chain:
            # latest correspondence body -> latest evidence summary.
            try:
                latest_corr_r = await session.execute(
                    text(
                        """
                        SELECT body, subject
                        FROM legal.correspondence
                        WHERE case_id = :cid
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"cid": case_row.id},
                )
                latest_corr = latest_corr_r.fetchone()
                if latest_corr:
                    corr_text = (latest_corr.body or "").strip()
                    if corr_text:
                        source_candidates.insert(0, corr_text)
                    elif latest_corr.subject and str(latest_corr.subject).strip():
                        source_candidates.insert(0, str(latest_corr.subject).strip())
            except Exception:
                pass

            try:
                latest_evidence_r = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM legal.case_evidence
                        WHERE case_id = :cid
                        ORDER BY discovered_at DESC
                        LIMIT 1
                        """
                    ),
                    {"cid": case_row.id},
                )
                latest_evidence = latest_evidence_r.fetchone()
                if latest_evidence:
                    evidence_row = _row_to_dict(latest_evidence)
                    evidence_parts = []
                    summary = evidence_row.get("summary") or evidence_row.get("description") or evidence_row.get("notes")
                    if summary and str(summary).strip():
                        evidence_parts.append(str(summary).strip())
                    content_hash = evidence_row.get("content_hash")
                    if content_hash and str(content_hash).strip():
                        evidence_parts.append(f"Evidence Hash: {str(content_hash).strip()}")
                    if evidence_parts:
                        source_candidates.append("\n".join(evidence_parts))
            except Exception:
                pass

        source_text = "\n\n".join([s for s in source_candidates if s and s.strip()]).strip()

        if not source_text.strip():
            raise HTTPException(status_code=422, detail="No extraction source text found")

        await session.execute(
            text("""
                UPDATE legal.cases
                SET extraction_status = 'queued', updated_at = now()
                WHERE id = :cid
            """),
            {"cid": case_row.id},
        )
        await session.commit()

    background_tasks.add_task(
        _run_extraction_job,
        slug=slug,
        case_id=case_row.id,
        target=body.target,
        source_text=source_text,
        correspondence_id=corr_id,
    )

    logger.info("legal_extraction_queued", slug=slug, target=body.target, correspondence_id=corr_id)
    return {
        "queued": True,
        "status": "queued",
        "message": "Extraction job accepted",
        "extraction": "queued",
        "target": body.target,
        "id": case_row.id,
    }


@router.get("/crm/overview", summary="Legal CRM overview")
async def crm_overview():
    async with LegacySession() as session:
        cases_r = await session.execute(text("""
            SELECT id, case_slug, case_number, case_name, court, case_type, our_role,
                   status, critical_date, extraction_status, risk_score,
                   COALESCE(updated_at, created_at) AS updated_at
            FROM legal.cases
            ORDER BY critical_date ASC NULLS LAST, id
        """))
        cases = [_row_to_dict(r) for r in cases_r.fetchall()]

        deadlines_r = await session.execute(text("""
            SELECT d.*, c.case_slug
            FROM legal.deadlines d
            JOIN legal.cases c ON c.id = d.case_id
            ORDER BY d.due_date ASC
        """))
        deadlines = [_compute_deadline_fields(_row_to_dict(r)) for r in deadlines_r.fetchall()]

        correspondence_r = await session.execute(text("""
            SELECT corr.id, corr.case_id, c.case_slug, corr.direction, corr.comm_type,
                   corr.status, corr.subject, corr.recipient, corr.created_at, corr.sent_at
            FROM legal.correspondence corr
            JOIN legal.cases c ON c.id = corr.case_id
            ORDER BY corr.created_at DESC
            LIMIT 100
        """))
        correspondence = [_row_to_dict(r) for r in correspondence_r.fetchall()]

        actions_r = await session.execute(text("""
            SELECT a.id, a.case_id, c.case_slug, a.action_type, a.description,
                   a.status, a.action_date
            FROM legal.case_actions a
            JOIN legal.cases c ON c.id = a.case_id
            ORDER BY a.action_date DESC
            LIMIT 200
        """))
        actions = [_row_to_dict(r) for r in actions_r.fetchall()]

    today = date.today()
    due_within_7 = 0
    overdue = 0
    for d in deadlines:
        effective = d.get("effective_date") or d.get("due_date")
        try:
            dt = date.fromisoformat(str(effective)[:10]) if effective else None
        except ValueError:
            dt = None
        if not dt:
            continue
        days = (dt - today).days
        if days < 0:
            overdue += 1
        if days <= 7:
            due_within_7 += 1

    status_counts: dict[str, int] = {}
    for c in cases:
        st = c.get("status") or "unknown"
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "summary": {
            "total_cases": len(cases),
            "overdue_cases": overdue,
            "due_within_7_days": due_within_7,
            "status_counts": status_counts,
        },
        "cases": cases,
        "deadlines": deadlines,
        "correspondence": correspondence,
        "actions": actions,
    }


@router.get("/health", summary="Legal subsystem health")
async def legal_health():
    async with LegacySession() as session:
        counts = {}
        for table in ("legal.cases", "legal.deadlines", "legal.correspondence", "legal.case_actions"):
            result = await session.execute(text(f"SELECT COUNT(*) AS c FROM {table}"))
            counts[table] = int(result.scalar() or 0)

    return {
        "status": "ok",
        "service": "legal_api",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "counts": counts,
    }


HYDRA_SYNTH_URL = (os.getenv("DGX_REASONER_URL") or "http://192.168.0.100/v1").rstrip("/")
HYDRA_SYNTH_MODEL = os.getenv("DGX_REASONER_MODEL", "deepseek-r1:70b")
HYDRA_SYNTH_TIMEOUT = httpx.Timeout(connect=10.0, read=40.0, write=10.0, pool=10.0)
FAST_SYNTH_URL = (os.getenv("DGX_FAST_URL") or os.getenv("DGX_REASONER_URL") or "http://192.168.0.100/v1").rstrip("/")
FAST_SYNTH_MODEL = "qwen2.5:7b"
FAST_SYNTH_TIMEOUT = httpx.Timeout(connect=8.0, read=25.0, write=8.0, pool=8.0)

LEGAL_SYNTHESIS_PROMPT = (
    "You are Fortress Legal Synthesis. Return concise JSON with keys: "
    "executive_summary (string), immediate_actions (array of strings), "
    "risk_assessment (string), deadlines (array of {description,due_date})."
)




class SynthesizeRequest(BaseModel):
    prompt: str = Field(default="Generate strategic case synthesis")


@router.post("/cases/{slug}/synthesize", summary="Generate AI synthesis for a legal case")
async def synthesize_case(slug: str, body: SynthesizeRequest):
    async with LegacySession() as session:
        case_r = await session.execute(text("SELECT * FROM legal.cases WHERE case_slug = :slug"), {"slug": slug})
        case_row = case_r.fetchone()
        if not case_row:
            raise HTTPException(status_code=404, detail=f"Case '{slug}' not found")

        corr_r = await session.execute(
            text("""
                SELECT id, subject, body, direction, status, created_at
                FROM legal.correspondence
                WHERE case_id = :cid
                ORDER BY created_at DESC
                LIMIT 20
            """),
            {"cid": case_row.id},
        )
        correspondence = [_row_to_dict(r) for r in corr_r.fetchall()]

        dl_r = await session.execute(
            text("""
                SELECT id, description, due_date, extended_to, status, review_status
                FROM legal.deadlines
                WHERE case_id = :cid
                ORDER BY due_date ASC
                LIMIT 20
            """),
            {"cid": case_row.id},
        )
        deadlines = [_compute_deadline_fields(_row_to_dict(r)) for r in dl_r.fetchall()]

        act_r = await session.execute(
            text("""
                SELECT id, action_type, description, status, action_date
                FROM legal.case_actions
                WHERE case_id = :cid
                ORDER BY action_date DESC
                LIMIT 30
            """),
            {"cid": case_row.id},
        )
        actions = [_row_to_dict(r) for r in act_r.fetchall()]

    raw_case = _row_to_dict(case_row)
    case_payload = {
        "case_slug": raw_case.get("case_slug"),
        "case_number": raw_case.get("case_number"),
        "case_name": raw_case.get("case_name"),
        "court": raw_case.get("court"),
        "status": raw_case.get("status"),
        "our_role": raw_case.get("our_role"),
        "risk_score": raw_case.get("risk_score"),
        "critical_date": raw_case.get("critical_date"),
        "critical_note": raw_case.get("critical_note"),
    }

    compact_deadlines = [
        {
            "description": d.get("description"),
            "due_date": d.get("effective_date") or d.get("due_date"),
            "urgency": d.get("urgency"),
            "status": d.get("status"),
        }
        for d in deadlines[:10]
    ]

    compact_correspondence = [
        {
            "id": c.get("id"),
            "direction": c.get("direction"),
            "status": c.get("status"),
            "subject": c.get("subject"),
            "created_at": c.get("created_at"),
            "body_preview": (c.get("body") or "")[:280],
        }
        for c in correspondence[:10]
    ]

    compact_actions = [
        {
            "id": a.get("id"),
            "action_type": a.get("action_type"),
            "status": a.get("status"),
            "action_date": a.get("action_date"),
            "description": (a.get("description") or "")[:220],
        }
        for a in actions[:12]
    ]

    synth_input = {
        "case": case_payload,
        "deadlines": compact_deadlines,
        "correspondence": compact_correspondence,
        "actions": compact_actions,
        "operator_prompt": body.prompt,
    }

    messages = [
        {"role": "system", "content": LEGAL_SYNTHESIS_PROMPT},
        {"role": "user", "content": json.dumps(synth_input, ensure_ascii=False)},
    ]

    async def _call_model(
        base_url: str,
        model: str,
        timeout: httpx.Timeout,
        attempts: int = 1,
        base_backoff_s: float = 1.0,
    ) -> tuple[bool, str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
        }

        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(f"{base_url}/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                logger.warning(
                    "legal_synthesize_upstream_error",
                    slug=slug,
                    model=model,
                    attempt=attempt,
                    attempts=attempts,
                    error=str(exc)[:240],
                )
                r = None

            if r is not None and r.status_code == 200:
                try:
                    data = r.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return True, content
                except Exception:
                    pass

            if r is not None and r.status_code != 200:
                logger.warning(
                    "legal_synthesize_non200",
                    slug=slug,
                    model=model,
                    attempt=attempt,
                    attempts=attempts,
                    status=r.status_code,
                    body=r.text[:260],
                )

            if attempt < attempts:
                backoff = base_backoff_s * (2 ** (attempt - 1)) + random.uniform(0.0, 0.4)
                await asyncio.sleep(backoff)

        return False, ""

    ok, content = await _call_model(HYDRA_SYNTH_URL, HYDRA_SYNTH_MODEL, HYDRA_SYNTH_TIMEOUT)
    model_used = HYDRA_SYNTH_MODEL
    if not ok:
        ok, content = await _call_model(FAST_SYNTH_URL, FAST_SYNTH_MODEL, FAST_SYNTH_TIMEOUT, attempts=3, base_backoff_s=1.0)
        model_used = FAST_SYNTH_MODEL

    if not ok:
        raise HTTPException(status_code=502, detail="Synthesis failed on DGX models (deepseek + qwen)")

    return {
        "case_slug": slug,
        "model": model_used,
        "input": synth_input,
        "output": content,
    }


# ─── Sanctions Alerts (Phase 2B) ─────────────────────────────────────────

@router.get("/cases/{slug}/sanctions/drafts", summary="List draft sanctions alerts")
async def get_sanctions_drafts(slug: str):
    """Return all draft Rule 11 / Spoliation alerts for a case."""
    from sqlalchemy import text as sa_text
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            sa_text("""
                SELECT id, case_slug, alert_type, filing_ref,
                       contradiction_summary, draft_content_ref, status, created_at
                FROM legal.sanctions_alerts
                WHERE case_slug = :slug
                ORDER BY created_at DESC
            """),
            {"slug": slug},
        )
        alerts = []
        for row in r.fetchall():
            d = dict(row._mapping)
            d["id"] = str(d["id"])
            if d.get("created_at"):
                d["created_at"] = str(d["created_at"])
            alerts.append(d)
    return {"case_slug": slug, "alerts": alerts, "total": len(alerts)}


# ─── Harvey Engine: Master Chronology ─────────────────────────────────

@router.post("/cases/{slug}/chronology/build", summary="Build master chronology from evidence")
async def build_case_chronology(slug: str, background_tasks: BackgroundTasks):
    """Trigger chronology extraction (runs against local DGX)."""
    from backend.services.legal_chronology import build_chronology

    async def _bg():
        async with AsyncSessionLocal() as db:
            await build_chronology(db, slug)

    background_tasks.add_task(asyncio.coroutine(_bg) if False else _bg)
    return {"status": "queued", "case_slug": slug}


@router.post("/cases/{slug}/deliberate", summary="Convene the Counsel of 9")
async def deliberate_case(slug: str):
    """Run the Counsel of 9 deliberation against the case graph + chronology."""
    from backend.services.legal_council import run_council_deliberation
    from backend.services.legal_case_graph import get_case_graph_snapshot
    from backend.services.legal_chronology import get_chronology
    import json as _json

    async with AsyncSessionLocal() as db:
        snapshot = await get_case_graph_snapshot(db, case_slug=slug)
        timeline = await get_chronology(db, slug)

    nodes = snapshot.get("nodes", [])
    edges = snapshot.get("edges", [])
    node_lines = []
    for n in nodes:
        label = n.label if hasattr(n, "label") else n.get("label", "?")
        etype = n.entity_type if hasattr(n, "entity_type") else n.get("entity_type", "?")
        node_lines.append(f"[{etype}] {label}")
    edge_lines = []
    label_by_id = {}
    for n in nodes:
        nid = str(n.id if hasattr(n, "id") else n.get("id", "?"))
        label = n.label if hasattr(n, "label") else n.get("label", "?")
        label_by_id[nid] = label
    for e in edges:
        src = label_by_id.get(str(e.source_node_id if hasattr(e, "source_node_id") else e.get("source_node_id", "?")), "?")
        tgt = label_by_id.get(str(e.target_node_id if hasattr(e, "target_node_id") else e.get("target_node_id", "?")), "?")
        rel = e.relationship_type if hasattr(e, "relationship_type") else e.get("relationship_type", "?")
        edge_lines.append(f"{src} --({rel})--> {tgt}")

    chrono_lines = []
    for ev in timeline:
        chrono_lines.append(f"{ev.get('event_date','?')}: {ev.get('event_description','')}")

    case_brief = (
        f"Case: {slug}\n\n"
        f"ENTITIES:\n" + "\n".join(node_lines) + "\n\n"
        f"RELATIONSHIPS:\n" + "\n".join(edge_lines) + "\n\n"
        f"CHRONOLOGY:\n" + "\n".join(chrono_lines)
    )

    import uuid as _uuid
    result = await run_council_deliberation(
        session_id=str(_uuid.uuid4()),
        case_brief=case_brief,
        context=f"Graph: {len(nodes)} entities, {len(edges)} edges. Timeline: {len(timeline)} events.",
        case_slug=slug,
        trigger_type="GLASS_DELIBERATE",
    )

    return result


@router.get("/cases/{slug}/chronology", summary="Get master chronology timeline")
async def get_case_chronology(slug: str):
    """Return the chronological timeline for a case."""
    from backend.services.legal_chronology import get_chronology
    async with AsyncSessionLocal() as db:
        events = await get_chronology(db, slug)
    return {"case_slug": slug, "events": events, "total": len(events)}


# ─── Jurisprudence Engine (Level 15) ──────────────────────────────

class PrecedentSearchRequest(BaseModel):
    keywords: list = Field(..., min_length=1)

class AttorneyReconRequest(BaseModel):
    query: str = Field(..., min_length=2)


@router.post("/cases/{slug}/jurisprudence/precedent", summary="Search Georgia precedent")
async def search_precedent(slug: str, body: PrecedentSearchRequest):
    from backend.services.legal_jurisprudence import search_georgia_precedent
    async with AsyncSessionLocal() as db:
        result = await search_georgia_precedent(body.keywords, db=db)
    return result.model_dump()


@router.post("/cases/{slug}/jurisprudence/attorney-recon", summary="Profile attorney")
async def attorney_recon(slug: str, body: AttorneyReconRequest):
    from backend.services.legal_counsel_recon import profile_georgia_attorney
    async with AsyncSessionLocal() as db:
        result = await profile_georgia_attorney(body.query, db=db)
    return result.model_dump()
