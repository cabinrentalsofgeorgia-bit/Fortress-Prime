"""
Sanctions Tripwire API endpoints.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from backend.core.database import AsyncSessionLocal
from backend.services.legal_sanctions_tripwire import LegalSanctionsTripwire

router = APIRouter()


@router.post("/cases/{case_slug}/sanctions/sweep", summary="Run sanctions tripwire sweep")
async def run_tripwire_sweep(case_slug: str):
    async with AsyncSessionLocal() as db:
        try:
            return await LegalSanctionsTripwire.run_sweep(case_slug=case_slug, db=db)
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Tripwire sweep failed: {str(exc)[:220]}") from exc


@router.get("/cases/{case_slug}/sanctions/alerts", summary="List sanctions alerts")
async def list_sanctions_alerts(case_slug: str):
    async with AsyncSessionLocal() as db:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, case_slug, alert_type, contradiction_summary, confidence_score, status, created_at
                        FROM legal.sanctions_alerts_v2
                        WHERE case_slug = :case_slug
                        ORDER BY confidence_score DESC NULLS LAST, created_at DESC
                        """
                    ),
                    {"case_slug": case_slug},
                )
            ).mappings().all()

            alerts = [
                {
                    "id": str(row["id"]),
                    "case_slug": row["case_slug"],
                    "alert_type": row["alert_type"],
                    "contradiction_summary": row["contradiction_summary"],
                    "confidence_score": row["confidence_score"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                for row in rows
            ]
            return {"case_slug": case_slug, "alerts": alerts, "total": len(alerts)}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to load sanctions alerts: {str(exc)[:220]}") from exc
