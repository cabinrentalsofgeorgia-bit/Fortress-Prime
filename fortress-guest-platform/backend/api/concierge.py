from fastapi import APIRouter

router = APIRouter(prefix="/api/concierge")


@router.get("/health")
async def concierge_health():
    return {"status": "ok", "service": "concierge"}

