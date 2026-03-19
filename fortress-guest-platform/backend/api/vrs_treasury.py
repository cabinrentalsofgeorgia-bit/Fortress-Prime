from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
async def vrs_treasury_status():
    return {"status": "ok", "service": "vrs_treasury"}

