from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def dispatch_health():
    return {"status": "ok", "service": "dispatch"}

