#!/usr/bin/env python3
"""
=============================================================================
 THE LISTING DOCTOR — Operation Rebrand
 Cabin Rentals of Georgia  •  Fortress-Prime
=============================================================================
 Diagnoses underperforming listings and generates Fortune 500-grade
 marketing copy using DeepSeek-R1 as the Chief Marketing Officer.

 The Doctor:
   1. Pulls hard metadata from PostgreSQL (property, amenities, location)
   2. Pulls the Streamline listing description (the "Before" state)
   3. Pulls the QuantRevenue rate card (price positioning)
   4. Pulls the Foundry analysis (performance diagnosis)
   5. Feeds everything to R1 with a CMO-grade prompt
   6. Generates:
      - Airbnb Title (max 50 chars)
      - Hero Description (2-3 sentences, emotional hook)
      - 5 Benefit-Driven Bullet Points
      - "About This Space" narrative (250-350 words)
      - Suggested SEO keywords

 Usage:
   python3 src/listing_doctor.py cherokee_sunrise --target "Anniversary Couples"
   python3 src/listing_doctor.py rolling_river --target "Adventure Families"
   python3 src/listing_doctor.py the_rivers_edge --target "Corporate Retreats"

 Module: Operation Rebrand — CF-02 QuantRevenue / CF-07 Command Center
=============================================================================
"""

import os
import re
import sys
import json
import time
import html
import argparse
import logging
from datetime import datetime, date
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests as http_requests

try:
    from dotenv import load_dotenv
    load_dotenv("/home/admin/Fortress-Prime/.env")
except ImportError:
    pass

# ─── Configuration ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs" / "listing_doctor"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", "5432"))
PG_DB = os.getenv("DB_NAME", "fortress_db")
PG_USER = os.getenv("DB_USER", "miner_bot")
PG_PASS = os.getenv("DB_PASSWORD", "")

OLLAMA_URL = os.getenv("LLM_URL", "http://localhost:11434/api/chat")
LLM_MODEL = "deepseek-r1:70b"   # The CMO doesn't send a clerk
LLM_FAST = "deepseek-r1:8b"     # Fast mode for iteration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ListingDoctor] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("listing_doctor")


