#!/usr/bin/env python3
"""
God Head Dispatcher
===================
Filters Drupal legacy blueprint noise and emits high-value Swarm targets.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.database import AsyncSessionLocal


BLUEPRINT_PATH = Path(__file__).resolve().parent / "drupal_granular_blueprint.json"
OUTPUT_PATH = Path(__file__).resolve().parent / "swarm_target_list.json"

TIER1_TYPE_HINTS = {"property", "properties", "cabin", "cabins", "accommodation", "accommodations"}
TIER2_HINTS = {
    "blue-ridge",
    "pet-friendly",
    "mountain-view",
    "waterfront",
    "riverfront",
    "hot-tub",
    "family",
    "romantic",
    "luxury",
    "downtown",
}
NOISE_WORDS = {
    "blue",
    "ridge",
    "the",
    "on",
    "cabin",
    "lodge",
    "retreat",
    "sanctuary",
    "hideaway",
    "creek",
    "river",
    "mountain",
    "lake",
    "view",
    "views",
    "luxury",
}


def _slugify(value: str) -> str:
    slug = value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def _clean_alias(alias: str | None) -> str:
    raw = (alias or "").strip().strip("/")
    return raw


def _extract_slug_from_alias(alias: str | None) -> str | None:
    cleaned = _clean_alias(alias)
    if not cleaned:
        return None
    parts = [part for part in cleaned.split("/") if part]
    if not parts:
        return None
    return parts[-1]


def _is_tier1_node(node_type: str, alias: str | None) -> bool:
    node_type_norm = (node_type or "").lower()
    alias_norm = _clean_alias(alias).lower()

    if any(h in node_type_norm for h in TIER1_TYPE_HINTS):
        return True
    if alias_norm.startswith("cabin/"):
        return True
    return False


def _collect_tier2_signals(blueprint: dict[str, Any]) -> list[str]:
    tier2 = set(TIER2_HINTS)

    taxonomy = blueprint.get("taxonomy", {})
    terms = taxonomy.get("terms", [])
    for term in terms:
        name = str(term.get("name") or "").strip()
        if not name:
            continue
        slug = _slugify(name)
        if (
            "blue-ridge" in slug
            or "pet" in slug
            or "mountain" in slug
            or "river" in slug
            or "waterfront" in slug
            or "hot-tub" in slug
            or "luxury" in slug
            or "family" in slug
            or "romantic" in slug
            or "amenit" in slug
            or "location" in slug
        ):
            tier2.add(slug)

    menus = blueprint.get("menus", {})

    def walk_menu(items: list[dict[str, Any]]) -> None:
        for item in items:
            path = _slugify(str(item.get("link_path") or ""))
            title = _slugify(str(item.get("title") or ""))
            for text in (path, title):
                if text and (
                    "blue-ridge" in text
                    or "pet" in text
                    or "mountain" in text
                    or "river" in text
                    or "waterfront" in text
                    or "hot-tub" in text
                    or "luxury" in text
                    or "amenit" in text
                ):
                    tier2.add(text)
            walk_menu(item.get("children") or [])

    for menu_items in menus.values():
        if isinstance(menu_items, list):
            walk_menu(menu_items)

    return sorted(tier2)


async def _load_properties_by_slug() -> tuple[dict[str, str], str | None]:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    """
                    SELECT id, slug
                    FROM properties
                    WHERE slug IS NOT NULL
                      AND is_active = true
                    """
                )
            )
            out: dict[str, str] = {}
            for prop_id, slug in result.fetchall():
                key = (slug or "").strip().lower()
                if key:
                    out[key] = str(prop_id)
            return out, None
    except Exception as exc:
        return {}, str(exc)


def _derive_target_keyword(slug: str, alias: str, tier2_signals: list[str]) -> str:
    alias_norm = _slugify(alias)
    for signal in tier2_signals:
        if signal and signal in alias_norm:
            return f"luxury cabin {signal.replace('-', ' ')}"
    return f"luxury cabin {_slugify(slug).replace('-', ' ')} blue ridge"


def _semantic_tokens(slug: str) -> set[str]:
    return {part for part in slug.lower().split("-") if part and part not in NOISE_WORDS}


async def main() -> None:
    if not BLUEPRINT_PATH.exists():
        raise FileNotFoundError(f"Blueprint not found: {BLUEPRINT_PATH}")

    blueprint = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    nodes_by_type = blueprint.get("nodes_by_type", {})
    total_nodes = sum(len((v or {}).get("nodes", [])) for v in nodes_by_type.values())

    tier2_signals = _collect_tier2_signals(blueprint)
    properties_by_slug, db_error = await _load_properties_by_slug()
    available_db_slugs = sorted(properties_by_slug.keys())

    tier1_candidates: dict[str, dict[str, Any]] = {}

    for node_type, payload in nodes_by_type.items():
        for node in (payload or {}).get("nodes", []):
            alias = str(node.get("url_alias") or "")
            if not _is_tier1_node(node_type, alias):
                continue

            slug = _extract_slug_from_alias(alias)
            if not slug:
                continue

            slug_norm = slug.lower().strip("/")
            if not slug_norm:
                continue

            tier1_candidates.setdefault(
                slug_norm,
                {
                    "slug": slug_norm,
                    "source_type": node_type,
                    "source_alias": alias,
                },
            )

    matched_targets = []
    unmatched_candidates = []

    for slug, info in sorted(tier1_candidates.items()):
        property_id = properties_by_slug.get(slug)
        keyword = _derive_target_keyword(slug, info["source_alias"], tier2_signals)
        target = {
            "property_id": property_id,
            "slug": slug,
            "target_keyword": keyword,
            "source_type": info["source_type"],
            "source_alias": info["source_alias"],
        }
        if property_id:
            matched_targets.append(target)
        else:
            unmatched_candidates.append(target)

    # Pass 2: strict semantic token fallback with one-to-one DB slug claiming.
    claimed_db_slugs = set()
    for item in matched_targets:
        if item.get("property_id"):
            claimed_db_slugs.add(item["slug"])

    if available_db_slugs:
        still_unmatched = []
        for candidate in unmatched_candidates:
            legacy_slug = candidate["slug"]
            legacy_tokens = _semantic_tokens(legacy_slug)
            if not legacy_tokens:
                still_unmatched.append(candidate)
                continue

            best_slug = None
            best_score = 0
            best_db_token_count = 0
            for db_slug in available_db_slugs:
                if db_slug in claimed_db_slugs:
                    continue

                db_tokens = _semantic_tokens(db_slug)
                if not db_tokens:
                    continue

                intersection = legacy_tokens.intersection(db_tokens)
                score = len(intersection)
                is_valid = score >= 2 or (score == 1 and len(db_tokens) == 1)
                if not is_valid:
                    continue

                if (
                    score > best_score
                    or (score == best_score and len(db_tokens) > best_db_token_count)
                    or (
                        score == best_score
                        and len(db_tokens) == best_db_token_count
                        and best_slug is not None
                        and db_slug < best_slug
                    )
                ):
                    best_slug = db_slug
                    best_score = score
                    best_db_token_count = len(db_tokens)

            if best_slug:
                candidate["property_id"] = properties_by_slug.get(best_slug)
                candidate["semantic_matched_slug"] = best_slug
                matched_targets.append(candidate)
                claimed_db_slugs.add(best_slug)
                print(f"Semantic Match: {legacy_slug} -> {best_slug}")
            else:
                still_unmatched.append(candidate)
        unmatched_candidates = still_unmatched

    output = {
        "source_blueprint": str(BLUEPRINT_PATH),
        "summary": {
            "total_nodes": total_nodes,
            "tier1_candidates_isolated": len(tier1_candidates),
            "tier1_matched_properties": len(matched_targets),
            "tier1_unmatched_candidates": len(unmatched_candidates),
            "tier2_signal_count": len(tier2_signals),
            "db_cross_reference_status": "ok" if not db_error else "failed",
        },
        "db_cross_reference_error": db_error,
        "tier2_signals": tier2_signals,
        "targets": matched_targets,
        "unmatched_candidates": unmatched_candidates,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("God Head Dispatcher complete.")
    print(f"Blueprint nodes scanned: {total_nodes}")
    print(f"Tier 1 money pages isolated: {len(tier1_candidates)}")
    print(f"Tier 1 matched to Postgres properties: {len(matched_targets)}")
    print(f"Unmatched Tier 1 candidates: {len(unmatched_candidates)}")
    if db_error:
        print(f"DB cross-reference status: failed ({db_error})")
    else:
        print("DB cross-reference status: ok")
    print(f"Tier 2 category signals collected: {len(tier2_signals)}")
    print(f"Output target list: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

