"""
Work Orders API - Maintenance tracking
BETTER THAN: All competitors (AI-detected issues, auto-creation from messages)
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.core.websocket import emit_work_order_update
from backend.models import WorkOrder, Property

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])


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
