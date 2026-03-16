"""
AI Agent API — Autonomous orchestration and intelligence endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.agentic_orchestrator import AgenticOrchestrator

router = APIRouter()
orchestrator = AgenticOrchestrator()


@router.get("/stats")
async def agent_stats(db: AsyncSession = Depends(get_db)):
    """Get AI agent performance statistics."""
    return await orchestrator.get_agent_stats(db)


@router.post("/run-daily")
async def run_daily_automation(db: AsyncSession = Depends(get_db)):
    """Manually trigger the daily automation run."""
    return await orchestrator.run_daily_automation(db)


@router.post("/run-lifecycle")
async def run_lifecycle(db: AsyncSession = Depends(get_db)):
    """Manually trigger the lifecycle engine (pre-arrival, checkout, etc)."""
    from backend.services.lifecycle_engine import LifecycleEngine
    engine = LifecycleEngine(db)
    results = await engine.process_all_lifecycle_events()
    return {"ok": True, "results": results}


@router.get("/templates")
async def list_templates():
    """List all available response templates."""
    try:
        templates = {}
        for name, tmpl in orchestrator.RESPONSE_TEMPLATES.items():
            templates[name] = tmpl[:80] + "..." if len(tmpl) > 80 else tmpl
        return {"templates": templates, "count": len(templates)}
    except Exception:
        return {"templates": {}, "count": 0}
