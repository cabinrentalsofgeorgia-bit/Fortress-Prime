"""
Channel Manager API — OTA distribution and webhook handling
"""
from uuid import UUID
from datetime import date
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.core.event_publisher import EventPublisher
from backend.services.channel_manager import ChannelManager

logger = structlog.get_logger(service="channels")
router = APIRouter()
manager = ChannelManager()


async def _emit_ota_revenue_event(result: dict, source: str):
    """Publish trust.revenue.staged for paid OTA reservations."""
    if not result.get("success") or result.get("action") != "imported":
        return
    code = result.get("confirmation_code")
    total = result.get("total_amount", 0)
    if not code or float(total or 0) <= 0:
        return
    payload = {
        "property_id": str(result.get("property_id", "")),
        "confirmation_code": code,
        "total_amount": float(total),
        "cleaning_fee": float(result.get("cleaning_fee", 0)),
        "tax_amount": float(result.get("tax_amount", 0)),
        "nightly_rate": float(result.get("nightly_rate", 0)),
        "nights_count": int(result.get("nights_count", 0)),
    }
    await EventPublisher.publish("trust.revenue.staged", payload, key=code)
    logger.info("ota_revenue_emitted", source=source, confirmation_code=code)


@router.get("/status/{property_id}")
async def channel_status(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Get connection status for all channels for a property."""
    return await manager.get_channel_status(property_id)


@router.post("/sync/{property_id}")
async def sync_availability(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Push availability to all connected channels."""
    return await manager.sync_availability_to_channels(property_id, db)


@router.get("/performance")
async def channel_performance(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Revenue breakdown by booking channel."""
    return await manager.get_channel_performance(start_date, end_date, db)


@router.get("/rate-parity/{property_id}")
async def rate_parity(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Check rate consistency across channels."""
    return await manager.get_rate_parity(property_id, db)


@router.post("/block-dates/{property_id}")
async def block_dates(
    property_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    reason: str = Query(default="owner_hold"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Block dates across all channels."""
    return await manager.block_dates(property_id, start_date, end_date, reason)


@router.post("/unblock-dates/{property_id}")
async def unblock_dates(
    property_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """Unblock dates across all channels."""
    return await manager.unblock_dates(property_id, start_date, end_date)


# ── OTA Webhook Endpoints ──

@router.post("/webhooks/airbnb")
async def airbnb_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle incoming Airbnb reservation notifications."""
    payload = await request.json()
    result = await manager.handle_airbnb_webhook(payload, db)
    await _emit_ota_revenue_event(result, "airbnb")
    return result


@router.post("/webhooks/vrbo")
async def vrbo_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle incoming VRBO reservation notifications."""
    payload = await request.json()
    result = await manager.handle_vrbo_webhook(payload, db)
    await _emit_ota_revenue_event(result, "vrbo")
    return result


@router.post("/webhooks/booking-com")
async def booking_com_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle incoming Booking.com reservation notifications."""
    payload = await request.json()
    result = await manager.handle_booking_com_webhook(payload, db)
    await _emit_ota_revenue_event(result, "booking_com")
    return result
