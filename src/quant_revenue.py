#!/usr/bin/env python3
"""
=============================================================================
 CF-02: QuantRevenue — Dynamic Pricing Engine
 Cabin Rentals of Georgia  •  Fortress-Prime
=============================================================================
 A weighted-factor pricing model that generates a 30-day forward rate card
 for every managed property.  Factors:
   1. Seasonal curve     — Blue Ridge tourism calendar
   2. Day-of-week        — Weekend premium, mid-week floor
   3. Occupancy yield    — Forward-booking density adjustment
   4. Days-until-checkin  — Urgency / last-minute discounting
   5. Event calendar     — Local festival & holiday demand spikes
   6. Commander overrides — Respect ops_overrides rate_override entries

 Output → revenue_ledger table (one row per property per date per run)
 Schedule → cron daily at 05:30 (before Watchtower at 06:00)
=============================================================================
"""

import os
import sys
import math
import uuid
import yaml
import argparse
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import psycopg2
import psycopg2.extras

# ─── Configuration ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
RATES_FILE = BASE_DIR / "cabins" / "_base_rates.yaml"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB = os.getenv("PG_DB", "fortress_db")
PG_USER = os.getenv("PG_USER", "miner_bot")
PG_PASS = os.getenv("PG_PASS", "")

ENGINE_VERSION = "2.0.0"
FORECAST_DAYS = 30       # Default forward-looking window

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [QuantRevenue] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("quant_revenue")


# =============================================================================
# 1. DATA LOADERS
# =============================================================================

def load_base_rates() -> dict:
    """Load the canonical base-rate registry from cabins/_base_rates.yaml."""
    with open(RATES_FILE) as f:
        data = yaml.safe_load(f)
    defaults = data.get("defaults", {})
    properties = {}
    for prop_id, cfg in data.get("properties", {}).items():
        if cfg.get("status") in ("sold", "retired", "inactive"):
            continue
        properties[prop_id] = {
            "property_id": prop_id,
            "display_name": cfg.get("display_name", prop_id),
            "bedrooms": cfg.get("bedrooms", 2),
            "base_rate": float(cfg.get("base_rate", 200)),
            "tier": cfg.get("tier", "standard"),
            "floor_pct": float(cfg.get("floor_pct", defaults.get("floor_pct", 0.60))),
            "ceiling_pct": float(cfg.get("ceiling_pct", defaults.get("ceiling_pct", 2.00))),
            "cleaning_fee": float(cfg.get("cleaning_fee", defaults.get("cleaning_fee", 150))),
            "min_nights": int(cfg.get("min_nights", defaults.get("min_nights", 2))),
        }
    return properties


def get_db():
    """Return a psycopg2 connection with RealDictCursor."""
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER,
        password=PG_PASS if PG_PASS else None,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def load_overrides(conn) -> dict:
    """Load active rate overrides from ops_overrides."""
    cur = conn.cursor()
    cur.execute("""
        SELECT entity_id, override_type, reason, effective_until
        FROM ops_overrides
        WHERE active = TRUE
          AND (effective_until IS NULL OR effective_until > NOW())
    """)
    overrides = {}
    for row in cur.fetchall():
        eid = row["entity_id"]
        if eid not in overrides:
            overrides[eid] = []
        overrides[eid].append(dict(row))
    return overrides


