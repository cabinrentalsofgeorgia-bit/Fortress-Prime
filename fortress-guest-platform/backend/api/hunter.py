from fastapi import APIRouter

router = APIRouter()


@router.get("/hunter/health")
async def hunter_health():
    return {"status": "ok", "service": "hunter"}

