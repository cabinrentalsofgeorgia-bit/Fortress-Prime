"""
Fortress Prime — Guest Email Topic Classifier
===============================================
Classifies guest emails into topic categories for dynamic few-shot
example retrieval. Works with the starred_db to inject the most
relevant approved examples into prompts.

Topics map to the starred_responses topic_tag field, enabling the
Learning Loop: detect topic -> fetch starred examples -> inject into prompt.

Usage:
    from prompts.topic_classifier import classify_topic

    result = classify_topic("Can I charge my Tesla at the cabin?")
    print(result.primary)    # "ev_charging"
    print(result.secondary)  # ["parking", "amenities"]
    print(result.confidence) # 0.85
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TopicResult:
    """Result of topic classification."""
    primary: str                       # Primary topic (highest relevance)
    secondary: List[str] = field(default_factory=list)  # Secondary topics
    confidence: float = 0.0            # 0.0-1.0
    matched_keywords: List[str] = field(default_factory=list)


# =============================================================================
# TOPIC DEFINITIONS
# =============================================================================

TOPIC_PROFILES = {
    "ev_charging": {
        "keywords": [
            "ev", "electric vehicle", "tesla", "rivian", "charger", "charging",
            "charge my car", "charge my vehicle", "ev charger", "ev charging",
            "level 2", "level 1", "nema", "j1772", "14-50", "240v",
            "plug in", "electric car", "hybrid plug",
        ],
        "patterns": [
            r'\bcharg(?:e|ing)\s+(?:my|a|the)?\s*(?:car|vehicle|ev|tesla)',
            r'\bev\s+charg',
            r'\belectric\s+(?:car|vehicle)',
            r'\btesla\b',
        ],
        "weight": 1.0,
    },
    "pets": {
        "keywords": [
            "pet", "pets", "dog", "dogs", "cat", "cats", "puppy", "kitten",
            "pet friendly", "pet-friendly", "pet policy", "pet fee", "pet deposit",
            "bring my dog", "bring my cat", "animal", "animals",
            "service dog", "service animal", "emotional support", "esa",
        ],
        "patterns": [
            r'\b(?:bring|have)\s+(?:my|a|our)\s+(?:dog|cat|pet)',
            r'\bpet[\s-]?(?:friendly|policy|fee|deposit)',
            r'\bservice\s+(?:dog|animal)',
        ],
        "weight": 1.0,
    },
    "hot_tub": {
        "keywords": [
            "hot tub", "hottub", "jacuzzi", "spa", "jets",
            "hot tub temperature", "hot tub clean", "hot tub chemicals",
            "hot tub cover", "soak",
        ],
        "patterns": [
            r'\bhot\s*tub',
            r'\bjacuzzi\b',
        ],
        "weight": 1.0,
    },
    "internet": {
        "keywords": [
            "wifi", "wi-fi", "internet", "wireless", "network", "password",
            "streaming", "netflix", "work from", "remote work", "zoom",
            "video call", "bandwidth", "speed", "starlink", "router",
            "ethernet", "signal",
        ],
        "patterns": [
            r'\bwi[\s-]?fi\b',
            r'\binternet\s+(?:speed|access|connection)',
            r'\bwork\s+(?:from|remote)',
            r'\bstream(?:ing)?\b',
        ],
        "weight": 1.0,
    },
    "checkin": {
        "keywords": [
            "check in", "check-in", "checkin", "arrival", "arrive",
            "early check in", "early arrival", "key", "keys", "lockbox",
            "door code", "access code", "keypad", "entry", "directions",
            "address", "how to get", "find the cabin",
        ],
        "patterns": [
            r'\bcheck[\s-]?in\b',
            r'\b(?:early|late)\s+(?:check[\s-]?in|arrival)',
            r'\b(?:door|access|entry)\s+code',
            r'\bhow\s+(?:do\s+(?:we|i)|to)\s+get\s+(?:in|to|there)',
        ],
        "weight": 1.0,
    },
    "checkout": {
        "keywords": [
            "check out", "check-out", "checkout", "departure", "leave",
            "late check out", "late checkout", "leaving time", "departure time",
            "what time do we", "cleaning",
        ],
        "patterns": [
            r'\bcheck[\s-]?out\b',
            r'\blate\s+check[\s-]?out',
            r'\bwhat\s+time\s+(?:do\s+we|should\s+we)\s+(?:leave|check)',
        ],
        "weight": 1.0,
    },
    "hvac": {
        "keywords": [
            "heat", "heater", "heating", "furnace", "thermostat",
            "air conditioning", "ac", "a/c", "cooling", "cold",
            "warm", "temperature", "fireplace", "gas fireplace",
            "wood burning", "pellet stove", "space heater",
        ],
        "patterns": [
            r'\b(?:heat|ac|a/c|air\s+conditioning)\b',
            r'\bthermostat\b',
            r'\bfireplace\b',
            r'\b(?:too|very|really)\s+(?:hot|cold|warm|cool)\b',
        ],
        "weight": 1.0,
    },
    "kitchen": {
        "keywords": [
            "kitchen", "cook", "cooking", "grill", "bbq", "barbecue",
            "oven", "stove", "microwave", "dishwasher", "coffee",
            "coffee maker", "keurig", "nespresso", "pots", "pans",
            "utensils", "dishes", "blender", "toaster",
            "groceries", "grocery store",
        ],
        "patterns": [
            r'\b(?:gas|charcoal|propane)\s+grill',
            r'\bcoffee\s+(?:maker|machine|pot)',
            r'\bfully\s+(?:equipped|stocked)\s+kitchen',
        ],
        "weight": 1.0,
    },
    "parking": {
        "keywords": [
            "parking", "park", "driveway", "garage", "carport",
            "4wd", "4x4", "four wheel drive", "all wheel drive", "awd",
            "steep driveway", "gravel", "paved", "how many cars",
            "trailer", "rv", "boat trailer",
        ],
        "patterns": [
            r'\b(?:park|parking)\s+(?:spot|space|area)',
            r'\b(?:steep|gravel|paved)\s+(?:driveway|road)',
            r'\bhow\s+many\s+cars',
            r'\b(?:4wd|4x4|awd)\b',
        ],
        "weight": 1.0,
    },
    "activities": {
        "keywords": [
            "hiking", "hike", "trail", "trails", "fishing", "fish",
            "tubing", "tube", "kayak", "kayaking", "canoe", "rafting",
            "swimming", "swim", "lake", "river", "waterfall",
            "horseback", "riding", "zipline", "zip line",
            "vineyard", "winery", "wine tasting", "brewery",
            "shopping", "downtown", "things to do", "attractions",
            "restaurants", "dining", "apple picking", "pumpkin patch",
        ],
        "patterns": [
            r'\bthings\s+to\s+do\b',
            r'\bwhat\s+(?:is|are)\s+(?:there|nearby|around)',
            r'\brecommend\s+(?:any|some)',
            r'\bactivit(?:y|ies)\b',
        ],
        "weight": 0.9,
    },
    "accessibility": {
        "keywords": [
            "wheelchair", "accessible", "accessibility", "ada",
            "handicap", "disabled", "disability", "mobility",
            "stairs", "steps", "ramp", "elevator", "level entry",
            "ground floor", "first floor", "walk in shower",
            "grab bar", "walker",
        ],
        "patterns": [
            r'\bwheel\s*chair\s+accessible',
            r'\bada\s+(?:compliant|accessible)',
            r'\bhow\s+many\s+(?:stairs|steps)',
            r'\b(?:mobility|physical)\s+(?:issue|limitation|challenge)',
        ],
        "weight": 1.0,
    },
    "policies": {
        "keywords": [
            "cancel", "cancellation", "refund", "deposit",
            "damage", "security deposit", "rules", "house rules",
            "noise", "quiet hours", "smoking", "no smoking",
            "party", "parties", "event", "events",
            "age", "minimum age", "under 25",
            "occupancy", "max guests", "extra guests",
        ],
        "patterns": [
            r'\bcancellation\s+policy',
            r'\bhouse\s+rules',
            r'\bquiet\s+hours',
            r'\bmax(?:imum)?\s+(?:guests|occupancy|people)',
            r'\bsecurity\s+deposit',
        ],
        "weight": 1.0,
    },
    "amenities": {
        "keywords": [
            "amenities", "amenity", "feature", "features",
            "washer", "dryer", "laundry", "washing machine",
            "game room", "pool table", "foosball", "arcade",
            "fire pit", "firepit", "campfire", "s'mores",
            "deck", "porch", "balcony", "view", "mountain view",
            "tv", "television", "smart tv", "cable",
            "board games", "books", "library",
            "towels", "linens", "sheets", "bedding",
        ],
        "patterns": [
            r'\bwhat\s+(?:amenities|features)',
            r'\bdo\s+you\s+(?:have|provide|offer)',
            r'\bis\s+there\s+a\b',
        ],
        "weight": 0.8,  # Lower weight — catch-all category
    },
}


# =============================================================================
# CLASSIFICATION ENGINE
# =============================================================================

def classify_topic(email_text: str) -> TopicResult:
    """
    Classify a guest email into topic categories.

    Returns primary topic (strongest match) and secondary topics.
    Used to fetch relevant starred examples for dynamic few-shot injection.

    Args:
        email_text: The guest email text to classify.

    Returns:
        TopicResult with primary topic, secondaries, confidence, and matched keywords.

    Example:
        result = classify_topic("Can I charge my Tesla at the cabin? Also, is there WiFi?")
        print(result.primary)    # "ev_charging"
        print(result.secondary)  # ["internet"]
    """
    if not email_text:
        return TopicResult(primary="general", confidence=0.0)

    text_lower = email_text.lower()
    scores = {}

    for topic_name, profile in TOPIC_PROFILES.items():
        matched = []
        score = 0.0

        # Keyword matching (word-boundary aware for short keywords)
        for kw in profile["keywords"]:
            if " " in kw:
                if kw in text_lower:
                    matched.append(kw)
                    score += 1.0
            else:
                if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    matched.append(kw)
                    score += 1.0

        # Pattern matching (higher value — more specific)
        for pattern in profile["patterns"]:
            if re.search(pattern, text_lower):
                match = re.search(pattern, text_lower)
                if match:
                    matched.append(f"[pattern: {match.group()}]")
                    score += 2.0

        # Apply topic weight
        score *= profile["weight"]

        if score > 0:
            scores[topic_name] = {
                "score": score,
                "matched": matched,
            }

    if not scores:
        return TopicResult(primary="general", confidence=0.0)

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: -x[1]["score"])

    primary_name = ranked[0][0]
    primary_data = ranked[0][1]

    # Calculate confidence (normalized against max possible)
    max_possible = max(
        len(TOPIC_PROFILES[primary_name]["keywords"]) +
        len(TOPIC_PROFILES[primary_name]["patterns"]) * 2,
        1
    )
    confidence = min(primary_data["score"] / max_possible * 3, 1.0)

    # Secondary topics (score > 0 and at least 30% of primary score)
    primary_score = primary_data["score"]
    secondary = [
        name for name, data in ranked[1:]
        if data["score"] >= primary_score * 0.3
    ]

    return TopicResult(
        primary=primary_name,
        secondary=secondary[:3],  # Max 3 secondary topics
        confidence=round(confidence, 2),
        matched_keywords=primary_data["matched"][:5],
    )


def classify_topic_tag(email_text: str) -> str:
    """
    Convenience function — returns just the primary topic tag string.
    Drop-in for use with load_dynamic_examples().

    Usage:
        topic = classify_topic_tag(guest_email)
        examples = load_dynamic_examples(topic)
    """
    return classify_topic(email_text).primary


# =============================================================================
# CLI: python -m prompts.topic_classifier
# =============================================================================

if __name__ == "__main__":
    test_emails = [
        "Can I charge my Tesla at the cabin?",
        "Do you allow dogs? We have a golden retriever.",
        "What's the WiFi password? I need to work remotely.",
        "How do I turn on the hot tub?",
        "What time is check-in? Do you have a lockbox?",
        "Is there a gas grill? What about a coffee maker?",
        "The cabin is freezing! How do I turn on the heat?",
        "How steep is the driveway? Do I need 4WD?",
        "What hiking trails are nearby?",
        "Is the cabin wheelchair accessible? My mother uses a walker.",
        "What's your cancellation policy?",
        "Can I charge my Rivian? Also, is there a hot tub?",
        "What amenities does the cabin have?",
        "We're celebrating our anniversary! Any upgrades?",
        "Hello, what time is checkout and can I bring my small dog?",
    ]

    print("=" * 70)
    print("  FORTRESS PRIME — TOPIC CLASSIFIER TEST")
    print("=" * 70)

    for email in test_emails:
        result = classify_topic(email)
        sec_str = f" + {', '.join(result.secondary)}" if result.secondary else ""
        kw_str = ", ".join(result.matched_keywords[:3])
        print(f"\n  Topic: {result.primary:<18} Conf: {result.confidence:.2f}{sec_str}")
        print(f"  Email: \"{email[:65]}\"")
        print(f"  Keys:  {kw_str}")

    print(f"\n{'=' * 70}")