def load_forward_occupancy(conn, properties: dict, horizon_days: int = 30) -> dict:
    """
    Estimate forward occupancy for each property by counting booked nights
    in the next `horizon_days` from ops_turnovers.
    Returns {property_id: occupancy_fraction}.
    """
    cur = conn.cursor()
    now = datetime.now()
    horizon_end = now + timedelta(days=horizon_days)

    # Get all upcoming turnovers — a turnover with reservation_id_in means
    # a guest is checking in, implying the property is booked for some period.
    cur.execute("""
        SELECT t.property_id, t.checkout_time, t.checkin_time,
               LEAD(t.checkout_time) OVER (
                   PARTITION BY t.property_id ORDER BY t.checkout_time
               ) as next_checkout
        FROM ops_turnovers t
        WHERE t.checkout_time >= %s AND t.checkout_time <= %s
        ORDER BY t.property_id, t.checkout_time
    """, (now, horizon_end + timedelta(days=14)))

    # Estimate booked nights per property
    booked_nights = {}
    for row in cur.fetchall():
        pid = row["property_id"]
        checkin = row["checkin_time"]
        next_checkout = row["next_checkout"]

        if checkin and next_checkout:
            # Guest checks in at checkin_time, stays until next_checkout
            stay_start = checkin.date() if isinstance(checkin, datetime) else checkin
            stay_end = next_checkout.date() if isinstance(next_checkout, datetime) else next_checkout
            nights = (stay_end - stay_start).days
            if nights > 0:
                booked_nights[pid] = booked_nights.get(pid, 0) + min(nights, horizon_days)

    # Map DB property_id → config property_id
    cur.execute("SELECT property_id, internal_name FROM ops_properties WHERE bedrooms IS NOT NULL")
    db_to_config = {}
    for row in cur.fetchall():
        # Normalize: "Cherokee Sunrise on Noontootla Creek" → "cherokee_sunrise_on_noontootla_creek"
        config_key = row["internal_name"].lower().replace(" ", "_").replace("'", "")
        db_to_config[row["property_id"]] = config_key

    # Also build reverse: config_key → db_property_id for lookup
    config_to_db = {v: k for k, v in db_to_config.items()}

    occupancy = {}
    for prop_id in properties:
        # Try exact match first, then fuzzy prefix match
        db_pid = config_to_db.get(prop_id)
        if not db_pid:
            for config_name, db_id in config_to_db.items():
                if config_name.startswith(prop_id[:12]) or prop_id.startswith(config_name[:12]):
                    db_pid = db_id
                    break
        nights = booked_nights.get(db_pid, 0) if db_pid else 0
        occupancy[prop_id] = min(1.0, nights / horizon_days)

    return occupancy


# =============================================================================
# 2. PRICING FACTORS
# =============================================================================

# ── Seasonal Curve ──────────────────────────────────────────────────────────
# Blue Ridge, GA tourism calendar:
#   Peak:   Oct (foliage), Jun-Aug (summer), late Dec (holidays)
#   Shoulder: Mar-May (spring), Sep, Nov
#   Trough:  Jan-Feb
# Modeled as a sinusoidal curve calibrated to local patterns.

SEASONAL_CURVE = {
    # month: (standard_mult, premium_mult)
    1:  (0.75, 0.80),   # January — deep trough
    2:  (0.78, 0.82),   # February — Valentine's bump
    3:  (0.88, 0.92),   # March — early spring
    4:  (0.95, 1.00),   # April — spring break
    5:  (1.00, 1.05),   # May — warming up
    6:  (1.15, 1.20),   # June — summer peak begins
    7:  (1.20, 1.30),   # July — peak summer
    8:  (1.15, 1.25),   # August — summer winding down
    9:  (1.00, 1.05),   # September — shoulder
    10: (1.30, 1.45),   # October — FOLIAGE PEAK
    11: (1.05, 1.15),   # November — Thanksgiving spike
    12: (1.10, 1.20),   # December — holiday season
}

