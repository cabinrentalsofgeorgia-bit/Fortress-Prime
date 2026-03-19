from fastapi import APIRouter

router = APIRouter()


@router.get("/operations/ping")
async def vrs_operations_ping():
    return {"status": "ok", "service": "vrs_operations"}

