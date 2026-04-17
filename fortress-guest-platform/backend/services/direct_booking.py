"""
Direct Booking Engine - Guest-Facing Reservation Widget
BETTER THAN: Lodgify Direct, Hostaway Direct, Guesty Booking Widget

Powers the direct booking flow on the Fortress website:
1. Availability search & calendar display
2. Real-time quote generation with transparent fee breakdown
3. Secure booking initiation and confirmation
4. Cancellation with policy-aware refund calculation

Key advantages over OTA bookings:
- 0% commission vs 3-15% on Airbnb/VRBO/Booking.com
- Full guest data ownership
- Branded experience
- Lower service fee for guests (3% vs 6-14%)
- Instant confirmation
"""
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass, field
from enum import Enum

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Property, Reservation, Guest

logger = structlog.get_logger()


# ── Data Classes ──


@dataclass
class AvailabilityResult:
    """Result of an availability check for a specific property and date range."""
    available: bool
    reason: Optional[str] = None
    alternative_dates: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class BookingQuote:
    """Detailed price quote for a potential booking."""
    id: str
    property_id: str
    property_name: str
    check_in: date
    check_out: date
    nights: int
    guests: int
    nightly_rates: List[Dict[str, Any]]
    subtotal: Decimal
    cleaning_fee: Decimal
    taxes: Decimal
    service_fee: Decimal
    total: Decimal
    valid_until: datetime
    currency: str = "USD"


@dataclass
class PendingBooking:
    """A booking that has been initiated but not yet confirmed with payment."""
    id: str
    quote_id: str
    guest_info: Dict[str, Any]
    status: str
    expires_at: datetime
    confirmation_code: str


@dataclass
class CancellationResult:
    """Result of a booking cancellation request."""
    success: bool
    refund_amount: Decimal
    policy_applied: str
    message: str = ""


# ── Cancellation Policy ──


class CancellationPolicy(str, Enum):
    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    NO_REFUND = "no_refund"


# ── Engine ──


