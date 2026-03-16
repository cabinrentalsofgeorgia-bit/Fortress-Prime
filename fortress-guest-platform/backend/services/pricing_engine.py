"""
Dynamic Pricing Engine — Fortress Guest Platform
Enterprise-grade rate management for Blue Ridge, GA cabin rentals.

Handles seasonal multipliers, length-of-stay discounts, demand-based pricing,
extra-guest fees, revenue forecasting, and market comparison.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Property, Reservation

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants — Blue Ridge GA cabin market
# ---------------------------------------------------------------------------

# Base nightly rate by bedroom count
BASE_RATES: Dict[int, Decimal] = {
    1: Decimal("150"),
    2: Decimal("200"),
    3: Decimal("275"),
    4: Decimal("350"),
    5: Decimal("450"),
    6: Decimal("550"),
}
_DEFAULT_LARGE_CABIN_RATE = Decimal("650")  # 7+ bedrooms

# Extra-guest fee (per night, over base occupancy of 2 per bedroom)
EXTRA_GUEST_FEE = Decimal("25")

# Seasonal multipliers
PEAK_MULTIPLIER = Decimal("1.4")       # June–Aug, October
HOLIDAY_MULTIPLIER = Decimal("1.6")    # Major holidays
SHOULDER_MULTIPLIER = Decimal("1.0")   # Mar–May, Sep, Nov non-holiday
OFF_PEAK_MULTIPLIER = Decimal("0.8")   # Jan–Feb

# Length-of-stay discount tiers (min_nights, discount_pct)
LOS_DISCOUNTS: List[Tuple[int, Decimal]] = [
    (28, Decimal("0.25")),   # monthly
    (14, Decimal("0.15")),   # bi-weekly
    (7,  Decimal("0.10")),   # weekly
    (3,  Decimal("0.05")),   # short stay
]

# Fixed holiday dates (month, day) — year-agnostic
_FIXED_HOLIDAYS = {
    (1, 1),    # New Year's Day
    (7, 4),    # Independence Day
    (12, 25),  # Christmas Day
    (12, 31),  # New Year's Eve
}

# Holiday windows that include surrounding days
_HOLIDAY_WINDOWS = [
    # Thanksgiving — 4th Thursday of November ± 3 days (handled dynamically)
    # Christmas week
    ((12, 20), (12, 31)),
]

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thanksgiving(year: int) -> date:
    """Return the date of Thanksgiving (4th Thursday of November)."""
    nov1 = date(year, 11, 1)
    # weekday(): Monday=0 … Sunday=6; Thursday=3
    offset = (3 - nov1.weekday()) % 7
    first_thursday = nov1 + timedelta(days=offset)
    return first_thursday + timedelta(weeks=3)


def _memorial_day(year: int) -> date:
    """Last Monday of May."""
    may31 = date(year, 5, 31)
    offset = (may31.weekday() - 0) % 7  # Monday=0
    return may31 - timedelta(days=offset)


def _labor_day(year: int) -> date:
    """First Monday of September."""
    sep1 = date(year, 9, 1)
    offset = (0 - sep1.weekday()) % 7
    return sep1 + timedelta(days=offset)


def _is_holiday(target: date) -> bool:
    """Check if a date falls within a major holiday window."""
    md = (target.month, target.day)
    if md in _FIXED_HOLIDAYS:
        return True

    # Christmas / NYE window
    for (sm, sd), (em, ed) in _HOLIDAY_WINDOWS:
        start = date(target.year, sm, sd)
        end = date(target.year, em, ed)
        if start <= target <= end:
            return True

    # Thanksgiving window (Wed before through Sunday after)
    tg = _thanksgiving(target.year)
    if tg - timedelta(days=1) <= target <= tg + timedelta(days=3):
        return True

    # Memorial Day weekend (Sat–Mon)
    md_day = _memorial_day(target.year)
    if md_day - timedelta(days=2) <= target <= md_day:
        return True

    # Labor Day weekend (Sat–Mon)
    ld_day = _labor_day(target.year)
    if ld_day - timedelta(days=2) <= target <= ld_day:
        return True

    # July 4th window
    jul4 = date(target.year, 7, 4)
    if jul4 - timedelta(days=2) <= target <= jul4 + timedelta(days=2):
        return True

    return False


# ---------------------------------------------------------------------------
# Pricing Engine
# ---------------------------------------------------------------------------

class PricingEngine:
    """
    Dynamic pricing for the Blue Ridge GA cabin portfolio.

    Composes seasonal multipliers, demand signals, length-of-stay discounts,
    and extra-guest fees into a single nightly or per-stay price.
    """

    def __init__(self):
        self.log = logger.bind(service="pricing_engine")

    # ------------------------------------------------------------------
    # 1. Full stay price calculation
    # ------------------------------------------------------------------
    async def calculate_stay_price(
        self,
        property_id,
        check_in: date,
        check_out: date,
        num_guests: int,
        db: AsyncSession,
    ) -> Dict:
        """Compute the total price for a reservation."""

        prop = await db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        nights = (check_out - check_in).days
        if nights <= 0:
            raise ValueError("check_out must be after check_in")

        base_rate = self._base_rate(prop.bedrooms)
        base_occupancy = prop.bedrooms * 2
        extra_guests = max(0, num_guests - base_occupancy)

        los_discount = self.get_length_of_stay_discount(nights)

        nightly_details: List[Dict] = []
        subtotal = Decimal("0")

        current = check_in
        for _ in range(nights):
            seasonal = self.get_seasonal_multiplier(current)
            demand = await self.get_demand_multiplier(property_id, current, db)
            nightly = (base_rate * seasonal * demand).quantize(TWO_PLACES, ROUND_HALF_UP)

            extra_fee = EXTRA_GUEST_FEE * extra_guests
            total_nightly = nightly + extra_fee

            nightly_details.append({
                "date": current.isoformat(),
                "base_rate": float(base_rate),
                "seasonal_multiplier": float(seasonal),
                "demand_multiplier": float(demand),
                "nightly_rate": float(nightly),
                "extra_guest_fee": float(extra_fee),
                "total": float(total_nightly),
            })
            subtotal += total_nightly
            current += timedelta(days=1)

        discount_amount = (subtotal * los_discount).quantize(TWO_PLACES, ROUND_HALF_UP)
        total = subtotal - discount_amount

        self.log.info(
            "stay_price_calculated",
            property=prop.name,
            nights=nights,
            total=float(total),
        )

        return {
            "property_id": str(property_id),
            "property_name": prop.name,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "nights": nights,
            "num_guests": num_guests,
            "base_occupancy": base_occupancy,
            "extra_guests": extra_guests,
            "subtotal": float(subtotal),
            "los_discount_pct": float(los_discount * 100),
            "los_discount_amount": float(discount_amount),
            "total": float(total),
            "average_nightly": float((total / nights).quantize(TWO_PLACES, ROUND_HALF_UP)),
            "nightly_breakdown": nightly_details,
        }

    # ------------------------------------------------------------------
    # 2. Single-night rate
    # ------------------------------------------------------------------
    async def get_nightly_rate(
        self, property_id, target_date: date, db: AsyncSession
    ) -> Dict:
        """Get the fully-adjusted nightly rate for a specific date."""

        prop = await db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        base = self._base_rate(prop.bedrooms)
        seasonal = self.get_seasonal_multiplier(target_date)
        demand = await self.get_demand_multiplier(property_id, target_date, db)
        rate = (base * seasonal * demand).quantize(TWO_PLACES, ROUND_HALF_UP)

        return {
            "property_id": str(property_id),
            "date": target_date.isoformat(),
            "base_rate": float(base),
            "seasonal_multiplier": float(seasonal),
            "demand_multiplier": float(demand),
            "nightly_rate": float(rate),
            "season": self._season_label(target_date),
        }

    # ------------------------------------------------------------------
    # 3. Seasonal multiplier
    # ------------------------------------------------------------------
    @staticmethod
    def get_seasonal_multiplier(target_date: date) -> Decimal:
        """Return the seasonal pricing multiplier for a given date."""

        if _is_holiday(target_date):
            return HOLIDAY_MULTIPLIER

        month = target_date.month

        # Peak: June–August, October (fall foliage)
        if month in (6, 7, 8, 10):
            return PEAK_MULTIPLIER

        # Off-peak: January–February
        if month in (1, 2):
            return OFF_PEAK_MULTIPLIER

        # Shoulder: everything else (Mar–May, Sep, Nov, Dec non-holiday)
        return SHOULDER_MULTIPLIER

    # ------------------------------------------------------------------
    # 4. Length-of-stay discount
    # ------------------------------------------------------------------
    @staticmethod
    def get_length_of_stay_discount(nights: int) -> Decimal:
        """Return the discount percentage (as a Decimal fraction) for the stay length."""
        for min_nights, discount in LOS_DISCOUNTS:
            if nights >= min_nights:
                return discount
        return Decimal("0")

    # ------------------------------------------------------------------
    # 5. Demand multiplier
    # ------------------------------------------------------------------
    async def get_demand_multiplier(
        self, property_id, target_date: date, db: AsyncSession
    ) -> Decimal:
        """
        Calculate a demand-based multiplier by checking occupancy in a ±3-day
        window across the entire portfolio.
        """
        window_start = target_date - timedelta(days=3)
        window_end = target_date + timedelta(days=3)

        total_props = await db.execute(
            select(func.count(Property.id)).where(Property.is_active.is_(True))
        )
        total = total_props.scalar() or 14

        booked = await db.execute(
            select(func.count(func.distinct(Reservation.property_id))).where(
                and_(
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date <= window_end,
                    Reservation.check_out_date >= window_start,
                )
            )
        )
        occupied = booked.scalar() or 0
        occupancy_rate = occupied / total if total else 0

        # Scale: 0% occupancy → 0.95x,  100% occupancy → 1.20x
        multiplier = Decimal("0.95") + Decimal(str(round(occupancy_rate * 0.25, 4)))
        return multiplier.quantize(Decimal("0.01"), ROUND_HALF_UP)

    # ------------------------------------------------------------------
    # 6. Rate calendar
    # ------------------------------------------------------------------
    async def generate_rate_calendar(
        self,
        property_id,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> List[Dict]:
        """Produce a list of daily rate records for a date range."""

        if end_date <= start_date:
            raise ValueError("end_date must be after start_date")

        prop = await db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        base = self._base_rate(prop.bedrooms)
        calendar: List[Dict] = []
        current = start_date

        while current <= end_date:
            seasonal = self.get_seasonal_multiplier(current)
            demand = await self.get_demand_multiplier(property_id, current, db)
            rate = (base * seasonal * demand).quantize(TWO_PLACES, ROUND_HALF_UP)

            # Check if the property is booked this night
            booked_result = await db.execute(
                select(func.count(Reservation.id)).where(
                    and_(
                        Reservation.property_id == property_id,
                        Reservation.status.in_(["confirmed", "checked_in"]),
                        Reservation.check_in_date <= current,
                        Reservation.check_out_date > current,
                    )
                )
            )
            is_booked = (booked_result.scalar() or 0) > 0

            calendar.append({
                "date": current.isoformat(),
                "day_of_week": current.strftime("%A"),
                "nightly_rate": float(rate),
                "seasonal_multiplier": float(seasonal),
                "demand_multiplier": float(demand),
                "season": self._season_label(current),
                "is_booked": is_booked,
                "available": not is_booked,
            })
            current += timedelta(days=1)

        return calendar

    # ------------------------------------------------------------------
    # 7. AI-style rate suggestion
    # ------------------------------------------------------------------
    async def suggest_rate_adjustment(self, property_id, db: AsyncSession) -> Dict:
        """
        Suggest a rate adjustment based on upcoming occupancy and booking
        velocity. Returns human-readable advice.
        """
        prop = await db.get(Property, property_id)
        if not prop:
            raise ValueError(f"Property {property_id} not found")

        today = date.today()
        horizon = today + timedelta(days=30)

        # Count booked nights in the next 30 days
        res_result = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.property_id == property_id,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date <= horizon,
                    Reservation.check_out_date >= today,
                )
            )
        )
        reservations = res_result.scalars().all()

        booked_nights = 0
        for r in reservations:
            eff_start = max(r.check_in_date, today)
            eff_end = min(r.check_out_date, horizon)
            booked_nights += (eff_end - eff_start).days

        total_nights = (horizon - today).days
        occupancy_pct = round(booked_nights / total_nights * 100, 1) if total_nights else 0

        base = self._base_rate(prop.bedrooms)
        current_seasonal = self.get_seasonal_multiplier(today)

        if occupancy_pct >= 85:
            suggestion = "increase"
            adjustment_pct = Decimal("10")
            reason = (
                f"Occupancy at {occupancy_pct}% for the next 30 days — strong demand. "
                "Consider raising rates to maximise revenue."
            )
        elif occupancy_pct >= 60:
            suggestion = "maintain"
            adjustment_pct = Decimal("0")
            reason = (
                f"Occupancy at {occupancy_pct}% — healthy range. "
                "Current pricing is well-positioned."
            )
        elif occupancy_pct >= 35:
            suggestion = "decrease"
            adjustment_pct = Decimal("-5")
            reason = (
                f"Occupancy at {occupancy_pct}% — below target. "
                "A modest discount could stimulate bookings."
            )
        else:
            suggestion = "decrease"
            adjustment_pct = Decimal("-15")
            reason = (
                f"Occupancy at {occupancy_pct}% — significantly low. "
                "Recommend a promotional rate to drive bookings."
            )

        suggested_rate = (
            base * current_seasonal * (Decimal("1") + adjustment_pct / Decimal("100"))
        ).quantize(TWO_PLACES, ROUND_HALF_UP)

        return {
            "property_id": str(property_id),
            "property_name": prop.name,
            "current_base_rate": float(base),
            "current_seasonal": float(current_seasonal),
            "occupancy_next_30d": occupancy_pct,
            "booked_nights": booked_nights,
            "total_nights": total_nights,
            "suggestion": suggestion,
            "adjustment_pct": float(adjustment_pct),
            "suggested_nightly_rate": float(suggested_rate),
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # 8. Revenue forecast
    # ------------------------------------------------------------------
    async def get_revenue_forecast(
        self, start_date: date, end_date: date, db: AsyncSession
    ) -> Dict:
        """Forecast revenue across the entire portfolio for a date range."""

        if end_date <= start_date:
            raise ValueError("end_date must be after start_date")

        res_result = await db.execute(
            select(Reservation, Property).join(
                Property, Reservation.property_id == Property.id
            ).where(
                and_(
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.check_in_date <= end_date,
                    Reservation.check_out_date >= start_date,
                )
            )
        )
        rows = res_result.all()

        total_revenue = Decimal("0")
        property_revenue: Dict[str, Decimal] = {}
        total_nights_booked = 0

        for reservation, prop in rows:
            eff_start = max(reservation.check_in_date, start_date)
            eff_end = min(reservation.check_out_date, end_date)
            nights = (eff_end - eff_start).days
            if nights <= 0:
                continue

            base = self._base_rate(prop.bedrooms)
            nightly_sum = Decimal("0")
            current = eff_start
            for _ in range(nights):
                seasonal = self.get_seasonal_multiplier(current)
                nightly_sum += (base * seasonal).quantize(TWO_PLACES, ROUND_HALF_UP)
                current += timedelta(days=1)

            total_revenue += nightly_sum
            total_nights_booked += nights
            prop_key = prop.name or str(prop.id)
            property_revenue[prop_key] = property_revenue.get(prop_key, Decimal("0")) + nightly_sum

        total_props_result = await db.execute(
            select(func.count(Property.id)).where(Property.is_active.is_(True))
        )
        total_props = total_props_result.scalar() or 14
        total_available_nights = total_props * (end_date - start_date).days
        occupancy_pct = (
            round(total_nights_booked / total_available_nights * 100, 1)
            if total_available_nights else 0
        )

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_properties": total_props,
            "total_revenue": float(total_revenue.quantize(TWO_PLACES)),
            "total_nights_booked": total_nights_booked,
            "total_available_nights": total_available_nights,
            "occupancy_pct": occupancy_pct,
            "average_nightly_revenue": float(
                (total_revenue / total_nights_booked).quantize(TWO_PLACES)
            ) if total_nights_booked else 0,
            "by_property": {
                k: float(v.quantize(TWO_PLACES)) for k, v in property_revenue.items()
            },
        }

    # ------------------------------------------------------------------
    # 9. Market comparison
    # ------------------------------------------------------------------
    def compare_to_market(self, property_id) -> Dict:
        """
        Compare our pricing to the Blue Ridge GA vacation rental market.

        Uses curated market benchmarks.  In production this would pull from
        AirDNA / PriceLabs / Wheelhouse APIs.
        """
        # Market averages for Blue Ridge GA (curated benchmarks)
        market_averages: Dict[int, Dict] = {
            1: {"avg_rate": 160, "median_rate": 145, "occupancy": 58},
            2: {"avg_rate": 215, "median_rate": 195, "occupancy": 62},
            3: {"avg_rate": 290, "median_rate": 265, "occupancy": 65},
            4: {"avg_rate": 375, "median_rate": 340, "occupancy": 60},
            5: {"avg_rate": 480, "median_rate": 440, "occupancy": 55},
            6: {"avg_rate": 580, "median_rate": 530, "occupancy": 50},
            7: {"avg_rate": 700, "median_rate": 630, "occupancy": 45},
        }

        # Without a live DB call we return benchmarks keyed to a generic cabin
        # The caller should combine this with get_nightly_rate() for a full picture.
        default_br = 3
        benchmarks = market_averages.get(default_br, market_averages[3])

        our_base = float(BASE_RATES.get(default_br, _DEFAULT_LARGE_CABIN_RATE))
        diff_pct = round((our_base - benchmarks["avg_rate"]) / benchmarks["avg_rate"] * 100, 1)

        position = "at_market"
        if diff_pct > 5:
            position = "above_market"
        elif diff_pct < -5:
            position = "below_market"

        return {
            "property_id": str(property_id),
            "market": "Blue Ridge, GA",
            "our_base_rate": our_base,
            "market_avg_rate": benchmarks["avg_rate"],
            "market_median_rate": benchmarks["median_rate"],
            "market_avg_occupancy": benchmarks["occupancy"],
            "difference_pct": diff_pct,
            "position": position,
            "recommendation": (
                "Rates are competitive with the local market. "
                "Seasonal and demand adjustments keep pricing optimised."
                if position == "at_market"
                else f"Rates are {abs(diff_pct)}% {'above' if diff_pct > 0 else 'below'} "
                     f"market average — review with suggest_rate_adjustment() for fine-tuning."
            ),
            "data_source": "Curated Blue Ridge GA benchmarks (connect AirDNA/PriceLabs for live data)",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _base_rate(bedrooms: int) -> Decimal:
        """Look up the base nightly rate by bedroom count."""
        if bedrooms <= 0:
            bedrooms = 1
        return BASE_RATES.get(bedrooms, _DEFAULT_LARGE_CABIN_RATE)

    @staticmethod
    def _season_label(target_date: date) -> str:
        """Human-friendly season label for a date."""
        if _is_holiday(target_date):
            return "holiday"
        month = target_date.month
        if month in (6, 7, 8, 10):
            return "peak"
        if month in (1, 2):
            return "off_peak"
        return "shoulder"
