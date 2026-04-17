"""
Work Orders API - Maintenance tracking
BETTER THAN: All competitors (AI-detected issues, auto-creation from messages)
"""
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

import structlog

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.core.websocket import emit_work_order_update
from backend.models import WorkOrder, Property

logger = structlog.get_logger(service="workorders_api")
router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])

# ── NAS photo storage ─────────────────────────────────────────────────────────

_WO_NAS_ROOT = Path(settings.nas_work_orders_root)
_WO_NAS_FALLBACK = Path("/home/admin/Fortress-Prime/data/work_orders")
# Both roots are valid for path-traversal validation on download
_WO_VALID_ROOTS = (str(_WO_NAS_ROOT), str(_WO_NAS_FALLBACK))


def _resolve_wo_nas_dir(work_order_id: str) -> Path:
    """Try NAS root first; fall back to local path if NAS is unavailable."""
    try:
        if _WO_NAS_ROOT.exists():
            target = _WO_NAS_ROOT / work_order_id
            target.mkdir(parents=True, exist_ok=True)
            return target
    except (PermissionError, OSError) as exc:
        logger.warning("wo_nas_unavailable", error=str(exc)[:120])
    target = _WO_NAS_FALLBACK / work_order_id
    target.mkdir(parents=True, exist_ok=True)
    return target


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    resolution_notes: Optional[str] = None


class WorkOrderResponse(BaseModel):
    id: UUID
    ticket_number: str
    property_id: UUID
    property_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    notes: Optional[str] = None
    category: str
    priority: str
    status: str
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None
    is_urgent: bool = False
    is_open: bool = True
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_wo(cls, wo: "WorkOrder", property_name: str = None) -> "WorkOrderResponse":
        return cls(
            id=wo.id,
            ticket_number=wo.ticket_number,
            property_id=wo.property_id,
            property_name=property_name,
            title=wo.title,
            description=wo.description,
            notes=wo.description,
            category=wo.category,
            priority=wo.priority,
            status=wo.status,
            assigned_to=wo.assigned_to,
            resolution_notes=wo.resolution_notes,
            is_urgent=wo.priority in ("urgent", "high"),
            is_open=wo.status not in ("completed", "cancelled"),
            created_at=wo.created_at,
            resolved_at=wo.resolved_at,
        )


class WorkOrderCreate(BaseModel):
    property_id: UUID
    title: str
    description: str
    category: str = "other"
    priority: str = "medium"
    reservation_id: Optional[UUID] = None
    guest_id: Optional[UUID] = None


