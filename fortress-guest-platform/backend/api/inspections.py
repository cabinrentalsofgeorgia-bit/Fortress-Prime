"""
Inspections API — Bridge to CF-01 GuardianOps Vision Engine
Proxies inspection history from maintenance_log and surfaces it alongside
damage claims for a unified property-care workflow.
"""
import os
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

from backend.core.database import get_db

router = APIRouter()

CF01_BASE = os.getenv("CF01_GUARDIAN_URL", "http://localhost:8001/v1")


class InspectionHistoryItem(BaseModel):
    id: int
    run_id: str
    cabin_name: str
    room_type: str
    room_display: Optional[str] = None
    overall_score: float
    verdict: str
    ai_confidence_score: Optional[float] = None
    inspector_id: Optional[str] = None
    issues_found: Optional[str] = None
    generated_at: Optional[str] = None
    items_passed: Optional[int] = None
    items_failed: Optional[int] = None
    items_total: Optional[int] = None


@router.get("/history", response_model=List[InspectionHistoryItem])
async def inspection_history(
    limit: int = Query(default=50, ge=1, le=500),
    cabin: Optional[str] = None,
    verdict: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Fetch inspection history from maintenance_log (CF-01 audit trail)."""
    query = """
        SELECT id, run_id, cabin_name, room_type, room_display,
               overall_score, verdict, ai_confidence_score,
               inspector_id, issues_found,
               generated_at::text,
               items_passed, items_failed, items_total
        FROM maintenance_log
        WHERE 1=1
    """
    params = {}
    if cabin:
        query += " AND cabin_name = :cabin"
        params["cabin"] = cabin
    if verdict:
        query += " AND verdict = :verdict"
        params["verdict"] = verdict.upper()

    query += " ORDER BY generated_at DESC LIMIT :limit"
    params["limit"] = limit

    try:
        result = await db.execute(text(query), params)
        rows = result.mappings().all()
        return [InspectionHistoryItem(**dict(r)) for r in rows]
    except Exception:
        return []


@router.get("/failed-items")
async def failed_inspection_items(
    cabin: Optional[str] = None,
    since: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return recent failed inspection items that may warrant a damage claim."""
    query = """
        SELECT id, run_id, cabin_name, room_type, room_display,
               overall_score, verdict, issues_found, generated_at::text,
               items_failed
        FROM maintenance_log
        WHERE verdict = 'FAIL'
    """
    params = {}
    if cabin:
        query += " AND cabin_name = :cabin"
        params["cabin"] = cabin
    if since:
        query += " AND generated_at >= :since"
        params["since"] = since

    query += " ORDER BY generated_at DESC LIMIT 100"

    try:
        result = await db.execute(text(query), params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


@router.get("/summary")
async def inspection_summary(db: AsyncSession = Depends(get_db)):
    """Dashboard summary: recent pass/fail rates, total inspections, etc."""
    try:
        result = await db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE verdict = 'PASS') as passed,
                COUNT(*) FILTER (WHERE verdict = 'FAIL') as failed,
                ROUND(AVG(overall_score)::numeric, 1) as avg_score,
                COUNT(DISTINCT cabin_name) as cabins_inspected,
                MAX(generated_at)::text as last_inspection
            FROM maintenance_log
        """))
        row = result.mappings().first()
        return dict(row) if row else {
            "total": 0, "passed": 0, "failed": 0,
            "avg_score": 0, "cabins_inspected": 0, "last_inspection": None,
        }
    except Exception:
        return {
            "total": 0, "passed": 0, "failed": 0,
            "avg_score": 0, "cabins_inspected": 0, "last_inspection": None,
        }