# Holiday overrides (fixed dates get an extra bump)
HOLIDAY_BUMPS = {
    # (month, day): multiplier
    (1, 1):   1.10,   # New Year's Day
    (1, 20):  1.08,   # MLK Weekend
    (2, 14):  1.15,   # Valentine's Day
    (2, 15):  1.10,   # Valentine's weekend
    (5, 24):  1.15,   # Memorial Day weekend (approx)
    (5, 25):  1.20,   # Memorial Day
    (5, 26):  1.15,
    (7, 3):   1.20,   # July 4th weekend
    (7, 4):   1.25,   # July 4th
    (7, 5):   1.15,
    (9, 1):   1.15,   # Labor Day weekend (approx)
    (9, 2):   1.10,
    (10, 10): 1.15,   # Columbus Day / Fall break
    (10, 11): 1.10,
    (10, 12): 1.10,
    (11, 27): 1.20,   # Thanksgiving
    (11, 28): 1.25,
    (11, 29): 1.20,
    (12, 20): 1.15,   # Christmas week
    (12, 21): 1.20,
    (12, 22): 1.25,
    (12, 23): 1.30,
    (12, 24): 1.35,   # Christmas Eve
    (12, 25): 1.30,   # Christmas
    (12, 26): 1.25,
    (12, 27): 1.20,
    (12, 28): 1.20,
    (12, 29): 1.20,
    (12, 30): 1.25,   # NYE week
    (12, 31): 1.35,   # New Year's Eve
}


def seasonal_multiplier(target_date: date, tier: str) -> float:
    """Return the seasonal multiplier for a given date and tier."""
    month = target_date.month
    std_mult, prem_mult = SEASONAL_CURVE.get(month, (1.0, 1.0))
    base_mult = prem_mult if tier == "premium" else std_mult

    # Check for holiday bump
    holiday_bump = HOLIDAY_BUMPS.get((target_date.month, target_date.day), 1.0)

    return base_mult * holiday_bump


# ── Day-of-Week Factor ──────────────────────────────────────────────────────
DOW_FACTORS = {
    0: 0.85,   # Monday
    1: 0.82,   # Tuesday — lowest mid-week
    2: 0.85,   # Wednesday
    3: 0.92,   # Thursday — weekend travelers arrive
    4: 1.10,   # Friday — weekend begins
    5: 1.25,   # Saturday — peak weekend
    6: 0.95,   # Sunday — checkout day
}


def dow_factor(target_date: date) -> float:
    """Return the day-of-week multiplier."""
    return DOW_FACTORS.get(target_date.weekday(), 1.0)


# ── Occupancy Yield Factor ──────────────────────────────────────────────────
def occupancy_factor(forward_occupancy: float) -> float:
    """
    Adjust rate based on forward booking density.
    Low occupancy (<30%) → discount to stimulate demand.
    High occupancy (>70%) → premium to capture surplus.
    """
    if forward_occupancy >= 0.85:
        return 1.25   # Almost full — maximize yield
    elif forward_occupancy >= 0.70:
        return 1.15
    elif forward_occupancy >= 0.50:
        return 1.05   # Healthy — slight premium
    elif forward_occupancy >= 0.30:
        return 1.00   # Baseline
    elif forward_occupancy >= 0.15:
        return 0.92   # Stimulate bookings
    else:
        return 0.85   # Aggressive discount to fill


# ── Days-Until-Checkin (Urgency) Factor ─────────────────────────────────────
def urgency_factor(days_until: int) -> float:
    """
    Adjust rate based on how far out the date is.
    Last-minute (1-2 days): slight discount to fill
    Sweet spot (3-14 days): standard
    Far out (15-30 days): slight discount for early birds
    """
    if days_until <= 1:
        return 0.88   # Last-minute deal
    elif days_until <= 3:
        return 0.93   # Approaching fast
    elif days_until <= 7:
        return 1.00   # Prime booking window
    elif days_until <= 14:
        return 1.02   # Moderate advance — slight uptick
    elif days_until <= 21:
        return 1.00   # Standard
    else:
        return 0.97   # Far out — early-bird incentive