def get_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER,
        password=PG_PASS if PG_PASS else None,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def clean_html(text: str) -> str:
    """Strip HTML tags and decode entities from Streamline descriptions."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =============================================================================
# 1. PROPERTY INTELLIGENCE GATHERER
# =============================================================================

def gather_property_intel(property_name: str) -> dict:
    """
    Pull every piece of intelligence we have on a property.
    Returns a rich dict with metadata, listing content, performance, and pricing.
    """
    conn = get_db()
    cur = conn.cursor()

    # Normalize name for fuzzy matching
    normalized = property_name.lower().replace(" ", "_").replace("-", "_").replace("'", "")

    # 1. Core property record
    cur.execute("""
        SELECT * FROM ops_properties
        WHERE LOWER(REPLACE(internal_name, ' ', '_')) LIKE %s
           OR property_id LIKE %s
        LIMIT 1
    """, (f"%{normalized[:20]}%", f"%{normalized[:20]}%"))
    prop = cur.fetchone()
    if not prop:
        conn.close()
        return {"error": f"Property '{property_name}' not found"}

    prop = dict(prop)

    # 2. Parse rich metadata from raw_json (Streamline data)
    raw = prop.get("raw_json", {}) or {}
    streamline_desc = clean_html(raw.get("description", "") or prop.get("description_short", ""))
    global_desc = clean_html(raw.get("global_description", ""))

    # 3. Financial performance
    cur.execute("""
        SELECT * FROM fin_owner_balances
        WHERE property_name ILIKE %s
    """, (f"%{prop['internal_name'][:20]}%",))
    fin = cur.fetchone()

    # 4. Turnover history
    cur.execute("""
        SELECT COUNT(*) as turn_count,
               MIN(checkout_time) as first_turn,
               MAX(checkout_time) as last_turn
        FROM ops_turnovers
        WHERE property_id = %s
    """, (prop["property_id"],))
    turns = dict(cur.fetchone())

    # 5. Active overrides
    cur.execute("""
        SELECT override_type, reason, effective_until
        FROM ops_overrides
        WHERE entity_id = %s AND active = TRUE
    """, (prop["property_id"],))
    overrides = [dict(r) for r in cur.fetchall()]

    # 6. Latest QuantRevenue rate card
    cur.execute("""
        SELECT cabin_name, target_date, adjusted_rate, trading_signal,
               event_name, base_rate
        FROM revenue_ledger
        WHERE cabin_name LIKE %s
          AND engine_version >= '2.0.0'
          AND target_date >= CURRENT_DATE
        ORDER BY generated_at DESC, target_date
        LIMIT 14
    """, (f"%{normalized[:15]}%",))
    rate_card = [dict(r) for r in cur.fetchall()]

    # 7. VISUAL INTELLIGENCE (The Eye — Division 6)
    # Pull what the AI has *seen* in the property photos
    visual_intel = []
    try:
        cur.execute("""
            SELECT file_name, description, room_type, features
            FROM ops_visuals
            WHERE status = 'DONE'
              AND description IS NOT NULL
              AND (
                  property_id = %s
                  OR property_name ILIKE %s
                  OR file_path ILIKE %s
                  OR file_name ILIKE %s
              )
            ORDER BY scanned_at DESC
            LIMIT 20
        """, (
            prop["property_id"],
            f"%{prop['internal_name'][:20]}%",
            f"%{prop['internal_name'][:15]}%",
            f"%{prop['internal_name'][:15]}%",
        ))
        visual_intel = [dict(r) for r in cur.fetchall()]
        if visual_intel:
            log.info(f"  The Eye: {len(visual_intel)} photos analyzed for this property")
    except Exception as e:
        log.warning(f"  Vision query failed (ops_visuals may not exist): {e}")
        conn.rollback()

    conn.close()

    # Build the intel package
    return {
        "property_id": prop["property_id"],
        "name": prop["internal_name"],
        "address": prop.get("address", ""),
        "city": prop.get("city", "Blue Ridge"),
        "state": prop.get("state_name", "GA"),
        "zip": prop.get("zip", ""),
        "latitude": float(prop.get("latitude", 0) or 0),
        "longitude": float(prop.get("longitude", 0) or 0),
        "bedrooms": int(float(prop.get("bedrooms", 0) or 0)),
        "bathrooms": int(float(prop.get("bathrooms", 0) or 0)),
        "max_occupants": int(prop.get("max_occupants", 0) or 0),
        "max_pets": int(raw.get("max_pets", 0) or 0),
        "location_area": prop.get("location_area_name", ""),
        "resort_area": prop.get("resort_area_name", "Blue Ridge"),
        "view": prop.get("view_name", ""),
        "seo_title": prop.get("seo_title", ""),
        "flyer_url": prop.get("flyer_url", ""),
        "default_image": prop.get("default_image_url", ""),
        "streamline_description": streamline_desc,
        "global_description": global_desc,
        "layout": _extract_layout(global_desc or streamline_desc),
        "amenities": _extract_amenities(global_desc or streamline_desc, raw),
        "nearby": _extract_nearby(global_desc or streamline_desc),
        "unique_features": _extract_unique(global_desc or streamline_desc),
        "visual_intel": visual_intel,
        "performance": {
            "revenue": float(fin["gross_revenue"]) if fin else 0,
            "nights_booked": int(fin["total_booked_nights"]) if fin else 0,
            "turnovers": turns["turn_count"],
            "first_turnover": str(turns["first_turn"]) if turns["first_turn"] else None,
            "last_turnover": str(turns["last_turn"]) if turns["last_turn"] else None,
        },
        "overrides": overrides,
        "rate_card": rate_card,
        "current_rate": float(rate_card[0]["base_rate"]) if rate_card else None,
        "avg_recommended": round(
            sum(r["adjusted_rate"] for r in rate_card) / len(rate_card), 2
        ) if rate_card else None,
    }


def _extract_layout(desc: str) -> list:
    """Extract room layout from description."""
    layout = []
    for line in desc.split("\n"):
        line = line.strip()
        if any(kw in line.lower() for kw in [
            "bedroom", "bathroom", "living room", "kitchen", "porch",
            "game room", "loft", "deck", "dining",
        ]):
            if len(line) > 10 and len(line) < 200:
                layout.append(line)
    return layout


def _extract_amenities(desc: str, raw: dict = None) -> list:
    """Extract amenities from description text."""
    amenities = []
    amenity_keywords = [
        "hot tub", "fire pit", "pool table", "game room", "smart tv",
        "wifi", "starlink", "ev charger", "washer", "dryer", "coffee",
        "grill", "pond", "creek", "fishing", "fire table", "soundbar",
        "wood stove", "leather", "barn-wood", "linen", "king",
        "screened-in porch", "mountain view", "river view",
    ]
    desc_lower = desc.lower()
    for kw in amenity_keywords:
        if kw in desc_lower:
            amenities.append(kw.title())
    return amenities


def _extract_nearby(desc: str) -> list:
    """Extract nearby attractions from description."""
    nearby = []
    for line in desc.split("\n"):
        line = line.strip()
        if "miles" in line.lower() and ":" in line:
            nearby.append(line.lstrip("- ").strip())
    return nearby


def _extract_unique(desc: str) -> list:
    """Extract unique selling points."""
    unique = []
    keywords = [
        "cherokee", "historic", "noontootla", "fly fishing",
        "30 acres", "creek frontage", "restoration hardware",
        "moonshine", "farmhouse", "private pond", "sunrise",
    ]
    desc_lower = desc.lower()
    for kw in keywords:
        if kw in desc_lower:
            unique.append(kw.title())
    return unique


# =============================================================================
# 2. THE CMO (R1) — LISTING GENERATOR
# =============================================================================

def generate_listing(intel: dict, target_demo: str, fast: bool = False) -> dict:
    """
    Feed property intelligence to R1 and generate conversion-grade listing copy.
    """
    model = LLM_FAST if fast else LLM_MODEL
    log.info(f"Consulting the CMO ({model}) for {intel['name']}...")

    # Build the property dossier for R1
    dossier = f"""PROPERTY DOSSIER: {intel['name']}
