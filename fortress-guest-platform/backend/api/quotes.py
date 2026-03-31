"""
Quotes API — CRUD for multi-property pricing quotes attached to leads.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models.staff import StaffUser
from backend.models.quote import Quote

logger = structlog.get_logger()
router = APIRouter()


@router.get("/")
async def list_quotes(
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_operator_manager_admin),
):
    result = await db.execute(
        select(Quote).order_by(Quote.created_at.desc()).limit(50)
    )
    quotes = result.scalars().all()
    return [
        {
            "id": str(q.id),
            "lead_id": str(q.lead_id),
            "status": q.status,
            "created_at": str(q.created_at),
        }
        for q in quotes
    ]