# ── Event Calendar ──────────────────────────────────────────────────────────
# Blue Ridge, GA events that drive cabin demand.
# Format: (month, start_day, end_day, name, weight 1-10)
BLUE_RIDGE_EVENTS = [
    (3, 14, 16, "St. Patrick's Day Weekend", 4),
    (4, 4, 6, "Spring Fling Arts Festival", 5),
    (4, 18, 20, "Easter Weekend", 6),
    (5, 1, 3, "Blue Ridge Mountains Arts Assoc Show", 5),
    (5, 24, 26, "Memorial Day Weekend", 8),
    (6, 6, 8, "Aska Adventure Race", 5),
    (6, 20, 22, "Juneteenth Weekend", 4),
    (7, 3, 5, "Fourth of July Weekend", 9),
    (7, 18, 20, "Blue Ridge Barbecue Festival", 6),
    (8, 1, 3, "Summer Concert Series Finale", 5),
    (9, 1, 2, "Labor Day Weekend", 8),
    (9, 19, 21, "Fannin County Fair", 5),
    (10, 3, 5, "Fall Festival & Craft Show", 7),
    (10, 10, 12, "Columbus Day / Fall Break", 7),
    (10, 17, 19, "Blue Ridge Blues Festival", 8),
    (10, 24, 26, "Peak Foliage Weekend", 9),
    (10, 31, 31, "Halloween", 5),
    (11, 8, 9, "Veteran's Day Weekend", 4),
    (11, 27, 30, "Thanksgiving Weekend", 9),
    (12, 5, 7, "Christmas Parade & Light Up BR", 6),
    (12, 20, 31, "Christmas / NYE Season", 9),
    (1, 1, 2, "New Year's Recovery Weekend", 5),
    (2, 13, 15, "Valentine's Day Weekend", 6),
]


def event_factor(target_date: date) -> tuple:
    """
    Return (multiplier, event_name, event_weight) if the target date falls
    within any known event window.  Otherwise (1.0, None, 0).
    """
    month = target_date.month
    day = target_date.day
    best_event = None
    best_weight = 0

    for evt_month, start_day, end_day, name, weight in BLUE_RIDGE_EVENTS:
        if month == evt_month and start_day <= day <= end_day:
            if weight > best_weight:
                best_event = name
                best_weight = weight

    if best_event:
        # Weight 1-10 maps to multiplier 1.02-1.20
        mult = 1.0 + (best_weight / 50.0)
        return mult, best_event, best_weight

    return 1.0, None, 0


# =============================================================================
# 3. COMPOSITE PRICING ENGINE
# =============================================================================

