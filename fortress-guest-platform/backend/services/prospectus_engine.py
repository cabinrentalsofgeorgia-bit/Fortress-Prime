"""
Prospectus Engine — Dual-purpose data aggregator for the SOTA owner pitch PDF.

Queries Iron Dome financial data, reservation history, and market benchmarks to
produce a ProspectusPayload that feeds both WeasyPrint PDF rendering and a JSON
API endpoint for the Next.js marketing page.
"""

import calendar
import shutil
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.contract_generator import (
    CONTRACT_STORAGE,
    NAS_CONTRACT_BASE,
    _fetch_capex_markup,
    _fetch_management_split,
    _fetch_owner_info,
    _fetch_property_info,
    _jinja_env,
)

logger = structlog.get_logger(service="prospectus_engine")

BLUE_RIDGE_BENCHMARKS: Dict[int, Dict[str, float]] = {
    1: {"avg_rate": 160, "occupancy": 58},
    2: {"avg_rate": 215, "occupancy": 62},
    3: {"avg_rate": 290, "occupancy": 65},
    4: {"avg_rate": 375, "occupancy": 60},
    5: {"avg_rate": 480, "occupancy": 55},
    6: {"avg_rate": 580, "occupancy": 50},
    7: {"avg_rate": 700, "occupancy": 45},
}

SEASONALITY_WEIGHTS: Dict[int, float] = {
    1: 0.70,   # Jan
    2: 0.70,   # Feb
    3: 0.75,   # Mar
    4: 0.90,   # Apr
    5: 0.95,   # May
    6: 1.20,   # Jun
    7: 1.25,   # Jul
    8: 1.20,   # Aug
    9: 1.15,   # Sep
    10: 1.20,  # Oct (fall foliage peak)
    11: 0.90,  # Nov
    12: 0.85,  # Dec (holiday bump)
}

LUXURY_KEYWORDS = {
    "hot tub": "Hot Tub",
    "hottub": "Hot Tub",
    "jacuzzi": "Hot Tub",
    "game room": "Game Room",
    "pool table": "Game Room",
    "arcade": "Game Room",
    "theater": "Home Theater",
    "theatre": "Home Theater",
    "media room": "Home Theater",
    "fire pit": "Fire Pit",
    "firepit": "Fire Pit",
    "sauna": "Sauna",
    "ev charger": "EV Charger",
    "mountain view": "Mountain View",
    "creek": "Creek Access",
    "river": "River Access",
}


