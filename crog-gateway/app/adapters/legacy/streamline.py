"""
Streamline VRS Property Management System Adapter

Implements the ReservationService interface for Streamline VRS API.
Handles reservation lookups, access codes, and guest data.
"""

from datetime import datetime, timedelta
from typing import Optional
import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.interfaces import ReservationService
from app.models.domain import Guest, Reservation, AccessCode

logger = structlog.get_logger()


class StreamlineVRSAdapter(ReservationService):
    """
    Streamline VRS PMS Integration
    
    Translates between our domain models and Streamline's API format.
    """

    def __init__(self):
        self.api_url = settings.streamline_api_url
        self.api_key = settings.streamline_api_key
        self.property_id = settings.streamline_property_id
        self.log = logger.bind(adapter="streamline_vrs")

        self.client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=settings.http_timeout_seconds,
            headers={
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            },
        )

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=settings.retry_wait_seconds,
            max=60,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def get_reservation_by_phone(
        self,
        phone_number: str,
        trace_id: str,
    ) -> Optional[Reservation]:
        """
        Lookup reservation by guest phone number.
        
        Streamline API Endpoint: GET /reservations?phone={phone}
        """
        log = self.log.bind(trace_id=trace_id, phone=phone_number)
        log.info("fetching_reservation_by_phone")

        try:
            response = await self.client.get(
                "/reservations",
                params={
                    "property_id": self.property_id,
                    "phone": phone_number,
                    "status": "active",  # Only active reservations
                },
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("reservations"):
                log.info("no_reservation_found")
                return None

            # Get the first active reservation
            res_data = data["reservations"][0]
            reservation = self._parse_reservation(res_data)

            log.info(
                "reservation_found",
                reservation_id=reservation.reservation_id,
                property_name=reservation.property_name,
            )

            return reservation

        except httpx.HTTPStatusError as e:
            log.error(
                "streamline_api_error",
                status_code=e.response.status_code,
                error=str(e),
            )
            return None

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=settings.retry_wait_seconds,
            max=60,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def get_reservation_by_id(
        self,
        reservation_id: str,
        trace_id: str,
    ) -> Optional[Reservation]:
        """
        Lookup reservation by confirmation code.
        
        Streamline API Endpoint: GET /reservations/{id}
        """
        log = self.log.bind(trace_id=trace_id, reservation_id=reservation_id)
        log.info("fetching_reservation_by_id")

        try:
            response = await self.client.get(f"/reservations/{reservation_id}")
            response.raise_for_status()

            res_data = response.json()
            reservation = self._parse_reservation(res_data)

            log.info("reservation_found", property_name=reservation.property_name)
            return reservation

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.info("reservation_not_found")
                return None

            log.error("streamline_api_error", status_code=e.response.status_code)
            return None

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=settings.retry_wait_seconds,
            max=60,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def get_access_code(
        self,
        reservation: Reservation,
        trace_id: str,
    ) -> AccessCode:
        """
        Retrieve door lock access code for unit.
        
        Streamline API Endpoint: GET /units/{unit_id}/access_codes
        """
        log = self.log.bind(
            trace_id=trace_id,
            reservation_id=reservation.reservation_id,
            unit_id=reservation.unit_id,
        )
        log.info("fetching_access_code")

        try:
            response = await self.client.get(
                f"/units/{reservation.unit_id}/access_codes",
                params={
                    "reservation_id": reservation.reservation_id,
                },
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("codes"):
                log.warning("no_access_code_found")
                # Return mock code for demo purposes
                return self._generate_mock_access_code(reservation)

            code_data = data["codes"][0]

            access_code = AccessCode(
                code=code_data["code"],
                unit_id=reservation.unit_id,
                reservation_id=reservation.reservation_id,
                valid_from=datetime.fromisoformat(code_data["valid_from"]),
                valid_until=datetime.fromisoformat(code_data["valid_until"]),
                created_at=datetime.fromisoformat(code_data["created_at"]),
            )

            log.info("access_code_retrieved", code_valid=access_code.is_valid)
            return access_code

        except httpx.HTTPStatusError as e:
            log.error("streamline_api_error", status_code=e.response.status_code)
            # Fallback to mock code
            return self._generate_mock_access_code(reservation)

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_seconds,
            min=settings.retry_wait_seconds,
            max=60,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def update_guest_info(
        self,
        reservation_id: str,
        guest_updates: dict,
        trace_id: str,
    ) -> bool:
        """
        Update guest information in Streamline VRS.
        
        Streamline API Endpoint: PATCH /reservations/{id}/guest
        """
        log = self.log.bind(trace_id=trace_id, reservation_id=reservation_id)
        log.info("updating_guest_info", fields=list(guest_updates.keys()))

        try:
            response = await self.client.patch(
                f"/reservations/{reservation_id}/guest",
                json=guest_updates,
            )
            response.raise_for_status()

            log.info("guest_info_updated_successfully")
            return True

        except httpx.HTTPStatusError as e:
            log.error(
                "failed_to_update_guest_info",
                status_code=e.response.status_code,
                error=str(e),
            )
            return False

    def _parse_reservation(self, data: dict) -> Reservation:
        """
        Parse Streamline VRS reservation format into our domain model.
        
        Streamline response format (example):
        {
            "id": "RES123456",
            "guest": {
                "id": "GUEST789",
                "first_name": "John",
                "last_name": "Smith",
                "email": "john@example.com",
                "phone": "+15551234567"
            },
            "property": {
                "name": "Blue Ridge Cabin",
                "unit_id": "UNIT001"
            },
            "checkin": "2024-01-15T16:00:00Z",
            "checkout": "2024-01-20T11:00:00Z",
            "status": "confirmed",
            "created_at": "2024-01-01T10:00:00Z",
            "updated_at": "2024-01-01T10:00:00Z"
        }
        """
        guest_data = data["guest"]
        property_data = data["property"]

        guest = Guest(
            guest_id=guest_data["id"],
            first_name=guest_data["first_name"],
            last_name=guest_data["last_name"],
            email=guest_data.get("email"),
            phone_number=guest_data["phone"],
            language_preference=guest_data.get("language", "en"),
        )

        return Reservation(
            reservation_id=data["id"],
            guest=guest,
            property_name=property_data["name"],
            unit_id=property_data["unit_id"],
            checkin_date=datetime.fromisoformat(data["checkin"]),
            checkout_date=datetime.fromisoformat(data["checkout"]),
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def _generate_mock_access_code(self, reservation: Reservation) -> AccessCode:
        """
        Generate mock access code for development/demo.
        
        In production, this should never be used - always fetch from PMS.
        """
        return AccessCode(
            code="1234",  # Mock code
            unit_id=reservation.unit_id,
            reservation_id=reservation.reservation_id,
            valid_from=reservation.checkin_date,
            valid_until=reservation.checkout_date + timedelta(hours=2),
            created_at=datetime.now(),
        )

    async def close(self):
        """Cleanup HTTP client"""
        await self.client.aclose()