def compute_rate(
    base_rate: float,
    tier: str,
    floor_pct: float,
    ceiling_pct: float,
    target_date: date,
    forward_occupancy: float,
    days_until_checkin: int,
    override_rate: float = None,
) -> dict:
    """
    Compute the adjusted nightly rate for a property on a given date.
    Returns a dict with all factors, the final rate, and a trading signal.
    """
    # If Commander has a rate override, use it as the base
    effective_base = override_rate if override_rate else base_rate

    # Step 1: Seasonal
    s_mult = seasonal_multiplier(target_date, tier)
    seasonal_baseline = effective_base * s_mult

    # Step 2: Day of week
    d_mult = dow_factor(target_date)
    dow_adjusted = seasonal_baseline * d_mult

    # Step 3: Occupancy yield
    o_mult = occupancy_factor(forward_occupancy)
    yield_adjusted = dow_adjusted * o_mult

    # Step 4: Urgency
    u_mult = urgency_factor(days_until_checkin)
    urgency_adjusted = yield_adjusted * u_mult

    # Step 5: Events
    e_mult, e_name, e_weight = event_factor(target_date)
    event_adjusted = urgency_adjusted * e_mult

    # Step 6: Guardrails
    floor_rate = effective_base * floor_pct
    ceiling_rate = effective_base * ceiling_pct
    final_rate = max(floor_rate, min(ceiling_rate, event_adjusted))

    # Round to nearest $5
    final_rate = round(final_rate / 5) * 5

    # Rate change from base
    rate_change = final_rate - effective_base
    rate_change_pct = (rate_change / effective_base * 100) if effective_base > 0 else 0

    # Composite sentiment score — demand-oriented
    # Positive = conditions favor raising rates; Negative = conditions favor lowering
    # Weight seasonal heavily (it's the dominant driver in Blue Ridge)
    seasonal_delta = (s_mult - 1.0) * 30         # -6 (Jan) to +13 (Oct peak)
    demand_pressure = forward_occupancy * 20      # 0 (empty) to 20 (full)
    event_boost = (e_mult - 1.0) * 50             # 0 to 10
    dow_boost = (d_mult - 1.0) * 10               # -1.8 to +2.5
    composite = seasonal_delta + demand_pressure + event_boost + dow_boost
    sentiment = max(-1.0, min(1.0, composite / 30))

    # Volatility index (spread of factors)
    factor_values = [s_mult, d_mult, o_mult, u_mult, e_mult]
    mean_f = sum(factor_values) / len(factor_values)
    variance = sum((f - mean_f) ** 2 for f in factor_values) / len(factor_values)
    volatility = math.sqrt(variance)

    # Trading signal — based on demand composite, not just rate change
    signal, confidence = _trading_signal(composite, sentiment, volatility)

    return {
        "base_rate": effective_base,
        "seasonal_baseline": round(seasonal_baseline, 2),
        "adjusted_rate": final_rate,
        "alpha": round(final_rate - seasonal_baseline, 2),
        "previous_rate": effective_base,
        "rate_change": round(rate_change, 2),
        "rate_change_pct": round(rate_change_pct, 2),
        "sentiment_score": round(sentiment, 4),
        "weather_factor": 0.0,       # Placeholder — no weather API yet
        "event_factor": round(e_mult, 4),
        "competitor_factor": 0.0,    # Placeholder — no competitor data yet
        "volatility_index": round(volatility, 4),
        "trading_signal": signal,
        "confidence": round(confidence, 4),
        "weather_condition": None,
        "weather_temp_f": None,
        "event_name": e_name,
        "event_weight": e_weight or 0,
        "competitor_direction": "stable",
        "competitor_rate_change": 0.0,
        "days_until_checkin": days_until_checkin,
        # Extra context (not stored in revenue_ledger but useful for API)
        "_factors": {
            "seasonal": round(s_mult, 4),
            "dow": round(d_mult, 4),
            "occupancy": round(o_mult, 4),
            "urgency": round(u_mult, 4),
            "event": round(e_mult, 4),
        },
        "_floor": round(floor_rate, 2),
        "_ceiling": round(ceiling_rate, 2),
    }


def _trading_signal(composite: float, sentiment: float, volatility: float) -> tuple:
    """
    Determine the trading signal and confidence.
    composite: demand composite score (roughly -10 to +40 range)
    Returns (signal_str, confidence_float).

    Signal meaning for vacation rental managers:
      STRONG_BUY  — Peak demand window. Raise rates aggressively.
      BUY         — Above-average demand. Modest rate increase.
      HOLD        — Normal conditions. Rates are appropriate.
      SELL        — Below-average demand. Consider discounts.
      STRONG_SELL — Deep trough. Aggressive discounting to fill.
    """
    # Confidence is inverse of volatility
    confidence = max(0.3, min(0.98, 1.0 - volatility * 2))

    if composite > 20:
        return "STRONG_BUY", confidence
    elif composite > 8:
        return "BUY", confidence
    elif composite > -3:
        return "HOLD", confidence
    elif composite > -10:
        return "SELL", confidence
    else:
        return "STRONG_SELL", confidence


# =============================================================================
# 4. RATE CARD GENERATOR
# =============================================================================