async def _fetch_trailing_performance(
    db: AsyncSession, property_id: str
) -> Dict[str, Any]:
    """Aggregate trailing-12-month reservation data for the property."""
    lookback = date.today() - timedelta(days=365)
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(total_amount), 0)                                  AS gross_revenue,
                COALESCE(SUM(nights_count), 0)                                  AS total_nights,
                COUNT(*)                                                         AS booking_count,
                COALESCE(SUM(total_amount) / NULLIF(SUM(nights_count), 0), 0)   AS avg_nightly_rate,
                COALESCE(SUM(cleaning_fee), 0)                                  AS total_cleaning,
                COALESCE(SUM(tax_amount), 0)                                    AS total_tax
            FROM reservations
            WHERE property_id::text = :pid
              AND status != 'cancelled'
              AND nights_count > 0
              AND total_amount > 0
              AND check_in_date >= :lb
        """),
        {"pid": property_id, "lb": lookback},
    )
    row = result.first()
    if not row:
        return {
            "gross_revenue": 0.0,
            "total_nights": 0,
            "booking_count": 0,
            "avg_nightly_rate": 0.0,
            "total_cleaning": 0.0,
            "total_tax": 0.0,
            "occupancy_pct": 0.0,
        }

    total_nights = int(row.total_nights)
    return {
        "gross_revenue": round(float(row.gross_revenue), 2),
        "total_nights": total_nights,
        "booking_count": int(row.booking_count),
        "avg_nightly_rate": round(float(row.avg_nightly_rate), 2),
        "total_cleaning": round(float(row.total_cleaning), 2),
        "total_tax": round(float(row.total_tax), 2),
        "occupancy_pct": round(total_nights / 365 * 100, 1),
    }


async def _fetch_amenities(db: AsyncSession, property_id: str) -> List[str]:
    """Return de-duped list of luxury amenity labels detected for this property."""
    result = await db.execute(
        text("SELECT amenities FROM properties WHERE id::text = :pid LIMIT 1"),
        {"pid": property_id},
    )
    row = result.first()
    if not row or not row.amenities:
        return []

    existing_lower: set = set()
    raw = row.amenities if isinstance(row.amenities, list) else []
    for a in raw:
        name = ""
        if isinstance(a, dict):
            name = (a.get("amenity_name") or a.get("name") or "").strip()
        elif isinstance(a, str):
            name = a.strip()
        if name:
            existing_lower.add(name.lower())

    detected: dict = {}
    for keyword, label in LUXURY_KEYWORDS.items():
        if any(keyword in am for am in existing_lower):
            detected[label] = True
    return sorted(detected.keys())


def _build_pro_forma(
    adr: float,
    occupancy_pct: float,
    pm_pct: float,
) -> List[Dict[str, Any]]:
    """
    Build a 12-month pro forma projection.

    Each month: projected_revenue, mgmt_fee, net_to_owner, based on the
    property's ADR, expected occupancy, and seasonal weight.
    """
    months: List[Dict[str, Any]] = []
    annual_gross = 0.0
    annual_fee = 0.0
    annual_net = 0.0

    today = date.today()
    start_month = today.month
    start_year = today.year

    for i in range(12):
        m = ((start_month - 1 + i) % 12) + 1
        y = start_year + ((start_month - 1 + i) // 12)
        days_in_month = calendar.monthrange(y, m)[1]

        weight = SEASONALITY_WEIGHTS.get(m, 1.0)
        base_occ_nights = occupancy_pct / 100 * days_in_month
        adj_nights = base_occ_nights * weight
        adj_nights = min(adj_nights, days_in_month)

        gross = round(adr * adj_nights, 2)
        fee = round(gross * pm_pct / 100, 2)
        net = round(gross - fee, 2)

        annual_gross += gross
        annual_fee += fee
        annual_net += net

        months.append({
            "month": calendar.month_abbr[m],
            "year": y,
            "projected_nights": round(adj_nights, 1),
            "projected_revenue": gross,
            "mgmt_fee": fee,
            "net_to_owner": net,
        })

    return months


def _generate_market_insight(
    bedrooms: int,
    adr: float,
    luxury_amenities: List[str],
) -> str:
    """Generate a human-readable market insight string."""
    bench = BLUE_RIDGE_BENCHMARKS.get(bedrooms, BLUE_RIDGE_BENCHMARKS[3])
    market_adr = bench["avg_rate"]

    if adr > market_adr:
        pct_above = round((adr - market_adr) / market_adr * 100)
        position = f"currently commanding a {pct_above}% premium over"
    elif adr < market_adr:
        pct_below = round((market_adr - adr) / market_adr * 100)
        position = f"currently {pct_below}% below"
    else:
        position = "tracking at parity with"

    amenity_clause = ""
    if luxury_amenities:
        if len(luxury_amenities) == 1:
            amenity_clause = f" with {luxury_amenities[0]}"
        elif len(luxury_amenities) == 2:
            amenity_clause = f" with {luxury_amenities[0]} and {luxury_amenities[1]}"
        else:
            amenity_clause = (
                f" with {', '.join(luxury_amenities[:-1])}, and {luxury_amenities[-1]}"
            )

    return (
        f"Cabins{amenity_clause} in the {bedrooms}-bedroom tier "
        f"are {position} the Blue Ridge market average of ${market_adr:,.0f}/night. "
        f"Our algorithmic yield engine and direct booking syndicate are designed to "
        f"capture peak-season demand surges and maximize your net owner yield."
    )


async def generate_prospectus_data(
    owner_id: str,
    property_id: str,
    db: AsyncSession,
    term_years: int = 1,
    effective_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Assemble the complete prospectus payload.

    This data feeds both the WeasyPrint PDF and the JSON API response.
    """
    if effective_date is None:
        effective_date = date.today()

    owner_info = await _fetch_owner_info(db, owner_id)
    prop_info = await _fetch_property_info(db, property_id)
    split_info = await _fetch_management_split(db, property_id)
    capex_markup = await _fetch_capex_markup(db, property_id)

    if not prop_info:
        raise ValueError(f"Property {property_id} not found")

    bedrooms = int(prop_info.get("bedrooms") or 3)
    perf = await _fetch_trailing_performance(db, property_id)
    luxury_amenities = await _fetch_amenities(db, property_id)

    adr = perf["avg_nightly_rate"]
    occupancy_pct = perf["occupancy_pct"]

    bench = BLUE_RIDGE_BENCHMARKS.get(bedrooms, BLUE_RIDGE_BENCHMARKS[3])
    if adr <= 0:
        adr = bench["avg_rate"]
    if occupancy_pct <= 0:
        occupancy_pct = bench["occupancy"]

    pm_pct = float(split_info.get("pm_pct", "35"))

    pro_forma = _build_pro_forma(adr, occupancy_pct, pm_pct)

    annual_gross = round(sum(m["projected_revenue"] for m in pro_forma), 2)
    annual_fee = round(sum(m["mgmt_fee"] for m in pro_forma), 2)
    annual_net = round(sum(m["net_to_owner"] for m in pro_forma), 2)

    market_insight = _generate_market_insight(bedrooms, adr, luxury_amenities)

    return {
        "owner": owner_info,
        "property": {
            **prop_info,
            "luxury_amenities": luxury_amenities,
        },
        "split": split_info,
        "capex_markup_pct": capex_markup,
        "term_years": term_years,
        "effective_date": effective_date.strftime("%B %d, %Y"),
        "effective_date_iso": effective_date.isoformat(),
        "performance": perf,
        "pro_forma": {
            "adr_used": round(adr, 2),
            "occupancy_used": round(occupancy_pct, 1),
            "months": pro_forma,
            "annual_gross": annual_gross,
            "annual_mgmt_fee": annual_fee,
            "annual_net_to_owner": annual_net,
        },
        "market": {
            "benchmark_adr": bench["avg_rate"],
            "benchmark_occupancy": bench["occupancy"],
            "bedrooms_tier": bedrooms,
            "insight": market_insight,
        },
        "generated_date": date.today().strftime("%B %d, %Y"),
    }


