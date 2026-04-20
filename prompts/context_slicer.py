"""
Fortress Prime — Context Slicer
=================================
Topic-aware cabin data retrieval for precision prompt injection.

THE PROBLEM:
  Injecting the entire cabin manual (3,000+ tokens) into every prompt
  causes local models (even 70b) to hallucinate from "noise." If the
  guest asks about the grill, they don't need the WiFi password.

THE SOLUTION:
  Use the topic_classifier's output to slice cabin data. Only the
  relevant section goes into {cabin_context}, making the AI
  laser-focused and hallucination-proof.

DATA FORMAT:
  Cabin data is stored as YAML files in the cabins/ directory:
    cabins/rolling_river.yaml
    cabins/five_peaks.yaml

  Each YAML file has topic-keyed sections that map 1:1 to the
  topic_classifier's output tags (ev_charging, pets, hot_tub, etc.).

USAGE:
    from prompts.context_slicer import slice_context, load_cabin, list_cabins

    # Full flow:
    topic = classify_topic_tag(guest_email)    # "ev_charging"
    ctx = slice_context("rolling_river", topic) # Only the EV section

    # Multi-topic (guest asks about EV + parking):
    result = classify_topic(guest_email)
    ctx = slice_context("rolling_river", result.primary, result.secondary)

    # List available cabins:
    cabins = list_cabins()  # ["rolling_river", "five_peaks"]
"""

import sys
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# Centralized path resolution (NAS-first, local fallback)
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.fortress_paths import CABINS_DIR as _RESOLVED_CABINS_DIR

# Cabin data directory — resolved by fortress_paths:
#   NAS:   /mnt/fortress_nas/fortress_data/ai_brain/cabins
#   Local: ./data/cabins
# Falls back to project root cabins/ if NAS dir is empty (first run)
_LOCAL_CABINS_DIR = Path(__file__).parent.parent / "cabins"
CABINS_DIR = _RESOLVED_CABINS_DIR if any(_RESOLVED_CABINS_DIR.glob("*.yaml")) else _LOCAL_CABINS_DIR

# Cache loaded cabin data (keyed by cabin slug)
_cabin_cache: Dict[str, Dict[str, Any]] = {}


@dataclass
class SliceResult:
    """Result of a context slice operation."""
    cabin_name: str                   # Display name (e.g., "Rolling River")
    primary_topic: str                # Primary topic that was sliced for
    context: str                      # The sliced context text
    topics_included: List[str] = field(default_factory=list)  # All topics in the slice
    token_estimate: int = 0           # Rough token count (~4 chars/token)
    full_context_tokens: int = 0      # What the FULL cabin data would have cost


# =============================================================================
# CABIN DATA LOADING
# =============================================================================

def load_cabin(cabin_slug: str) -> Dict[str, Any]:
    """
    Load cabin data from YAML. Returns the full parsed dict.
    Results are cached for performance.

    Args:
        cabin_slug: Filename without extension (e.g., "rolling_river")

    Returns:
        Full cabin data dict with all topic sections.

    Raises:
        FileNotFoundError: If the cabin YAML doesn't exist.
    """
    if cabin_slug in _cabin_cache:
        return _cabin_cache[cabin_slug]

    filepath = CABINS_DIR / f"{cabin_slug}.yaml"
    if not filepath.exists():
        available = list_cabins()
        raise FileNotFoundError(
            f"Cabin data not found: {filepath}\n"
            f"Available cabins: {', '.join(available) if available else '(none)'}\n"
            f"Create one from the template: cabins/_template.yaml"
        )

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Empty or invalid cabin YAML: {filepath}")

    _cabin_cache[cabin_slug] = data
    return data


