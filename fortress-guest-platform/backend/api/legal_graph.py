"""
Legal Case Graph API (Phase 2 Hybrid MVP).
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.core.database import AsyncSessionLocal
from backend.core.security import require_manager_or_admin
from backend.services.legal_case_graph import LegalCaseGraphBuilder

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


@router.post("/cases/{case_slug}/graph/refresh", summary="Build legal case graph baseline")
async def refresh_case_graph(case_slug: str):
    async with AsyncSessionLocal() as session:
        try:
            result = await LegalCaseGraphBuilder.build_baseline_graph(case_slug=case_slug, db=session)
            return result
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=500, detail=f"Graph refresh failed: {str(exc)[:240]}") from exc


@router.get("/cases/{case_slug}/graph/snapshot", summary="Get legal case graph snapshot")
async def get_graph_snapshot(case_slug: str):
    async with AsyncSessionLocal() as session:
        try:
            snapshot = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=session)
            if not snapshot or not snapshot.get("nodes"):
                await LegalCaseGraphBuilder.build_baseline_graph(case_slug=case_slug, db=session)
                snapshot = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=session)
            if not snapshot or not snapshot.get("nodes"):
                raise HTTPException(status_code=404, detail="Case graph not found or empty.")
            return snapshot
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=500, detail=f"Graph snapshot failed: {str(exc)[:240]}") from exc

