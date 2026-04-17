"""
Acquisition Pipeline API — Kanban + Due Diligence + Document Vault.

Endpoints:
  GET  /pipeline/kanban                              — all stages + cards (kanban data)
  GET  /pipeline/stats                               — funnel counts per stage
  POST /pipeline                                     — create new pipeline entry for a property
  PATCH /pipeline/{pipeline_id}/stage                — advance / set stage
  GET  /pipeline/{pipeline_id}/due-diligence         — checklist items
  PATCH /pipeline/{pipeline_id}/due-diligence/{key}  — update a checklist item
  POST /pipeline/{pipeline_id}/due-diligence/seed    — seed default checklist items
  POST /pipeline/{pipeline_id}/documents             — upload document to NAS vault
  GET  /pipeline/{pipeline_id}/documents             — list documents
  GET  /pipeline/{pipeline_id}/documents/{doc_id}    — download document
"""
from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.acquisition import (
    ACQUISITION_SCHEMA,
    AcquisitionDocument,
    AcquisitionDueDiligence,
    AcquisitionParcel,
    AcquisitionPipeline,
    AcquisitionProperty,
    FunnelStage,
)

# ── NAS document storage ──────────────────────────────────────────────────────

_ACQ_NAS_ROOT = Path(settings.nas_acquisitions_root)
_ACQ_NAS_FALLBACK = Path("/home/admin/Fortress-Prime/data/acquisitions")
_ACQ_VALID_ROOTS = (str(_ACQ_NAS_ROOT), str(_ACQ_NAS_FALLBACK))


def _resolve_acq_nas_dir(pipeline_id: str) -> Path:
    """Try NAS root first; fall back to local path if NAS is unavailable."""
    try:
        if _ACQ_NAS_ROOT.exists():
            target = _ACQ_NAS_ROOT / pipeline_id
            target.mkdir(parents=True, exist_ok=True)
            return target
    except (PermissionError, OSError) as exc:
        logger.warning("acq_nas_unavailable", error=str(exc)[:120])
    target = _ACQ_NAS_FALLBACK / pipeline_id
    target.mkdir(parents=True, exist_ok=True)
    return target

logger = structlog.get_logger(service="acquisition_pipeline_api")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Default checklist definition (same as migration seed)
# ---------------------------------------------------------------------------
DEFAULT_CHECKLIST: list[tuple[str, str, int]] = [
    ("title_search",                  "Title Search & Lien Check",                1),
    ("property_inspection",           "Physical Property Inspection",              2),
    ("revenue_history",               "Revenue History Review (2+ Years)",         3),
    ("hoa_review",                    "HOA Documents Review",                      4),
    ("tax_records",                   "Tax Records & Assessment Verification",     5),
    ("zoning",                        "Zoning & Land-Use Compliance",              6),
    ("competitor_rates",              "Competitive Rate & Occupancy Analysis",     7),
    ("owner_motivation",              "Owner Motivation Interview",                8),
    ("str_license_verification",      "STR License Verification (Fannin/Gilmer)", 9),
    ("hoa_str_policy_review",         "HOA STR Policy Review",                    10),
    ("comparable_revenue_streamline", "Comparable Revenue from Streamline",       11),
]

STAGE_ORDER = [
    FunnelStage.RADAR,
    FunnelStage.TARGET_LOCKED,
    FunnelStage.DEPLOYED,
    FunnelStage.ENGAGED,
    FunnelStage.ACQUIRED,
    FunnelStage.REJECTED,
]


# ── Serializers ───────────────────────────────────────────────────────────────

def _pipeline_card(pipeline: AcquisitionPipeline, prop: AcquisitionProperty | None) -> dict[str, Any]:
    parcel_id = str(prop.parcel_id) if prop and prop.parcel_id else None
    return {
        "pipeline_id": str(pipeline.id),
        "property_id": str(pipeline.property_id),
        "stage": pipeline.stage.value if isinstance(pipeline.stage, FunnelStage) else str(pipeline.stage),
        "llm_viability_score": float(pipeline.llm_viability_score) if pipeline.llm_viability_score else None,
        "next_action_date": pipeline.next_action_date.isoformat() if pipeline.next_action_date else None,
        "rejection_reason": pipeline.rejection_reason,
        "updated_at": pipeline.updated_at.isoformat() if pipeline.updated_at else None,
        # property fields
        "bedrooms": prop.bedrooms if prop else None,
        "bathrooms": float(prop.bathrooms) if prop and prop.bathrooms else None,
        "projected_adr": float(prop.projected_adr) if prop and prop.projected_adr else None,
        "projected_annual_revenue": float(prop.projected_annual_revenue) if prop and prop.projected_annual_revenue else None,
        "management_company": prop.management_company if prop else None,
        "status": prop.status.value if prop and prop.status else None,
        "parcel_id": parcel_id,
        "airbnb_listing_id": prop.airbnb_listing_id if prop else None,
        "vrbo_listing_id": prop.vrbo_listing_id if prop else None,
    }


