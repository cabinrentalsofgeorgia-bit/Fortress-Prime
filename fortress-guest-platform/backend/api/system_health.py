from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def system_health_root():
    return {"status": "ok", "service": "system_health"}

