"""
Mechanical (MEP) Discipline Analyzer
========================================
The systems brain. Handles HVAC, plumbing, electrical, fire protection,
hot tubs, generators, and all building systems.

Mountain cabin MEP specifics (Blue Ridge, GA):
    - HVAC: Heat pumps common (dual fuel w/ propane backup for deep cold)
    - Plumbing: Well water systems, septic (see civil), hot tubs standard
    - Electrical: 200A typical, whole-house generators common (winter storms)
    - Fire: Wood-burning fireplaces, gas logs; smoke/CO detectors critical
    - Hot tubs: 220V dedicated circuit, GFCI, proper drainage/pad
    - Elevation: 2000-4000ft — affects HVAC sizing (altitude correction)
    - Winter: Freeze protection mandatory (pipe insulation, heat tape)
    - Propane: LP gas common for heat, fireplaces, range, water heater
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_engineering.mechanical")

ANALYSIS_MODEL = "deepseek-r1:8b"


# =============================================================================
# HVAC ANALYSIS
# =============================================================================

def analyze_hvac_system(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an HVAC document (plan, load calculation, or specification)
    to extract system details and evaluate sizing adequacy.
    """
    prompt = f"""Analyze this HVAC document for a mountain cabin in Blue Ridge, Georgia.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "system_type": "heat_pump/furnace/boiler/mini_split/geothermal/unknown",
    "fuel_type": "electric/propane/natural_gas/dual_fuel/unknown",
    "heating_capacity_btu": number or null,
    "cooling_capacity_tons": number or null,
    "seer_rating": number or null,
    "hspf_rating": number or null,
    "manufacturer": "brand name or null",
    "model_number": "model or null",
    "zones": number of zones or null,
    "ductwork_type": "flex/rigid/ductless/unknown",
    "thermostat_type": "programmable/smart/manual/unknown",
    "supplemental_heat": "propane/electric_strip/wood/none/unknown",
    "filter_size": "filter dimensions or null",
    "condensate_drain": "gravity/pump/unknown",
    "install_date": "YYYY-MM-DD or null",
    "sqft_served": number or null,
    "altitude_correction_applied": true/false/null,
    "issues": ["any concerns identified"],
    "recommendations": ["maintenance or upgrade recommendations"]
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.15, "num_predict": 1024},
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

            # Mountain-specific HVAC checks
            issues = result.get("issues", [])

            seer = result.get("seer_rating")
            if seer and isinstance(seer, (int, float)) and seer < 14:
                issues.append(
                    f"LOW EFFICIENCY: SEER {seer} below current minimum (14). "
                    "Consider upgrade for energy savings."
                )

            if result.get("system_type") == "heat_pump" and not result.get("supplemental_heat"):
                issues.append(
                    "Heat pump without supplemental heat — Blue Ridge temps "
                    "can drop below heat pump effective range (< 25F). "
                    "Recommend propane or electric strip backup."
                )

            if not result.get("altitude_correction_applied"):
                issues.append(
                    "Altitude correction may not be applied — Blue Ridge "
                    "elevation (2000-4000ft) affects HVAC capacity ~5-10%"
                )

            result["issues"] = issues
            return result
    except Exception as e:
        logger.error(f"HVAC analysis failed: {e}")

    return {"error": "Analysis failed"}


def calculate_hvac_sizing(
    sqft: float,
    levels: int = 1,
    insulation_quality: str = "average",
    elevation_ft: float = 2500,
    num_windows: int = 10,
    vaulted_ceiling: bool = False,
) -> Dict[str, Any]:
    """
    Rough HVAC sizing calculation for a mountain cabin.

    This is a Manual J approximation — NOT a replacement for a
    proper ACCA Manual J calculation, but useful for quick validation.

    Blue Ridge specifics:
    - Design heating temp: ~10F (-12C)
    - Design cooling temp: ~92F (33C)
    - Altitude derating: ~4% per 1000ft above 1000ft
    """
    # Base BTU per sqft by insulation quality
    base_btu_per_sqft = {
        "poor": 45,
        "average": 35,
        "good": 28,
        "excellent": 22,
    }

    base = base_btu_per_sqft.get(insulation_quality, 35)

    # Adjustments
    btu_total = sqft * base

    # Multi-level adjustment (+10% per additional level)
    btu_total *= 1 + (levels - 1) * 0.10

    # Vaulted ceiling adjustment (+15%)
    if vaulted_ceiling:
        btu_total *= 1.15

    # Window adjustment (large windows = more loss)
    if num_windows > 15:
        btu_total *= 1.10

    # Altitude derating (~4% per 1000ft above 1000ft for combustion equipment)
    altitude_factor = max(0, (elevation_ft - 1000) / 1000) * 0.04
    btu_total *= (1 + altitude_factor)

    # Convert to tons for cooling
    tons = btu_total / 12000

    return {
        "sqft": sqft,
        "levels": levels,
        "insulation_quality": insulation_quality,
        "elevation_ft": elevation_ft,
        "heating_btu_recommended": round(btu_total),
        "cooling_tons_recommended": round(tons * 0.8, 1),  # Cooling ~80% of heating
        "altitude_correction_factor": round(altitude_factor, 3),
        "note": (
            "Approximation only — formal Manual J calculation required "
            "for permit applications. Consult licensed HVAC contractor."
        ),
    }


# =============================================================================
# ELECTRICAL ANALYSIS
# =============================================================================

def analyze_electrical_system(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an electrical document (panel schedule, plan, or permit)
    to extract service size, circuit details, and code compliance.
    """
    prompt = f"""Analyze this electrical document for a mountain cabin rental property.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "service_size_amps": number or null,
    "voltage": "120/240 single phase or null",
    "panel_manufacturer": "brand or null",
    "panel_model": "model or null",
    "total_circuits": number or null,
    "available_spaces": number of open breaker spaces or null,
    "has_gfci_protection": true/false/null,
    "has_afci_protection": true/false/null,
    "has_whole_house_surge": true/false/null,
    "hot_tub_circuit": "circuit details or null",
    "generator_transfer_switch": true/false/null,
    "generator_size_kw": number or null,
    "smoke_detectors": "hardwired/battery/combination/unknown",
    "co_detectors": true/false/null,
    "outdoor_lighting": "type and wattage or null",
    "ev_charger_ready": true/false/null,
    "issues": ["any concerns identified"],
    "nec_violations": ["specific NEC code violations if any"]
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.15, "num_predict": 1024},
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

            # Rental property electrical checks
            issues = result.get("issues", [])

            service = result.get("service_size_amps")
            if service and isinstance(service, (int, float)) and service < 200:
                issues.append(
                    f"UNDERSIZED SERVICE: {service}A service — "
                    "200A recommended for rental cabins with hot tubs, "
                    "HVAC, and appliances"
                )

            if result.get("hot_tub_circuit") and not result.get("has_gfci_protection"):
                issues.append(
                    "HOT TUB WITHOUT GFCI: NEC 680.44 requires GFCI protection "
                    "for all hot tub/spa circuits"
                )

            if not result.get("generator_transfer_switch"):
                issues.append(
                    "No generator transfer switch detected — "
                    "recommended for mountain properties (winter storms)"
                )

            if not result.get("co_detectors"):
                issues.append(
                    "CO detectors not confirmed — required in rental properties "
                    "with fuel-burning appliances or attached garage"
                )

            result["issues"] = issues
            return result
    except Exception as e:
        logger.error(f"Electrical analysis failed: {e}")

    return {"error": "Analysis failed"}


# =============================================================================
# PLUMBING ANALYSIS
# =============================================================================

def analyze_plumbing_system(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a plumbing document for a mountain cabin.

    Key mountain cabin plumbing concerns:
    - Well water: pump, pressure tank, filtration, UV treatment
    - Hot water: tankless vs. tank, sized for hot tub + occupancy
    - Freeze protection: heat tape, insulation, pipe routing
    - Septic: see civil discipline
    """
    prompt = f"""Analyze this plumbing document for a mountain cabin rental property.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "water_source": "well/municipal/spring/unknown",
    "well_depth_ft": number or null,
    "well_pump_hp": number or null,
    "pressure_tank_gallons": number or null,
    "water_treatment": "type of treatment system or null",
    "uv_purification": true/false/null,
    "water_softener": true/false/null,
    "water_heater_type": "tankless/tank/heat_pump/solar/unknown",
    "water_heater_gallons": number or null,
    "water_heater_fuel": "electric/propane/natural_gas/unknown",
    "hot_tub_plumbing": true/false/null,
    "bathroom_count": number or null,
    "fixture_count": total number of fixtures or null,
    "main_line_size": "pipe diameter or null",
    "pipe_material": "PEX/copper/CPVC/galvanized/unknown",
    "freeze_protection": "heat_tape/insulation/both/none/unknown",
    "hose_bibs": number of outdoor faucets or null,
    "issues": ["any concerns identified"],
    "recommendations": ["maintenance or upgrade recommendations"]
}}"""

    payload = {
        "model": ANALYSIS_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.15, "num_predict": 1024},
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

            issues = result.get("issues", [])

            # Mountain cabin freeze protection
            if result.get("freeze_protection") in ("none", None):
                issues.append(
                    "FREEZE PROTECTION MISSING: Blue Ridge winter temps "
                    "regularly drop below freezing. Heat tape and insulation "
                    "mandatory for exposed pipes."
                )

            # Well water treatment for rentals
            if result.get("water_source") == "well" and not result.get("uv_purification"):
                issues.append(
                    "Well water without UV purification — recommended for "
                    "rental properties to ensure potable water for guests"
                )

            # Hot tub water heater sizing
            if result.get("hot_tub_plumbing"):
                wh_gallons = result.get("water_heater_gallons") or 0
                if wh_gallons and wh_gallons < 50:
                    issues.append(
                        f"Water heater ({wh_gallons} gal) may be undersized "
                        "for property with hot tub — consider 75+ gallon or "
                        "tankless with adequate flow rate"
                    )

            result["issues"] = issues
            return result
    except Exception as e:
        logger.error(f"Plumbing analysis failed: {e}")

    return {"error": "Analysis failed"}


