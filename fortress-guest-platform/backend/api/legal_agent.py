"""
Legal Agent Mission API — triggers the ReAct orchestrator.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.database import AsyncSessionLocal
from backend.core.security import require_manager_or_admin
from backend.services.legal_agent_orchestrator import execute_legal_mission

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class MissionRequest(BaseModel):
    strategic_objective: str = Field(..., min_length=10, max_length=5000)


@router.post("/cases/{slug}/agent/mission", summary="Execute agentic legal mission")
async def start_mission(slug: str, body: MissionRequest):
    async with AsyncSessionLocal() as db:
        try:
            result = await execute_legal_mission(
                db=db,
                case_slug=slug,
                objective=body.strategic_objective,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result