def _dd_item(item: AcquisitionDueDiligence) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "pipeline_id": str(item.pipeline_id),
        "item_key": item.item_key,
        "label": item.label,
        "display_order": item.display_order,
        "status": item.status,
        "notes": item.notes,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "completed_by": item.completed_by,
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class PipelineCreate(BaseModel):
    property_id: str
    stage: str = FunnelStage.RADAR.value
    llm_viability_score: Optional[float] = Field(None, ge=0, le=1)
    next_action_date: Optional[str] = None
    notes: Optional[str] = None


class StageUpdate(BaseModel):
    stage: str
    rejection_reason: Optional[str] = None
    next_action_date: Optional[str] = None


class DueDiligenceUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|passed|failed|waived)$")
    notes: Optional[str] = None
    completed_by: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/pipeline/kanban")
async def get_pipeline_kanban(db: AsyncSession = Depends(get_db)):
    """
    Returns the full pipeline grouped by stage for kanban rendering.
    Each stage has a list of card objects.
    """
    result = await db.execute(
        select(AcquisitionPipeline, AcquisitionProperty)
        .outerjoin(
            AcquisitionProperty,
            AcquisitionPipeline.property_id == AcquisitionProperty.id,
        )
        .order_by(AcquisitionPipeline.updated_at.desc())
    )
    rows = result.all()

    kanban: dict[str, list[dict]] = {stage.value: [] for stage in STAGE_ORDER}
    for pipeline, prop in rows:
        stage_val = pipeline.stage.value if isinstance(pipeline.stage, FunnelStage) else str(pipeline.stage)
        if stage_val in kanban:
            kanban[stage_val].append(_pipeline_card(pipeline, prop))

    return {
        "stages": [{"stage": s.value, "cards": kanban[s.value]} for s in STAGE_ORDER],
        "total": sum(len(v) for v in kanban.values()),
    }


@router.get("/pipeline/stats")
async def get_pipeline_stats(db: AsyncSession = Depends(get_db)):
    """Returns per-stage counts for dashboard metrics."""
    result = await db.execute(
        select(AcquisitionPipeline.stage, func.count(AcquisitionPipeline.id))
        .group_by(AcquisitionPipeline.stage)
    )
    counts = {str(row[0].value if isinstance(row[0], FunnelStage) else row[0]): row[1] for row in result.all()}
    total = sum(counts.values())
    return {
        "stages": {stage.value: counts.get(stage.value, 0) for stage in STAGE_ORDER},
        "total": total,
    }