async def render_prospectus_pdf(
    owner_id: str,
    property_id: str,
    db: AsyncSession,
    term_years: int = 1,
    effective_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Generate the full prospectus PDF (pitch + embedded management agreement).

    Returns dict with: pdf_path, nas_path, payload (the data dict), rendered_html
    """
    payload = await generate_prospectus_data(
        owner_id, property_id, db, term_years, effective_date,
    )

    template_vars = {
        "owner_name": payload["owner"].get("owner_name", ""),
        "owner_email": payload["owner"].get("owner_email", ""),
        "owner_phone": payload["owner"].get("owner_phone", ""),
        "property_name": payload["property"].get("property_name", ""),
        "property_address": payload["property"].get("property_address", ""),
        "bedrooms": payload["property"].get("bedrooms", ""),
        "bathrooms": payload["property"].get("bathrooms", ""),
        "max_guests": payload["property"].get("max_guests", ""),
        "nightly_rate_range": payload["property"].get("nightly_rate_range", ""),
        "luxury_amenities": payload["property"].get("luxury_amenities", []),
        "owner_pct": payload["split"].get("owner_pct", "65"),
        "pm_pct": payload["split"].get("pm_pct", "35"),
        "capex_markup_pct": payload["capex_markup_pct"],
        "term_years": str(payload["term_years"]),
        "effective_date": payload["effective_date"],
        "generated_date": payload["generated_date"],
        "pro_forma_months": payload["pro_forma"]["months"],
        "annual_gross": f"{payload['pro_forma']['annual_gross']:,.2f}",
        "annual_mgmt_fee": f"{payload['pro_forma']['annual_mgmt_fee']:,.2f}",
        "annual_net_to_owner": f"{payload['pro_forma']['annual_net_to_owner']:,.2f}",
        "adr_used": f"{payload['pro_forma']['adr_used']:,.2f}",
        "occupancy_used": f"{payload['pro_forma']['occupancy_used']:.1f}",
        "market_insight": payload["market"]["insight"],
        "benchmark_adr": f"{payload['market']['benchmark_adr']:,.0f}",
        "benchmark_occupancy": f"{payload['market']['benchmark_occupancy']:.0f}",
        "hist_gross": f"{payload['performance']['gross_revenue']:,.2f}",
        "hist_nights": payload["performance"]["total_nights"],
        "hist_bookings": payload["performance"]["booking_count"],
        "hist_adr": f"{payload['performance']['avg_nightly_rate']:,.2f}",
        "hist_occupancy": f"{payload['performance']['occupancy_pct']:.1f}",
    }

    template = _jinja_env.get_template("prospectus.html")
    rendered_html = template.render(**template_vars)

    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint_not_installed")
        return {
            "pdf_path": None,
            "rendered_html": rendered_html,
            "payload": payload,
            "error": "WeasyPrint not installed",
        }

    owner_dir = CONTRACT_STORAGE / owner_id
    owner_dir.mkdir(parents=True, exist_ok=True)

    eff = effective_date or date.today()
    filename = f"prospectus_{property_id}_{eff.isoformat()}.pdf"
    pdf_path = owner_dir / filename

    try:
        HTML(string=rendered_html).write_pdf(str(pdf_path))
        logger.info(
            "prospectus_generated",
            owner_id=owner_id,
            property_id=property_id,
            pdf_path=str(pdf_path),
        )
    except Exception as e:
        logger.error("prospectus_pdf_failed", error=str(e)[:300])
        return {
            "pdf_path": None,
            "rendered_html": rendered_html,
            "payload": payload,
            "error": str(e)[:300],
        }

    nas_path = None
    try:
        nas_owner_dir = NAS_CONTRACT_BASE / owner_id
        if NAS_CONTRACT_BASE.exists():
            nas_owner_dir.mkdir(parents=True, exist_ok=True)
            nas_dest = nas_owner_dir / filename
            shutil.copy2(str(pdf_path), str(nas_dest))
            nas_path = str(nas_dest)
            logger.info("prospectus_nas_copy", nas_path=nas_path)
    except Exception as e:
        logger.warning("prospectus_nas_copy_failed", error=str(e)[:200])

    return {
        "pdf_path": str(pdf_path),
        "nas_path": nas_path,
        "rendered_html": rendered_html,
        "payload": payload,
    }