def generate_rate_cards(
    properties: dict,
    overrides: dict,
    occupancy: dict,
    forecast_days: int = FORECAST_DAYS,
    today: date = None,
) -> dict:
    """
    Generate rate cards for all properties for the next N days.
    Returns {property_id: [rate_dict, ...]}
    """
    today = today or date.today()
    cards = {}

    for prop_id, cfg in properties.items():
        # Check for suppression override (skip pricing)
        prop_overrides = overrides.get(prop_id, [])
        is_suppressed = any(
            o["override_type"] == "suppress_alert" for o in prop_overrides
        )
        if is_suppressed:
            log.info(f"  ⏸  {cfg['display_name']} — suppressed, skipping")
            continue

        # Check for rate override
        override_rate = None
        for o in prop_overrides:
            if o["override_type"] == "rate_override":
                # Parse rate from reason like "Target rate: $175/night"
                reason = o.get("reason", "")
                import re
                match = re.search(r'\$(\d+)', reason)
                if match:
                    override_rate = float(match.group(1))
                    log.info(f"  🎯 {cfg['display_name']} — rate override: ${override_rate}")

        fwd_occ = occupancy.get(prop_id, 0.0)
        daily_rates = []

        for day_offset in range(forecast_days):
            target = today + timedelta(days=day_offset)
            rate_data = compute_rate(
                base_rate=cfg["base_rate"],
                tier=cfg["tier"],
                floor_pct=cfg["floor_pct"],
                ceiling_pct=cfg["ceiling_pct"],
                target_date=target,
                forward_occupancy=fwd_occ,
                days_until_checkin=day_offset,
                override_rate=override_rate,
            )
            rate_data["target_date"] = target
            rate_data["target_dow"] = target.strftime("%A")
            rate_data["cabin_name"] = prop_id
            rate_data["tier"] = cfg["tier"]
            daily_rates.append(rate_data)

        cards[prop_id] = daily_rates
        avg_rate = sum(r["adjusted_rate"] for r in daily_rates) / len(daily_rates)
        signals = {}
        for r in daily_rates:
            signals[r["trading_signal"]] = signals.get(r["trading_signal"], 0) + 1
        dominant_signal = max(signals, key=signals.get)
        log.info(
            f"  📊 {cfg['display_name']:35s} | base: ${cfg['base_rate']:>6.0f} "
            f"| avg: ${avg_rate:>6.0f} | occ: {fwd_occ:.0%} | signal: {dominant_signal}"
        )

    return cards


# =============================================================================
# 5. DATABASE WRITER
# =============================================================================

def write_rate_cards(conn, cards: dict, run_id: str) -> int:
    """
    Write rate cards to revenue_ledger. Uses upsert on (cabin_name, target_date, run_id).
    Returns number of rows written.
    """
    cur = conn.cursor()
    count = 0

    for prop_id, daily_rates in cards.items():
        for rate in daily_rates:
            cur.execute("""
                INSERT INTO revenue_ledger (
                    run_id, cabin_name, target_date, target_dow,
                    base_rate, seasonal_baseline, adjusted_rate, alpha,
                    previous_rate, rate_change, rate_change_pct,
                    sentiment_score, weather_factor, event_factor,
                    competitor_factor, volatility_index,
                    trading_signal, confidence,
                    weather_condition, weather_temp_f,
                    event_name, event_weight,
                    competitor_direction, competitor_rate_change,
                    days_until_checkin, engine_version, tier
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (cabin_name, target_date, run_id) DO UPDATE SET
                    adjusted_rate = EXCLUDED.adjusted_rate,
                    rate_change = EXCLUDED.rate_change,
                    rate_change_pct = EXCLUDED.rate_change_pct,
                    trading_signal = EXCLUDED.trading_signal,
                    confidence = EXCLUDED.confidence,
                    generated_at = NOW()
            """, (
                run_id, rate["cabin_name"], rate["target_date"], rate["target_dow"],
                rate["base_rate"], rate["seasonal_baseline"], rate["adjusted_rate"], rate["alpha"],
                rate["previous_rate"], rate["rate_change"], rate["rate_change_pct"],
                rate["sentiment_score"], rate["weather_factor"], rate["event_factor"],
                rate["competitor_factor"], rate["volatility_index"],
                rate["trading_signal"], rate["confidence"],
                rate["weather_condition"], rate["weather_temp_f"],
                rate["event_name"], rate["event_weight"],
                rate["competitor_direction"], rate["competitor_rate_change"],
                rate["days_until_checkin"], ENGINE_VERSION, rate["tier"],
            ))
            count += 1

    conn.commit()
    return count