═══════════════════════════════════════════════════
Location: {intel['city']}, {intel['state']} ({intel['location_area']})
View: {intel['view']}
Bedrooms: {intel['bedrooms']} | Bathrooms: {intel['bathrooms']} | Sleeps: {intel['max_occupants']}
Pets: {'Yes (max {})'.format(intel['max_pets']) if intel['max_pets'] > 0 else 'No'}
Current Rate: ${intel['current_rate']}/night
"""

    if intel['unique_features']:
        dossier += f"\nUNIQUE SELLING POINTS:\n"
        for f in intel['unique_features']:
            dossier += f"  - {f}\n"

    if intel['amenities']:
        dossier += f"\nAMENITIES:\n"
        for a in intel['amenities']:
            dossier += f"  - {a}\n"

    if intel['layout']:
        dossier += f"\nROOM LAYOUT:\n"
        for l in intel['layout']:
            dossier += f"  - {l}\n"

    if intel['nearby']:
        dossier += f"\nNEARBY ATTRACTIONS:\n"
        for n in intel['nearby']:
            dossier += f"  - {n}\n"

    # VISUAL EVIDENCE — What The Eye has seen in the actual photos
    if intel.get('visual_intel'):
        dossier += f"\nVISUAL EVIDENCE FROM PROPERTY PHOTOS ({len(intel['visual_intel'])} images analyzed by AI):\n"
        dossier += "(These are AI-generated descriptions of the ACTUAL photos of this property.\n"
        dossier += " Use these details to write accurate, specific copy. These are VERIFIED visual facts.)\n\n"
        for vi in intel['visual_intel']:
            fname = vi.get('file_name', 'unknown')
            desc = vi.get('description', '')
            if desc:
                dossier += f"  PHOTO [{fname}]:\n    {desc}\n\n"
    else:
        dossier += f"\nVISUAL EVIDENCE: NONE (No photos have been analyzed by the Vision AI yet.)\n"

    dossier += f"\nPERFORMANCE DATA:\n"
    dossier += f"  Revenue to date: ${intel['performance']['revenue']:,.0f}\n"
    dossier += f"  Nights booked: {intel['performance']['nights_booked']}\n"
    dossier += f"  Turnovers: {intel['performance']['turnovers']}\n"
    if intel['performance']['turnovers'] == 0:
        dossier += f"  STATUS: ZERO BOOKINGS — INVISIBLE LISTING\n"

    dossier += f"\nCURRENT LISTING (THE 'BEFORE' — THIS IS WHAT WE'RE REPLACING):\n"
    dossier += f"{intel['global_description'][:2000]}\n"

    # The CMO prompt
    system_prompt = f"""You are the Chief Marketing Officer for a luxury vacation rental company in Blue Ridge, Georgia.

