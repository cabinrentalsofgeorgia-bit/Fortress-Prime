from fastapi import APIRouter

router = APIRouter(prefix="/api/vrs")


@router.get("/health")
async def vrs_health():
    return {"status": "ok", "service": "vrs_health"}

