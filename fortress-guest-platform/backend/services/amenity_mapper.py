"""
amenity_mapper.py — Categorise raw Streamline amenity payloads into a
structured, guest-facing amenity matrix.

Streamline stores ~28 group_name buckets.  We collapse them into six
display categories, humanise the amenity names, and aggressively dedup.
"""
from __future__ import annotations

from typing import Any

# ── Display categories with their absorbing Streamline groups ───────────

_GROUP_TO_CATEGORY: dict[str, str] = {
    # Kitchen
    "Kitchen and Dining":        "Kitchen & Dining",
    "Kitchen Details":           "Kitchen & Dining",
    # Outdoor
    "Outdoor Living":            "Outdoor & Views",
    "Outdoor":                   "Outdoor & Views",
    "Pool/Spa":                  "Outdoor & Views",
    "Location Types":            "Outdoor & Views",
    "The Drive":                 "Outdoor & Views",
    # Entertainment
    "Unit Entertainment":        "Entertainment",
    "Entertainment":             "Entertainment",
    # Activities
    "Leisure":                   "Activities & Nearby",
    "Activities":                "Activities & Nearby",
    "Sports and Adventure":      "Activities & Nearby",
    # Comfort
    "Amenities":                 "Comfort & Convenience",
    "Accommodations":            "Comfort & Convenience",
    "Suitability":               "Comfort & Convenience",
    "Unit Suitability":          "Comfort & Convenience",
    "House Details":             "Comfort & Convenience",
    "Family Friendly Amenities": "Comfort & Convenience",
    # Safety
    "Safety Features":           "Safety",
    "Emergency":                 "Safety",
    "Cleanliness":               "Safety",
}

_SKIP_GROUPS: set[str] = {
    "Changeover/Arrival Day",
    "Distance to Town",
    "Car",
    "Purchasable Amenities",
    "Themes",
    "Attractions",
    "Local Features",
}

_SKIP_AMENITIES: set[str] = {
    # Basics every cabin has — not worth listing
    "essentials", "linens", "linens provided", "towels", "towels provided",
    "bed linens", "hangers", "shampoo", "conditioner", "body soap",
    "shower gel", "hot water", "proximity", "cell service",
    "cleaning disinfection", "enhanced cleaning practices",
    "all towels and bedding washed in hot water that's at least 60ºc",
    "high-touch surfaces cleaned with disinfectant",
    "self check in / check out", "self check-in", "self check-in / check-out",
    "atm bank", "coin laundry", "laundromat", "hospital", "rec center",
    "churches", "library", "duty free", "groceries", "grocery stores",
    "dvd", "laptop friendly", "gambling", "eco tourism",
    "telephone", "desk", "desk chair", "satellite or cable",
    "television", "bathtub", "ensuite baths",
    "living room", "dining area", "hvac", "central heating",
    "cooking basics", "kitchen", "oils/spices", "spices",
    "cook island", "dishes utensils", "parking", "parking space",
    "antiquing", "photography", "bird watching", "wildlife viewing",
    "bowling", "shopping", "miniature golf", "horse riding nearby",
    "accessible parking", "parking space accessible",
    "not wheelchair accessible", "suitable for elderly",
    "age restriction", "minimum age 25+", "minimum age 25",
    "minimum age limit", "minimum age",
    "mountain", "river", "waterfront", "water view", "water views",
    "mountain views", "deck patio uncovered", "terrace",
    "private yard", "conversational seating",
    "fully furnished w/ luxury linens, towels, paper products, soaps",
    "large stone wood-burning fireplace on main level",
    "washer/dryer w/ detergent", "keurig/regular coffee maker",
    "iron board", "keypad", "heating", "dryer", "iron",
    "pets considered", "lock box entry", "lock box",
    "tubing/kayaking", "fishing nearby",
    "all paved roads", "stainless steel appliances",
    "deadbolt lock", "outdoor lighting",
    "fire extinguisher", "smoke detector", "safe",
    "concierge service", "private chef available",
    "smart lock", "smartlock",
    "basketball court", "orchards",
    # Noise / themes that sneak through
    "city getaway", "country getaway", "romantic getaway", "getaway",
    "gravel roads", "paved roads", "unpaved roads",
    "proximity", "cable/satellite tv",
    "dvd player",
    "downtown", "town", "rural area", "suburban", "village",
    "family fun", "outlet shopping",
    # Redundant suitability entries
    "pets allowed", "pets not allowed", "children ask",
    "no pets", "pet friendly",
    "children welcome", "not wheelchair accessible",
    "wheelchair accessible", "accessibility wheelchair accessible",
    "accessibility wheelchair inaccessible",
    "other services concierge", "other services massage",
    "other services private chef", "other services staff",
    "watersports nearby",
    "restaurants",
    # Redundant structural items
    "lanai gazebo covered", "private living room",
    "hair dryer", "garbage disposal",
}