Your mission: Rewrite this property listing to CONVERT BOOKINGS from a specific target demographic.

TARGET DEMOGRAPHIC: {target_demo}

You are NOT writing a generic description. You are writing a SALES WEAPON. Every sentence must:
1. Speak DIRECTLY to the target demographic's desires and pain points.
2. Paint a SPECIFIC sensory picture (sounds, textures, light, temperature).
3. Use POWER WORDS that trigger emotional booking decisions.
4. Follow the "AIDA" framework: Attention → Interest → Desire → Action.

CRITICAL RULES:
- NO generic phrases like "something for everyone" or "perfect getaway."
- NO listing every single amenity. Focus on 5-7 that MATTER to the target demographic.
- NO SEO-stuffed language. Write like a human talking to a friend.
- Pricing at ${intel['current_rate']}/night is AGGRESSIVE — use it as a weapon ("at this price, you're not renting a cabin, you're stealing a memory").
- The property has REAL history (Cherokee Indian settlement, 1900s farmhouse) — use this as AUTHENTICITY, not a museum tour.
- Bedrooms: {intel['bedrooms']}, Bathrooms: {intel['bathrooms']}, Sleeps: {intel['max_occupants']} — be ACCURATE. Never invent rooms or amenities that don't exist.
- VISUAL EVIDENCE: The dossier includes AI-analyzed descriptions of actual property photos. These are VERIFIED FACTS about what the property looks like. Prioritize these visual details over generic assumptions. If the photos show granite countertops, say "granite countertops" — not "modern kitchen." Specific visual details convert bookings.

OUTPUT FORMAT (use EXACTLY these headers):

## TITLE
(Airbnb title. Max 50 characters. Emotional, specific, bookable.)

## HERO
(2-3 sentences. The emotional hook. This is the first thing they read. Make them feel something.)

## HIGHLIGHTS
(Exactly 5 bullet points. Benefit-driven, not feature-driven. Each starts with an action verb or emotional trigger.)
- Highlight 1
- Highlight 2
- Highlight 3
- Highlight 4
- Highlight 5

## ABOUT THIS SPACE
(250-350 words. Storytelling narrative. Walk the guest through the experience chronologically: arrival → evening → morning → departure. Use sensory language. End with a soft call to action.)

## SEO KEYWORDS
(Comma-separated list of 8-10 search terms the target demographic would use to find this property.)"""

    user_prompt = f"""Here is the complete property intelligence. Rewrite this listing to convert {target_demo}.

{dossier}

Remember: This property is INVISIBLE right now (zero bookings). The current listing is failing. Your job is to make someone stop scrolling and click BOOK NOW."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.8, "num_predict": 4096},
    }

    try:
        t0 = time.time()
        resp = http_requests.post(OLLAMA_URL, json=payload, timeout=1800)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        answer = strip_think_tags(raw)
        elapsed = time.time() - t0
        log.info(f"CMO delivered in {elapsed:.1f}s ({len(answer)} chars)")

        # Parse the structured output
        result = _parse_listing_output(answer)
        result["raw_output"] = answer
        result["model"] = model
        result["elapsed_seconds"] = round(elapsed, 1)
        result["target_demographic"] = target_demo
        result["property_name"] = intel["name"]
        result["property_id"] = intel["property_id"]
        result["generated_at"] = datetime.now().isoformat()

        return result

    except Exception as e:
        log.error(f"CMO failed: {e}")
        return {"error": str(e)}


