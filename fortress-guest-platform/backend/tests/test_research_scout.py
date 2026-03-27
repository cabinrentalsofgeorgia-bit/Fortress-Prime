from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.research_scout import compute_intelligence_dedupe_hash
from backend.services.scout_action_router import _extract_target_tags


def test_intelligence_dedupe_hash_is_stable_for_reordered_urls() -> None:
    first = compute_intelligence_dedupe_hash(
        category="content_gap",
        title="Pet-friendly cabin itineraries are undersupplied",
        summary="Travelers are searching for dog-friendly Blue Ridge itineraries with trail content.",
        market="Blue Ridge, Georgia",
        locality="Blue Ridge",
        source_urls=[
            "https://example.com/trends",
            "https://example.com/competitor/",
        ],
    )
    second = compute_intelligence_dedupe_hash(
        category="content_gap",
        title="Pet-friendly cabin itineraries are undersupplied",
        summary="Travelers are searching for dog-friendly Blue Ridge itineraries with trail content.",
        market="Blue Ridge, Georgia",
        locality="Blue Ridge",
        source_urls=[
            "https://example.com/competitor",
            "https://example.com/trends/",
        ],
    )

    assert first == second


def test_intelligence_dedupe_hash_changes_for_distinct_finding() -> None:
    first = compute_intelligence_dedupe_hash(
        category="competitor_trend",
        title="Competitor launched romance package",
        summary="A local competitor is bundling hot tub and vineyard itineraries into a romance package.",
        market="Blue Ridge, Georgia",
        locality="Blue Ridge",
        source_urls=["https://example.com/romance-package"],
    )
    second = compute_intelligence_dedupe_hash(
        category="competitor_trend",
        title="Competitor launched workcation package",
        summary="A local competitor is bundling hot tub and vineyard itineraries into a romance package.",
        market="Blue Ridge, Georgia",
        locality="Blue Ridge",
        source_urls=["https://example.com/romance-package"],
    )

    assert first != second


def test_extract_target_tags_detects_amenity_and_event_signals() -> None:
    entry = SimpleNamespace(
        category="market_shift",
        title="Blue Ridge Fly Fishing Festival weekend is driving river demand",
        summary="Travelers are searching for river cabins and fly fishing lodging near Blue Ridge.",
        locality="Blue Ridge",
        query_topic="market_shift",
        finding_payload={"notes": ["riverfront", "angler traffic rising"]},
    )

    assert _extract_target_tags(entry) == ["fishing-nearby", "river-access"]
