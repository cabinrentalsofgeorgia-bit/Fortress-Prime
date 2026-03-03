"""
Civil Engineering Discipline Analyzer
========================================
The ground truth. Handles site plans, grading, drainage, septic systems,
surveys, stormwater management, and erosion control.

Mountain cabin specifics (Fannin County, GA):
    - Steep terrain: 15-45% slopes common
    - Well water + septic (no municipal services)
    - Gravel access roads / shared driveways
    - Mountain streams / wetland buffers (50' state buffer)
    - Heavy rainfall events (flash flood risk)
    - Soil types: rocky clay, decomposed granite
    - Percolation rates vary wildly by ridge vs. valley
    - Fannin County Health Department for septic permits
    - Georgia EPD for stormwater / erosion (>1 acre disturbed)
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_engineering.civil")

ANALYSIS_MODEL = "deepseek-r1:8b"


# =============================================================================
# SEPTIC SYSTEM ANALYSIS
# =============================================================================

def analyze_septic_system(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a septic system document (plan, permit, or inspection).

    Septic is CRITICAL for mountain rental properties:
    - Overloaded septic = health hazard + county violation
    - System capacity must match max occupancy (bedrooms × 2)
    - Pump schedule based on usage (rentals = higher frequency)
    - Drain field lifespan: 15-25 years depending on soil/usage
    """
    prompt = f"""Analyze this septic system document for a mountain cabin rental property.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "system_type": "conventional/advanced/mound/drip_irrigation/aerobic/unknown",
    "tank_size_gallons": number or null,
    "bedrooms_rated": number of bedrooms the system is rated for or null,
    "max_daily_flow_gpd": gallons per day capacity or null,
    "drain_field_type": "conventional/chamber/gravel_trench/drip/unknown",
    "drain_field_length_ft": linear feet or null,
    "soil_type": "identified soil type or null",
    "perc_rate_mpi": "minutes per inch or null",
    "install_date": "YYYY-MM-DD or null",
    "last_pump_date": "YYYY-MM-DD or null",
    "permit_number": "permit number or null",
    "setbacks_met": true/false/null,
    "issues": ["any problems or concerns identified"],
    "recommendations": ["maintenance or upgrade recommendations"]
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }

    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        response = resp.json().get("response", "")
        clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))

            # Apply rental property business logic
            if result.get("bedrooms_rated") and result.get("max_daily_flow_gpd"):
                # Rental occupancy rule: bedrooms × 2 guests × 75 gpd/person
                max_guests = result["bedrooms_rated"] * 2
                daily_demand = max_guests * 75
                if daily_demand > result["max_daily_flow_gpd"]:
                    result.setdefault("issues", []).append(
                        f"CAPACITY WARNING: Max occupancy ({max_guests} guests) "
                        f"demands ~{daily_demand} gpd, system rated for "
                        f"{result['max_daily_flow_gpd']} gpd"
                    )

            return result
    except Exception as e:
        logger.error(f"Septic analysis failed: {e}")

    return {"error": "Analysis failed"}


def calculate_septic_pump_schedule(
    tank_size_gallons: int,
    bedrooms: int,
    is_rental: bool = True,
    avg_occupancy_pct: float = 0.65,
) -> Dict[str, Any]:
    """
    Calculate recommended septic pump frequency based on usage.

    Rental properties need more frequent pumping due to:
    - Higher guest turnover (more laundry, more cleaning)
    - Guests less careful about what goes down drains
    - Peak season = near-continuous occupancy
    """
    # Base annual flow calculation
    max_occupants = bedrooms * 2
    avg_occupants = max_occupants * avg_occupancy_pct
    daily_flow = avg_occupants * 75  # gpd per person
    annual_flow = daily_flow * 365

    # Sludge accumulation rate (higher for rentals)
    sludge_rate_gpd = 0.5 if is_rental else 0.3  # gallons/person/day
    annual_sludge = avg_occupants * sludge_rate_gpd * 365

    # Pump when sludge reaches 1/3 of tank capacity
    pump_threshold = tank_size_gallons / 3
    months_to_pump = (pump_threshold / annual_sludge) * 12

    # Cap between 6 months and 36 months
    months_to_pump = max(6, min(36, months_to_pump))

    return {
        "tank_size_gallons": tank_size_gallons,
        "bedrooms": bedrooms,
        "is_rental": is_rental,
        "avg_occupancy_pct": avg_occupancy_pct,
        "max_occupants": max_occupants,
        "avg_daily_flow_gpd": round(daily_flow, 0),
        "annual_flow_gallons": round(annual_flow, 0),
        "recommended_pump_interval_months": round(months_to_pump),
        "note": (
            "Rental properties should pump every "
            f"{round(months_to_pump)} months. "
            "Increase frequency during peak season (Jun-Oct)."
        ),
    }


# =============================================================================
# SITE ANALYSIS
# =============================================================================

def analyze_site_plan(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a site plan to extract terrain, access, setbacks, utilities,
    and environmental constraints.
    """
    prompt = f"""Analyze this site plan for a mountain cabin property in Fannin County, Georgia.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "lot_size_acres": number or null,
    "building_footprint_sqft": number or null,
    "slope_percentage": "average slope or null",
    "access_type": "paved/gravel/dirt/shared_driveway/unknown",
    "driveway_length_ft": number or null,
    "driveway_grade_pct": number or null,
    "water_source": "well/municipal/spring/unknown",
    "sewer_type": "septic/municipal/unknown",
    "power_source": "utility/solar/generator/unknown",
    "setbacks": {{
        "front_ft": number or null,
        "side_ft": number or null,
        "rear_ft": number or null
    }},
    "stream_buffer_ft": number or null,
    "wetland_present": true/false/null,
    "flood_zone": "zone designation or null",
    "retaining_walls": true/false,
    "erosion_control": "type of erosion control or null",
    "impervious_coverage_pct": number or null,
    "issues": ["any concerns identified"],
    "notes": "additional relevant information"
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }

    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        response = resp.json().get("response", "")
        clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))

            # Mountain-specific compliance checks
            issues = result.get("issues", [])

            slope = result.get("slope_percentage")
            if slope and isinstance(slope, (int, float)) and slope > 25:
                issues.append(
                    f"STEEP SLOPE WARNING: {slope}% grade — may require "
                    "special foundation and erosion control measures"
                )

            stream_buf = result.get("stream_buffer_ft")
            if stream_buf and isinstance(stream_buf, (int, float)) and stream_buf < 50:
                issues.append(
                    "STREAM BUFFER VIOLATION: Georgia requires minimum "
                    "50-foot buffer from perennial streams (O.C.G.A. 12-7-6)"
                )

            driveway_grade = result.get("driveway_grade_pct")
            if driveway_grade and isinstance(driveway_grade, (int, float)) and driveway_grade > 15:
                issues.append(
                    f"STEEP DRIVEWAY: {driveway_grade}% grade — "
                    "may be hazardous in winter (ice/snow). "
                    "Consider heated driveway or paving"
                )

            result["issues"] = issues
            return result
    except Exception as e:
        logger.error(f"Site plan analysis failed: {e}")

    return {"error": "Analysis failed"}


def check_stormwater_compliance(
    lot_size_acres: float,
    impervious_pct: float,
    slope_pct: float,
) -> Dict[str, Any]:
    """
    Check Georgia EPD stormwater compliance requirements.

    Key triggers:
    - > 1 acre disturbed: Georgia General Permit (GAR 100001) required
    - > 25% impervious: enhanced stormwater management needed
    - > 25% slope: erosion control plan required regardless of size
    """
    requirements = []
    permits_needed = []

    if lot_size_acres > 1.0:
        requirements.append(
            "Georgia EPD General Permit (GAR 100001) required — "
            "land disturbance > 1 acre"
        )
        permits_needed.append("GAR_100001_Stormwater")

    if impervious_pct > 25:
        requirements.append(
            "Enhanced stormwater management required — "
            f"impervious coverage {impervious_pct}% exceeds 25% threshold"
        )

    if slope_pct > 25:
        requirements.append(
            "Erosion and sediment control plan required — "
            f"slope {slope_pct}% exceeds 25% threshold"
        )
        permits_needed.append("Erosion_Control_Plan")

    if lot_size_acres > 5.0:
        requirements.append(
            "Stormwater Pollution Prevention Plan (SWPPP) required — "
            "disturbance > 5 acres"
        )
        permits_needed.append("SWPPP")

    return {
        "lot_size_acres": lot_size_acres,
        "impervious_pct": impervious_pct,
        "slope_pct": slope_pct,
        "compliant": len(requirements) == 0,
        "requirements": requirements,
        "permits_needed": permits_needed,
        "jurisdiction": "Georgia EPD / Fannin County",
    }


# =============================================================================
# SURVEY ANALYSIS
# =============================================================================

def analyze_survey(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a boundary or topographic survey to extract property boundaries,
    easements, encroachments, and topographic features.
    """
    prompt = f"""Analyze this property survey for a mountain property in Fannin County, Georgia.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "survey_type": "boundary/topographic/alta/construction/as-built",
    "surveyor_name": "surveyor name or null",
    "survey_date": "YYYY-MM-DD or null",
    "lot_size_acres": number or null,
    "parcel_id": "county parcel ID or null",
    "deed_book_page": "book/page reference or null",
    "boundaries": ["description of boundary lines"],
    "easements": ["list of recorded easements"],
    "encroachments": ["any encroachments noted"],
    "elevation_range_ft": {{"min": number, "max": number}} or null,
    "benchmarks": ["survey benchmarks noted"],
    "utilities_shown": ["utilities visible on survey"],
    "streams_wetlands": ["water features identified"],
    "flood_zone": "FEMA flood zone or null",
    "issues": ["any concerns or discrepancies noted"]
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }

    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        response = resp.json().get("response", "")
        clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        logger.error(f"Survey analysis failed: {e}")

    return {"error": "Analysis failed"}