def _parse_listing_output(text: str) -> dict:
    """Parse structured listing output from R1."""
    sections = {
        "title": "",
        "hero": "",
        "highlights": [],
        "about": "",
        "seo_keywords": [],
    }

    current_section = None
    current_lines = []

    for line in text.split("\n"):
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("## TITLE"):
            if current_section:
                _save_section(sections, current_section, current_lines)
            current_section = "title"
            current_lines = []
        elif stripped.startswith("## HERO"):
            if current_section:
                _save_section(sections, current_section, current_lines)
            current_section = "hero"
            current_lines = []
        elif stripped.startswith("## HIGHLIGHT"):
            if current_section:
                _save_section(sections, current_section, current_lines)
            current_section = "highlights"
            current_lines = []
        elif stripped.startswith("## ABOUT"):
            if current_section:
                _save_section(sections, current_section, current_lines)
            current_section = "about"
            current_lines = []
        elif stripped.startswith("## SEO"):
            if current_section:
                _save_section(sections, current_section, current_lines)
            current_section = "seo_keywords"
            current_lines = []
        elif current_section:
            current_lines.append(line)

    # Save the last section
    if current_section:
        _save_section(sections, current_section, current_lines)

    return sections


def _save_section(sections: dict, key: str, lines: list):
    """Save parsed lines into the appropriate section."""
    content = "\n".join(lines).strip()
    if key == "title":
        sections["title"] = content.strip('"').strip("*").strip()
    elif key == "hero":
        sections["hero"] = content
    elif key == "highlights":
        highlights = []
        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                highlights.append(line[2:].strip())
            elif line.startswith("1.") or line.startswith("2.") or line.startswith("3.") or line.startswith("4.") or line.startswith("5."):
                highlights.append(line[2:].strip().lstrip(". "))
        sections["highlights"] = highlights
    elif key == "about":
        sections["about"] = content
    elif key == "seo_keywords":
        # Parse comma-separated keywords
        kw = [k.strip().strip('"') for k in content.split(",") if k.strip()]
        sections["seo_keywords"] = kw


# =============================================================================
# 3. REPORT GENERATOR
# =============================================================================

def generate_report(intel: dict, listing: dict) -> str:
    """Generate a markdown report with the before/after listing."""
    lines = [
        f"# The Listing Doctor — Operation Rebrand",
        f"**Property:** {intel['name']}",
        f"**Target Demographic:** {listing.get('target_demographic', 'General')}",
        f"**Generated:** {listing.get('generated_at', '')}",
        f"**Model:** {listing.get('model', '')} ({listing.get('elapsed_seconds', 0)}s)",
        "",
        "---",
        "",
        "## DIAGNOSIS",
        "",
        f"- **Revenue:** ${intel['performance']['revenue']:,.0f}",
        f"- **Bookings:** {intel['performance']['turnovers']}",
        f"- **Rate:** ${intel['current_rate']}/night",
        f"- **Status:** {'INVISIBLE — Zero turnovers' if intel['performance']['turnovers'] == 0 else 'Underperforming'}",
        "",
        "---",
        "",
        "## NEW LISTING COPY",
        "",
        f"### Title",
        f"**{listing.get('title', 'N/A')}**",
        "",
        f"### Hero Description",
        listing.get("hero", "N/A"),
        "",
        f"### Highlights",
    ]

    for h in listing.get("highlights", []):
        lines.append(f"- {h}")

    lines.extend([
        "",
        f"### About This Space",
        listing.get("about", "N/A"),
        "",
        f"### SEO Keywords",
        ", ".join(listing.get("seo_keywords", [])),
        "",
        "---",
        "",
        "## FULL R1 OUTPUT",
        "",
        listing.get("raw_output", "N/A"),
    ])

    return "\n".join(lines)


# =============================================================================
# 4. MAIN
# =============================================================================

