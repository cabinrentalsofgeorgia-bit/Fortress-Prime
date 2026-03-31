"""
Reservation Engine - Full reservation lifecycle management
REPLACES: Streamline VRS reservation management

Handles the complete booking lifecycle:
- Reservation CRUD with conflict detection
- Availability and calendar queries
- Dynamic pricing for Blue Ridge GA cabin market
- Access code generation and validity windows
- Automatic status transitions (check-in / check-out)
- Occupancy reporting and full-text search
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import calendar
import random
import string

import structlog
from sqlalchemy import select, and_, or_, func
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.blocked_day import BlockedDay
from backend.models import Reservation, Guest, Property
from backend.models.reservation_hold import ReservationHold
from backend.core.time import combine_utc, utc_now

logger = structlog.get_logger()
OCCUPYING_AVAILABILITY_STATUSES = ("pending", "confirmed", "checked_in", "pending_payment")


def _missing_runtime_table(exc: ProgrammingError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "does not exist" in message or "undefinedtable" in message


class ReservationEngine:
    """
    Production-grade reservation management for Fortress Guest Platform.

    Instantiate with no arguments. Every public method is async and accepts
    an ``AsyncSession`` (``db``) so the caller controls the unit of work.

    Seasonal pricing is tuned for the **Blue Ridge, GA cabin market** where
    peak demand runs mid-June through October (leaves), with holiday spikes
    around Thanksgiving, Christmas / New Year, Memorial Day, and July 4th.
    """

    # ------------------------------------------------------------------
    # Seasonal pricing configuration — Blue Ridge GA cabins
    # ------------------------------------------------------------------
    # Multipliers applied on top of the property's base nightly rate.
    SEASON_MULTIPLIERS: Dict[str, Decimal] = {
        "peak_summer":   Decimal("1.35"),   # Jun 15 – Aug 15
        "peak_fall":     Decimal("1.50"),   # Oct 1 – Nov 15 (leaf season)
        "shoulder":      Decimal("1.15"),   # Mar 15 – Jun 14, Aug 16 – Sep 30
        "off_season":    Decimal("1.00"),   # Nov 16 – Mar 14
    }

    HOLIDAY_MULTIPLIERS: Dict[str, Decimal] = {
        "thanksgiving":     Decimal("1.60"),
        "christmas":        Decimal("1.75"),
        "new_year":         Decimal("1.70"),
        "memorial_day":     Decimal("1.40"),
        "july_4th":         Decimal("1.50"),
        "labor_day":        Decimal("1.40"),
        "mlk_day":          Decimal("1.20"),
        "presidents_day":   Decimal("1.20"),
    }

    # Length-of-stay discounts
    LOS_DISCOUNTS: List[Tuple[int, Decimal]] = [
        (28, Decimal("0.20")),   # 28+ nights → 20 % off
        (14, Decimal("0.12")),   # 14-27 nights → 12 % off
        (7,  Decimal("0.08")),   # 7-13 nights → 8 % off
    ]

    # Per-additional-guest fee (over base occupancy of 2)
    PER_EXTRA_GUEST_FEE = Decimal("25.00")
    BASE_OCCUPANCY = 2

    # Base nightly rate fallback when property has no stored rate
    DEFAULT_BASE_RATE = Decimal("199.00")

    # Minimum stay (nights)
    MIN_STAY = 2

    # Access code check-in / check-out buffer hours
    ACCESS_CODE_EARLY_HOURS = 2   # available 2 h before 3 PM check-in
    ACCESS_CODE_LATE_HOURS = 2    # valid 2 h after 11 AM check-out

    # Standard check-in / check-out times (Eastern)
    DEFAULT_CHECKIN_HOUR = 15     # 3 PM
    DEFAULT_CHECKOUT_HOUR = 11    # 11 AM

    # Confirmation-code prefix
    CONFIRMATION_PREFIX = "CRG"

    def __init__(self) -> None:
        self.log = logger.bind(service="reservation_engine")

    # ==================================================================
    # 1. CREATE RESERVATION
    # ==================================================================
    async def create_reservation(
        self,
        db: AsyncSession,
        data: Dict[str, Any],
    ) -> Reservation:
        """
        Create a new reservation with:
        - Confirmation code generation (CRG-XXXXX)
        - Availability conflict check
        - Access code pre-assignment
        - Total amount calculation when not provided

        ``data`` keys mirror the Reservation model columns. Required:
        ``guest_id``, ``property_id``, ``check_in_date``, ``check_out_date``,
        ``num_guests``.
        """
        self.log.info("create_reservation_start", property_id=str(data.get("property_id")))

        check_in = self._ensure_date(data["check_in_date"])
        check_out = self._ensure_date(data["check_out_date"])

        if check_out <= check_in:
            raise ValueError("check_out_date must be after check_in_date")

        nights = (check_out - check_in).days
        if nights < self.MIN_STAY:
            raise ValueError(f"Minimum stay is {self.MIN_STAY} nights")

        property_id = UUID(str(data["property_id"])) if not isinstance(data["property_id"], UUID) else data["property_id"]

        exclude_hold = data.get("exclude_hold_id")
        exclude_hold_uuid: Optional[UUID] = None
        if exclude_hold is not None:
            exclude_hold_uuid = UUID(str(exclude_hold)) if not isinstance(exclude_hold, UUID) else exclude_hold

        available = await self.get_availability(
            db,
            property_id,
            check_in,
            check_out,
            exclude_hold_id=exclude_hold_uuid,
        )
        if not available:
            raise ValueError("Property is not available for the requested dates")

        prop = await db.get(Property, property_id)
        if prop and data.get("num_guests", 1) > prop.max_guests:
            raise ValueError(f"Guest count exceeds property maximum of {prop.max_guests}")

        confirmation_code = await self.generate_confirmation_code(db)
        access_code = self._generate_access_code()

        access_valid_from = combine_utc(
            check_in, time(self.DEFAULT_CHECKIN_HOUR - self.ACCESS_CODE_EARLY_HOURS, 0)
        )
        access_valid_until = combine_utc(
            check_out, time(self.DEFAULT_CHECKOUT_HOUR + self.ACCESS_CODE_LATE_HOURS, 0)
        )

        total_amount = data.get("total_amount")
        if total_amount is None:
            pricing = await self.calculate_pricing(
                db,
                property_id,
                check_in,
                check_out,
                data.get("num_guests", 1),
            )
            total_amount = pricing["total"]

        reservation = Reservation(
            id=uuid4(),
            confirmation_code=confirmation_code,
            guest_id=UUID(str(data["guest_id"])) if not isinstance(data["guest_id"], UUID) else data["guest_id"],
            property_id=property_id,
            check_in_date=check_in,
            check_out_date=check_out,
            num_guests=data.get("num_guests", 1),
            num_adults=data.get("num_adults"),
            num_children=data.get("num_children"),
            status="confirmed",
            access_code=access_code,
            access_code_valid_from=access_valid_from,
            access_code_valid_until=access_valid_until,
            booking_source=data.get("booking_source", "direct"),
            total_amount=Decimal(str(total_amount)),
            currency=data.get("currency", "USD"),
            internal_notes=data.get("internal_notes"),
            streamline_reservation_id=data.get("streamline_reservation_id"),
        )

        db.add(reservation)
        await db.flush()

        self.log.info(
            "reservation_created",
            reservation_id=str(reservation.id),
            confirmation_code=confirmation_code,
            check_in=str(check_in),
            check_out=str(check_out),
        )
        return reservation

    # ==================================================================
    # 2. UPDATE RESERVATION
    # ==================================================================
    async def update_reservation(
        self,
        db: AsyncSession,
        reservation_id: UUID,
        data: Dict[str, Any],
    ) -> Reservation:
        """
        Update an existing reservation with date-conflict detection.

        Only non-cancelled/non-checked-out reservations may be modified.
        If dates change, availability is re-verified.
        """
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"Reservation {reservation_id} not found")

        if reservation.status in ("cancelled", "checked_out"):
            raise ValueError(f"Cannot modify reservation in '{reservation.status}' status")

        new_check_in = self._ensure_date(data["check_in_date"]) if "check_in_date" in data else None
        new_check_out = self._ensure_date(data["check_out_date"]) if "check_out_date" in data else None
        dates_changed = new_check_in or new_check_out

        effective_in = new_check_in or reservation.check_in_date
        effective_out = new_check_out or reservation.check_out_date

        if effective_out <= effective_in:
            raise ValueError("check_out_date must be after check_in_date")

        if dates_changed:
            available = await self.get_availability(
                db, reservation.property_id, effective_in, effective_out,
                exclude_reservation_id=reservation.id,
            )
            if not available:
                raise ValueError("Property is not available for the new dates")

            reservation.access_code_valid_from = combine_utc(
                effective_in, time(self.DEFAULT_CHECKIN_HOUR - self.ACCESS_CODE_EARLY_HOURS, 0)
            )
            reservation.access_code_valid_until = combine_utc(
                effective_out, time(self.DEFAULT_CHECKOUT_HOUR + self.ACCESS_CODE_LATE_HOURS, 0)
            )

        allowed_fields = {
            "check_in_date", "check_out_date", "num_guests", "num_adults",
            "num_children", "booking_source", "total_amount", "currency",
            "internal_notes", "guest_id", "property_id",
        }
        for field, value in data.items():
            if field in allowed_fields:
                if field in ("check_in_date", "check_out_date"):
                    value = self._ensure_date(value)
                if field == "total_amount" and value is not None:
                    value = Decimal(str(value))
                setattr(reservation, field, value)

        reservation.updated_at = utc_now()
        await db.flush()

        self.log.info(
            "reservation_updated",
            reservation_id=str(reservation_id),
            fields=list(data.keys()),
        )
        return reservation

    # ==================================================================
    # 3. CANCEL RESERVATION
    # ==================================================================
    async def cancel_reservation(
        self,
        db: AsyncSession,
        reservation_id: UUID,
        reason: Optional[str] = None,
    ) -> Reservation:
        """
        Cancel a reservation with audit trail.

        Cancellation policy (Blue Ridge standard):
        - 30+ days before check-in: full refund
        - 14-29 days: 50 % refund
        - <14 days: no refund

        Returns the updated reservation with cancellation notes.
        """
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"Reservation {reservation_id} not found")

        if reservation.status in ("cancelled", "checked_out"):
            raise ValueError(f"Reservation is already {reservation.status}")

        days_until = (reservation.check_in_date - date.today()).days

        if days_until >= 30:
            refund_pct = Decimal("1.00")
            policy = "full_refund"
        elif days_until >= 14:
            refund_pct = Decimal("0.50")
            policy = "partial_refund"
        else:
            refund_pct = Decimal("0.00")
            policy = "no_refund"

        refund_amount = (reservation.total_amount or Decimal("0")) * refund_pct

        cancel_note = (
            f"CANCELLED {utc_now().isoformat()} | "
            f"Policy: {policy} | Refund: ${refund_amount:.2f} | "
            f"Reason: {reason or 'Not specified'}"
        )

        reservation.status = "cancelled"
        reservation.internal_notes = (
            f"{reservation.internal_notes or ''}\n{cancel_note}".strip()
        )
        reservation.access_code = None
        reservation.access_code_valid_from = None
        reservation.access_code_valid_until = None
        reservation.updated_at = utc_now()

        await db.flush()

        self.log.info(
            "reservation_cancelled",
            reservation_id=str(reservation_id),
            policy=policy,
            refund_amount=str(refund_amount),
            days_until_checkin=days_until,
        )
        return reservation

    # ==================================================================
    # 4. CHECK-IN
    # ==================================================================
    async def check_in(
        self,
        db: AsyncSession,
        reservation_id: UUID,
    ) -> Reservation:
        """
        Transition reservation to ``checked_in``.

        - Activates the access code window (valid from now)
        - Sets ``access_info_sent`` for lifecycle-engine coordination
        """
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"Reservation {reservation_id} not found")

        if reservation.status != "confirmed":
            raise ValueError(
                f"Cannot check in — current status is '{reservation.status}', expected 'confirmed'"
            )

        now = utc_now()

        if not reservation.access_code:
            reservation.access_code = self._generate_access_code()

        reservation.access_code_valid_from = now
        reservation.access_code_valid_until = combine_utc(
            reservation.check_out_date,
            time(self.DEFAULT_CHECKOUT_HOUR + self.ACCESS_CODE_LATE_HOURS, 0),
        )

        reservation.status = "checked_in"
        reservation.access_info_sent = True
        reservation.updated_at = now

        await db.flush()

        self.log.info(
            "guest_checked_in",
            reservation_id=str(reservation_id),
            confirmation_code=reservation.confirmation_code,
            access_code_until=str(reservation.access_code_valid_until),
        )
        return reservation

    # ==================================================================
    # 5. CHECK-OUT
    # ==================================================================
    async def check_out(
        self,
        db: AsyncSession,
        reservation_id: UUID,
    ) -> Dict[str, Any]:
        """
        Transition reservation to ``checked_out``.

        - Invalidates access code
        - Marks post-stay follow-up ready
        - Returns a housekeeping trigger payload for downstream scheduling
        """
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"Reservation {reservation_id} not found")

        if reservation.status not in ("confirmed", "checked_in"):
            raise ValueError(
                f"Cannot check out — current status is '{reservation.status}'"
            )

        now = utc_now()

        reservation.status = "checked_out"
        reservation.access_code_valid_until = now
        reservation.checkout_reminder_sent = True
        reservation.updated_at = now

        guest = await db.get(Guest, reservation.guest_id)
        if guest:
            guest.total_stays = (guest.total_stays or 0) + 1
            guest.last_stay_date = date.today()

        await db.flush()

        housekeeping_payload = {
            "action": "schedule_housekeeping",
            "reservation_id": str(reservation.id),
            "property_id": str(reservation.property_id),
            "checkout_time": now.isoformat(),
            "confirmation_code": reservation.confirmation_code,
            "request_review": True,
        }

        self.log.info(
            "guest_checked_out",
            reservation_id=str(reservation_id),
            confirmation_code=reservation.confirmation_code,
        )
        return housekeeping_payload

    # ==================================================================
    # 6. AVAILABILITY CHECK
    # ==================================================================
    async def get_availability(
        self,
        db: AsyncSession,
        property_id: UUID,
        start_date: date,
        end_date: date,
        exclude_reservation_id: Optional[UUID] = None,
        exclude_hold_id: Optional[UUID] = None,
        include_active_holds: bool = True,
    ) -> bool:
        """
        Return True if the property has no overlapping blocked days, occupying
        reservations, and optionally no active non-expired checkout holds.
        """
        blocked_stmt = (
            select(func.count())
            .select_from(BlockedDay)
            .where(
                and_(
                    BlockedDay.property_id == property_id,
                    BlockedDay.start_date < end_date,
                    BlockedDay.end_date > start_date,
                )
            )
        )
        try:
            blocked_count = (await db.execute(blocked_stmt)).scalar_one()
        except ProgrammingError as exc:
            if not _missing_runtime_table(exc):
                raise
            logger.warning("reservation_engine_blocked_days_table_missing")
            await db.rollback()
            blocked_count = 0
        if int(blocked_count) > 0:
            return False

        stmt = (
            select(func.count())
            .select_from(Reservation)
            .where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(OCCUPYING_AVAILABILITY_STATUSES),
                    Reservation.check_in_date < end_date,
                    Reservation.check_out_date > start_date,
                )
            )
        )
        if exclude_reservation_id:
            stmt = stmt.where(Reservation.id != exclude_reservation_id)

        try:
            result = await db.execute(stmt)
            conflict_count = result.scalar_one()
        except ProgrammingError as exc:
            if not _missing_runtime_table(exc):
                raise
            logger.warning("reservation_engine_reservations_table_missing")
            await db.rollback()
            conflict_count = 0
        if int(conflict_count) > 0:
            return False

        if not include_active_holds:
            return True

        now = utc_now()
        hold_conds = [
            ReservationHold.property_id == property_id,
            ReservationHold.status == "active",
            ReservationHold.expires_at > now,
            ReservationHold.check_in_date < end_date,
            ReservationHold.check_out_date > start_date,
        ]
        hold_stmt = select(func.count()).select_from(ReservationHold).where(and_(*hold_conds))
        if exclude_hold_id is not None:
            hold_stmt = hold_stmt.where(ReservationHold.id != exclude_hold_id)
        try:
            hold_count = (await db.execute(hold_stmt)).scalar_one()
        except ProgrammingError as exc:
            if not _missing_runtime_table(exc):
                raise
            logger.warning("reservation_engine_reservation_holds_table_missing")
            await db.rollback()
            hold_count = 0
        return int(hold_count) == 0

    # ==================================================================
    # 7. CALENDAR
    # ==================================================================
    def _resolve_nightly_rate(
        self,
        stay_date: date,
        *,
        base_rate: Decimal,
    ) -> tuple[Decimal, str, Decimal]:
        holiday = self._get_holiday(stay_date)
        if holiday:
            multiplier = self.HOLIDAY_MULTIPLIERS[holiday]
            season_label = f"holiday_{holiday}"
        else:
            season_label = self._get_season(stay_date)
            multiplier = self.SEASON_MULTIPLIERS[season_label]

        nightly_rate = (base_rate * multiplier).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        return nightly_rate, season_label, multiplier

    async def get_blocked_dates_for_month(
        self,
        db: AsyncSession,
        property_id: UUID,
        month: int,
        year: int,
    ) -> Dict[str, Any]:
        """Return flat blocked-date telemetry for a monthly availability view."""
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        month_end_exclusive = last_day + timedelta(days=1)
        blocked_dates: set[date] = set()

        def add_range(start: date, end: date) -> None:
            cursor = max(start, first_day)
            stop = min(end, month_end_exclusive)
            while cursor < stop:
                blocked_dates.add(cursor)
                cursor += timedelta(days=1)

        blocked_rows = (
            await db.execute(
                select(BlockedDay.start_date, BlockedDay.end_date)
                .where(
                    and_(
                        BlockedDay.property_id == property_id,
                        BlockedDay.start_date < month_end_exclusive,
                        BlockedDay.end_date > first_day,
                    )
                )
            )
        ).all()
        for start_date, end_date in blocked_rows:
            add_range(start_date, end_date)

        reservation_rows = (
            await db.execute(
                select(Reservation.check_in_date, Reservation.check_out_date)
                .where(
                    and_(
                        Reservation.property_id == property_id,
                        Reservation.status.in_(OCCUPYING_AVAILABILITY_STATUSES),
                        Reservation.check_in_date < month_end_exclusive,
                        Reservation.check_out_date > first_day,
                    )
                )
            )
        ).all()
        for check_in_date, check_out_date in reservation_rows:
            add_range(check_in_date, check_out_date)

        active_hold_rows = (
            await db.execute(
                select(ReservationHold.check_in_date, ReservationHold.check_out_date)
                .where(
                    and_(
                        ReservationHold.property_id == property_id,
                        ReservationHold.status == "active",
                        ReservationHold.expires_at > utc_now(),
                        ReservationHold.check_in_date < month_end_exclusive,
                        ReservationHold.check_out_date > first_day,
                    )
                )
            )
        ).all()
        for check_in_date, check_out_date in active_hold_rows:
            add_range(check_in_date, check_out_date)

        blocked_dates_list = [value.isoformat() for value in sorted(blocked_dates)]
        return {
            "property_id": str(property_id),
            "month": month,
            "year": year,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "blocked_dates": blocked_dates_list,
            "blocked_dates_count": len(blocked_dates_list),
            "available_dates_count": max(0, last_day_num - len(blocked_dates_list)),
            "generated_at": utc_now().isoformat(),
        }

    async def get_calendar_v2(
        self,
        db: AsyncSession,
        property_id: UUID,
        month: int,
        year: int,
    ) -> Dict[str, Any]:
        """Return a local month grid with availability state and nightly rate hints."""
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        month_end_exclusive = last_day + timedelta(days=1)

        prop = await db.get(Property, property_id)
        base_rate = self.DEFAULT_BASE_RATE

        blocked_payload = await self.get_blocked_dates_for_month(
            db,
            property_id,
            month,
            year,
        )
        blocked_dates = set(blocked_payload["blocked_dates"])
        month_grid: Dict[str, Dict[str, Any]] = {}

        cursor = first_day
        while cursor <= last_day:
            iso = cursor.isoformat()
            is_blocked = iso in blocked_dates
            nightly_rate, season_label, multiplier = self._resolve_nightly_rate(
                cursor,
                base_rate=base_rate,
            )
            month_grid[iso] = {
                "date": iso,
                "status": "blocked" if is_blocked else "available",
                "available": not is_blocked,
                "nightly_rate": None if is_blocked else float(nightly_rate),
                "season": season_label,
                "multiplier": float(multiplier),
            }
            cursor += timedelta(days=1)

        return {
            **blocked_payload,
            "month_grid": month_grid,
            "pricing_source": "local_ledger",
            "availability_source": "local_blocked_days",
        }

    async def get_fleet_calendar_v2(
        self,
        db: AsyncSession,
        month: int,
        year: int,
    ) -> Dict[str, Any]:
        """Return a bulk month-grid response for the active portfolio."""
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        month_end_exclusive = last_day + timedelta(days=1)
        generated_at = utc_now().isoformat()

        properties = list(
            (
                await db.execute(
                    select(Property)
                    .where(Property.is_active.is_(True))
                    .order_by(Property.name.asc())
                )
            ).scalars().all()
        )
        if not properties:
            return {
                "month": month,
                "year": year,
                "start_date": first_day.isoformat(),
                "end_date": last_day.isoformat(),
                "generated_at": generated_at,
                "property_count": 0,
                "pricing_source": "local_ledger",
                "availability_source": "local_blocked_days",
                "properties": [],
            }

        property_ids = [prop.id for prop in properties]
        blocked_by_property: Dict[UUID, set[date]] = {prop.id: set() for prop in properties}

        def add_range(property_id: UUID, start: date, end: date) -> None:
            target = blocked_by_property.setdefault(property_id, set())
            cursor = max(start, first_day)
            stop = min(end, month_end_exclusive)
            while cursor < stop:
                target.add(cursor)
                cursor += timedelta(days=1)

        blocked_rows = (
            await db.execute(
                select(BlockedDay.property_id, BlockedDay.start_date, BlockedDay.end_date)
                .where(
                    and_(
                        BlockedDay.property_id.in_(property_ids),
                        BlockedDay.start_date < month_end_exclusive,
                        BlockedDay.end_date > first_day,
                    )
                )
            )
        ).all()
        for property_id, start_date, end_date in blocked_rows:
            add_range(property_id, start_date, end_date)

        reservation_rows = (
            await db.execute(
                select(Reservation.property_id, Reservation.check_in_date, Reservation.check_out_date)
                .where(
                    and_(
                        Reservation.property_id.in_(property_ids),
                        Reservation.status.in_(OCCUPYING_AVAILABILITY_STATUSES),
                        Reservation.check_in_date < month_end_exclusive,
                        Reservation.check_out_date > first_day,
                    )
                )
            )
        ).all()
        for property_id, check_in_date, check_out_date in reservation_rows:
            add_range(property_id, check_in_date, check_out_date)

        active_hold_rows = (
            await db.execute(
                select(ReservationHold.property_id, ReservationHold.check_in_date, ReservationHold.check_out_date)
                .where(
                    and_(
                        ReservationHold.property_id.in_(property_ids),
                        ReservationHold.status == "active",
                        ReservationHold.expires_at > utc_now(),
                        ReservationHold.check_in_date < month_end_exclusive,
                        ReservationHold.check_out_date > first_day,
                    )
                )
            )
        ).all()
        for property_id, check_in_date, check_out_date in active_hold_rows:
            add_range(property_id, check_in_date, check_out_date)

        fleet_rows: List[Dict[str, Any]] = []
        for prop in properties:
            blocked_dates = blocked_by_property.get(prop.id, set())
            month_grid: Dict[str, Dict[str, Any]] = {}
            available_days = 0
            blocked_days = 0
            average_accumulator = Decimal("0.00")

            cursor = first_day
            while cursor <= last_day:
                iso = cursor.isoformat()
                is_blocked = cursor in blocked_dates
                nightly_rate, season_label, multiplier = self._resolve_nightly_rate(
                    cursor,
                    base_rate=self.DEFAULT_BASE_RATE,
                )
                if is_blocked:
                    blocked_days += 1
                else:
                    available_days += 1
                    average_accumulator += nightly_rate
                month_grid[iso] = {
                    "date": iso,
                    "status": "blocked" if is_blocked else "available",
                    "available": not is_blocked,
                    "nightly_rate": None if is_blocked else float(nightly_rate),
                    "season": season_label,
                    "multiplier": float(multiplier),
                }
                cursor += timedelta(days=1)

            average_nightly_rate = (
                float((average_accumulator / available_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                if available_days > 0
                else 0.0
            )
            fleet_rows.append(
                {
                    "property_id": str(prop.id),
                    "property_name": prop.name,
                    "slug": prop.slug,
                    "property_type": prop.property_type,
                    "bedrooms": prop.bedrooms,
                    "bathrooms": float(prop.bathrooms) if prop.bathrooms is not None else None,
                    "max_guests": prop.max_guests,
                    "address": prop.address,
                    "month_grid": month_grid,
                    "summary": {
                        "available_days": available_days,
                        "blocked_days": blocked_days,
                        "average_nightly_rate": average_nightly_rate,
                    },
                }
            )

        return {
            "month": month,
            "year": year,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "generated_at": generated_at,
            "property_count": len(fleet_rows),
            "pricing_source": "local_ledger",
            "availability_source": "local_blocked_days",
            "properties": fleet_rows,
        }

    async def get_calendar(
        self,
        db: AsyncSession,
        property_id: UUID,
        month: int,
        year: int,
    ) -> Dict[str, Any]:
        """
        Build a full monthly calendar for a property showing nightly status.

        Returns::

            {
              "property_id": "...",
              "month": 10, "year": 2026,
              "days": {
                "2026-10-01": {"status": "available"},
                "2026-10-02": {"status": "booked", "reservation_id": "...", "confirmation_code": "..."},
                ...
              }
            }
        """
        first_day = date(year, month, 1)
        _, last_day_num = calendar.monthrange(year, month)
        last_day = date(year, month, last_day_num)

        stmt = (
            select(Reservation)
            .where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date <= last_day,
                    Reservation.check_out_date >= first_day,
                )
            )
            .order_by(Reservation.check_in_date)
        )
        result = await db.execute(stmt)
        reservations = result.scalars().all()

        booked_map: Dict[date, Reservation] = {}
        for res in reservations:
            cursor = max(res.check_in_date, first_day)
            end = min(res.check_out_date, last_day + timedelta(days=1))
            while cursor < end:
                booked_map[cursor] = res
                cursor += timedelta(days=1)

        days: Dict[str, Dict[str, Any]] = {}
        cursor = first_day
        while cursor <= last_day:
            iso = cursor.isoformat()
            if cursor in booked_map:
                res = booked_map[cursor]
                days[iso] = {
                    "status": "booked",
                    "reservation_id": str(res.id),
                    "confirmation_code": res.confirmation_code,
                    "guest_id": str(res.guest_id),
                    "is_checkin": cursor == res.check_in_date,
                    "is_checkout": cursor == res.check_out_date,
                }
            else:
                days[iso] = {"status": "available"}
            cursor += timedelta(days=1)

        return {
            "property_id": str(property_id),
            "month": month,
            "year": year,
            "days": days,
        }

    # ==================================================================
    # 8. ACCESS CODE ASSIGNMENT
    # ==================================================================
    async def auto_assign_access_codes(
        self,
        db: AsyncSession,
        reservation_id: UUID,
    ) -> Dict[str, Any]:
        """
        Generate a random 4-digit access code and set validity to the stay window.
        """
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"Reservation {reservation_id} not found")

        code = self._generate_access_code()

        reservation.access_code = code
        reservation.access_code_valid_from = combine_utc(
            reservation.check_in_date,
            time(self.DEFAULT_CHECKIN_HOUR - self.ACCESS_CODE_EARLY_HOURS, 0),
        )
        reservation.access_code_valid_until = combine_utc(
            reservation.check_out_date,
            time(self.DEFAULT_CHECKOUT_HOUR + self.ACCESS_CODE_LATE_HOURS, 0),
        )
        reservation.updated_at = utc_now()
        await db.flush()

        self.log.info(
            "access_code_assigned",
            reservation_id=str(reservation_id),
            valid_from=str(reservation.access_code_valid_from),
            valid_until=str(reservation.access_code_valid_until),
        )
        return {
            "reservation_id": str(reservation_id),
            "access_code": code,
            "valid_from": reservation.access_code_valid_from.isoformat(),
            "valid_until": reservation.access_code_valid_until.isoformat(),
        }

    # ==================================================================
    # 9. DYNAMIC PRICING
    # ==================================================================
    async def calculate_pricing(
        self,
        db: AsyncSession,
        property_id: UUID,
        check_in: date,
        check_out: date,
        guests: int = 2,
    ) -> Dict[str, Any]:
        """
        Dynamic nightly pricing with seasonal multipliers, holiday surcharges,
        length-of-stay discounts, and per-extra-guest fees.

        Returns a detailed breakdown::

            {
              "nights": 5,
              "nightly_breakdown": [{"date": "...", "rate": 249.00, "season": "peak_fall"}, ...],
              "subtotal": Decimal,
              "los_discount": Decimal,
              "extra_guest_fee": Decimal,
              "total": Decimal,
            }
        """
        check_in = self._ensure_date(check_in)
        check_out = self._ensure_date(check_out)

        prop = await db.get(Property, property_id)
        base_rate = self.DEFAULT_BASE_RATE

        nights = (check_out - check_in).days
        if nights <= 0:
            raise ValueError("check_out must be after check_in")

        nightly_breakdown: List[Dict[str, Any]] = []
        subtotal = Decimal("0.00")

        cursor = check_in
        while cursor < check_out:
            nightly_rate, season_label, multiplier = self._resolve_nightly_rate(
                cursor,
                base_rate=base_rate,
            )
            nightly_breakdown.append({
                "date": cursor.isoformat(),
                "rate": float(nightly_rate),
                "season": season_label,
                "multiplier": float(multiplier),
            })
            subtotal += nightly_rate
            cursor += timedelta(days=1)

        los_discount = Decimal("0.00")
        for min_nights, discount_pct in self.LOS_DISCOUNTS:
            if nights >= min_nights:
                los_discount = (subtotal * discount_pct).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                break

        extra_guests = max(0, guests - self.BASE_OCCUPANCY)
        extra_guest_fee = (
            self.PER_EXTRA_GUEST_FEE * extra_guests * nights
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total = (subtotal - los_discount + extra_guest_fee).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return {
            "property_id": str(property_id),
            "nights": nights,
            "base_rate": float(base_rate),
            "nightly_breakdown": nightly_breakdown,
            "subtotal": total_as_decimal(subtotal),
            "los_discount": total_as_decimal(los_discount),
            "los_discount_nights_threshold": next(
                (n for n, _ in self.LOS_DISCOUNTS if nights >= n), None
            ),
            "extra_guest_fee": total_as_decimal(extra_guest_fee),
            "extra_guests": extra_guests,
            "total": total_as_decimal(total),
        }

    # ==================================================================
    # 10. CONFIRMATION CODE GENERATION
    # ==================================================================
    async def generate_confirmation_code(self, db: AsyncSession) -> str:
        """
        Generate a unique confirmation code in ``CRG-XXXXX`` format.

        Retries up to 10 times to guarantee uniqueness against the database.
        """
        for _ in range(10):
            suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
            code = f"{self.CONFIRMATION_PREFIX}-{suffix}"

            exists = await db.execute(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.confirmation_code == code)
            )
            if exists.scalar_one() == 0:
                return code

        raise RuntimeError("Failed to generate a unique confirmation code after 10 attempts")

    # ==================================================================
    # 11. UPCOMING ARRIVALS
    # ==================================================================
    async def get_upcoming_arrivals(
        self,
        db: AsyncSession,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        All confirmed reservations arriving within the next ``days`` days.
        """
        today = date.today()
        end = today + timedelta(days=days)

        stmt = (
            select(Reservation)
            .where(
                and_(
                    Reservation.status == "confirmed",
                    Reservation.check_in_date >= today,
                    Reservation.check_in_date <= end,
                )
            )
            .order_by(Reservation.check_in_date)
        )
        result = await db.execute(stmt)
        reservations = result.scalars().all()

        arrivals: List[Dict[str, Any]] = []
        for res in reservations:
            guest = await db.get(Guest, res.guest_id)
            prop = await db.get(Property, res.property_id)
            arrivals.append({
                "reservation_id": str(res.id),
                "confirmation_code": res.confirmation_code,
                "guest_name": guest.full_name if guest else "Unknown",
                "guest_phone": guest.phone_number if guest else None,
                "property_name": prop.name if prop else "Unknown",
                "check_in_date": res.check_in_date.isoformat(),
                "check_out_date": res.check_out_date.isoformat(),
                "nights": (res.check_out_date - res.check_in_date).days,
                "num_guests": res.num_guests,
                "access_code": res.access_code,
                "booking_source": res.booking_source,
                "days_until_arrival": (res.check_in_date - today).days,
            })

        self.log.info("upcoming_arrivals", count=len(arrivals), window_days=days)
        return arrivals

    # ==================================================================
    # 12. UPCOMING DEPARTURES
    # ==================================================================
    async def get_upcoming_departures(
        self,
        db: AsyncSession,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        All confirmed/checked-in reservations departing within the next ``days`` days.
        """
        today = date.today()
        end = today + timedelta(days=days)

        stmt = (
            select(Reservation)
            .where(
                and_(
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_out_date >= today,
                    Reservation.check_out_date <= end,
                )
            )
            .order_by(Reservation.check_out_date)
        )
        result = await db.execute(stmt)
        reservations = result.scalars().all()

        departures: List[Dict[str, Any]] = []
        for res in reservations:
            guest = await db.get(Guest, res.guest_id)
            prop = await db.get(Property, res.property_id)
            departures.append({
                "reservation_id": str(res.id),
                "confirmation_code": res.confirmation_code,
                "guest_name": guest.full_name if guest else "Unknown",
                "guest_phone": guest.phone_number if guest else None,
                "property_name": prop.name if prop else "Unknown",
                "check_in_date": res.check_in_date.isoformat(),
                "check_out_date": res.check_out_date.isoformat(),
                "nights": (res.check_out_date - res.check_in_date).days,
                "num_guests": res.num_guests,
                "booking_source": res.booking_source,
                "days_until_departure": (res.check_out_date - today).days,
                "needs_review_request": not res.post_stay_followup_sent,
            })

        self.log.info("upcoming_departures", count=len(departures), window_days=days)
        return departures

    # ==================================================================
    # 13. AUTO STATUS UPDATE (background task)
    # ==================================================================
    async def auto_status_update(self, db: AsyncSession) -> Dict[str, int]:
        """
        Background task intended to run on a schedule (e.g. every 15 min).

        - Auto check-in: reservations whose check-in date is today or past and
          still ``confirmed`` → ``checked_in``
        - Auto check-out: reservations whose check-out date is today or past
          and still ``checked_in`` → ``checked_out``
        - No-show detection: reservations where check-in date passed by 1+ day
          and status is still ``confirmed``

        Returns counts of each transition performed.
        """
        today = date.today()
        now = utc_now()
        counts = {"auto_checkin": 0, "auto_checkout": 0, "no_show": 0}

        # --- auto check-in ---
        stmt = select(Reservation).where(
            and_(
                Reservation.status == "confirmed",
                Reservation.check_in_date <= today,
                Reservation.check_out_date > today,
            )
        )
        result = await db.execute(stmt)
        for res in result.scalars().all():
            res.status = "checked_in"
            if not res.access_code:
                res.access_code = self._generate_access_code()
            res.access_code_valid_from = now
            res.access_code_valid_until = combine_utc(
                res.check_out_date,
                time(self.DEFAULT_CHECKOUT_HOUR + self.ACCESS_CODE_LATE_HOURS, 0),
            )
            res.updated_at = now
            counts["auto_checkin"] += 1

        # --- auto check-out ---
        stmt = select(Reservation).where(
            and_(
                Reservation.status == "checked_in",
                Reservation.check_out_date <= today,
            )
        )
        result = await db.execute(stmt)
        for res in result.scalars().all():
            res.status = "checked_out"
            res.access_code_valid_until = now
            res.updated_at = now
            guest = await db.get(Guest, res.guest_id)
            if guest:
                guest.total_stays = (guest.total_stays or 0) + 1
                guest.last_stay_date = today
            counts["auto_checkout"] += 1

        # --- no-show detection ---
        yesterday = today - timedelta(days=1)
        stmt = select(Reservation).where(
            and_(
                Reservation.status == "confirmed",
                Reservation.check_in_date <= yesterday,
                Reservation.check_out_date <= today,
            )
        )
        result = await db.execute(stmt)
        for res in result.scalars().all():
            res.status = "no_show"
            res.access_code = None
            res.access_code_valid_from = None
            res.access_code_valid_until = None
            res.internal_notes = (
                f"{res.internal_notes or ''}\nNO-SHOW detected {now.isoformat()}"
            ).strip()
            res.updated_at = now
            counts["no_show"] += 1

        await db.flush()

        self.log.info("auto_status_update_complete", **counts)
        return counts

    # ==================================================================
    # 14. OCCUPANCY REPORT
    # ==================================================================
    async def get_occupancy_report(
        self,
        db: AsyncSession,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """
        Occupancy rate per property for an arbitrary date range.

        Returns a list of property summaries including booked nights,
        total nights in the window, occupancy percentage, and revenue.
        """
        start_date = self._ensure_date(start_date)
        end_date = self._ensure_date(end_date)
        total_nights = (end_date - start_date).days
        if total_nights <= 0:
            raise ValueError("end_date must be after start_date")

        props_result = await db.execute(
            select(Property).where(Property.is_active == True).order_by(Property.name)
        )
        properties = props_result.scalars().all()

        report: List[Dict[str, Any]] = []

        for prop in properties:
            stmt = (
                select(Reservation)
                .where(
                    and_(
                        Reservation.property_id == prop.id,
                        Reservation.status.in_(["confirmed", "checked_in", "checked_out"]),
                        Reservation.check_in_date < end_date,
                        Reservation.check_out_date > start_date,
                    )
                )
            )
            result = await db.execute(stmt)
            reservations = result.scalars().all()

            booked_nights = 0
            total_revenue = Decimal("0.00")

            for res in reservations:
                overlap_start = max(res.check_in_date, start_date)
                overlap_end = min(res.check_out_date, end_date)
                overlap_nights = (overlap_end - overlap_start).days
                if overlap_nights > 0:
                    booked_nights += overlap_nights
                    if res.total_amount:
                        res_nights = (res.check_out_date - res.check_in_date).days or 1
                        nightly = res.total_amount / res_nights
                        total_revenue += nightly * overlap_nights

            occupancy_pct = round((booked_nights / total_nights) * 100, 1) if total_nights else 0

            report.append({
                "property_id": str(prop.id),
                "property_name": prop.name,
                "total_nights": total_nights,
                "booked_nights": booked_nights,
                "available_nights": total_nights - booked_nights,
                "occupancy_pct": occupancy_pct,
                "revenue": float(total_revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "avg_nightly_rate": float(
                    (total_revenue / booked_nights).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ) if booked_nights else 0.0,
            })

        self.log.info(
            "occupancy_report",
            start=str(start_date),
            end=str(end_date),
            properties=len(report),
        )
        return report

    # ==================================================================
    # 15. SEARCH RESERVATIONS
    # ==================================================================
    async def search_reservations(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search across confirmation code, guest name, property name,
        booking source, and internal notes.
        """
        if not query or not query.strip():
            return []

        pattern = f"%{query.strip()}%"

        stmt = (
            select(Reservation, Guest, Property)
            .outerjoin(Guest, Reservation.guest_id == Guest.id)
            .outerjoin(Property, Reservation.property_id == Property.id)
            .where(
                or_(
                    Reservation.confirmation_code.ilike(pattern),
                    Reservation.booking_source.ilike(pattern),
                    Reservation.internal_notes.ilike(pattern),
                    Reservation.streamline_reservation_id.ilike(pattern),
                    Guest.first_name.ilike(pattern),
                    Guest.last_name.ilike(pattern),
                    Guest.email.ilike(pattern),
                    Guest.phone_number.ilike(pattern),
                    Property.name.ilike(pattern),
                )
            )
            .order_by(Reservation.check_in_date.desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        rows = result.all()

        results: List[Dict[str, Any]] = []
        for res, guest, prop in rows:
            results.append({
                "reservation_id": str(res.id),
                "confirmation_code": res.confirmation_code,
                "status": res.status,
                "guest_name": guest.full_name if guest else "Unknown",
                "guest_phone": guest.phone_number if guest else None,
                "guest_email": guest.email if guest else None,
                "property_name": prop.name if prop else "Unknown",
                "check_in_date": res.check_in_date.isoformat(),
                "check_out_date": res.check_out_date.isoformat(),
                "nights": (res.check_out_date - res.check_in_date).days,
                "num_guests": res.num_guests,
                "total_amount": float(res.total_amount) if res.total_amount else None,
                "booking_source": res.booking_source,
                "created_at": res.created_at.isoformat() if res.created_at else None,
            })

        self.log.info("search_reservations", query=query, results=len(results))
        return results

    # ==================================================================
    # PRIVATE HELPERS
    # ==================================================================

    @staticmethod
    def _generate_access_code() -> str:
        """Random 4-digit numeric access code (avoids leading zero)."""
        return str(random.randint(1000, 9999))

    @staticmethod
    def _ensure_date(value: Any) -> date:
        """Coerce a string or datetime to a ``date`` object."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse date: {value}")
        raise TypeError(f"Expected date, got {type(value)}")

    def _get_season(self, d: date) -> str:
        """Determine the pricing season for a given date (Blue Ridge GA)."""
        md = (d.month, d.day)

        if (6, 15) <= md <= (8, 15):
            return "peak_summer"
        if (10, 1) <= md <= (11, 15):
            return "peak_fall"
        if (3, 15) <= md <= (6, 14) or (8, 16) <= md <= (9, 30):
            return "shoulder"
        return "off_season"

    def _resolve_nightly_rate(
        self,
        d: date,
        *,
        base_rate: Decimal | None = None,
    ) -> tuple[Decimal, str, Decimal]:
        """
        Backward-compatible nightly rate helper for cache/export callers.

        Returns ``(nightly_rate, season_label, multiplier)`` using the same
        holiday/season logic as ``calculate_pricing()``.
        """
        resolved_base_rate = (base_rate or self.DEFAULT_BASE_RATE).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        holiday = self._get_holiday(d)
        if holiday:
            multiplier = self.HOLIDAY_MULTIPLIERS[holiday]
            season_label = f"holiday_{holiday}"
        else:
            season_label = self._get_season(d)
            multiplier = self.SEASON_MULTIPLIERS[season_label]

        nightly_rate = (resolved_base_rate * multiplier).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        return nightly_rate, season_label, multiplier

    def _get_holiday(self, d: date) -> Optional[str]:
        """
        Check if a date falls within a holiday surcharge window.
        Returns the holiday key or None.
        """
        year = d.year

        # Thanksgiving: 4th Thursday of November ± 2 days
        nov_first = date(year, 11, 1)
        thanksgiving = nov_first + timedelta(
            days=(3 - nov_first.weekday()) % 7 + 21
        )
        if thanksgiving - timedelta(days=2) <= d <= thanksgiving + timedelta(days=2):
            return "thanksgiving"

        # Christmas: Dec 22 – Dec 26
        if date(year, 12, 22) <= d <= date(year, 12, 26):
            return "christmas"

        # New Year: Dec 29 – Jan 2
        if d >= date(year, 12, 29) or d <= date(year, 1, 2):
            return "new_year"

        # Memorial Day: last Monday of May ± 2 days
        may_last = date(year, 5, 31)
        memorial = may_last - timedelta(days=(may_last.weekday()) % 7)
        if memorial - timedelta(days=2) <= d <= memorial + timedelta(days=1):
            return "memorial_day"

        # July 4th: Jul 2 – Jul 5
        if date(year, 7, 2) <= d <= date(year, 7, 5):
            return "july_4th"

        # Labor Day: 1st Monday of September ± 2 days
        sep_first = date(year, 9, 1)
        labor = sep_first + timedelta(days=(7 - sep_first.weekday()) % 7)
        if labor - timedelta(days=2) <= d <= labor + timedelta(days=1):
            return "labor_day"

        # MLK Day: 3rd Monday of January
        jan_first = date(year, 1, 1)
        mlk = jan_first + timedelta(days=(7 - jan_first.weekday()) % 7 + 14)
        if mlk - timedelta(days=1) <= d <= mlk + timedelta(days=1):
            return "mlk_day"

        # Presidents Day: 3rd Monday of February
        feb_first = date(year, 2, 1)
        presidents = feb_first + timedelta(days=(7 - feb_first.weekday()) % 7 + 14)
        if presidents - timedelta(days=1) <= d <= presidents + timedelta(days=1):
            return "presidents_day"

        return None


def total_as_decimal(value: Decimal) -> float:
    """Convenience: Decimal → float for JSON-safe output."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
