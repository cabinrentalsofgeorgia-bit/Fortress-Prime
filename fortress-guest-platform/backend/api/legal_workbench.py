"""Counsel Review Workbench API.

All routes are staff-authenticated through the legal API router dependency and
return derived work product only. Raw document bodies and locked content are
not read or returned here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.security import require_manager_or_admin
from backend.services.legal_counsel_workbench import load_latest_workbench

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


@router.get("/cases/{slug}/counsel-workbench", summary="Get counsel review workbench packet")
async def get_counsel_workbench(slug: str):
    packet = load_latest_workbench(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Counsel workbench packet not found.")
    return packet