def list_cabins() -> List[str]:
    """
    List all available cabin slugs (YAML filenames without extension).
    Excludes the _template.yaml file.

    Returns:
        Sorted list of cabin slugs (e.g., ["five_peaks", "rolling_river"])
    """
    if not CABINS_DIR.exists():
        return []

    slugs = []
    for f in CABINS_DIR.glob("*.yaml"):
        if f.stem.startswith("_"):
            continue
        with open(f, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data and data.get("status") in ("sold", "retired", "inactive"):
            continue
        slugs.append(f.stem)
    return sorted(slugs)


def get_cabin_summary(cabin_slug: str) -> Dict[str, Any]:
    """
    Return cabin metadata (name, bedrooms, status, etc.) without topic data.
    Useful for cabin selection UIs and admin views.
    """
    data = load_cabin(cabin_slug)
    return {
        "slug": cabin_slug,
        "name": data.get("name", cabin_slug),
        "status": data.get("status", "unknown"),
        "bedrooms": data.get("bedrooms", 0),
        "bathrooms": data.get("bathrooms", 0),
        "max_guests": data.get("max_guests", 0),
        "pet_friendly": data.get("pet_friendly", False),
    }


def clear_cache():
    """Clear the cabin data cache (for hot-reload or testing)."""
    _cabin_cache.clear()


# =============================================================================
# CONTEXT SLICING — THE CORE ENGINE
# =============================================================================

# Topics that map to YAML sections (must match topic_classifier output)
TOPIC_SECTIONS = [
    "ev_charging", "pets", "hot_tub", "internet", "checkin", "checkout",
    "hvac", "kitchen", "parking", "activities", "accessibility",
    "policies", "amenities",
]

# Maximum number of secondary topics to include alongside primary
MAX_SECONDARY = 2

# Always-include header: cabin identity for every response
HEADER_FIELDS = ["name", "bedrooms", "bathrooms", "max_guests", "pet_friendly"]


def slice_context(
    cabin_slug: str,
    primary_topic: str,
    secondary_topics: Optional[List[str]] = None,
    include_summary: bool = True,
    max_sections: int = 3,
) -> SliceResult:
    """
    Slice cabin data to only the relevant section(s) for a given topic.

    Instead of injecting 3,000 tokens of full cabin data, this returns
    only the 200-500 tokens the AI actually needs to answer the question.

    Args:
        cabin_slug:        Cabin identifier (e.g., "rolling_river")
        primary_topic:     Primary topic from classify_topic_tag() (e.g., "ev_charging")
        secondary_topics:  Optional list of secondary topics to include
        include_summary:   Whether to prepend the general cabin summary (default: True)
        max_sections:      Max number of topic sections to include (default: 3)

    Returns:
        SliceResult with the focused context text, token estimates, and metadata.

    Example:
        result = slice_context("rolling_river", "ev_charging", ["parking"])
        print(result.context)
        # -> "CABIN: Rolling River (3BR/2BA, sleeps 8)\n\nEV Charging: NEMA 14-50..."
        print(result.token_estimate)     # ~150 tokens
        print(result.full_context_tokens) # ~800 tokens (savings: 650 tokens)
    """
    data = load_cabin(cabin_slug)
    cabin_name = data.get("name", cabin_slug)

    parts = []
    topics_included = []

    # --- HEADER: Cabin identity (always included, ~30 tokens) ---
    header_parts = [f"CABIN: {cabin_name}"]
    meta = []
    if data.get("bedrooms"):
        meta.append(f"{data['bedrooms']}BR")
    if data.get("bathrooms"):
        meta.append(f"{data['bathrooms']}BA")
    if data.get("max_guests"):
        meta.append(f"sleeps {data['max_guests']}")
    if data.get("pet_friendly"):
        meta.append("pet-friendly")
    if meta:
        header_parts[0] += f" ({', '.join(meta)})"
    parts.append(header_parts[0])

    # --- GENERAL SUMMARY: Short overview (if requested and topic is vague) ---
    if include_summary and primary_topic in ("general", "amenities", "activities"):
        general = data.get("general_summary", "").strip()
        if general:
            parts.append(f"\nOverview:\n{general}")
            topics_included.append("general_summary")

    # --- PRIMARY TOPIC SECTION ---
    if primary_topic in TOPIC_SECTIONS and primary_topic in data:
        section = data[primary_topic].strip()
        parts.append(f"\n{section}")
        topics_included.append(primary_topic)
    elif primary_topic == "general":
        # General queries get the summary (already added above if include_summary)
        if not include_summary:
            general = data.get("general_summary", "").strip()
            if general:
                parts.append(f"\n{general}")
                topics_included.append("general_summary")
    else:
        # Unknown topic — fall back to general summary
        general = data.get("general_summary", "").strip()
        if general and "general_summary" not in topics_included:
            parts.append(f"\nOverview:\n{general}")
            topics_included.append("general_summary")

    # --- SECONDARY TOPICS (limited) ---
    if secondary_topics:
        added = 0
        for sec_topic in secondary_topics[:MAX_SECONDARY]:
            if added >= (max_sections - 1):
                break
            if sec_topic in TOPIC_SECTIONS and sec_topic in data:
                if sec_topic not in topics_included:
                    section = data[sec_topic].strip()
                    parts.append(f"\n{section}")
                    topics_included.append(sec_topic)
                    added += 1

    # --- BUILD RESULT ---
    context = "\n".join(parts)

    # Calculate token estimates
    token_estimate = len(context) // 4

    # Calculate what the full context would have cost
    full_text = "\n".join(
        str(data.get(key, ""))
        for key in TOPIC_SECTIONS
        if key in data
    )
    full_context_tokens = len(full_text) // 4

    return SliceResult(
        cabin_name=cabin_name,
        primary_topic=primary_topic,
        context=context,
        topics_included=topics_included,
        token_estimate=token_estimate,
        full_context_tokens=full_context_tokens,
    )


def slice_context_text(
    cabin_slug: str,
    primary_topic: str,
    secondary_topics: Optional[List[str]] = None,
) -> str:
    """
    Convenience function — returns just the context string.
    Drop-in replacement for raw cabin_context in prompt rendering.

    Usage:
        ctx = slice_context_text("rolling_river", "ev_charging")
        prompt = tmpl.render(cabin_context=ctx, ...)
    """
    return slice_context(cabin_slug, primary_topic, secondary_topics).context


# =============================================================================
# CLI: python -m prompts.context_slicer
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  FORTRESS PRIME — CONTEXT SLICER DEMO")
    print("=" * 70)

    cabins = list_cabins()
    if not cabins:
        print("\n  No cabin YAML files found in cabins/")
        print("  Create one from: cabins/_template.yaml")
        exit(1)

    cabin = cabins[0]
    print(f"\n  Cabin: {cabin}")
    print(f"  Available cabins: {', '.join(cabins)}")

    test_cases = [
        ("ev_charging", []),
        ("pets", []),
        ("hot_tub", ["amenities"]),
        ("general", []),
        ("kitchen", ["parking"]),
        ("checkin", []),
    ]

    for primary, secondary in test_cases:
        result = slice_context(cabin, primary, secondary or None)
        sec_str = f" + {', '.join(secondary)}" if secondary else ""
        savings = result.full_context_tokens - result.token_estimate
        pct = (savings / max(result.full_context_tokens, 1)) * 100

        print(f"\n  {'─' * 60}")
        print(f"  Topic: {primary}{sec_str}")
        print(f"  Tokens: {result.token_estimate} (full would be {result.full_context_tokens}, "
              f"saved {savings} = {pct:.0f}%)")
        print(f"  Sections: {', '.join(result.topics_included)}")
        # Show first 200 chars of context
        preview = result.context[:200].replace("\n", "\n  | ")
        print(f"  Preview:\n  | {preview}...")

    print(f"\n{'=' * 70}")
