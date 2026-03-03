"""
Engineering Code Compliance Engine
=====================================
Enforces Georgia building codes, Fannin County regulations, and
engineering standards for all cabin properties.

Jurisdiction Hierarchy:
    1. International Building Code (IBC) 2018 — Georgia adopted version
    2. International Residential Code (IRC) 2018 — for 1/2-family dwellings
    3. Georgia DCA Amendments — state-specific modifications
    4. Fannin County Building Department — local amendments
    5. Georgia EPD — environmental (stormwater, septic, erosion)
    6. Fannin County Health Department — septic permits
    7. NEC 2020 — National Electrical Code
    8. Georgia Energy Code (IECC 2015) — insulation, HVAC efficiency

Mountain Cabin Specific Concerns:
    - Snow load: 10-15 psf ground snow (Blue Ridge area)
    - Wind: 115 mph basic wind speed (ASCE 7-16)
    - Seismic: SDC B (low-moderate)
    - Frost depth: 12" minimum
    - Wildfire: WUI interface areas
    - Slope: foundation requirements for grades > 15%
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("division_engineering.compliance")


# =============================================================================
# CODE REFERENCE DATABASE
# =============================================================================

@dataclass
class CodeRequirement:
    """A specific building code requirement."""
    code: str                   # e.g., "IRC R310.1"
    title: str                  # Human-readable title
    description: str            # What it requires
    jurisdiction: str           # IBC, IRC, NEC, Georgia DCA, Fannin County
    discipline: str             # architectural, structural, mechanical, etc.
    severity: str = "HIGH"      # CRITICAL, HIGH, MEDIUM, LOW
    applies_to: str = "all"     # all, new_construction, renovation, rental


# Georgia / Fannin County Code Requirements for Mountain Cabins
CABIN_CODE_REQUIREMENTS: List[CodeRequirement] = [
    # ── ARCHITECTURAL ───────────────────────────────────────────
    CodeRequirement(
        code="IRC R310.1",
        title="Emergency Escape and Rescue Openings",
        description=(
            "Every sleeping room must have at least one emergency escape "
            "opening (egress window). Min 5.7 sqft net clear opening, "
            "min 24\" high, min 20\" wide, max 44\" sill height."
        ),
        jurisdiction="IRC 2018",
        discipline="architectural",
        severity="CRITICAL",
        applies_to="all",
    ),
    CodeRequirement(
        code="IRC R311.7",
        title="Stairway Requirements",
        description=(
            "Stairways: min 36\" width, max 7-3/4\" riser height, "
            "min 10\" tread depth. Handrails required on at least one side "
            "(34-38\" height). Open risers not permitted if stair > 30\" above grade."
        ),
        jurisdiction="IRC 2018",
        discipline="architectural",
        severity="HIGH",
    ),
    CodeRequirement(
        code="IRC R312.1",
        title="Guards (Deck Railings)",
        description=(
            "Guards required on open-sided walking surfaces > 30\" above "
            "grade. Min 36\" height (42\" for commercial/rental). "
            "Balusters spaced max 4\" apart (child safety)."
        ),
        jurisdiction="IRC 2018",
        discipline="architectural",
        severity="CRITICAL",
        applies_to="all",
    ),
    CodeRequirement(
        code="GA_DCA_120-3-20",
        title="Georgia Accessibility (Fair Housing)",
        description=(
            "Short-term rentals with 4+ units on a property must provide "
            "accessible ground-floor units per Fair Housing Act. "
            "Individual cabins: ADA recommended but not mandated "
            "unless public accommodation."
        ),
        jurisdiction="Georgia DCA",
        discipline="architectural",
        severity="MEDIUM",
        applies_to="rental",
    ),

    # ── STRUCTURAL ──────────────────────────────────────────────
    CodeRequirement(
        code="IRC R301.2.3",
        title="Snow Load — Blue Ridge (Fannin County)",
        description=(
            "Ground snow load: 10-15 psf (varies by elevation). "
            "Roof snow load calculated per ASCE 7-16 based on slope, "
            "exposure, and thermal factor. Log/timber frames may need "
            "additional analysis for drift loads."
        ),
        jurisdiction="IRC 2018 / ASCE 7-16",
        discipline="structural",
        severity="HIGH",
    ),
    CodeRequirement(
        code="IRC R403.1",
        title="Foundation — Frost Depth",
        description=(
            "Foundations must extend minimum 12\" below grade "
            "(Fannin County frost depth). Deeper for steep slopes. "
            "Pier/post foundations common for mountain cabins but "
            "require engineering for slopes > 15%."
        ),
        jurisdiction="IRC 2018",
        discipline="structural",
        severity="HIGH",
    ),
    CodeRequirement(
        code="IRC R301.2.1",
        title="Wind Speed Design",
        description=(
            "Basic wind speed: 115 mph (ASCE 7-16, Risk Category II). "
            "Exposure B (suburban/wooded) typical for mountain sites. "
            "Ridge-top sites may be Exposure C (open). Affects "
            "roof framing, window ratings, and deck connections."
        ),
        jurisdiction="IRC 2018 / ASCE 7-16",
        discipline="structural",
        severity="HIGH",
    ),

    # ── FIRE PROTECTION ─────────────────────────────────────────
    CodeRequirement(
        code="IRC R314.3",
        title="Smoke Alarms — Rental Properties",
        description=(
            "Smoke alarms required in every sleeping room, outside each "
            "sleeping area, and on every level (including basement). "
            "Must be interconnected (hardwired or wireless). "
            "10-year sealed lithium battery models acceptable for retrofit."
        ),
        jurisdiction="IRC 2018 / Georgia Fire Code",
        discipline="fire_protection",
        severity="CRITICAL",
        applies_to="rental",
    ),
    CodeRequirement(
        code="IRC R315.1",
        title="Carbon Monoxide Alarms",
        description=(
            "CO alarms required outside each sleeping area when property "
            "has fuel-burning appliances (propane, gas, wood fireplace) "
            "or an attached garage. Required in all rental properties."
        ),
        jurisdiction="IRC 2018 / Georgia Fire Code",
        discipline="fire_protection",
        severity="CRITICAL",
        applies_to="rental",
    ),
    CodeRequirement(
        code="NFPA_211",
        title="Chimney & Fireplace Safety",
        description=(
            "Wood-burning fireplaces and chimneys must comply with NFPA 211. "
            "Annual inspection required. Clearance to combustibles: 2\" min "
            "for masonry, per manufacturer specs for factory-built. "
            "Spark arrester required on chimney cap."
        ),
        jurisdiction="NFPA 211",
        discipline="fire_protection",
        severity="HIGH",
    ),

    # ── ELECTRICAL ──────────────────────────────────────────────
    CodeRequirement(
        code="NEC_680.44",
        title="Hot Tub / Spa GFCI Protection",
        description=(
            "All hot tub/spa circuits must have GFCI protection. "
            "Dedicated 220V/240V circuit required (40-60A typical). "
            "Disconnect switch within sight, 5-50 feet from tub. "
            "No overhead conductors within 22.5 feet horizontally."
        ),
        jurisdiction="NEC 2020",
        discipline="electrical",
        severity="CRITICAL",
    ),
    CodeRequirement(
        code="NEC_210.8",
        title="GFCI Requirements — Kitchens, Baths, Outdoors",
        description=(
            "GFCI protection required for all receptacles in kitchens "
            "(within 6' of sink), bathrooms, outdoors, garages, crawl spaces, "
            "and unfinished basements. AFCI required for all bedroom circuits."
        ),
        jurisdiction="NEC 2020",
        discipline="electrical",
        severity="HIGH",
    ),
    CodeRequirement(
        code="NEC_702",
        title="Generator Transfer Switch",
        description=(
            "Permanently installed generators must have a code-compliant "
            "transfer switch to prevent backfeed to utility lines. "
            "Recommended for all mountain properties due to frequent "
            "winter storm outages."
        ),
        jurisdiction="NEC 2020",
        discipline="electrical",
        severity="MEDIUM",
    ),

    # ── PLUMBING ────────────────────────────────────────────────
    CodeRequirement(
        code="GA_DHR_290-5-26",
        title="Septic System — Fannin County Health Dept",
        description=(
            "All septic systems must be permitted by Fannin County Health "
            "Department. System size based on bedroom count (not occupancy). "
            "Percolation test required. Professional engineer required for "
            "advanced systems (mound, drip, aerobic)."
        ),
        jurisdiction="Georgia DHR / Fannin County",
        discipline="civil",
        severity="CRITICAL",
    ),
    CodeRequirement(
        code="IRC_P2904",
        title="Water Supply — Private Well",
        description=(
            "Private wells must meet Georgia EPD requirements. "
            "Well construction standards per Georgia Water Well Standards Act. "
            "Water quality testing recommended annually for rental properties. "
            "UV treatment recommended for guest safety."
        ),
        jurisdiction="Georgia EPD / IRC 2018",
        discipline="plumbing",
        severity="HIGH",
    ),
    CodeRequirement(
        code="IRC_P2603.5",
        title="Freeze Protection — Piping",
        description=(
            "All water piping in unconditioned spaces must be insulated. "
            "Heat tape required for exposed exterior pipes in Fannin County "
            "(freeze zone). Outdoor hose bibs must be frost-free type "
            "or have accessible shutoff valves for winter draining."
        ),
        jurisdiction="IRC 2018",
        discipline="plumbing",
        severity="HIGH",
    ),

    # ── ENERGY CODE ─────────────────────────────────────────────
    CodeRequirement(
        code="IECC_2015_R402",
        title="Georgia Energy Code — Insulation",
        description=(
            "Climate Zone 4A (Fannin County): "
            "Ceiling R-49, Wall R-20 or R-13+5, "
            "Floor R-19, Basement wall R-10/13, "
            "Slab R-10 (2ft depth). Windows U-0.35 max."
        ),
        jurisdiction="IECC 2015 (Georgia adopted)",
        discipline="mechanical",
        severity="MEDIUM",
        applies_to="new_construction",
    ),
]


# =============================================================================
# COMPLIANCE ENGINE
# =============================================================================

class ComplianceEngine:
    """
    Evaluates engineering documents and projects against applicable
    building codes and generates compliance reports.
    """

    def __init__(self):
        self.requirements = CABIN_CODE_REQUIREMENTS

    def evaluate_project(
        self,
        project_type: str = "renovation",
        disciplines: Optional[List[str]] = None,
        is_rental: bool = True,
        property_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a compliance checklist for a project.

        Returns applicable code requirements filtered by project type,
        disciplines, and property features.
        """
        applicable = []
        features = property_features or {}

        for req in self.requirements:
            # Filter by applies_to
            if req.applies_to == "rental" and not is_rental:
                continue
            if req.applies_to == "new_construction" and project_type != "new_construction":
                continue

            # Filter by discipline
            if disciplines and req.discipline not in disciplines:
                continue

            applicable.append({
                "code": req.code,
                "title": req.title,
                "description": req.description,
                "jurisdiction": req.jurisdiction,
                "discipline": req.discipline,
                "severity": req.severity,
                "status": "unchecked",
            })

        # Add feature-specific requirements
        if features.get("has_hot_tub"):
            # Ensure hot tub GFCI is in the list
            if not any(r["code"] == "NEC_680.44" for r in applicable):
                applicable.append({
                    "code": "NEC_680.44",
                    "title": "Hot Tub / Spa GFCI Protection",
                    "description": "GFCI and dedicated circuit required for hot tub",
                    "jurisdiction": "NEC 2020",
                    "discipline": "electrical",
                    "severity": "CRITICAL",
                    "status": "unchecked",
                })

        if features.get("has_fireplace") or features.get("has_gas_logs"):
            if not any(r["code"] == "NFPA_211" for r in applicable):
                applicable.append({
                    "code": "NFPA_211",
                    "title": "Chimney & Fireplace Safety",
                    "description": "Annual inspection required for fireplaces",
                    "jurisdiction": "NFPA 211",
                    "discipline": "fire_protection",
                    "severity": "HIGH",
                    "status": "unchecked",
                })

        # Sort by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        applicable.sort(key=lambda r: severity_order.get(r["severity"], 99))

        return {
            "project_type": project_type,
            "is_rental": is_rental,
            "disciplines": disciplines or ["all"],
            "total_requirements": len(applicable),
            "by_severity": {
                "CRITICAL": sum(1 for r in applicable if r["severity"] == "CRITICAL"),
                "HIGH": sum(1 for r in applicable if r["severity"] == "HIGH"),
                "MEDIUM": sum(1 for r in applicable if r["severity"] == "MEDIUM"),
                "LOW": sum(1 for r in applicable if r["severity"] == "LOW"),
            },
            "requirements": applicable,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def check_rental_safety(
        self,
        property_name: str,
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Quick safety audit for a rental property.

        Checks critical safety requirements that apply to ALL rental cabins:
        - Smoke alarms (every bedroom + every level)
        - CO alarms (if fuel-burning appliances)
        - Deck railings (if > 30" above grade)
        - Hot tub safety (if applicable)
        - Egress windows (every bedroom)
        - Fire extinguishers
        """
        checks = []
        critical_count = 0
        passed_count = 0

        # Smoke alarms
        smoke = features.get("smoke_detectors")
        status = "pass" if smoke else "fail"
        if status == "fail":
            critical_count += 1
        else:
            passed_count += 1
        checks.append({
            "item": "Smoke Alarms",
            "code": "IRC R314.3",
            "status": status,
            "detail": (
                "Smoke alarms in every bedroom, outside sleeping areas, "
                "every level" if status == "fail" else
                f"Smoke alarms: {smoke}"
            ),
        })

        # CO alarms
        has_fuel = (
            features.get("has_fireplace") or
            features.get("has_gas_logs") or
            features.get("propane", False) or
            features.get("has_garage", False)
        )
        co = features.get("co_detectors")
        if has_fuel:
            status = "pass" if co else "fail"
            if status == "fail":
                critical_count += 1
            else:
                passed_count += 1
            checks.append({
                "item": "CO Alarms",
                "code": "IRC R315.1",
                "status": status,
                "detail": (
                    "CO alarms required — fuel-burning appliances present"
                    if status == "fail" else f"CO alarms: {co}"
                ),
            })

        # Deck railings
        if features.get("has_deck"):
            railings = features.get("deck_railings_compliant")
            status = "pass" if railings else "unknown"
            if status == "unknown":
                checks.append({
                    "item": "Deck Railings",
                    "code": "IRC R312.1",
                    "status": "needs_inspection",
                    "detail": "Deck present — verify railings 42\" height, "
                              "4\" max baluster spacing",
                })
            else:
                passed_count += 1
                checks.append({
                    "item": "Deck Railings",
                    "code": "IRC R312.1",
                    "status": "pass",
                    "detail": "Deck railings compliant",
                })

        # Hot tub
        if features.get("has_hot_tub"):
            gfci = features.get("hot_tub_gfci")
            status = "pass" if gfci else "fail"
            if status == "fail":
                critical_count += 1
            else:
                passed_count += 1
            checks.append({
                "item": "Hot Tub GFCI",
                "code": "NEC 680.44",
                "status": status,
                "detail": (
                    "Hot tub circuit requires GFCI protection and "
                    "disconnect switch" if status == "fail" else
                    "Hot tub GFCI compliant"
                ),
            })

        # Egress windows
        bedrooms = features.get("bedrooms", 0)
        egress = features.get("egress_windows_verified")
        if bedrooms:
            status = "pass" if egress else "needs_inspection"
            checks.append({
                "item": "Egress Windows",
                "code": "IRC R310.1",
                "status": status,
                "detail": (
                    f"{bedrooms} bedrooms — verify egress windows in each"
                    if status == "needs_inspection" else
                    f"{bedrooms} bedrooms — egress windows verified"
                ),
            })
            if status == "pass":
                passed_count += 1

        # Fire extinguishers (rental best practice)
        extinguishers = features.get("fire_extinguishers")
        status = "pass" if extinguishers else "recommended"
        checks.append({
            "item": "Fire Extinguishers",
            "code": "Best Practice",
            "status": status,
            "detail": (
                "Fire extinguisher recommended in kitchen and near fireplace"
                if status == "recommended" else
                f"Fire extinguishers: {extinguishers}"
            ),
        })
        if status == "pass":
            passed_count += 1

        total = len(checks)
        return {
            "property_name": property_name,
            "total_checks": total,
            "passed": passed_count,
            "critical_failures": critical_count,
            "needs_inspection": sum(
                1 for c in checks if c["status"] == "needs_inspection"
            ),
            "overall_status": (
                "CRITICAL" if critical_count > 0 else
                "NEEDS_REVIEW" if any(
                    c["status"] in ("needs_inspection", "unknown")
                    for c in checks
                ) else "COMPLIANT"
            ),
            "checks": checks,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_requirements_by_discipline(
        self, discipline: str
    ) -> List[Dict[str, Any]]:
        """Get all code requirements for a specific discipline."""
        return [
            {
                "code": r.code,
                "title": r.title,
                "description": r.description,
                "jurisdiction": r.jurisdiction,
                "severity": r.severity,
            }
            for r in self.requirements
            if r.discipline == discipline
        ]