def run_listing_doctor(property_name: str, target_demo: str, fast: bool = False) -> dict:
    """
    Full pipeline: gather intel → consult CMO → generate listing.
    Returns the listing dict for API consumption.
    """
    log.info(f"═══ THE LISTING DOCTOR ═══")
    log.info(f"  Patient: {property_name}")
    log.info(f"  Target: {target_demo}")
    log.info(f"  Model: {'FAST (8b)' if fast else 'FULL (70b)'}")

    # Step 1: Gather intelligence
    log.info("  Gathering property intelligence...")
    intel = gather_property_intel(property_name)
    if "error" in intel:
        log.error(f"  Failed: {intel['error']}")
        return intel

    log.info(f"  Found: {intel['name']} ({intel['bedrooms']}BR/{intel['bathrooms']}BA)")
    log.info(f"  Amenities: {len(intel['amenities'])} | Unique: {len(intel['unique_features'])}")
    log.info(f"  Performance: ${intel['performance']['revenue']:,.0f} / {intel['performance']['turnovers']} turnovers")

    # Step 2: Consult the CMO
    listing = generate_listing(intel, target_demo, fast)
    if "error" in listing:
        log.error(f"  CMO failed: {listing['error']}")
        return listing

    log.info(f"  Title: {listing.get('title', 'N/A')}")
    log.info(f"  Highlights: {len(listing.get('highlights', []))}")

    # Step 3: Archive
    report = generate_report(intel, listing)
    report_file = LOGS_DIR / f"{intel['property_id']}_{datetime.now():%Y%m%d_%H%M}.md"
    with open(report_file, "w") as f:
        f.write(report)
    log.info(f"  Report archived: {report_file}")

    log.info("═══ LISTING DOCTOR COMPLETE ═══")

    return {
        "status": "success",
        "property": intel["name"],
        "property_id": intel["property_id"],
        "target_demographic": target_demo,
        "listing": {
            "title": listing.get("title", ""),
            "hero": listing.get("hero", ""),
            "highlights": listing.get("highlights", []),
            "about": listing.get("about", ""),
            "seo_keywords": listing.get("seo_keywords", []),
        },
        "raw_output": listing.get("raw_output", ""),
        "model": listing.get("model", ""),
        "elapsed_seconds": listing.get("elapsed_seconds", 0),
        "intel": {
            "bedrooms": intel["bedrooms"],
            "bathrooms": intel["bathrooms"],
            "max_occupants": intel["max_occupants"],
            "rate": intel["current_rate"],
            "revenue": intel["performance"]["revenue"],
            "turnovers": intel["performance"]["turnovers"],
            "amenities": intel["amenities"],
            "unique_features": intel["unique_features"],
            "visual_photos_analyzed": len(intel.get("visual_intel", [])),
        },
        "report_path": str(report_file),
    }


def main():
    parser = argparse.ArgumentParser(description="The Listing Doctor — Operation Rebrand")
    parser.add_argument("property", help="Property name or ID (e.g. cherokee_sunrise)")
    parser.add_argument("--target", "-t", default="Luxury Travelers",
                        help="Target demographic (e.g. 'Anniversary Couples')")
    parser.add_argument("--fast", action="store_true",
                        help="Use fast model (R1:8b) instead of full 70b")
    args = parser.parse_args()

    result = run_listing_doctor(args.property, args.target, args.fast)

    if "error" in result:
        print(f"\nFailed: {result['error']}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  THE LISTING DOCTOR — PRESCRIPTION READY")
    print(f"{'='*60}")
    print(f"\n  Property: {result['property']}")
    print(f"  Target: {result['target_demographic']}")
    print(f"  Model: {result['model']} ({result['elapsed_seconds']}s)")
    print(f"\n{'─'*60}")
    print(f"\n  TITLE: {result['listing']['title']}")
    print(f"\n  HERO:\n  {result['listing']['hero']}")
    print(f"\n  HIGHLIGHTS:")
    for h in result['listing']['highlights']:
        print(f"    • {h}")
    print(f"\n  ABOUT THIS SPACE:")
    print(f"  {result['listing']['about'][:500]}...")
    print(f"\n  SEO: {', '.join(result['listing']['seo_keywords'][:6])}")
    print(f"\n  Report: {result['report_path']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