# After humanization, check again — catches entries whose RAW name
# didn't match _SKIP_AMENITIES but whose humanized form should be hidden.
_SKIP_HUMANIZED: set[str] = {
    "Minimum Age 25+", "Age Restriction", "No Pets", "Pets Considered",
    "Non-Smoking",  # keep only the explicit "No Smoking" or skip both
    "Deadbolt Lock", "Smart Lock", "Lock Box Entry",
    "Accessible Parking", "Not Wheelchair Accessible",
}

# ── Streamline raw → clean display name overrides ──────────────────────

_NAME_OVERRIDES: dict[str, str] = {
    "Cable/satellite TV":           "Cable TV",
    "Jacuzzi/hot tub":              "Hot Tub",
    "Fish/Tube from Property":      "Fish & Tube from Property",
    "Free Wifi":                    "Wi-Fi",
    "Wifi":                         "Wi-Fi",
    "Internet":                     "Wi-Fi",
    "Internet Access":              "Wi-Fi",
    "High Speed Internet":          "Wi-Fi",
    "Smoking Not Allowed":          "Non-Smoking",
    "No Smoking Inside or Outside on Decks": "Non-Smoking",
    "Pets allowed":                 "Pet-Friendly",
    "Pets Considered":              "Pet-Friendly",
    "Pets Not Allowed":             "No Pets",
    "Children Welcome":             "Kid-Friendly",
    "Children Ask":                 "Kid-Friendly",
    "Accessibility Wheelchair Accessible": "Wheelchair Accessible",
    "Fishing Fly":                  "Fly Fishing",
    "Fishing Freshwater":           "Freshwater Fishing",
    "Fishing nearby":               "Fishing Nearby",
    "Golf course within 30 min drive": "Golf Nearby",
    "Skiing Water":                 "Water Skiing",
    "Tubing Water":                 "River Tubing",
    "Watersports nearby":           "Watersports",
    "Tennis courts nearby":         "Tennis Nearby",
    "Cycling trips":                "Cycling",
    "Hiking trips":                 "Hiking",
    "Smart TV":                     "Smart TV",
    "Parking space":                "Free Parking",
    "Smartlock":                    "Smart Lock",
    "Lock Box":                     "Lock Box Entry",
    "Self Check-In":                "Self Check-In",
    "Deadbolt Lock":                "Deadbolt Lock",
    "Decked area":                  "Deck / Patio",
    "Deck Patio Uncovered":         "Deck / Patio",
    "Balcony/Terrace":              "Balcony / Terrace",
    "DVD player":                   "DVD Player",
    "Horseback Riding":             "Horseback Riding",
    "Mountain Climbing":            "Rock Climbing",
    # Verbose Streamline "show_on_website" names → concise icon-friendly labels
    "Close to Hiking Trails":       "Hiking Trails",
    "Close to Waterfall Hike":      "Waterfall Hike",
    "Close to Lake Blue Ridge Access": "Lake Access",
    "Guided fly-fishing on the Toccoa River w/ Toccoa River Outfitter": "Fly Fishing",
    "Outdoor Fireplace":            "Outdoor Fireplace",
    "Indoor Fireplace":             "Indoor Fireplace",
    "Pool Table":                   "Pool Table",
    "Billiard Table":               "Pool Table",
    "Foosball":                     "Foosball Table",
    "Shuffleboard":                 "Shuffleboard",
    "River Access":                 "River Access",
}

# ── Canonical dedup names (lowercase key → display form) ───────────────

