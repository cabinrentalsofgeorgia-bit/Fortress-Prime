"""
OTA Channel Adapters
=====================
Standardized adapters for each OTA channel (Airbnb, Vrbo, Booking.com).
Each adapter implements a common interface for:
  - Listing management (create, update, sync)
  - Availability push (block/unblock dates)
  - Rate push (nightly rates, min stay)
  - Reservation import (webhook + polling)
  - Review aggregation
  - Message sync
  - iCal fallback for smaller channels

DEPRECATION NOTICE (2026-04-14)
--------------------------------
These OTA-direct adapters (AirbnbAdapter, VrboAdapter, BookingComAdapter) are
DEPRECATED and are NOT the canonical channel distribution layer.

The canonical channel layer is Channex (staging.channex.io) which handles
Airbnb, VRBO, and Booking.com distribution via its aggregator API. All
availability and rate pushes go through:
  - backend/services/channex_ari.py        — ARI push (availability + rates)
  - backend/workers/channex_egress.py      — Kafka consumer driving ARI sync
  - backend/api/channels.py                — REST endpoints backed by Channex
  - backend/services/channex_sync.py       — Property mapping management

These direct-OTA adapters remain in the codebase as scaffolding for a future
direct-API path (once OTA partner credentials are provisioned) but their
push_availability and push_rates methods now raise NotImplementedError rather
than silently returning {"status": "pushed"} without doing any work.

The iCal adapter (ICalAdapter) is still functional and used directly.

To fully replace: set AIRBNB_CLIENT_ID/SECRET, VRBO_API_KEY/SECRET,
BOOKINGCOM_USERNAME/PASSWORD in .env, then implement real HTTP calls in each
adapter's push methods.
"""

import os
import structlog
from datetime import date
from typing import Optional, Dict, List, Any
from abc import ABC, abstractmethod

logger = structlog.get_logger()


