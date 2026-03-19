from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def internal_deck_health():
    return {"status": "ok", "service": "internal_deck"}

