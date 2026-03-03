"""
Architectural Discipline Analyzer
====================================
The building design brain. Handles floor plans, elevations, sections,
finish schedules, ADA compliance, and renovation analysis.

Mountain cabin specifics:
    - Log/timber frame construction common
    - Steep roof pitches for snow load
    - Large decks/porches (mountain views)
    - Open floor plans with great rooms
    - Loft spaces and vaulted ceilings
    - Stone fireplaces / masonry chimneys
    - ADA ground-floor considerations for rental compliance
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_engineering.architectural")

ANALYSIS_MODEL = "deepseek-r1:8b"


def analyze_floor_plan(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a floor plan document to extract room counts, square footage,
    layout details, and ADA compliance indicators.
    """
    prompt = f"""Analyze this floor plan document for a mountain cabin property.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "total_sqft": estimated square footage or null,
    "bedrooms": number of bedrooms or null,
    "bathrooms": number of bathrooms or null,
    "levels": number of levels/floors or null,
    "rooms": ["list of identified rooms"],
    "has_loft": true/false,
    "has_basement": true/false,
    "has_garage": true/false,
    "has_deck": true/false,
    "deck_sqft": estimated deck square footage or null,
    "ada_accessible": true/false/null,
    "ada_notes": "any ADA-related notes or null",
    "construction_type": "log/timber_frame/stick_frame/hybrid/unknown",
    "roof_type": "gable/hip/shed/flat/combined/unknown",
    "fireplace": true/false,
    "great_room": true/false,
    "key_features": ["notable architectural features"],
    "concerns": ["any potential issues identified"]
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
            return json.loads(json_match.group(0))
    except Exception as e:
        logger.error(f"Floor plan analysis failed: {e}")

    return {"error": "Analysis failed"}


def analyze_renovation(
    ocr_text: str,
    filename: str,
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a renovation plan to extract scope, estimated cost impact,
    and required permits.
    """
    prompt = f"""Analyze this renovation plan for a mountain cabin rental property.

Property: {property_name or 'Unknown'}
Filename: {filename}

Document text:
---
{ocr_text[:3000]}
---

Extract as JSON:
{{
    "renovation_type": "interior/exterior/addition/structural/cosmetic",
    "scope_summary": "brief description of work",
    "rooms_affected": ["list of rooms or areas affected"],
    "structural_changes": true/false,
    "requires_permit": true/false,
    "permit_types_needed": ["building", "mechanical", "electrical", etc.],
    "estimated_duration_days": number or null,
    "estimated_cost_range": "low-high estimate or null",
    "ada_impact": "positive/negative/neutral/unknown",
    "rental_impact_days": "estimated days property offline for guests",
    "materials": ["key materials specified"],
    "concerns": ["any issues or red flags"]
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
            return json.loads(json_match.group(0))
    except Exception as e:
        logger.error(f"Renovation analysis failed: {e}")

    return {"error": "Analysis failed"}


def check_ada_compliance(
    floor_plan_data: Dict[str, Any],
    property_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate ADA compliance for a rental property floor plan.

    Georgia short-term rental ADA considerations:
    - Ground-floor accessible bedroom + bathroom preferred
    - 36" minimum doorway widths for accessible routes
    - Accessible bathroom: roll-in shower or tub with grab bars
    - Ramp access if no ground-level entry
    """
    issues = []
    recommendations = []

    bedrooms = floor_plan_data.get("bedrooms", 0) or 0
    levels = floor_plan_data.get("levels", 1) or 1
    ada_accessible = floor_plan_data.get("ada_accessible")

    if levels > 1 and not floor_plan_data.get("has_basement"):
        issues.append(
            "Multi-level cabin — verify ground-floor bedroom + bath available"
        )
        recommendations.append(
            "Consider adding ground-floor accessible suite if not present"
        )

    if ada_accessible is False:
        issues.append("Floor plan indicates NOT ADA accessible")
        recommendations.append(
            "Evaluate feasibility of ADA retrofit: ramp, widened doors, "
            "accessible bathroom"
        )

    if floor_plan_data.get("has_loft") and bedrooms and bedrooms <= 2:
        issues.append(
            "Loft bedroom may be only sleeping option — not ADA accessible"
        )

    return {
        "property_name": property_name,
        "ada_status": "compliant" if not issues else "needs_review",
        "issues": issues,
        "recommendations": recommendations,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }


def estimate_replacement_cost(
    total_sqft: float,
    construction_type: str = "stick_frame",
    quality_tier: str = "standard",
) -> Dict[str, Any]:
    """
    Estimate construction replacement cost per square foot.
    Based on Fannin County / North Georgia mountain construction rates.

    These are 2025-2026 baseline rates for the Blue Ridge area.
    """
    # Base cost per sqft by construction type (2026 Blue Ridge rates)
    base_rates = {
        "stick_frame": 175.0,
        "log": 225.0,
        "timber_frame": 250.0,
        "hybrid": 200.0,
        "unknown": 190.0,
    }

    # Quality multipliers
    quality_multipliers = {
        "economy": 0.80,
        "standard": 1.00,
        "premium": 1.30,
        "luxury": 1.60,
    }

    base = base_rates.get(construction_type, 190.0)
    multiplier = quality_multipliers.get(quality_tier, 1.0)
    cost_per_sqft = base * multiplier
    total_cost = cost_per_sqft * total_sqft

    return {
        "construction_type": construction_type,
        "quality_tier": quality_tier,
        "cost_per_sqft": round(cost_per_sqft, 2),
        "total_sqft": total_sqft,
        "estimated_replacement_cost": round(total_cost, 2),
        "note": "2026 Blue Ridge, GA baseline estimate — does not include land value",
    }