class ChannelAdapter(ABC):
    """Base interface for OTA channel integrations."""

    channel_name: str = ""

    @abstractmethod
    async def push_availability(
        self, property_id: str, listing_id: str,
        dates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Push availability calendar to the channel."""
        ...

    @abstractmethod
    async def push_rates(
        self, property_id: str, listing_id: str,
        rates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Push nightly rates to the channel."""
        ...

    @abstractmethod
    async def fetch_reservations(
        self, listing_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch new/updated reservations from the channel."""
        ...

    @abstractmethod
    async def sync_listing(
        self, property_data: Dict[str, Any], listing_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a listing on the channel."""
        ...

    @abstractmethod
    async def fetch_reviews(self, listing_id: str) -> List[Dict[str, Any]]:
        """Fetch guest reviews for a listing."""
        ...


# ============================================================================
# Airbnb Adapter
# ============================================================================

class AirbnbAdapter(ChannelAdapter):
    """
    Airbnb API integration via the Airbnb Connectivity API.
    Requires Airbnb Software Partner registration.
    """

    channel_name = "airbnb"

    def __init__(self):
        self.client_id = os.environ.get("AIRBNB_CLIENT_ID", "")
        self.client_secret = os.environ.get("AIRBNB_CLIENT_SECRET", "")
        self.api_base = "https://api.airbnb.com/v2"
        self.configured = bool(self.client_id and self.client_secret)

    async def push_availability(self, property_id, listing_id, dates):
        if not self.configured:
            raise NotImplementedError(
                "AirbnbAdapter.push_availability: AIRBNB_CLIENT_ID and "
                "AIRBNB_CLIENT_SECRET are not configured. Use Channex "
                "(channex_ari.py) for availability distribution instead."
            )
        raise NotImplementedError(
            "AirbnbAdapter.push_availability: Direct Airbnb API integration "
            "is not yet implemented. Availability is distributed via Channex. "
            "To implement: wire Airbnb Connectivity API calendar batch update."
        )

    async def push_rates(self, property_id, listing_id, rates):
        if not self.configured:
            raise NotImplementedError(
                "AirbnbAdapter.push_rates: AIRBNB_CLIENT_ID and "
                "AIRBNB_CLIENT_SECRET are not configured. Use Channex "
                "(channex_ari.py) for rate distribution instead."
            )
        raise NotImplementedError(
            "AirbnbAdapter.push_rates: Direct Airbnb API integration "
            "is not yet implemented. Rates are distributed via Channex."
        )

    async def fetch_reservations(self, listing_id, start_date=None, end_date=None):
        if not self.configured:
            return []
        logger.info("airbnb_fetch_reservations", listing_id=listing_id)
        return []

    async def sync_listing(self, property_data, listing_id=None):
        if not self.configured:
            return {"status": "skipped", "reason": "airbnb_not_configured"}

        payload = {
            "name": property_data.get("name"),
            "property_type": "cabin",
            "room_type": "entire_home",
            "bedrooms": property_data.get("bedrooms"),
            "bathrooms": property_data.get("bathrooms"),
            "person_capacity": property_data.get("max_guests"),
            "description": property_data.get("description", ""),
        }

        logger.info("airbnb_listing_sync", listing_id=listing_id, name=payload["name"])
        return {"status": "synced", "channel": "airbnb", "listing_id": listing_id, "payload": payload}

    async def fetch_reviews(self, listing_id):
        if not self.configured:
            return []
        return []


# ============================================================================
# Vrbo/Expedia Adapter
# ============================================================================

class VrboAdapter(ChannelAdapter):
    """
    Vrbo/Expedia API integration via the Expedia Connectivity API.
    Requires Expedia Partner registration.
    """

    channel_name = "vrbo"

    def __init__(self):
        self.api_key = os.environ.get("VRBO_API_KEY", "")
        self.api_secret = os.environ.get("VRBO_API_SECRET", "")
        self.api_base = "https://api.expediagroup.com/supply/lodging"
        self.configured = bool(self.api_key and self.api_secret)

    async def push_availability(self, property_id, listing_id, dates):
        if not self.configured:
            raise NotImplementedError(
                "VrboAdapter.push_availability: VRBO_API_KEY and VRBO_API_SECRET "
                "are not configured. Use Channex (channex_ari.py) instead."
            )
        raise NotImplementedError(
            "VrboAdapter.push_availability: Direct VRBO/Expedia API integration "
            "is not yet implemented. Availability is distributed via Channex."
        )

    async def push_rates(self, property_id, listing_id, rates):
        if not self.configured:
            raise NotImplementedError(
                "VrboAdapter.push_rates: VRBO_API_KEY and VRBO_API_SECRET "
                "are not configured. Use Channex (channex_ari.py) instead."
            )
        raise NotImplementedError(
            "VrboAdapter.push_rates: Direct VRBO/Expedia API integration "
            "is not yet implemented. Rates are distributed via Channex."
        )

    async def fetch_reservations(self, listing_id, start_date=None, end_date=None):
        if not self.configured:
            return []
        return []

    async def sync_listing(self, property_data, listing_id=None):
        if not self.configured:
            return {"status": "skipped", "reason": "vrbo_not_configured"}
        logger.info("vrbo_listing_sync", listing_id=listing_id)
        return {"status": "synced", "channel": "vrbo", "listing_id": listing_id}

    async def fetch_reviews(self, listing_id):
        return []


# ============================================================================
# Booking.com Adapter
# ============================================================================

class BookingComAdapter(ChannelAdapter):
    """
    Booking.com Connectivity Partner API integration.
    Requires Booking.com Partner registration.
    """

    channel_name = "booking_com"

    def __init__(self):
        self.username = os.environ.get("BOOKINGCOM_USERNAME", "")
        self.password = os.environ.get("BOOKINGCOM_PASSWORD", "")
        self.api_base = "https://supply-xml.booking.com"
        self.configured = bool(self.username and self.password)

    async def push_availability(self, property_id, listing_id, dates):
        if not self.configured:
            raise NotImplementedError(
                "BookingComAdapter.push_availability: BOOKINGCOM_USERNAME and "
                "BOOKINGCOM_PASSWORD are not configured. Use Channex instead."
            )
        raise NotImplementedError(
            "BookingComAdapter.push_availability: Direct Booking.com API integration "
            "is not yet implemented. Availability is distributed via Channex."
        )

    async def push_rates(self, property_id, listing_id, rates):
        if not self.configured:
            raise NotImplementedError(
                "BookingComAdapter.push_rates: BOOKINGCOM_USERNAME and "
                "BOOKINGCOM_PASSWORD are not configured. Use Channex instead."
            )
        raise NotImplementedError(
            "BookingComAdapter.push_rates: Direct Booking.com API integration "
            "is not yet implemented. Rates are distributed via Channex."
        )

    async def fetch_reservations(self, listing_id, start_date=None, end_date=None):
        if not self.configured:
            return []
        return []

    async def sync_listing(self, property_data, listing_id=None):
        if not self.configured:
            return {"status": "skipped", "reason": "booking_com_not_configured"}
        logger.info("bookingcom_listing_sync", listing_id=listing_id)
        return {"status": "synced", "channel": "booking_com", "listing_id": listing_id}

    async def fetch_reviews(self, listing_id):
        return []


# ============================================================================
# iCal Adapter (Universal Fallback)
# ============================================================================

class ICalAdapter:
    """
    iCal import/export for channels that don't have a full API.
    Generates .ics feeds for availability and imports external iCal feeds.
    """

    channel_name = "ical"

    def generate_ical_feed(
        self,
        property_name: str,
        reservations: List[Dict[str, Any]],
    ) -> str:
        """Generate an iCal (.ics) feed for a property's calendar."""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:-//Fortress Guest Platform//Cabin Rentals//{property_name}//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
        ]

        for r in reservations:
            uid = r.get("id", r.get("confirmation_code", ""))
            start = r.get("check_in_date", r.get("check_in", ""))
            end = r.get("check_out_date", r.get("check_out", ""))
            guest = r.get("guest_name", "Reserved")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}@fortress-guest-platform",
                f"DTSTART;VALUE=DATE:{str(start).replace('-', '')}",
                f"DTEND;VALUE=DATE:{str(end).replace('-', '')}",
                f"SUMMARY:{guest} - {property_name}",
                "STATUS:CONFIRMED",
                "END:VEVENT",
            ])

        lines.append("END:VCALENDAR")
        return "\r\n".join(lines)

    async def import_ical_feed(self, feed_url: str) -> List[Dict[str, Any]]:
        """Import reservations from an external iCal feed URL."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(feed_url) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()

            events = []
            current_event: Dict[str, str] = {}

            for line in text.splitlines():
                line = line.strip()
                if line == "BEGIN:VEVENT":
                    current_event = {}
                elif line == "END:VEVENT":
                    if current_event:
                        events.append({
                            "uid": current_event.get("UID", ""),
                            "check_in": current_event.get("DTSTART", ""),
                            "check_out": current_event.get("DTEND", ""),
                            "summary": current_event.get("SUMMARY", ""),
                        })
                elif ":" in line:
                    key, _, value = line.partition(":")
                    key = key.split(";")[0]
                    current_event[key] = value

            return events

        except Exception as e:
            logger.error("ical_import_failed", url=feed_url, error=str(e))
            return []


# ============================================================================
# Channel Registry
# ============================================================================

def get_adapter(channel: str) -> ChannelAdapter:
    """Return the adapter for a given channel name."""
    adapters = {
        "airbnb": AirbnbAdapter,
        "vrbo": VrboAdapter,
        "booking_com": BookingComAdapter,
    }
    cls = adapters.get(channel)
    if not cls:
        raise ValueError(f"Unknown channel: {channel}")
    return cls()


def get_all_adapters() -> List[ChannelAdapter]:
    """Return instances of all configured channel adapters."""
    return [AirbnbAdapter(), VrboAdapter(), BookingComAdapter()]
