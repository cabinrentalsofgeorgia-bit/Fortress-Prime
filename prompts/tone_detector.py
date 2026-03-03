"""
Fortress Prime — Automated Tone Detector
==========================================
Scans guest email text for emotional signals and returns the appropriate
tone_modifier for the guest_email_reply prompt template.

Decouples LOGIC from EMOTION — the correct answer with the wrong tone
is still a failure in hospitality.

Usage:
    from prompts.tone_detector import detect_tone

    tone = detect_tone("Help! The pipes burst and water is everywhere!")
    # Returns: ToneResult(tone="emergency", modifier="Apologetic, empathetic, ...")

    # Use with the prompt template:
    from prompts.loader import load_prompt
    tmpl = load_prompt("guest_email_reply")
    prompt = tmpl.render(
        cabin_context=cabin_data,
        guest_email=email_text,
        tone_modifier=tone.modifier
    )
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


# =============================================================================
# TONE CATEGORIES
# =============================================================================

@dataclass
class ToneResult:
    """Result of tone detection with full traceability."""
    tone: str                          # Category: emergency, complaint, vip, standard
    modifier: str                      # The tone_modifier string for the template
    confidence: float                  # 0.0-1.0 how confident we are
    triggered_keywords: List[str]      # Which keywords matched
    escalation_required: bool = False  # Flag for human review


# Tone definitions with their modifier strings and keyword sets
TONE_PROFILES = {
    "emergency": {
        "modifier": (
            "Apologetic, empathetic, and urgent. This is a safety or habitability "
            "emergency. Acknowledge the severity immediately. Provide any interim "
            "solutions from the CABIN DATA. Assure them help is on the way. Give "
            "the emergency contact number. Do NOT minimize their experience."
        ),
        "keywords": [
            # Safety hazards
            "fire", "smoke", "gas smell", "gas leak", "carbon monoxide", "co detector",
            "smoke alarm", "flooding", "flooded", "burst pipe", "pipe burst",
            "water leak", "water everywhere", "ceiling leak",
            # Habitability
            "no heat", "heat broken", "no hot water", "no water", "no power",
            "power out", "electricity out", "no electricity", "freezing",
            "locked out", "can't get in", "lock broken", "door won't open",
            "key doesn't work", "code doesn't work", "keypad broken",
            # Wildlife/safety
            "snake", "bear", "break in", "broken into", "intruder",
            "someone outside", "stalker",
            # Medical
            "ambulance", "hospital", "injured", "hurt", "fell",
            "allergic reaction", "911",
        ],
        "patterns": [
            r'\bhelp\b.*\b(immediately|urgent|now|asap|please)\b',
            r'\b(can\'t|cannot)\s+(breathe|sleep|stay)',
            r'\b(emergency|dangerous|unsafe)\b',
            r'\bno\s+(heat|water|power|electricity|ac|air\s*conditioning)\b',
            r'\bpipe[s]?\s+(burst|broke|broken|leaking)\b',
        ],
        "base_confidence": 0.9,
        "escalation": True,
    },
    "complaint": {
        "modifier": (
            "Understanding, solution-oriented, and proactive. The guest has a "
            "legitimate concern. Acknowledge their frustration without being "
            "defensive. Explain what corrective action has been or will be taken. "
            "Offer a concrete remedy where appropriate. Never blame the guest."
        ),
        "keywords": [
            # Cleanliness
            "dirty", "filthy", "gross", "disgusting", "stain", "stains",
            "hair in", "mold", "mildew", "cobweb", "dust", "grimy",
            "not cleaned", "wasn't cleaned", "unclean",
            # Maintenance
            "broken", "doesn't work", "not working", "won't work",
            "needs repair", "needs fixing", "out of order", "leaking",
            "clogged", "backed up", "rusty",
            # Misrepresentation
            "false advertising", "not as described", "not as pictured",
            "misleading", "photos don't match", "listing said",
            # Noise / neighbors
            "noisy", "loud", "noise", "construction", "barking",
            "neighbors", "party next door",
            # Pests
            "bugs", "ants", "roaches", "cockroach", "mice", "mouse",
            "spider", "spiders", "pest", "pests", "rat",
            # General dissatisfaction
            "disappointed", "unacceptable", "terrible", "worst",
            "horrible", "awful", "never again", "refund", "compensation",
            "rip off", "overpriced", "waste of money",
        ],
        "patterns": [
            r'\b(very|extremely|incredibly)\s+(disappointed|upset|frustrated|unhappy)\b',
            r'\bwant\s+(a\s+)?refund\b',
            r'\bnot\s+what\s+(we|i)\s+(expected|paid\s+for)\b',
            r'\b(false|misleading)\s+(advertising|listing|photos?)\b',
        ],
        "base_confidence": 0.75,
        "escalation": False,
    },
    "vip": {
        "modifier": (
            "Warm, celebratory, and generous. The guest is celebrating a special "
            "occasion. Make them feel valued and special. Proactively suggest "
            "upgrades, complimentary touches, or personalized experiences from "
            "the CABIN DATA. Be enthusiastic without being over-the-top."
        ),
        "keywords": [
            # Celebrations
            "anniversary", "birthday", "honeymoon", "engagement",
            "proposal", "propose", "engaged", "wedding", "celebrate", "celebration",
            "milestone", "retirement", "graduation",
            "surprise", "special occasion", "romantic",
            # Upgrades
            "upgrade", "special request", "anything extra",
            "champagne", "wine", "flowers", "roses", "cake",
            "decoration", "decorate",
            # Returning guests
            "returning guest", "stayed before", "back again",
            "favorite cabin", "love this place",
            # Group events
            "reunion", "family gathering", "girls trip", "guys trip",
            "bachelorette", "bachelor party",
        ],
        "patterns": [
            r'\b(our|my)\s+(anniversary|birthday|honeymoon)\b',
            r'\b(celebrating|celebrate)\s+\w+\s+(year|birthday|anniversary)\b',
            r'\bgoing\s+to\s+propose\b',
            r'\bspecial\s+(occasion|event|trip|weekend)\b',
        ],
        "base_confidence": 0.8,
        "escalation": False,
    },
    "standard": {
        "modifier": (
            "Polite and helpful. Provide accurate information from the CABIN DATA "
            "in a warm, professional tone. Be concise but thorough."
        ),
        "keywords": [],
        "patterns": [],
        "base_confidence": 1.0,
        "escalation": False,
    },
}


# =============================================================================
# DETECTION ENGINE
# =============================================================================

def detect_tone(email_text: str) -> ToneResult:
    """
    Analyze guest email text and return the appropriate tone classification.

    Checks keywords and regex patterns against the email. Returns the highest-
    priority match: emergency > complaint > vip > standard.

    Args:
        email_text: The raw guest email text to analyze.

    Returns:
        ToneResult with tone category, modifier string, confidence,
        matched keywords, and escalation flag.

    Example:
        result = detect_tone("The pipes burst! Water is everywhere!")
        print(result.tone)      # "emergency"
        print(result.modifier)  # "Apologetic, empathetic, and urgent..."
        print(result.confidence)  # 0.95
        print(result.triggered_keywords)  # ["burst pipe", "water everywhere"]
    """
    if not email_text:
        return ToneResult(
            tone="standard",
            modifier=TONE_PROFILES["standard"]["modifier"],
            confidence=1.0,
            triggered_keywords=[],
        )

    text_lower = email_text.lower()

    # Score each tone category (priority order)
    results = {}
    for tone_name in ["emergency", "complaint", "vip"]:
        profile = TONE_PROFILES[tone_name]
        matched_keywords = []
        pattern_matches = 0

        # Check keywords (word-boundary matching to prevent substring false positives)
        for kw in profile["keywords"]:
            # Multi-word keywords use simple containment (already specific enough)
            # Single-word keywords use word boundaries to avoid "rat" matching "celebrate"
            if " " in kw:
                if kw in text_lower:
                    matched_keywords.append(kw)
            else:
                if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    matched_keywords.append(kw)

        # Check regex patterns
        for pattern in profile["patterns"]:
            if re.search(pattern, text_lower):
                pattern_matches += 1
                # Extract the matched text for traceability
                match = re.search(pattern, text_lower)
                if match:
                    matched_keywords.append(f"[pattern: {match.group()}]")

        # Calculate confidence
        total_signals = len(matched_keywords) + pattern_matches
        if total_signals > 0:
            # More matches = higher confidence, capped at base_confidence
            confidence = min(
                profile["base_confidence"],
                0.5 + (total_signals * 0.15)
            )
            results[tone_name] = {
                "confidence": confidence,
                "keywords": matched_keywords,
                "escalation": profile["escalation"],
            }

    # Priority: emergency > complaint > vip > standard
    for priority_tone in ["emergency", "complaint", "vip"]:
        if priority_tone in results:
            r = results[priority_tone]
            return ToneResult(
                tone=priority_tone,
                modifier=TONE_PROFILES[priority_tone]["modifier"],
                confidence=r["confidence"],
                triggered_keywords=r["keywords"],
                escalation_required=r["escalation"],
            )

    # Default: standard
    return ToneResult(
        tone="standard",
        modifier=TONE_PROFILES["standard"]["modifier"],
        confidence=1.0,
        triggered_keywords=[],
    )


def detect_tone_modifier(email_text: str) -> str:
    """
    Convenience function — returns just the modifier string.
    Drop-in replacement for hardcoded tone_modifier values.

    Usage:
        tone = detect_tone_modifier(guest_email)
        prompt = tmpl.render(cabin_context=ctx, guest_email=email, tone_modifier=tone)
    """
    return detect_tone(email_text).modifier


# =============================================================================
# CLI: python -m prompts.tone_detector
# =============================================================================

if __name__ == "__main__":
    test_emails = [
        ("STANDARD", "Hi, do you have a hot tub? Also, is there WiFi?"),
        ("EMERGENCY", "HELP! The pipes burst and water is flooding the kitchen!"),
        ("EMERGENCY", "We're locked out and it's below freezing. Kids are in the car."),
        ("COMPLAINT", "The cabin was filthy when we arrived. Hair in the shower, stains on the sheets. Very disappointed."),
        ("COMPLAINT", "The WiFi doesn't work and the hot tub is broken. Not what we paid for."),
        ("VIP", "We're celebrating our 25th anniversary! Any special touches you can add?"),
        ("VIP", "I'm planning to propose to my girlfriend during our stay. Can you help with decorations?"),
        ("STANDARD", "What time is check-in? And where do we pick up the keys?"),
        ("COMPLAINT", "I want a refund. This is unacceptable."),
        ("EMERGENCY", "There's a gas smell in the cabin. Should we leave?"),
    ]

    print("=" * 70)
    print("  FORTRESS PRIME — TONE DETECTOR TEST SUITE")
    print("=" * 70)

    passed = 0
    failed = 0
    for expected, email in test_emails:
        result = detect_tone(email)
        status = "PASS" if result.tone.upper() == expected else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1

        esc = " [ESCALATE]" if result.escalation_required else ""
        print(f"\n  [{status}] Expected: {expected:<12} Got: {result.tone.upper():<12} "
              f"Conf: {result.confidence:.2f}{esc}")
        print(f"         Email: \"{email[:65]}...\"")
        if result.triggered_keywords:
            print(f"         Triggers: {', '.join(result.triggered_keywords[:5])}")

    print(f"\n{'=' * 70}")
    print(f"  Results: {passed}/{passed + failed} passed")
    print(f"{'=' * 70}")