@router.post("/", response_model=WorkOrderResponse, status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new work order with an auto-generated ticket number."""
    today = datetime.utcnow().strftime("%Y%m%d")
    count_result = await db.execute(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.ticket_number.like(f"WO-{today}-%")
        )
    )
    seq = (count_result.scalar() or 0) + 1
    ticket_number = f"WO-{today}-{seq:04d}"

    wo = WorkOrder(
        ticket_number=ticket_number,
        property_id=body.property_id,
        title=body.title,
        description=body.description,
        category=body.category,
        priority=body.priority,
        reservation_id=body.reservation_id,
        guest_id=body.guest_id,
    )
    db.add(wo)
    await db.flush()
    await db.refresh(wo)
    prop = await db.get(Property, wo.property_id) if wo.property_id else None
    prop_name = prop.name if prop else None

    try:
        await emit_work_order_update({
            "id": str(wo.id),
            "ticket_number": wo.ticket_number,
            "title": wo.title,
            "status": wo.status,
            "priority": wo.priority,
            "property_name": prop_name,
            "action": "created",
        })
    except Exception:
        pass

    return WorkOrderResponse.from_wo(wo, prop_name)


@router.get("/", response_model=List[WorkOrderResponse])
async def list_work_orders(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    property_id: Optional[UUID] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List work orders with property names"""
    query = (
        select(WorkOrder, Property.name)
        .outerjoin(Property, WorkOrder.property_id == Property.id)
    )
    
    if status:
        query = query.where(WorkOrder.status == status)
    if priority:
        query = query.where(WorkOrder.priority == priority)
    if property_id:
        query = query.where(WorkOrder.property_id == property_id)
    
    query = query.limit(limit).order_by(WorkOrder.created_at.desc())
    
    result = await db.execute(query)
    
    return [WorkOrderResponse.from_wo(wo, prop_name) for wo, prop_name in result.all()]


@router.get("/{work_order_id}", response_model=WorkOrderResponse)
async def get_work_order(
    work_order_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get work order by ID with property name"""
    result = await db.execute(
        select(WorkOrder, Property.name)
        .outerjoin(Property, WorkOrder.property_id == Property.id)
        .where(WorkOrder.id == work_order_id)
    )
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    wo, prop_name = row
    return WorkOrderResponse.from_wo(wo, prop_name)


@router.patch("/{work_order_id}", response_model=WorkOrderResponse)
async def update_work_order(
    work_order_id: UUID,
    body: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a work order's status, assignment, or resolution."""
    wo = await db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    if body.status is not None:
        wo.status = body.status
        if body.status == "completed":
            wo.resolved_at = datetime.utcnow()
        if body.status == "in_progress" and wo.assigned_at is None:
            wo.assigned_at = datetime.utcnow()
    if body.assigned_to is not None:
        wo.assigned_to = body.assigned_to
        wo.assigned_at = datetime.utcnow()
    if body.priority is not None:
        wo.priority = body.priority
    if body.resolution_notes is not None:
        wo.resolution_notes = body.resolution_notes

    wo.updated_at = datetime.utcnow()
    prop = await db.get(Property, wo.property_id) if wo.property_id else None
    prop_name = prop.name if prop else None

    try:
        await emit_work_order_update({
            "id": str(wo.id),
            "ticket_number": wo.ticket_number,
            "title": wo.title,
            "status": wo.status,
            "priority": wo.priority,
            "property_name": prop_name,
            "action": "updated",
        })
    except Exception:
        pass

    return WorkOrderResponse.from_wo(wo, prop_name)


# ── Vendor assignment ─────────────────────────────────────────────────────────

class AssignVendorRequest(BaseModel):
    vendor_id: str
    vendor_name: str = ""


@router.post("/{work_order_id}/assign-vendor")
async def assign_vendor_to_work_order(
    work_order_id: UUID,
    body: AssignVendorRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set assigned_vendor_id FK; sync legacy assigned_to for backwards compat."""
    wo = await db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, f"Work order {work_order_id} not found")
    try:
        vid = _uuid.UUID(body.vendor_id)
    except ValueError:
        raise HTTPException(422, "Invalid vendor_id UUID")
    from backend.models.vendor import Vendor
    vendor = await db.get(Vendor, vid)
    if not vendor:
        raise HTTPException(404, f"Vendor {body.vendor_id} not found")
    wo.assigned_vendor_id = vid  # type: ignore[assignment]
    wo.assigned_to = body.vendor_name or vendor.name  # type: ignore[assignment]
    wo.assigned_at = datetime.utcnow()  # type: ignore[assignment]
    if wo.status == "open":
        wo.status = "in_progress"  # type: ignore[assignment]
    wo.updated_at = datetime.utcnow()  # type: ignore[assignment]
    await db.commit()
    logger.info("vendor_assigned_to_work_order", work_order_id=str(work_order_id), vendor_id=str(vid))
    return {"work_order_id": str(work_order_id), "vendor_id": str(vid), "vendor_name": vendor.name, "status": wo.status}


# ── Photo upload / download ───────────────────────────────────────────────────

_ALLOWED_PHOTO_TYPES = frozenset(["image/jpeg", "image/png", "image/webp", "image/heic"])
_MAX_PHOTO_BYTES = 20 * 1024 * 1024  # 20 MB

_PHOTO_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic",
}


@router.post("/{work_order_id}/photos")
async def upload_work_order_photo(
    work_order_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a photo for a work order and write it to the NAS (with local fallback).
    Path: /mnt/fortress_nas/work_orders/{work_order_id}/{uuid8}_{filename}
    Stores the absolute NAS path in work_orders.photo_urls.
    """
    wo = await db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, f"Work order {work_order_id} not found")

    content_type = file.content_type or "image/jpeg"
    if content_type not in _ALLOWED_PHOTO_TYPES:
        raise HTTPException(415, f"Unsupported type {content_type}. Allowed: {sorted(_ALLOWED_PHOTO_TYPES)}")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_PHOTO_BYTES:
        raise HTTPException(413, f"File too large. Max {_MAX_PHOTO_BYTES // 1024 // 1024} MB.")
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    # Build a safe filename: {8-hex-chars}_{original name, slashes stripped}
    orig_name = (file.filename or "photo.jpg").replace("/", "_").replace("\\", "_")
    stored_name = f"{_uuid.uuid4().hex[:8]}_{orig_name}"

    try:
        nas_dir = _resolve_wo_nas_dir(str(work_order_id))
        nfs_path = nas_dir / stored_name
        with open(nfs_path, "wb") as fh:
            fh.write(file_bytes)
    except OSError as exc:
        logger.error("work_order_photo_write_failed", error=str(exc)[:200])
        raise HTTPException(502, "Photo write to storage failed")

    current_urls = list(wo.photo_urls or [])
    current_urls.append(str(nfs_path))
    wo.photo_urls = current_urls  # type: ignore[assignment]
    wo.updated_at = datetime.utcnow()  # type: ignore[assignment]
    await db.commit()

    download_url = f"/api/workorders/{work_order_id}/photos/{stored_name}"
    logger.info(
        "work_order_photo_uploaded",
        work_order_id=str(work_order_id),
        nfs_path=str(nfs_path),
        total_photos=len(current_urls),
    )
    return {
        "work_order_id": str(work_order_id),
        "photo_url": download_url,
        "nfs_path": str(nfs_path),
        "total_photos": len(current_urls),
    }


@router.get("/{work_order_id}/photos/{filename}")
async def download_work_order_photo(
    work_order_id: UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Serve a previously uploaded work order photo from NAS/local storage.
    Validates path is within the configured storage roots before serving.
    """
    # Reject traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    wo = await db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, f"Work order {work_order_id} not found")

    # Find the stored path that ends with this filename
    nfs_path: Path | None = None
    for stored in (wo.photo_urls or []):
        if Path(stored).name == filename:
            nfs_path = Path(stored)
            break

    if nfs_path is None:
        raise HTTPException(404, f"Photo '{filename}' not found for work order {work_order_id}")

    resolved = nfs_path.resolve()
    if not any(str(resolved).startswith(root) for root in _WO_VALID_ROOTS):
        raise HTTPException(403, "Access denied")

    if not resolved.exists():
        raise HTTPException(404, "Photo file not found on storage")

    ext = resolved.suffix.lower()
    media_type = _PHOTO_MIME_MAP.get(ext, "application/octet-stream")
    return FileResponse(path=str(resolved), media_type=media_type, filename=filename)