class DirectBookingEngine:
    """
    Guest-facing direct booking engine for the Fortress website widget.

    Handles the complete booking lifecycle: search, quote, book, cancel.
    All fees are transparent and competitive with OTA pricing.
    """

    # Cleaning fees by bedroom count (Fannin County GA market rates)
    CLEANING_FEES: Dict[str, Decimal] = {
        "1-2": Decimal("150.00"),
        "3-4": Decimal("250.00"),
        "5-6": Decimal("350.00"),
        "7+": Decimal("450.00"),
    }

    # Tax rate: Georgia state (4%) + Fannin County (4%) + local lodging (5%) = 13%
    TAX_RATE: Decimal = Decimal("0.13")

    # Direct booking service fee (much lower than OTAs)
    SERVICE_FEE_RATE: Decimal = Decimal("0.03")

    # Quote validity window
    QUOTE_TTL_MINUTES: int = 30

    # Pending booking hold window
    BOOKING_HOLD_MINUTES: int = 15

    # Minimum stay (nights)
    MIN_STAY: int = 2

    def __init__(self) -> None:
        self.log = logger.bind(service="direct_booking_engine")
        self._pending_quotes: Dict[str, BookingQuote] = {}
        self._pending_bookings: Dict[str, PendingBooking] = {}

    # ── Availability ──

    async def check_availability(
        self,
        property_id: UUID,
        check_in: date,
        check_out: date,
        guests: int,
        db: AsyncSession,
    ) -> AvailabilityResult:
        """
        Check whether a property is available for the requested dates and guest count.

        Validates:
        - Property exists and is active
        - Date range is valid (future, min stay)
        - Guest count within capacity
        - No overlapping confirmed reservations
        """
        self.log.info(
            "check_availability",
            property_id=str(property_id),
            check_in=check_in.isoformat(),
            check_out=check_out.isoformat(),
            guests=guests,
        )

        prop_result = await db.execute(
            select(Property).where(
                and_(Property.id == property_id, Property.is_active == True)
            )
        )
        prop = prop_result.scalar_one_or_none()

        if not prop:
            return AvailabilityResult(
                available=False,
                reason="Property not found or is not active.",
            )

        today = date.today()
        if check_in < today:
            return AvailabilityResult(
                available=False,
                reason="Check-in date must be in the future.",
            )

        if check_out <= check_in:
            return AvailabilityResult(
                available=False,
                reason="Check-out must be after check-in.",
            )

        nights = (check_out - check_in).days
        if nights < self.MIN_STAY:
            return AvailabilityResult(
                available=False,
                reason=f"Minimum stay is {self.MIN_STAY} nights.",
            )

        if guests > prop.max_guests:
            return AvailabilityResult(
                available=False,
                reason=f"Maximum occupancy is {prop.max_guests} guests.",
            )

        conflict_result = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date < check_out,
                    Reservation.check_out_date > check_in,
                )
            )
        )
        conflicts = conflict_result.scalars().all()

        if conflicts:
            alternatives = await self._find_alternative_dates(
                property_id, check_in, check_out, db
            )
            return AvailabilityResult(
                available=False,
                reason="Selected dates are not available.",
                alternative_dates=alternatives,
            )

        return AvailabilityResult(available=True)

    async def _find_alternative_dates(
        self,
        property_id: UUID,
        check_in: date,
        check_out: date,
        db: AsyncSession,
    ) -> List[Dict[str, str]]:
        """Suggest up to 3 nearby alternative date ranges of the same length."""
        nights = (check_out - check_in).days
        alternatives: List[Dict[str, str]] = []

        for offset in range(1, 22):
            for direction in (1, -1):
                alt_in = check_in + timedelta(days=offset * direction)
                alt_out = alt_in + timedelta(days=nights)

                if alt_in < date.today():
                    continue

                conflict = await db.execute(
                    select(Reservation.id).where(
                        and_(
                            Reservation.property_id == property_id,
                            Reservation.status.in_(["confirmed", "checked_in"]),
                            Reservation.check_in_date < alt_out,
                            Reservation.check_out_date > alt_in,
                        )
                    ).limit(1)
                )
                if not conflict.scalar_one_or_none():
                    alternatives.append({
                        "check_in": alt_in.isoformat(),
                        "check_out": alt_out.isoformat(),
                    })
                    if len(alternatives) >= 3:
                        return alternatives

        return alternatives

    # ── Quote Generation ──

    async def create_quote(
        self,
        property_id: UUID,
        check_in: date,
        check_out: date,
        guests: int,
        db: AsyncSession,
    ) -> BookingQuote:
        """
        Generate a detailed price quote with transparent fee breakdown.

        Builds nightly rate schedule, calculates cleaning fee based on
        property size, applies Fannin County tax, and adds service fee.
        """
        availability = await self.check_availability(
            property_id, check_in, check_out, guests, db
        )
        if not availability.available:
            raise ValueError(
                f"Property not available: {availability.reason}"
            )

        prop_result = await db.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = prop_result.scalar_one()

        nights = (check_out - check_in).days
        nightly_rate = self._get_nightly_rate(prop, check_in, check_out)
        nightly_rates = []
        subtotal = Decimal("0")

        current = check_in
        while current < check_out:
            rate = self._rate_for_date(nightly_rate, current)
            nightly_rates.append({
                "date": current.isoformat(),
                "rate": str(rate),
                "is_weekend": current.weekday() >= 4,
            })
            subtotal += rate
            current += timedelta(days=1)

        cleaning_fee = self._get_cleaning_fee(prop.bedrooms)
        fees = self.calculate_fees(subtotal, cleaning_fee)

        quote = BookingQuote(
            id=f"Q-{uuid4().hex[:12].upper()}",
            property_id=str(property_id),
            property_name=prop.name,
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            guests=guests,
            nightly_rates=nightly_rates,
            subtotal=subtotal,
            cleaning_fee=fees["cleaning_fee"],
            taxes=fees["taxes"],
            service_fee=fees["service_fee"],
            total=fees["total"],
            valid_until=datetime.utcnow() + timedelta(minutes=self.QUOTE_TTL_MINUTES),
        )

        self._pending_quotes[quote.id] = quote

        self.log.info(
            "quote_created",
            quote_id=quote.id,
            property=prop.name,
            nights=nights,
            total=str(quote.total),
        )
        return quote

    def _get_nightly_rate(
        self, prop: Property, check_in: date, check_out: date
    ) -> Decimal:
        """
        Determine base nightly rate for a property.

        In production this would pull from a dynamic pricing engine
        (PriceLabs, Wheelhouse, etc.). For now, estimate by bedroom count.
        """
        bedroom_rates: Dict[int, Decimal] = {
            1: Decimal("149.00"),
            2: Decimal("199.00"),
            3: Decimal("269.00"),
            4: Decimal("329.00"),
            5: Decimal("399.00"),
            6: Decimal("449.00"),
            7: Decimal("549.00"),
            8: Decimal("649.00"),
        }
        return bedroom_rates.get(prop.bedrooms, Decimal("299.00"))

    def _rate_for_date(self, base_rate: Decimal, d: date) -> Decimal:
        """Apply weekend / seasonal premiums to the base rate."""
        rate = base_rate

        # Weekend premium: Fri-Sat nights +20%
        if d.weekday() in (4, 5):
            rate = (rate * Decimal("1.20")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # Peak season premium: Jun-Aug, Oct, Dec +15%
        if d.month in (6, 7, 8, 10, 12):
            rate = (rate * Decimal("1.15")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        return rate

    def _get_cleaning_fee(self, bedrooms: int) -> Decimal:
        """Look up cleaning fee by bedroom count."""
        if bedrooms <= 2:
            return self.CLEANING_FEES["1-2"]
        elif bedrooms <= 4:
            return self.CLEANING_FEES["3-4"]
        elif bedrooms <= 6:
            return self.CLEANING_FEES["5-6"]
        else:
            return self.CLEANING_FEES["7+"]

    def calculate_fees(
        self,
        subtotal: Decimal,
        cleaning_fee: Optional[Decimal] = None,
    ) -> Dict[str, Decimal]:
        """
        Calculate the full fee breakdown for a booking.

        Returns cleaning fee, taxes (13% state + county for Fannin County GA),
        service fee (3% for direct bookings), and grand total.
        """
        if cleaning_fee is None:
            cleaning_fee = self.CLEANING_FEES["3-4"]

        taxable = subtotal + cleaning_fee
        taxes = (taxable * self.TAX_RATE).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        service_fee = (subtotal * self.SERVICE_FEE_RATE).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total = subtotal + cleaning_fee + taxes + service_fee

        return {
            "subtotal": subtotal,
            "cleaning_fee": cleaning_fee,
            "taxes": taxes,
            "tax_rate": self.TAX_RATE,
            "service_fee": service_fee,
            "service_fee_rate": self.SERVICE_FEE_RATE,
            "total": total,
        }

    # ── Booking Lifecycle ──

    async def initiate_booking(
        self,
        quote_id: str,
        guest_info: Dict[str, Any],
        db: AsyncSession,
    ) -> PendingBooking:
        """
        Initiate a booking from a valid quote.

        Creates a hold on the dates and returns a PendingBooking that
        must be confirmed with payment within BOOKING_HOLD_MINUTES.
        """
        quote = self._pending_quotes.get(quote_id)
        if not quote:
            raise ValueError("Quote not found or expired.")

        if datetime.utcnow() > quote.valid_until:
            self._pending_quotes.pop(quote_id, None)
            raise ValueError("Quote has expired. Please generate a new quote.")

        required_fields = ["first_name", "last_name", "email", "phone"]
        missing = [f for f in required_fields if not guest_info.get(f)]
        if missing:
            raise ValueError(f"Missing required guest fields: {', '.join(missing)}")

        confirmation_code = f"FGP-{uuid4().hex[:8].upper()}"

        pending = PendingBooking(
            id=f"PB-{uuid4().hex[:12].upper()}",
            quote_id=quote_id,
            guest_info=guest_info,
            status="pending_payment",
            expires_at=datetime.utcnow() + timedelta(minutes=self.BOOKING_HOLD_MINUTES),
            confirmation_code=confirmation_code,
        )

        self._pending_bookings[pending.id] = pending

        self.log.info(
            "booking_initiated",
            booking_id=pending.id,
            quote_id=quote_id,
            confirmation_code=confirmation_code,
            guest_email=guest_info.get("email"),
        )
        return pending

    async def confirm_booking(
        self,
        booking_id: str,
        payment_method: Dict[str, Any],
        db: AsyncSession,
    ) -> Reservation:
        """
        Confirm a pending booking after successful payment processing.

        Creates the Guest record (or finds existing), persists the
        Reservation, and removes the pending booking hold.
        """
        pending = self._pending_bookings.get(booking_id)
        if not pending:
            raise ValueError("Pending booking not found.")

        if datetime.utcnow() > pending.expires_at:
            self._pending_bookings.pop(booking_id, None)
            raise ValueError("Booking hold has expired. Please start over.")

        quote = self._pending_quotes.get(pending.quote_id)
        if not quote:
            raise ValueError("Associated quote no longer available.")

        self.log.info(
            "processing_payment",
            booking_id=booking_id,
            method=payment_method.get("type", "unknown"),
            amount=str(quote.total),
        )

        info = pending.guest_info
        guest_result = await db.execute(
            select(Guest).where(Guest.email == info["email"])
        )
        guest = guest_result.scalar_one_or_none()
        if not guest:
            guest = Guest(
                phone_number=info["phone"],
                email=info["email"],
                first_name=info["first_name"],
                last_name=info["last_name"],
            )
            db.add(guest)
            await db.flush()

        reservation = Reservation(
            confirmation_code=pending.confirmation_code,
            guest_id=guest.id,
            property_id=UUID(quote.property_id),
            check_in_date=quote.check_in,
            check_out_date=quote.check_out,
            num_guests=quote.guests,
            num_adults=info.get("num_adults"),
            num_children=info.get("num_children"),
            status="confirmed",
            booking_source="direct",
            total_amount=quote.total,
            currency=quote.currency,
        )
        db.add(reservation)
        await db.commit()
        await db.refresh(reservation)

        self._pending_bookings.pop(booking_id, None)
        self._pending_quotes.pop(pending.quote_id, None)

        self.log.info(
            "booking_confirmed",
            confirmation_code=reservation.confirmation_code,
            total=str(quote.total),
            guest=guest.full_name,
        )
        return reservation

    async def cancel_booking(
        self,
        booking_id: UUID,
        reason: str,
        db: AsyncSession,
    ) -> CancellationResult:
        """
        Cancel a confirmed reservation with ledger-aware refund calculation.

        Delegates to the unified refund engine (``calculate_refund_ledger``)
        which reads the Universal Ledger line items from the booking for
        cents-precise refund calculation.  Policy tiers:

        - >= 30 days: full refund of all refundable items
        - 14-29 days: 50% lodging, 100% cleaning, recalculated taxes
        - < 14 days: cleaning fee + associated taxes only
        """
        from backend.services.refund_engine import calculate_refund_ledger

        result = await db.execute(
            select(Reservation).where(Reservation.id == booking_id)
        )
        reservation = result.scalar_one_or_none()

        if not reservation:
            return CancellationResult(
                success=False,
                refund_amount=Decimal("0"),
                policy_applied="none",
                message="Reservation not found.",
            )

        if reservation.status == "cancelled":
            return CancellationResult(
                success=False,
                refund_amount=Decimal("0"),
                policy_applied="none",
                message="Reservation is already cancelled.",
            )

        days_until = (reservation.check_in_date - date.today()).days
        refund_cents = calculate_refund_ledger(reservation, days_until)
        refund = Decimal(refund_cents) / Decimal(100)

        if days_until >= 30:
            policy = CancellationPolicy.FULL_REFUND
        elif days_until >= 14:
            policy = CancellationPolicy.PARTIAL_REFUND
        else:
            policy = CancellationPolicy.NO_REFUND

        reservation.status = "cancelled"
        reservation.internal_notes = (
            f"{reservation.internal_notes or ''}\n"
            f"[{datetime.utcnow().isoformat()}] Cancelled by guest: {reason} "
            f"| Policy: {policy.value} | Refund: ${refund:.2f} ({refund_cents}¢)"
        ).strip()

        await db.commit()

        self.log.info(
            "booking_cancelled",
            confirmation_code=reservation.confirmation_code,
            policy=policy.value,
            refund_cents=refund_cents,
            reason=reason,
        )

        return CancellationResult(
            success=True,
            refund_amount=refund,
            policy_applied=policy.value,
            message=(
                f"Reservation {reservation.confirmation_code} cancelled. "
                f"Refund of ${refund:.2f} will be processed within 5-10 business days."
            ),
        )

    # ── Public Calendar ──

    async def get_property_calendar_public(
        self,
        property_id: UUID,
        month: int,
        year: int,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """
        Return a public-facing calendar for the booking widget showing
        which dates are available, blocked, or have minimum-stay restrictions.
        """
        from calendar import monthrange

        _, days_in_month = monthrange(year, month)
        first_day = date(year, month, 1)
        last_day = date(year, month, days_in_month)

        res_result = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date <= last_day,
                    Reservation.check_out_date >= first_day,
                )
            )
        )
        reservations = res_result.scalars().all()

        booked_dates: set[date] = set()
        for res in reservations:
            current = max(res.check_in_date, first_day)
            end = min(res.check_out_date, last_day + timedelta(days=1))
            while current < end:
                booked_dates.add(current)
                current += timedelta(days=1)

        today = date.today()
        calendar_days: List[Dict[str, Any]] = []
        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            if d < today:
                status = "past"
            elif d in booked_dates:
                status = "booked"
            else:
                status = "available"

            calendar_days.append({
                "date": d.isoformat(),
                "day": day_num,
                "status": status,
                "is_weekend": d.weekday() >= 5,
                "is_checkout_only": d in booked_dates and (d - timedelta(days=1)) not in booked_dates,
            })

        return calendar_days

    # ── Property Search ──

    async def search_available_properties(
        self,
        check_in: date,
        check_out: date,
        guests: int,
        amenities: Optional[List[str]],
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """
        Search all active properties that are available for the requested
        dates and can accommodate the guest count.

        Returns a list of properties with pricing preview so guests can
        compare options on the booking widget.
        """
        if check_out <= check_in:
            raise ValueError("Check-out must be after check-in.")

        nights = (check_out - check_in).days
        if nights < self.MIN_STAY:
            raise ValueError(f"Minimum stay is {self.MIN_STAY} nights.")

        prop_result = await db.execute(
            select(Property).where(
                and_(
                    Property.is_active == True,
                    Property.max_guests >= guests,
                )
            )
        )
        properties = prop_result.scalars().all()

        available: List[Dict[str, Any]] = []
        for prop in properties:
            conflict_result = await db.execute(
                select(Reservation.id).where(
                    and_(
                        Reservation.property_id == prop.id,
                        Reservation.status.in_(["confirmed", "checked_in"]),
                        Reservation.check_in_date < check_out,
                        Reservation.check_out_date > check_in,
                    )
                ).limit(1)
            )
            if conflict_result.scalar_one_or_none():
                continue

            base_rate = self._get_nightly_rate(prop, check_in, check_out)
            cleaning = self._get_cleaning_fee(prop.bedrooms)
            est_subtotal = base_rate * nights
            fees = self.calculate_fees(est_subtotal, cleaning)

            available.append({
                "property_id": str(prop.id),
                "name": prop.name,
                "slug": prop.slug,
                "property_type": prop.property_type,
                "bedrooms": prop.bedrooms,
                "bathrooms": str(prop.bathrooms),
                "max_guests": prop.max_guests,
                "nightly_rate_from": str(base_rate),
                "estimated_total": str(fees["total"]),
                "cleaning_fee": str(cleaning),
                "nights": nights,
            })

        available.sort(key=lambda p: Decimal(p["estimated_total"]))

        self.log.info(
            "property_search",
            check_in=check_in.isoformat(),
            check_out=check_out.isoformat(),
            guests=guests,
            results=len(available),
        )
        return available