# =============================================================================
# MEP SYSTEM LIFECYCLE TRACKING
# =============================================================================

def assess_mep_system_health(
    system_type: str,
    install_date: Optional[str],
    last_service_date: Optional[str],
    condition: str = "unknown",
) -> Dict[str, Any]:
    """
    Assess the health of a MEP system and recommend maintenance/replacement.

    Expected lifespans for mountain cabin equipment:
    - HVAC heat pump: 12-15 years
    - Furnace: 15-20 years
    - Water heater (tank): 8-12 years
    - Water heater (tankless): 15-20 years
    - Well pump: 8-15 years
    - Hot tub: 5-10 years (rental use reduces lifespan)
    - Electrical panel: 25-40 years
    - Septic tank: 20-30 years (with proper pumping)
    - Generator: 15-25 years
    """
    expected_lifespans = {
        "heat_pump": 13,
        "hvac": 13,
        "furnace": 17,
        "ac_condenser": 13,
        "water_heater": 10,
        "tankless_water_heater": 17,
        "well_pump": 12,
        "hot_tub": 7,
        "electrical_panel": 30,
        "septic": 25,
        "generator": 20,
        "fireplace": 30,
        "smoke_detector": 10,
        "co_detector": 7,
        "fire_extinguisher": 12,
    }

    # Service intervals (months) for rental properties
    service_intervals = {
        "heat_pump": 6,
        "hvac": 6,
        "furnace": 12,
        "ac_condenser": 12,
        "water_heater": 12,
        "well_pump": 12,
        "hot_tub": 3,
        "generator": 6,
        "fireplace": 12,
        "smoke_detector": 6,
        "co_detector": 6,
        "fire_extinguisher": 12,
    }

    expected_life = expected_lifespans.get(system_type, 15)
    service_interval = service_intervals.get(system_type, 12)

    result = {
        "system_type": system_type,
        "expected_lifespan_years": expected_life,
        "service_interval_months": service_interval,
        "condition": condition,
        "alerts": [],
        "recommendations": [],
    }

    now = datetime.now(timezone.utc)

    if install_date:
        try:
            installed = datetime.fromisoformat(install_date).replace(tzinfo=timezone.utc)
            age_years = (now - installed).days / 365.25
            result["age_years"] = round(age_years, 1)
            result["remaining_life_years"] = round(expected_life - age_years, 1)

            if age_years > expected_life:
                result["alerts"].append(
                    f"PAST EXPECTED LIFESPAN: {age_years:.1f} years old "
                    f"(expected {expected_life} years). Replace immediately."
                )
                result["condition"] = "critical"
            elif age_years > expected_life * 0.85:
                result["alerts"].append(
                    f"APPROACHING END OF LIFE: {age_years:.1f} years old "
                    f"(expected {expected_life} years). Plan replacement."
                )
                if condition in ("unknown", "good"):
                    result["condition"] = "fair"
            elif age_years > expected_life * 0.65:
                result["recommendations"].append(
                    f"System is {age_years:.1f} years into {expected_life}-year "
                    f"expected life. Increase monitoring frequency."
                )
        except (ValueError, TypeError):
            pass

    if last_service_date:
        try:
            last_svc = datetime.fromisoformat(last_service_date).replace(tzinfo=timezone.utc)
            months_since = (now - last_svc).days / 30.44
            result["months_since_service"] = round(months_since, 1)

            if months_since > service_interval * 1.5:
                result["alerts"].append(
                    f"SERVICE OVERDUE: Last serviced {months_since:.0f} months ago "
                    f"(interval: every {service_interval} months)"
                )
            elif months_since > service_interval:
                result["recommendations"].append(
                    f"Service due: last serviced {months_since:.0f} months ago "
                    f"(recommended every {service_interval} months)"
                )
        except (ValueError, TypeError):
            pass

    return result