@router.post("/pipeline", status_code=201)
async def create_pipeline_entry(
    body: PipelineCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new pipeline entry for a property and seed its due-diligence checklist."""
    try:
        prop_uuid = _uuid.UUID(body.property_id)
    except ValueError:
        raise HTTPException(422, "Invalid property_id UUID")

    # Validate stage
    try:
        stage = FunnelStage(body.stage)
    except ValueError:
        raise HTTPException(422, f"Invalid stage. Valid stages: {[s.value for s in STAGE_ORDER]}")

    # Check for duplicate
    existing = (
        await db.execute(
            select(AcquisitionPipeline).where(
                AcquisitionPipeline.property_id == prop_uuid
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Pipeline entry already exists for property {body.property_id}")

    pipeline = AcquisitionPipeline(
        property_id=prop_uuid,
        stage=stage,
        llm_viability_score=body.llm_viability_score,
    )
    db.add(pipeline)
    await db.flush()

    # Seed due-diligence checklist
    for item_key, label, order in DEFAULT_CHECKLIST:
        db.add(AcquisitionDueDiligence(
            pipeline_id=pipeline.id,
            item_key=item_key,
            label=label,
            display_order=order,
            status="pending",
        ))

    await db.commit()
    await db.refresh(pipeline)
    logger.info("pipeline_entry_created", pipeline_id=str(pipeline.id), property_id=str(prop_uuid), stage=stage.value)
    return {"pipeline_id": str(pipeline.id), "stage": stage.value, "checklist_seeded": len(DEFAULT_CHECKLIST)}


@router.patch("/pipeline/{pipeline_id}/stage")
async def update_pipeline_stage(
    pipeline_id: str,
    body: StageUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Advance or set the pipeline stage for a property."""
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    try:
        new_stage = FunnelStage(body.stage)
    except ValueError:
        raise HTTPException(422, f"Invalid stage. Valid: {[s.value for s in STAGE_ORDER]}")

    pipeline = await db.get(AcquisitionPipeline, pid)
    if not pipeline:
        raise HTTPException(404, f"Pipeline entry {pipeline_id} not found")

    old_stage = pipeline.stage
    pipeline.stage = new_stage  # type: ignore[assignment]
    pipeline.updated_at = datetime.now(_UTC)  # type: ignore[assignment]
    if body.rejection_reason is not None:
        pipeline.rejection_reason = body.rejection_reason  # type: ignore[assignment]
    if body.next_action_date is not None:
        from datetime import date
        try:
            pipeline.next_action_date = date.fromisoformat(body.next_action_date)  # type: ignore[assignment]
        except ValueError:
            raise HTTPException(422, "next_action_date must be ISO date string YYYY-MM-DD")

    await db.commit()
    logger.info(
        "pipeline_stage_updated",
        pipeline_id=pipeline_id,
        old_stage=str(old_stage),
        new_stage=new_stage.value,
    )
    return {"pipeline_id": pipeline_id, "old_stage": str(old_stage), "new_stage": new_stage.value}


@router.get("/pipeline/{pipeline_id}/due-diligence")
async def get_due_diligence(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    pipeline = await db.get(AcquisitionPipeline, pid)
    if not pipeline:
        raise HTTPException(404, f"Pipeline entry {pipeline_id} not found")

    result = await db.execute(
        select(AcquisitionDueDiligence)
        .where(AcquisitionDueDiligence.pipeline_id == pid)
        .order_by(AcquisitionDueDiligence.display_order)
    )
    items = result.scalars().all()
    return {
        "pipeline_id": pipeline_id,
        "items": [_dd_item(i) for i in items],
        "summary": {
            "total": len(items),
            "passed": sum(1 for i in items if i.status == "passed"),
            "failed": sum(1 for i in items if i.status == "failed"),
            "pending": sum(1 for i in items if i.status == "pending"),
            "waived": sum(1 for i in items if i.status == "waived"),
        },
    }


@router.patch("/pipeline/{pipeline_id}/due-diligence/{item_key}")
async def update_due_diligence_item(
    pipeline_id: str,
    item_key: str,
    body: DueDiligenceUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    result = await db.execute(
        select(AcquisitionDueDiligence).where(
            AcquisitionDueDiligence.pipeline_id == pid,
            AcquisitionDueDiligence.item_key == item_key,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, f"Due diligence item '{item_key}' not found for pipeline {pipeline_id}")

    item.status = body.status  # type: ignore[assignment]
    if body.notes is not None:
        item.notes = body.notes  # type: ignore[assignment]
    if body.completed_by is not None:
        item.completed_by = body.completed_by  # type: ignore[assignment]
    if body.status in ("passed", "failed"):
        item.completed_at = datetime.now(_UTC)  # type: ignore[assignment]
    item.updated_at = datetime.now(_UTC)  # type: ignore[assignment]

    await db.commit()
    logger.info("dd_item_updated", pipeline_id=pipeline_id, item_key=item_key, status=body.status)
    return _dd_item(item)


@router.post("/pipeline/{pipeline_id}/due-diligence/seed")
async def seed_due_diligence(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    """Seed missing default checklist items for a pipeline entry (idempotent)."""
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    pipeline = await db.get(AcquisitionPipeline, pid)
    if not pipeline:
        raise HTTPException(404, f"Pipeline entry {pipeline_id} not found")

    # Find which item_keys already exist
    existing_result = await db.execute(
        select(AcquisitionDueDiligence.item_key).where(
            AcquisitionDueDiligence.pipeline_id == pid
        )
    )
    existing_keys = {row[0] for row in existing_result.all()}

    added = 0
    for item_key, label, order in DEFAULT_CHECKLIST:
        if item_key not in existing_keys:
            db.add(AcquisitionDueDiligence(
                pipeline_id=pid,
                item_key=item_key,
                label=label,
                display_order=order,
                status="pending",
            ))
            added += 1

    await db.commit()
    return {"pipeline_id": pipeline_id, "added": added, "already_existed": len(existing_keys)}


# ── Document vault ────────────────────────────────────────────────────────────

_ACQ_ALLOWED_TYPES = frozenset([
    "application/pdf", "image/jpeg", "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # xlsx
    "text/csv", "text/plain",
])
_ACQ_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

_ACQ_MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
}

_ACQ_VALID_DOC_TYPES = frozenset([
    "general", "due_diligence", "contract", "inspection",
    "revenue_history", "hoa", "zoning", "title", "tax", "other",
])


@router.post("/pipeline/{pipeline_id}/documents", status_code=201)
async def upload_acquisition_document(
    pipeline_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form(default="general"),
    uploaded_by: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document to the acquisition pipeline vault.
    Writes to /mnt/fortress_nas/acquisitions/{pipeline_id}/ with local fallback.
    """
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    pipeline = await db.get(AcquisitionPipeline, pid)
    if not pipeline:
        raise HTTPException(404, f"Pipeline entry {pipeline_id} not found")

    if doc_type not in _ACQ_VALID_DOC_TYPES:
        raise HTTPException(422, f"Invalid doc_type. Valid: {sorted(_ACQ_VALID_DOC_TYPES)}")

    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ACQ_ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported type {content_type}. Allowed: {sorted(_ACQ_ALLOWED_TYPES)}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")
    if len(file_bytes) > _ACQ_MAX_BYTES:
        raise HTTPException(413, f"File too large. Max {_ACQ_MAX_BYTES // 1024 // 1024} MB.")

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    orig_name = (file.filename or "document").replace("/", "_").replace("\\", "_")
    stored_name = f"{_uuid.uuid4().hex[:8]}_{orig_name}"

    try:
        nas_dir = _resolve_acq_nas_dir(pipeline_id)
        nfs_path = nas_dir / stored_name
        with open(nfs_path, "wb") as fh:
            fh.write(file_bytes)
    except OSError as exc:
        logger.error("acq_doc_write_failed", error=str(exc)[:200])
        raise HTTPException(502, "Document write to storage failed")

    doc = AcquisitionDocument(
        pipeline_id=pid,
        file_name=orig_name,
        nfs_path=str(nfs_path),
        mime_type=content_type,
        file_hash=file_hash,
        file_size_bytes=len(file_bytes),
        doc_type=doc_type,
        uploaded_by=uploaded_by or None,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info(
        "acq_document_uploaded",
        pipeline_id=pipeline_id,
        document_id=str(doc.id),
        nfs_path=str(nfs_path),
    )
    return {
        "document_id": str(doc.id),
        "file_name": orig_name,
        "doc_type": doc_type,
        "nfs_path": str(nfs_path),
        "file_size_bytes": len(file_bytes),
        "download_url": f"/api/acquisition/pipeline/{pipeline_id}/documents/{doc.id}",
    }


@router.get("/pipeline/{pipeline_id}/documents")
async def list_acquisition_documents(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    """List all documents in a pipeline entry's vault."""
    try:
        pid = _uuid.UUID(pipeline_id)
    except ValueError:
        raise HTTPException(422, "Invalid pipeline_id UUID")

    pipeline = await db.get(AcquisitionPipeline, pid)
    if not pipeline:
        raise HTTPException(404, f"Pipeline entry {pipeline_id} not found")

    result = await db.execute(
        select(AcquisitionDocument)
        .where(AcquisitionDocument.pipeline_id == pid)
        .order_by(AcquisitionDocument.created_at)
    )
    docs = result.scalars().all()
    return {
        "pipeline_id": pipeline_id,
        "documents": [
            {
                "id": str(d.id),
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "mime_type": d.mime_type,
                "file_size_bytes": d.file_size_bytes,
                "uploaded_by": d.uploaded_by,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "download_url": f"/api/acquisition/pipeline/{pipeline_id}/documents/{d.id}",
            }
            for d in docs
        ],
        "total": len(docs),
    }


@router.get("/pipeline/{pipeline_id}/documents/{doc_id}")
async def download_acquisition_document(
    pipeline_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a document from the acquisition vault."""
    try:
        pid = _uuid.UUID(pipeline_id)
        did = _uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(422, "Invalid UUID")

    result = await db.execute(
        select(AcquisitionDocument).where(
            AcquisitionDocument.id == did,
            AcquisitionDocument.pipeline_id == pid,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found for pipeline {pipeline_id}")

    nfs_path = Path(doc.nfs_path)
    resolved = nfs_path.resolve()

    if not any(str(resolved).startswith(root) for root in _ACQ_VALID_ROOTS):
        raise HTTPException(403, "Access denied")

    if not resolved.exists():
        raise HTTPException(404, "Document file not found on storage")

    ext = resolved.suffix.lower()
    media_type = _ACQ_MIME_MAP.get(ext, doc.mime_type or "application/octet-stream")
    return FileResponse(path=str(resolved), media_type=media_type, filename=doc.file_name)
