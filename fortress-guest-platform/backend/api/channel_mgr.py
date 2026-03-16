"""
Channel Manager API — manage OTA distribution from the dashboard.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.core.database import get_db
from backend.integrations.channel_adapters import (
    get_adapter, get_all_adapters, ICalAdapter,
)

router = APIRouter()


# ── Models ──

class ChannelMapping(BaseModel):
    property_id: str
    channel: str
    listing_id: str
    is_active: bool = True


class RatePush(BaseModel):
    property_id: str
    channels: list[str]
    dates: list[dict]


class AvailabilityPush(BaseModel):
    property_id: str
    channels: list[str]
    dates: list[dict]


# ── Endpoints ──

@router.get("/status")
async def channel_status():
    """Get the connection status of all channel integrations."""
    adapters = get_all_adapters()
    return {
        "channels": [
            {
                "name": a.channel_name,
                "configured": a.configured,
                "status": "connected" if a.configured else "not_configured",
            }
            for a in adapters
        ],
        "ical": {"name": "ical", "configured": True, "status": "always_available"},
    }


@router.get("/mappings")
async def list_channel_mappings(db: AsyncSession = Depends(get_db)):
    """List all property-to-channel listing mappings."""
    result = await db.execute(
        text("""
            SELECT cm.*, p.name as property_name
            FROM channel_mappings cm
            JOIN properties p ON cm.property_id = p.id::text
            ORDER BY p.name, cm.channel
        """)
    )
    rows = result.fetchall()
    if not rows:
        return []
    return [dict(r._mapping) for r in rows]


@router.post("/mappings")
async def create_channel_mapping(body: ChannelMapping, db: AsyncSession = Depends(get_db)):
    """Map a property to a channel listing ID."""
    await db.execute(
        text("""
            INSERT INTO channel_mappings (property_id, channel, listing_id, is_active)
            VALUES (:property_id, :channel, :listing_id, :is_active)
            ON CONFLICT (property_id, channel) DO UPDATE SET
                listing_id = EXCLUDED.listing_id,
                is_active = EXCLUDED.is_active
        """),
        body.model_dump(),
    )
    await db.commit()
    return {"status": "created", **body.model_dump()}


@router.post("/push-availability")
async def push_availability(body: AvailabilityPush):
    """Push availability to one or more channels."""
    results = {}
    for channel in body.channels:
        try:
            adapter = get_adapter(channel)
            result = await adapter.push_availability(body.property_id, "", body.dates)
            results[channel] = result
        except Exception as e:
            results[channel] = {"status": "error", "error": str(e)}
    return results


@router.post("/push-rates")
async def push_rates(body: RatePush):
    """Push rates to one or more channels."""
    results = {}
    for channel in body.channels:
        try:
            adapter = get_adapter(channel)
            result = await adapter.push_rates(body.property_id, "", body.dates)
            results[channel] = result
        except Exception as e:
            results[channel] = {"status": "error", "error": str(e)}
    return results


@router.post("/sync-all")
async def sync_all_channels(db: AsyncSession = Depends(get_db)):
    """Trigger a full sync across all configured channels."""
    adapters = get_all_adapters()
    results = {}
    for adapter in adapters:
        if adapter.configured:
            try:
                reservations = await adapter.fetch_reservations("")
                results[adapter.channel_name] = {
                    "status": "synced",
                    "reservations_fetched": len(reservations),
                }
            except Exception as e:
                results[adapter.channel_name] = {"status": "error", "error": str(e)}
        else:
            results[adapter.channel_name] = {"status": "not_configured"}
    return results


@router.get("/ical/{property_slug}.ics")
async def ical_feed(property_slug: str, db: AsyncSession = Depends(get_db)):
    """Generate an iCal feed for a property (for OTAs that use iCal import)."""
    prop = await db.execute(
        text("SELECT id, name FROM properties WHERE slug = :slug AND is_active = true"),
        {"slug": property_slug},
    )
    row = prop.fetchone()
    if not row:
        raise HTTPException(404, "Property not found")

    p = dict(row._mapping)

    reservations = await db.execute(
        text("""
            SELECT r.id, r.confirmation_code, r.check_in_date, r.check_out_date,
                   g.first_name || ' ' || g.last_name as guest_name
            FROM reservations r
            LEFT JOIN guests g ON r.guest_id = g.id
            WHERE r.property_id = :pid
            AND r.status IN ('confirmed', 'checked_in')
            AND r.check_out_date >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY r.check_in_date
        """),
        {"pid": p["id"]},
    )

    ical = ICalAdapter()
    feed = ical.generate_ical_feed(p["name"], [dict(r._mapping) for r in reservations.fetchall()])

    return PlainTextResponse(
        content=feed,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{property_slug}.ics"'},
    )