# =============================================================================
# 6. REPORT GENERATOR
# =============================================================================

def generate_report(cards: dict, properties: dict, run_id: str, forecast_days: int = FORECAST_DAYS) -> str:
    """Generate a markdown summary of the pricing run."""
    lines = [
        f"# QuantRevenue Rate Card — {date.today().strftime('%B %d, %Y')}",
        f"**Run ID:** `{run_id}`  |  **Engine:** v{ENGINE_VERSION}  |  **Forecast:** {forecast_days} days\n",
        "---\n",
    ]

    total_base_revenue = 0
    total_optimized_revenue = 0
    strong_buys = []
    sells = []

    for prop_id, daily_rates in sorted(cards.items()):
        cfg = properties.get(prop_id, {})
        display = cfg.get("display_name", prop_id)
        base = cfg.get("base_rate", 0)
        n_days = len(daily_rates)
        avg_rate = sum(r["adjusted_rate"] for r in daily_rates) / n_days
        min_rate = min(r["adjusted_rate"] for r in daily_rates)
        max_rate = max(r["adjusted_rate"] for r in daily_rates)

        signals = {}
        for r in daily_rates:
            signals[r["trading_signal"]] = signals.get(r["trading_signal"], 0) + 1
        dominant_signal = max(signals, key=signals.get)

        base_period = base * n_days
        optimized_period = sum(r["adjusted_rate"] for r in daily_rates)
        delta = optimized_period - base_period
        total_base_revenue += base_period
        total_optimized_revenue += optimized_period

        lines.append(f"### {display} ({cfg.get('bedrooms', '?')}BR — {cfg.get('tier', 'standard')})")
        lines.append(f"- **Base:** ${base:.0f}/night  |  **Avg Recommended:** ${avg_rate:.0f}/night")
        lines.append(f"- **Range:** ${min_rate:.0f} — ${max_rate:.0f}")
        lines.append(f"- **Signal:** {dominant_signal}  |  **{n_days}d Delta:** {'+' if delta >= 0 else ''}${delta:.0f}")
        lines.append("")

        if dominant_signal in ("STRONG_BUY", "BUY"):
            strong_buys.append((display, avg_rate, base, dominant_signal))
        elif dominant_signal in ("SELL", "STRONG_SELL"):
            sells.append((display, avg_rate, base, dominant_signal))

    # Summary
    delta_total = total_optimized_revenue - total_base_revenue
    summary_lines = [
        f"## Executive Summary",
        f"- **Portfolio Base Revenue ({forecast_days}d):** ${total_base_revenue:,.0f}",
        f"- **Optimized Revenue ({forecast_days}d):** ${total_optimized_revenue:,.0f}",
        f"- **Revenue Delta:** {'+' if delta_total >= 0 else ''}${delta_total:,.0f}",
        f"- **Properties Priced:** {len(cards)}",
    ]
    if strong_buys:
        summary_lines.append(f"- **Upside Opportunities:** {len(strong_buys)} properties — raise rates")
    if sells:
        summary_lines.append(f"- **Low-Season Adjustments:** {len(sells)} properties — consider discounts")
    summary_lines.append("")

    for i, line in enumerate(summary_lines):
        lines.insert(3 + i, line)

    return "\n".join(lines)


# =============================================================================
# 7. MAIN EXECUTION
# =============================================================================