_DEDUP_CANON: dict[str, str] = {
    "ceiling fans":       "Ceiling Fans",
    "ceiling fan":        "Ceiling Fans",
    "game room":          "Game Room",
    "grill":              "Gas Grill",
    "gas grill":          "Gas Grill",
    "charcoal grill":     "Charcoal Grill",
    "hot tub":            "Hot Tub",
    "jacuzzi":            "Hot Tub",
    "jacuzzi / hot tub":  "Hot Tub",
    "jacuzzi/hot tub":    "Hot Tub",
    "tv":                 "Smart TV",
    "televisions":        "Smart TV",
    "smart tv":           "Smart TV",
    "cable tv":           "Cable TV",
    "cable / satellite tv": "Cable TV",
    "parking":            "Free Parking",
    "free parking":       "Free Parking",
    "wi-fi":              "Wi-Fi",
    "free wi-fi":         "Wi-Fi",
    "wifi":               "Wi-Fi",
    "fireplace":          "Fireplace",
    "fireplaces":         "Fireplace",
    "indoor fireplace":   "Indoor Fireplace",
    "indoor fireplaces":  "Indoor Fireplace",
    "outdoor fireplace":  "Outdoor Fireplace",
    "outdoor fireplaces": "Outdoor Fireplace",
    "non-smoking":        "Non-Smoking",
    "no smoking":         "Non-Smoking",
    "washer":             "Washer / Dryer",
    "dryer":              "Washer / Dryer",
    "washer/dryer":       "Washer / Dryer",
    "patio":              "Deck / Patio",
    "deck / patio":       "Deck / Patio",
    "deck":               "Deck / Patio",
    "patio or balcony":   "Balcony / Terrace",
    "balcony":            "Balcony / Terrace",
    "pet-friendly":       "Pet-Friendly",
    "pet friendly":       "Pet-Friendly",
    "kid-friendly":       "Kid-Friendly",
    "children welcome":   "Kid-Friendly",
    "fridge":             "Refrigerator",
    "refrigerator":       "Refrigerator",
    "bbq":                "BBQ Grill",
    "golf":               "Golf Nearby",
    "golf nearby":        "Golf Nearby",
    "tennis":             "Tennis Nearby",
    "tennis nearby":      "Tennis Nearby",
    "garden":             "Garden",
    "garden or backyard": "Garden",
    "lake access":        "Lake Access",
    "lake":               "Lake Access",
    "lake view":          "Lake View",
}

# ── Forced category overrides (humanized name → category) ──────────────
# Fixes items that Streamline puts in the wrong group.

_FORCE_CATEGORY: dict[str, str] = {
    "Boating":            "Activities & Nearby",
    "Horseback Riding":   "Activities & Nearby",
    "Water Sports":       "Activities & Nearby",
    "Water Skiing":       "Activities & Nearby",
    "River Tubing":       "Activities & Nearby",
    "Fly Fishing":        "Activities & Nearby",
    "Freshwater Fishing": "Activities & Nearby",
    "Fishing":            "Activities & Nearby",
    "Fishing Nearby":     "Activities & Nearby",
    "Hiking":             "Activities & Nearby",
    "Rock Climbing":      "Activities & Nearby",
    "Cycling":            "Activities & Nearby",
    "Golf Nearby":        "Activities & Nearby",
    "Tennis Nearby":      "Activities & Nearby",
    "Watersports":        "Activities & Nearby",
    "Swimming":           "Activities & Nearby",
}

# ── Truncation for verbose Streamline descriptions ─────────────────────

_MAX_NAME_LEN = 40


CATEGORY_ORDER: list[str] = [
    "Comfort & Convenience",
    "Kitchen & Dining",
    "Outdoor & Views",
    "Entertainment",
    "Activities & Nearby",
    "Safety",
]


def _humanise(raw: str) -> str:
    overridden = _NAME_OVERRIDES.get(raw, raw)
    canon = _DEDUP_CANON.get(overridden.lower())
    if canon:
        return canon
    if len(overridden) > _MAX_NAME_LEN:
        overridden = overridden[:_MAX_NAME_LEN].rsplit(" ", 1)[0].rstrip(" ,;-") + "…"
    return overridden


def humanise_amenity(raw: str) -> str:
    """Public wrapper — humanise a single raw Streamline amenity name."""
    return _humanise(raw)


def build_amenity_matrix(raw_amenities: Any) -> dict[str, list[str]]:
    """Return ``{category: [amenity_name, ...]}`` from a Streamline JSONB blob."""
    if not raw_amenities or not isinstance(raw_amenities, list):
        return {}

    buckets: dict[str, set[str]] = {}

    for item in raw_amenities:
        if not isinstance(item, dict):
            continue

        group = (item.get("group_name") or "").strip()
        name  = (item.get("amenity_name") or item.get("name") or "").strip()
        if not name or group in _SKIP_GROUPS:
            continue
        if name.lower() in _SKIP_AMENITIES:
            continue

        human = _humanise(name)

        if human in _SKIP_HUMANIZED:
            continue

        forced_cat = _FORCE_CATEGORY.get(human)
        if forced_cat:
            category = forced_cat
        else:
            category = _GROUP_TO_CATEGORY.get(group, "Comfort & Convenience")

        buckets.setdefault(category, set()).add(human)

    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for cat in CATEGORY_ORDER:
        items = buckets.get(cat)
        if not items:
            continue
        unique = sorted(items - seen)
        if unique:
            result[cat] = unique
            seen.update(unique)
    return result