def run_engine(forecast_days: int = FORECAST_DAYS, dry_run: bool = False) -> dict:
    """
    Execute a full QuantRevenue pricing run.
    Returns the rate cards dict for API consumption.
    """
    run_id = uuid.uuid4().hex[:16]
    log.info(f"═══ QuantRevenue Engine v{ENGINE_VERSION} ═══")
    log.info(f"  Run ID: {run_id}")
    log.info(f"  Forecast: {forecast_days} days forward from {date.today()}")

    # Load configuration
    properties = load_base_rates()
    log.info(f"  Loaded {len(properties)} properties from base rates registry")

    # Connect to database
    try:
        conn = get_db()
    except Exception as e:
        log.error(f"FORTRESS PROTOCOL: Database unavailable — {e}. Serving stale rates.")
        return {
            "run_id": run_id,
            "properties_priced": 0,
            "total_entries": 0,
            "cards": {},
            "error": "database_unavailable",
            "fallback": "stale_rates_active",
        }

    # Load overrides
    overrides = load_overrides(conn)
    log.info(f"  Loaded {sum(len(v) for v in overrides.values())} active overrides")

    # Load forward occupancy
    occupancy = load_forward_occupancy(conn, properties, forecast_days)
    log.info(f"  Computed forward occupancy for {len(occupancy)} properties")

    # Generate rate cards
    log.info("  Generating rate cards...")
    cards = generate_rate_cards(
        properties, overrides, occupancy, forecast_days
    )
    log.info(f"  Generated {sum(len(v) for v in cards.values())} rate entries")

    if not dry_run:
        # Write to database
        rows = write_rate_cards(conn, cards, run_id)
        log.info(f"  Wrote {rows} rows to revenue_ledger")

        # Generate and archive report
        report = generate_report(cards, properties, run_id, forecast_days)
        report_path = LOGS_DIR / f"quantrevenue_{date.today().strftime('%Y%m%d')}.md"
        with open(report_path, "w") as f:
            f.write(report)
        log.info(f"  Report archived to {report_path}")

        # ── Revenue Bridge: Post forecast accruals to General Ledger ────
        try:
            # Ensure project root is importable (accounting/ lives there)
            import sys as _sys
            _proj_root = str(BASE_DIR)
            if _proj_root not in _sys.path:
                _sys.path.insert(0, _proj_root)
            from accounting.revenue_bridge import post_forecast_accruals
            bridge_result = post_forecast_accruals(run_id)
            log.info(
                f"  Revenue Bridge: {bridge_result['entries_posted']} accruals posted, "
                f"${float(bridge_result['total_accrued']):,.0f} accrued, "
                f"{bridge_result['reversed']} stale reversed"
            )
        except Exception as e:
            log.warning(f"  Revenue Bridge skipped (non-fatal): {e}")
    else:
        report = generate_report(cards, properties, run_id, forecast_days)
        log.info("  DRY RUN — no database writes")
        print("\n" + report)

    conn.close()
    log.info(f"═══ QuantRevenue Complete ═══\n")

    return {
        "run_id": run_id,
        "properties_priced": len(cards),
        "total_entries": sum(len(v) for v in cards.values()),
        "cards": cards,
    }


def main():
    parser = argparse.ArgumentParser(description="CF-02 QuantRevenue — Dynamic Pricing Engine")
    parser.add_argument("--days", type=int, default=FORECAST_DAYS, help="Forecast horizon in days")
    parser.add_argument("--dry-run", action="store_true", help="Print report without writing to DB")
    args = parser.parse_args()

    result = run_engine(forecast_days=args.days, dry_run=args.dry_run)
    print(f"\n✅ QuantRevenue Run Complete")
    print(f"   Run ID: {result['run_id']}")
    print(f"   Properties: {result['properties_priced']}")
    print(f"   Entries: {result['total_entries']}")


if __name__ == "__main__":
    main()
