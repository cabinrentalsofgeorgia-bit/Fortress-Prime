#!/usr/bin/env python3
"""
Generate SEO migration redirects from Drupal blueprint to Next.js routes.

Outputs a ranked candidate set and can optionally persist candidates into
`seo_redirects` while emitting signed OpenShell audit records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT_PATH = Path(__file__).resolve().parent / "drupal_granular_blueprint.json"
OUTPUT_PATH = Path(__file__).resolve().parent / "seo_migration_candidates.json"
ORPHAN_REPORT_PATH = Path(__file__).resolve().parent / "orphan_report.json"
ARCHIVE_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "archives" / "testimonials"
FRONTEND_APP_DIR = REPO_ROOT / "apps" / "storefront" / "src" / "app"

project_root = str(REPO_ROOT)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.services.sovereign_archive import build_signed_archive_record


@dataclass
class RedirectCandidate:
    source_path: str
    destination_path: str
    confidence: float
    strategy: str
    reason: str
    source_type: str
    title: str | None = None
    source_ref: str | None = None
    node_type: str | None = None
    taxonomy_terms: list[str] | None = None


@dataclass
class TaxonomyTerm:
    tid: int
    name: str
    description: str | None
    canonical_alias: str | None
    aliases: list[str]
    route_hint: str | None
    tokens: set[str]


@dataclass
class AliasObservation:
    source_path: str
    source_ref: str | None
    source_title: str | None
    node_type: str | None
    taxonomy_terms: list[str]
    destination_path: str
    confidence: float
    strategy: str
    reason: str
    route_hint: str | None


@dataclass
class ArchiveRecord:
    slug: str
    payload: dict[str, Any]


def _normalize_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return "/"
    # Strip domain if present.
    raw = re.sub(r"^https?://[^/]+", "", raw, flags=re.IGNORECASE)
    if not raw.startswith("/"):
        raw = f"/{raw}"
    # Collapse duplicate slashes.
    raw = re.sub(r"/{2,}", "/", raw)
    # Remove trailing slash except root.
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw[:-1]
    return raw


def _tokenize(value: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    tokens = {t for t in cleaned.split() if len(t) >= 2}
    return tokens


def _slug_from_path(path: str) -> str:
    normalized = _normalize_path(path)
    return normalized.strip("/").split("/")[-1] if normalized not in {"/", ""} else ""


def _normalize_requested_slug(value: str) -> str:
    slug = _slug_from_path(value or "")
    if not slug:
        raise ValueError("single slug cannot be blank")
    return slug


def _discover_next_routes(app_dir: Path) -> list[str]:
    routes: set[str] = {"/"}
    if not app_dir.exists():
        return sorted(routes)

    page_files = list(app_dir.rglob("page.tsx")) + list(app_dir.rglob("page.ts")) + list(app_dir.rglob("page.jsx")) + list(app_dir.rglob("page.js")) + list(app_dir.rglob("page.mdx"))
    for file_path in page_files:
        rel = file_path.relative_to(app_dir)
        parts = []
        for part in rel.parts[:-1]:
            # Skip route groups.
            if part.startswith("(") and part.endswith(")"):
                continue
            # Skip private folders.
            if part.startswith("_"):
                continue
            # Skip dynamic segment markers for static redirect targets.
            if "[" in part and "]" in part:
                if parts:
                    routes.add(_normalize_path("/" + "/".join(parts)))
                continue
            parts.append(part)
        route = "/" + "/".join(parts) if parts else "/"
        route = _normalize_path(route)
        routes.add(route)

    # Common app-level fallback targets used by migration strategy.
    routes.update(
        {
            "/properties",
            "/property-management",
            "/concierge",
            "/about",
            "/contact",
            "/faq",
            "/blog",
            "/experiences",
            "/specials",
            "/cabins",
        }
    )
    return sorted(routes)


def _flatten_menu_links(menus: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        out.append(node)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child)

    for tree in menus.values():
        if not isinstance(tree, list):
            continue
        for node in tree:
            if isinstance(node, dict):
                walk(node)
    return out


def _build_node_lookup(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    content_types = (
        blueprint.get("content_types")
        or blueprint.get("nodes_by_type")
        or {}
    )
    by_source: dict[str, dict[str, Any]] = {}
    for _, payload in content_types.items():
        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            source = node.get("source_path")
            if source:
                node_copy = dict(node)
                node_copy["node_type"] = node_copy.get("node_type") or _
                by_source[str(source)] = node_copy

    global_alias_sources = ((blueprint.get("global_alias_scan") or {}).get("by_source") or {})
    for source, payload in global_alias_sources.items():
        if not isinstance(payload, dict):
            continue
        node_payload = payload.get("node")
        if not isinstance(node_payload, dict):
            continue
        node_copy = dict(node_payload)
        node_copy["node_type"] = node_copy.get("node_type") or "unknown"
        if payload.get("canonical_alias") and not node_copy.get("url_alias"):
            node_copy["url_alias"] = payload.get("canonical_alias")
        by_source[str(source)] = node_copy
    return by_source


def _build_property_catalog(blueprint: dict[str, Any]) -> list[dict[str, str]]:
    content_types = (
        blueprint.get("content_types")
        or blueprint.get("nodes_by_type")
        or {}
    )
    catalog: list[dict[str, str]] = []
    for node_type, payload in content_types.items():
        if str(node_type).lower() not in {"cabin", "cabins", "property", "properties"}:
            continue
        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            alias = _normalize_path(str(node.get("url_alias") or ""))
            slug = _slug_from_path(alias)
            if not slug:
                continue
            title = str(node.get("title") or "").strip()
            token_source = " ".join(filter(None, [title, slug, alias]))
            catalog.append(
                {
                    "slug": slug,
                    "path": f"/cabins/{slug}",
                    "title": title,
                    "token_source": token_source,
                }
            )
    return catalog


def _infer_related_property(
    *,
    source_path: str,
    source_title: str | None,
    taxonomy_terms: list[TaxonomyTerm],
    property_catalog: list[dict[str, str]],
) -> dict[str, str] | None:
    source_tokens = _tokenize(
        " ".join(
            filter(
                None,
                [
                    source_path,
                    source_title or "",
                    " ".join(term.name for term in taxonomy_terms),
                ],
            )
        )
    )
    best_match: dict[str, str] | None = None
    best_score = 0.0
    for property_row in property_catalog:
        property_tokens = _tokenize(property_row.get("token_source", ""))
        if not property_tokens:
            continue
        overlap = len(source_tokens & property_tokens) / float(max(len(property_tokens), 1))
        slug_bonus = 1.0 if property_row["slug"] and property_row["slug"] in source_path.lower() else 0.0
        title_bonus = 1.0 if property_row["title"] and property_row["title"].lower() in f"{source_title or ''}".lower() else 0.0
        score = max(overlap, slug_bonus, title_bonus)
        if score > best_score:
            best_score = score
            best_match = property_row
    return best_match if best_score >= 0.34 else None


def _build_testimonial_archive_record(
    *,
    source_path: str,
    source_ref: str,
    source_title: str | None,
    taxonomy_terms: list[TaxonomyTerm],
    property_catalog: list[dict[str, str]],
    node_info: dict[str, Any],
) -> ArchiveRecord:
    slug = _slug_from_path(source_path)
    legacy_node_id = str(node_info.get("nid") or source_ref.rsplit("/", 1)[-1] or slug)
    content_body = str(node_info.get("body") or "").strip()
    body_status = "verified" if content_body else "missing_in_blueprint"
    related_property = _infer_related_property(
        source_path=source_path,
        source_title=source_title,
        taxonomy_terms=taxonomy_terms,
        property_catalog=property_catalog,
    )
    payload = build_signed_archive_record(
        legacy_node_id=legacy_node_id,
        original_slug=source_path,
        content_body=content_body,
        category_tags=[term.name for term in taxonomy_terms],
        title=source_title,
        archive_slug=slug,
        archive_path=f"/reviews/archive/{slug}",
        source_ref=source_ref or None,
        node_type="testimonial",
        related_property_slug=related_property["slug"] if related_property else None,
        related_property_path=related_property["path"] if related_property else None,
        related_property_title=related_property["title"] if related_property else None,
        body_status=body_status,
    )
    return ArchiveRecord(slug=slug, payload=payload)


def _route_hint_from_term_alias(canonical_alias: str | None, term_name: str) -> str | None:
    alias = _normalize_path(canonical_alias or "")
    value = f"{alias} {term_name}".lower()
    if alias.startswith(("/amenities/", "/bedrooms/", "/bathrooms/", "/level/", "/cabins/")):
        return "/properties"
    if alias.startswith(("/activity/", "/activities/", "/attractions/", "/trip-itineraries/")):
        return "/experiences"
    if any(keyword in value for keyword in ("pet", "mountain", "river", "lake", "luxury", "family reunion", "corporate retreat", "romantic")):
        return "/properties"
    if any(keyword in value for keyword in ("hiking", "fishing", "waterfalls", "orchards", "shopping", "restaurants", "railway", "itineraries")):
        return "/experiences"
    if any(keyword in value for keyword in ("massage", "spa", "chef", "concierge")):
        return "/concierge"
    return None


def _build_taxonomy_lookup(blueprint: dict[str, Any]) -> dict[int, TaxonomyTerm]:
    terms = ((blueprint.get("taxonomy") or {}).get("terms") or [])
    by_source = ((blueprint.get("url_aliases") or {}).get("by_source") or {})
    lookup: dict[int, TaxonomyTerm] = {}
    for term in terms:
        if not isinstance(term, dict):
            continue
        tid = int(term.get("tid") or 0)
        if tid <= 0:
            continue
        source_ref = f"taxonomy/term/{tid}"
        alias_payload = by_source.get(source_ref) or {}
        canonical_alias = alias_payload.get("canonical_alias")
        aliases = list(alias_payload.get("aliases") or [])
        name = str(term.get("name") or "").strip()
        description = str(term.get("description") or "").strip() or None
        token_source = " ".join(filter(None, [name, canonical_alias or "", description or ""]))
        lookup[tid] = TaxonomyTerm(
            tid=tid,
            name=name,
            description=description,
            canonical_alias=canonical_alias,
            aliases=aliases,
            route_hint=_route_hint_from_term_alias(canonical_alias, name),
            tokens=_tokenize(token_source),
        )
    return lookup


def _pick_hard_menu_destination(path: str, title: str, next_routes: list[str]) -> str:
    value = f"{path} {title}".lower()
    hard_map = [
        (("cabin", "cabins", "luxury", "riverfront", "mountain-view", "pet-friendly"), "/properties"),
        (("special", "discount", "deal"), "/specials"),
        (("experience", "activities", "attractions"), "/experiences"),
        (("concierge", "service"), "/concierge"),
        (("contact",), "/contact"),
        (("faq", "questions"), "/faq"),
        (("blog", "news", "article"), "/blog"),
        (("about", "company"), "/about"),
        (("management", "owners"), "/property-management"),
    ]
    for keys, destination in hard_map:
        if any(k in value for k in keys):
            if destination in next_routes:
                return destination
            return "/properties"
    return "/properties" if "/properties" in next_routes else "/"


def _best_semantic_destination(source_path: str, source_title: str | None, next_routes: list[str]) -> tuple[str, float]:
    source_for_match = f"{source_path} {source_title or ''}"
    source_tokens = _tokenize(source_for_match)
    if not source_tokens:
        return "/", 0.0

    best_route = "/"
    best_score = 0.0
    for route in next_routes:
        if route == "/":
            continue
        route_tokens = _tokenize(route.replace("/", " "))
        if not route_tokens:
            continue
        overlap = len(source_tokens & route_tokens) / float(max(len(source_tokens), 1))
        sequence = SequenceMatcher(a=source_path.lower(), b=route.lower()).ratio()
        score = 0.65 * overlap + 0.35 * sequence
        if score > best_score:
            best_score = score
            best_route = route

    if best_route == "/" and "/properties" in next_routes:
        return "/properties", 0.35
    return best_route, best_score


def _route_hint_from_node_type(node_type: str | None, source_path: str, source_title: str | None) -> str | None:
    node = (node_type or "").lower()
    value = f"{source_path} {source_title or ''}".lower()
    if node in {"activity", "activities"} or any(token in value for token in ("activity/", "/activities", "blue-ridge-experience", "trip-itineraries")):
        return "/experiences"
    if node in {"blog", "article", "post"} or "/blog/" in value:
        return "/blog"
    if node in {"cabin", "cabins", "property", "properties"} or "/cabin/" in value or "/cabins/" in value:
        return "/cabins"
    if any(token in value for token in ("owner", "management", "property-management")):
        return "/property-management"
    if any(token in value for token in ("massage", "spa", "chef", "concierge")):
        return "/concierge"
    if "faq" in value:
        return "/faq"
    if "contact" in value:
        return "/contact"
    if "about" in value:
        return "/about"
    return None


def _infer_taxonomy_terms(
    source_path: str,
    source_title: str | None,
    taxonomy_lookup: dict[int, TaxonomyTerm],
    *,
    max_terms: int = 4,
) -> list[TaxonomyTerm]:
    source_value = f"{source_path} {source_title or ''}".lower()
    source_tokens = _tokenize(source_value)
    scored: list[tuple[float, TaxonomyTerm]] = []
    for term in taxonomy_lookup.values():
        if not term.tokens:
            continue
        overlap = len(source_tokens & term.tokens) / float(max(len(term.tokens), 1))
        exact_name = 1.0 if term.name and term.name.lower() in source_value else 0.0
        alias_match = 0.0
        if term.canonical_alias:
            canonical = term.canonical_alias.lower().strip("/")
            if canonical and canonical in source_value:
                alias_match = 1.0
            elif canonical:
                alias_tokens = _tokenize(canonical.replace("/", " "))
                alias_match = len(source_tokens & alias_tokens) / float(max(len(alias_tokens), 1))
        score = max(overlap, exact_name, alias_match)
        if score >= 0.24:
            scored.append((score, term))
    scored.sort(key=lambda item: (item[0], len(item[1].tokens)), reverse=True)
    return [term for _score, term in scored[:max_terms]]


def _build_route_hint_scores(
    *,
    source_path: str,
    source_title: str | None,
    node_type: str | None,
    taxonomy_terms: list[TaxonomyTerm],
    next_routes: list[str],
) -> dict[str, float]:
    hints: dict[str, float] = defaultdict(float)

    def add(route: str | None, weight: float) -> None:
        if not route:
            return
        normalized = _normalize_path(route)
        if normalized not in next_routes:
            if normalized == "/cabins" and "/cabins" not in next_routes and "/properties" in next_routes:
                normalized = "/properties"
            elif normalized not in next_routes:
                return
        hints[normalized] += weight

    value = f"{source_path} {source_title or ''}".lower()
    add(_route_hint_from_node_type(node_type, source_path, source_title), 0.35)
    for term in taxonomy_terms:
        add(term.route_hint, 0.18)

    if any(token in value for token in ("pet-friendly", "pet friendly", "mountain view", "river", "lake", "hot tub", "luxury", "bedroom", "bathroom", "amenities/")):
        add("/properties", 0.22)
    if any(token in value for token in ("blue ridge", "experience", "activities", "attractions", "shopping", "hiking", "fishing", "waterfalls", "orchards", "trip-itineraries")):
        add("/experiences", 0.2)
    if "/blog/" in value or any(token in value for token in ("blog", "article", "news")):
        add("/blog", 0.2)
    if any(token in value for token in ("massage", "spa", "chef", "concierge")):
        add("/concierge", 0.2)
    return hints


def _best_taxonomy_aware_destination(
    *,
    source_path: str,
    source_title: str | None,
    node_type: str | None,
    taxonomy_terms: list[TaxonomyTerm],
    next_routes: list[str],
) -> tuple[str, float, str | None]:
    route_hints = _build_route_hint_scores(
        source_path=source_path,
        source_title=source_title,
        node_type=node_type,
        taxonomy_terms=taxonomy_terms,
        next_routes=next_routes,
    )
    semantic_route, semantic_score = _best_semantic_destination(source_path, source_title, next_routes)
    best_route = semantic_route
    best_score = semantic_score
    best_hint = None
    source_for_match = f"{source_path} {source_title or ''}"
    source_tokens = _tokenize(source_for_match)
    for route in next_routes:
        if route == "/":
            continue
        route_tokens = _tokenize(route.replace("/", " "))
        overlap = len(source_tokens & route_tokens) / float(max(len(source_tokens), 1)) if source_tokens else 0.0
        sequence = SequenceMatcher(a=source_path.lower(), b=route.lower()).ratio()
        hint_bonus = min(route_hints.get(route, 0.0), 0.45)
        score = 0.35 * overlap + 0.25 * sequence + 0.4 * hint_bonus
        if score > best_score:
            best_route = route
            best_score = score
            best_hint = route if hint_bonus > 0 else None
    if best_route == "/" and route_hints:
        route, weight = max(route_hints.items(), key=lambda item: item[1])
        return route, min(0.99, 0.45 + min(weight, 0.45)), route
    return best_route, min(0.99, best_score), best_hint


def _high_precision_fallback(
    *,
    source_path: str,
    source_ref: str,
    source_title: str | None,
    node_type: str | None,
    taxonomy_terms: list[TaxonomyTerm],
    next_routes: list[str],
) -> tuple[str | None, float, str | None]:
    value = f"{source_path} {source_title or ''}".lower()
    route_hints = _build_route_hint_scores(
        source_path=source_path,
        source_title=source_title,
        node_type=node_type,
        taxonomy_terms=taxonomy_terms,
        next_routes=next_routes,
    )

    def resolve(route: str | None) -> str | None:
        if not route:
            return None
        normalized = _normalize_path(route)
        if normalized in next_routes:
            return normalized
        if normalized == "/cabins" and "/cabins" not in next_routes and "/properties" in next_routes:
            return "/properties"
        return None

    for synonym, route in (
        ("about-us", "/about"),
        ("specials-discounts", "/specials"),
        ("faq", "/faq"),
        ("contact", "/contact"),
    ):
        if synonym in value:
            resolved = resolve(route)
            if resolved:
                return resolved, 0.76, "direct_synonym_fallback"

    if source_ref.startswith("taxonomy/term/"):
        hinted_route = resolve(max(route_hints.items(), key=lambda item: item[1])[0] if route_hints else None)
        if hinted_route:
            return hinted_route, 0.8, "taxonomy_term_intent_match"

    if node_type == "activity":
        resolved = resolve("/experiences")
        if resolved:
            return resolved, 0.74, "activity_archive_intent_match"

    if node_type == "blog":
        resolved = resolve("/blog")
        if resolved:
            return resolved, 0.74, "blog_archive_intent_match"

    if node_type in {"micro_site", "landing_page"} and any(
        token in value for token in ("cabin", "cabins", "bedroom", "pet-friendly", "mountain-view", "riverfront")
    ):
        resolved = resolve("/cabins") or resolve("/properties")
        if resolved:
            return resolved, 0.72, "collection_landing_intent_match"

    return None, 0.0, None


def _build_orphan_report(
    *,
    aliases: list[dict[str, Any]],
    selected_sources: set[str],
    near_misses: list[AliasObservation],
    node_lookup: dict[str, dict[str, Any]],
    taxonomy_lookup: dict[int, TaxonomyTerm],
) -> dict[str, Any]:
    near_miss_sources = {item.source_path for item in near_misses}
    node_type_counter: Counter[str] = Counter()
    taxonomy_counter: Counter[str] = Counter()
    orphan_samples: list[dict[str, Any]] = []
    by_node_type_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_taxonomy_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for alias in aliases:
        if not isinstance(alias, dict):
            continue
        source_path = _normalize_path(str(alias.get("alias_path") or ""))
        if source_path in {"/", ""} or source_path in selected_sources or source_path in near_miss_sources:
            continue
        source_ref = str(alias.get("source_path") or "")
        node_info = node_lookup.get(source_ref, {})
        source_title = node_info.get("title") if isinstance(node_info, dict) else None
        node_type = str(node_info.get("node_type") or "unknown") if isinstance(node_info, dict) else "unknown"
        inferred_terms = _infer_taxonomy_terms(source_path, source_title, taxonomy_lookup)
        term_names = [term.name for term in inferred_terms]
        node_type_counter[node_type] += 1
        for term_name in (term_names or ["unclassified"]):
            taxonomy_counter[term_name] += 1

        sample = {
            "source_path": source_path,
            "source_ref": source_ref or None,
            "title": source_title,
            "node_type": node_type,
            "taxonomy_terms": term_names,
        }
        if len(orphan_samples) < 250:
            orphan_samples.append(sample)
        if len(by_node_type_samples[node_type]) < 5:
            by_node_type_samples[node_type].append(sample)
        for term_name in term_names[:2] or ["unclassified"]:
            if len(by_taxonomy_samples[term_name]) < 5:
                by_taxonomy_samples[term_name].append(sample)

    by_node_type = [
        {"node_type": name, "count": count, "samples": by_node_type_samples[name]}
        for name, count in node_type_counter.most_common()
    ]
    by_taxonomy_term = [
        {"taxonomy_term": name, "count": count, "samples": by_taxonomy_samples[name]}
        for name, count in taxonomy_counter.most_common()
    ]
    return {
        "orphan_count": sum(node_type_counter.values()),
        "by_node_type": by_node_type,
        "by_taxonomy_term": by_taxonomy_term,
        "samples": orphan_samples,
    }


def _generate_candidates(
    blueprint: dict[str, Any],
    *,
    next_routes: list[str],
    max_candidates: int,
    min_confidence: float,
    monitoring_threshold: float,
) -> tuple[list[RedirectCandidate], list[ArchiveRecord], list[AliasObservation], dict[str, Any], dict[str, Any]]:
    node_lookup = _build_node_lookup(blueprint)
    taxonomy_lookup = _build_taxonomy_lookup(blueprint)
    property_catalog = _build_property_catalog(blueprint)
    seen_sources: set[str] = set()
    candidates: list[RedirectCandidate] = []
    archive_records: list[ArchiveRecord] = []
    near_misses: list[AliasObservation] = []
    visible_menu_sources: set[str] = set()

    # 1) Hard redirect menu links (non-negotiable)
    for menu_item in _flatten_menu_links(blueprint.get("menus", {}) or {}):
        if menu_item.get("hidden"):
            continue
        source = _normalize_path(str(menu_item.get("link_path", "")).strip())
        if source in {"/", ""}:
            continue
        visible_menu_sources.add(source)
        if source in seen_sources:
            continue
        title = str(menu_item.get("title") or "").strip()
        destination = _pick_hard_menu_destination(source, title, next_routes)
        if destination == source:
            continue
        seen_sources.add(source)
        candidates.append(
            RedirectCandidate(
                source_path=source,
                destination_path=destination,
                confidence=0.995,
                strategy="hard_redirect_menu",
                reason="top_level_navigation_guardrail",
                source_type="menu_link",
                title=title or None,
                source_ref=str(menu_item.get("mlid")) if menu_item.get("mlid") is not None else None,
                taxonomy_terms=[],
            )
        )

    # 2) Taxonomy-aware semantic alias mapping for node/taxonomy aliases.
    aliases = ((blueprint.get("url_aliases") or {}).get("records") or [])
    for alias in aliases:
        if not isinstance(alias, dict):
            continue
        source = _normalize_path(str(alias.get("alias_path") or ""))
        if source in {"/", ""} or source in seen_sources:
            continue

        source_ref = str(alias.get("source_path") or "")
        node_info = node_lookup.get(source_ref, {})
        source_title = node_info.get("title") if isinstance(node_info, dict) else None
        node_type = str(node_info.get("node_type") or "") if isinstance(node_info, dict) else ""
        inferred_terms = _infer_taxonomy_terms(source, source_title, taxonomy_lookup)
        if node_type.lower() == "testimonial":
            slug = _slug_from_path(source)
            if not slug:
                continue
            seen_sources.add(source)
            archive_records.append(
                _build_testimonial_archive_record(
                    source_path=source,
                    source_ref=source_ref,
                    source_title=source_title,
                    taxonomy_terms=inferred_terms,
                    property_catalog=property_catalog,
                    node_info=node_info if isinstance(node_info, dict) else {},
                )
            )
            candidates.append(
                RedirectCandidate(
                    source_path=source,
                    destination_path=f"/reviews/archive/{slug}",
                    confidence=0.995,
                    strategy="testimonial_archive_strategy",
                    reason="verified_archive_recovery",
                    source_type="testimonial_archive",
                    title=source_title,
                    source_ref=source_ref or None,
                    node_type=node_type or None,
                    taxonomy_terms=[term.name for term in inferred_terms],
                )
            )
            continue
        destination, score, route_hint = _high_precision_fallback(
            source_path=source,
            source_ref=source_ref,
            source_title=source_title,
            node_type=node_type or None,
            taxonomy_terms=inferred_terms,
            next_routes=next_routes,
        )
        if not destination:
            destination, score, route_hint = _best_taxonomy_aware_destination(
                source_path=source,
                source_title=source_title,
                node_type=node_type,
                taxonomy_terms=inferred_terms,
                next_routes=next_routes,
            )
        confidence = max(0.0, min(0.99, score))
        if destination == source:
            continue
        term_names = [term.name for term in inferred_terms]
        strategy = "semantic_alias_mapping"
        reason = "title_and_alias_semantic_similarity"
        if route_hint == "taxonomy_term_intent_match":
            strategy = "taxonomy_aware_fallback"
            reason = "taxonomy_term_intent_match"
        elif route_hint == "activity_archive_intent_match":
            strategy = "node_type_fallback"
            reason = "activity_archive_intent_match"
        elif route_hint == "blog_archive_intent_match":
            strategy = "node_type_fallback"
            reason = "blog_archive_intent_match"
        elif route_hint == "collection_landing_intent_match":
            strategy = "taxonomy_aware_fallback"
            reason = "collection_landing_intent_match"
        elif route_hint == "direct_synonym_fallback":
            strategy = "semantic_alias_mapping"
            reason = "direct_synonym_fallback"
        elif route_hint and term_names:
            strategy = "taxonomy_aware_fallback"
            reason = "taxonomy_term_and_node_type_intent_match"
        elif route_hint:
            strategy = "node_type_fallback"
            reason = "node_type_intent_match"

        if confidence < min_confidence:
            if confidence >= monitoring_threshold:
                near_misses.append(
                    AliasObservation(
                        source_path=source,
                        source_ref=source_ref or None,
                        source_title=source_title,
                        node_type=node_type or None,
                        taxonomy_terms=term_names,
                        destination_path=destination,
                        confidence=confidence,
                        strategy=strategy,
                        reason=reason,
                        route_hint=route_hint,
                    )
                )
            continue

        seen_sources.add(source)
        candidates.append(
            RedirectCandidate(
                source_path=source,
                destination_path=destination,
                confidence=confidence,
                strategy=strategy,
                reason=reason,
                source_type="url_alias",
                title=source_title,
                source_ref=source_ref or None,
                node_type=node_type or None,
                taxonomy_terms=term_names,
            )
        )

    # Rank and trim for first review batch.
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    archive_records.sort(key=lambda item: item.slug)
    near_misses.sort(key=lambda item: item.confidence, reverse=True)
    archive_candidates = [candidate for candidate in candidates if candidate.source_type == "testimonial_archive"]
    non_archive_candidates = [candidate for candidate in candidates if candidate.source_type != "testimonial_archive"]
    trimmed_candidates = archive_candidates + non_archive_candidates[:max_candidates]
    selected_sources = {candidate.source_path for candidate in candidates}
    orphan_report = _build_orphan_report(
        aliases=aliases,
        selected_sources=selected_sources,
        near_misses=near_misses,
        node_lookup=node_lookup,
        taxonomy_lookup=taxonomy_lookup,
    )
    metrics = {
        "top_level_protection": {
            "mapped": sum(1 for candidate in trimmed_candidates if candidate.source_type == "menu_link"),
            "total": len(visible_menu_sources),
        },
        "verified_archive_recovery": {
            "mapped": len(archive_records),
            "total": len(archive_records),
        },
        "long_tail_recovery": {
            "mapped": sum(
                1 for candidate in trimmed_candidates if candidate.source_type in {"url_alias", "testimonial_archive"}
            ),
            "total": len([alias for alias in aliases if isinstance(alias, dict)]),
        },
        "near_miss_count": len(near_misses),
        "orphan_count": orphan_report["orphan_count"],
    }
    return trimmed_candidates, archive_records, near_misses, orphan_report, metrics


async def _persist_candidates(candidates: list[RedirectCandidate]) -> tuple[int, int]:
    # Import lazily so the script still works in export-only mode.
    import sys

    project_root = str(REPO_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from sqlalchemy import select

    from backend.core.database import AsyncSessionLocal
    from backend.models.seo_redirect import SeoRedirect
    from backend.services.openshell_audit import record_audit_event

    request_id = f"seo-migration-{uuid.uuid4().hex[:12]}"
    inserted = 0
    updated = 0

    async with AsyncSessionLocal() as db:
        for candidate in candidates:
            existing = (
                await db.execute(select(SeoRedirect).where(SeoRedirect.source_path == candidate.source_path))
            ).scalar_one_or_none()

            auto_reason = f"[AUTO][CONF={candidate.confidence:.3f}] {candidate.reason}"
            actor = "nemoclaw_orchestrator"
            if existing is None:
                existing = SeoRedirect(
                    source_path=candidate.source_path,
                    destination_path=candidate.destination_path,
                    is_permanent=True,
                    reason=auto_reason,
                    created_by=actor,
                    updated_by=actor,
                    is_active=True,
                )
                db.add(existing)
                await db.flush()
                inserted += 1
            else:
                # Preserve manual edits unless previously auto-generated.
                manual_entry = not ((existing.reason or "").startswith("[AUTO]") or (existing.created_by or "") == actor)
                if manual_entry:
                    continue
                existing.destination_path = candidate.destination_path
                existing.is_permanent = True
                existing.reason = auto_reason
                existing.updated_by = actor
                existing.is_active = True
                await db.flush()
                updated += 1

            await record_audit_event(
                actor_id=actor,
                actor_email=None,
                action="seo.migration.redirect.generated",
                resource_type="seo_redirect",
                resource_id=str(existing.id),
                purpose="drupal_to_nextjs_redirect_migration",
                tool_name="generate_seo_migration_map",
                redaction_status="not_applicable",
                model_route="spark_node_2_leader",
                outcome="success",
                request_id=request_id,
                metadata_json={
                    "source_path": candidate.source_path,
                    "destination_path": candidate.destination_path,
                    "confidence": round(candidate.confidence, 4),
                    "strategy": candidate.strategy,
                    "source_type": candidate.source_type,
                    "source_ref": candidate.source_ref,
                    "title": candidate.title,
                },
                db=db,
            )

    return inserted, updated


async def _persist_observations(observations: list[AliasObservation]) -> int:
    import sys

    project_root = str(REPO_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from backend.services.openshell_audit import record_audit_event

    request_id = f"seo-monitor-{uuid.uuid4().hex[:12]}"
    written = 0
    for item in observations:
        row = await record_audit_event(
            actor_id="nemoclaw_orchestrator",
            actor_email=None,
            action="seo.migration.near_miss.detected",
            resource_type="seo_redirect_observation",
            resource_id=item.source_ref or item.source_path,
            purpose="drupal_to_nextjs_redirect_monitoring",
            tool_name="generate_seo_migration_map",
            redaction_status="not_applicable",
            model_route="spark_node_2_leader",
            outcome="success",
            request_id=request_id,
            metadata_json={
                "source_path": item.source_path,
                "destination_path": item.destination_path,
                "confidence": round(item.confidence, 4),
                "strategy": item.strategy,
                "reason": item.reason,
                "source_ref": item.source_ref,
                "title": item.source_title,
                "node_type": item.node_type,
                "taxonomy_terms": item.taxonomy_terms,
                "route_hint": item.route_hint,
            },
        )
        if row is not None:
            written += 1
    return written


def _serialize_candidates(candidates: list[RedirectCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "source_path": c.source_path,
            "destination_path": c.destination_path,
            "confidence": round(c.confidence, 4),
            "strategy": c.strategy,
            "reason": c.reason,
            "source_type": c.source_type,
            "title": c.title,
            "source_ref": c.source_ref,
            "node_type": c.node_type,
            "taxonomy_terms": c.taxonomy_terms or [],
        }
        for c in candidates
    ]


def _serialize_observations(observations: list[AliasObservation]) -> list[dict[str, Any]]:
    return [
        {
            "source_path": item.source_path,
            "source_ref": item.source_ref,
            "title": item.source_title,
            "node_type": item.node_type,
            "taxonomy_terms": item.taxonomy_terms,
            "destination_path": item.destination_path,
            "confidence": round(item.confidence, 4),
            "strategy": item.strategy,
            "reason": item.reason,
            "route_hint": item.route_hint,
        }
        for item in observations
    ]


def _serialize_archive_records(records: list[ArchiveRecord]) -> list[dict[str, Any]]:
    return [
        {
            "slug": item.slug,
            "archive_path": item.payload.get("archive_path"),
            "original_slug": item.payload.get("original_slug"),
            "legacy_node_id": item.payload.get("legacy_node_id"),
            "body_status": item.payload.get("body_status"),
            "category_tags": item.payload.get("category_tags", []),
            "related_property_slug": item.payload.get("related_property_slug"),
            "related_property_title": item.payload.get("related_property_title"),
        }
        for item in records
    ]


def _build_single_testimonial_target(
    blueprint: dict[str, Any],
    *,
    requested_slug: str,
) -> tuple[RedirectCandidate, ArchiveRecord] | None:
    target_slug = _normalize_requested_slug(requested_slug)
    node_lookup = _build_node_lookup(blueprint)
    taxonomy_lookup = _build_taxonomy_lookup(blueprint)
    property_catalog = _build_property_catalog(blueprint)
    aliases = ((blueprint.get("url_aliases") or {}).get("records") or [])

    for alias in aliases:
        if not isinstance(alias, dict):
            continue
        source = _normalize_path(str(alias.get("alias_path") or ""))
        if _slug_from_path(source) != target_slug:
            continue

        source_ref = str(alias.get("source_path") or "")
        node_info = node_lookup.get(source_ref, {})
        source_title = node_info.get("title") if isinstance(node_info, dict) else None
        node_type = str(node_info.get("node_type") or "") if isinstance(node_info, dict) else ""
        source_kind = str(alias.get("source_kind") or ("node" if source_ref.startswith("node/") else "")).lower()
        can_hydrate_from_global_alias = bool(isinstance(node_info, dict) and node_info and source_kind == "node")
        if node_type.lower() != "testimonial" and not can_hydrate_from_global_alias:
            continue

        inferred_terms = _infer_taxonomy_terms(source, source_title, taxonomy_lookup)
        strategy = "testimonial_archive_strategy"
        reason = "verified_archive_recovery"
        if node_type.lower() != "testimonial":
            strategy = "global_alias_archive_strategy"
            reason = "global_alias_hydration"
        record = _build_testimonial_archive_record(
            source_path=source,
            source_ref=source_ref,
            source_title=source_title,
            taxonomy_terms=inferred_terms,
            property_catalog=property_catalog,
            node_info=node_info if isinstance(node_info, dict) else {},
        )
        candidate = RedirectCandidate(
            source_path=source,
            destination_path=f"/reviews/archive/{target_slug}",
            confidence=0.995,
            strategy=strategy,
            reason=reason,
            source_type="testimonial_archive",
            title=source_title,
            source_ref=source_ref or None,
            node_type=node_type or None,
            taxonomy_terms=[term.name for term in inferred_terms],
        )
        return candidate, record

    return None


def _persist_archive_records(
    records: list[ArchiveRecord],
    output_dir: Path,
    *,
    overwrite_existing: bool = True,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for record in records:
        target = output_dir / f"{record.slug}.json"
        if target.exists() and not overwrite_existing:
            continue
        with target.open("w", encoding="utf-8") as handle:
            json.dump(record.payload, handle, indent=2, ensure_ascii=True)
        written += 1
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SEO migration redirect candidates.")
    parser.add_argument("--blueprint", type=Path, default=BLUEPRINT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--orphan-output", type=Path, default=ORPHAN_REPORT_PATH)
    parser.add_argument("--archive-output-dir", type=Path, default=ARCHIVE_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--min-confidence", type=float, default=0.68)
    parser.add_argument("--monitoring-threshold", type=float, default=0.40)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Export candidates only without writing to the database. This is already the default unless --write-db is provided.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Persist generated candidates to seo_redirects and emit OpenShell audit events.",
    )
    parser.add_argument(
        "--write-observations",
        action="store_true",
        help="Write near-miss observations to the OpenShell audit ledger without creating redirects.",
    )
    parser.add_argument("--single-slug", type=str, help="Target a specific testimonial slug for archive hydration.")
    parser.add_argument(
        "--force-sign",
        action="store_true",
        help="Rewrite the archive record even if the signed JSON already exists.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.dry_run and args.write_db:
        print("ERROR: --dry-run cannot be combined with --write-db")
        return 1
    if args.monitoring_threshold >= args.min_confidence:
        print("ERROR: --monitoring-threshold must be lower than --min-confidence")
        return 1
    if not args.blueprint.exists():
        print(f"ERROR: Blueprint not found: {args.blueprint}")
        return 1

    with args.blueprint.open("r", encoding="utf-8") as f:
        blueprint = json.load(f)

    if args.single_slug:
        target_slug = _normalize_requested_slug(args.single_slug)
        single_target = _build_single_testimonial_target(blueprint, requested_slug=target_slug)
        if single_target is None:
            print(f"ERROR: No testimonial archive source found for slug: {target_slug}")
            return 1
        candidate, archive_record = single_target
        candidates = [candidate]
        archive_records = [archive_record]
        near_misses = []
        orphan_report = {
            "orphan_count": 0,
            "orphans": [],
            "mode": "single_slug",
            "requested_slug": target_slug,
        }
        metrics = {
            "verified_archive_recovery": {"mapped": 1, "total": 1},
            "single_slug_mode": {"mapped": 1, "total": 1},
        }
        archive_written = _persist_archive_records(
            archive_records,
            args.archive_output_dir,
            overwrite_existing=bool(args.force_sign),
        )
    else:
        next_routes = _discover_next_routes(FRONTEND_APP_DIR)
        candidates, archive_records, near_misses, orphan_report, metrics = _generate_candidates(
            blueprint,
            next_routes=next_routes,
            max_candidates=max(1, int(args.batch_size)),
            min_confidence=float(args.min_confidence),
            monitoring_threshold=float(args.monitoring_threshold),
        )
        archive_written = _persist_archive_records(archive_records, args.archive_output_dir)
        target_slug = None

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_blueprint": str(args.blueprint),
        "next_routes_discovered": len(_discover_next_routes(FRONTEND_APP_DIR)) if not args.single_slug else 0,
        "candidate_count": len(candidates),
        "archive_record_count": len(archive_records),
        "archive_output_dir": str(args.archive_output_dir),
        "archive_records_written": archive_written,
        "batch_size": args.batch_size,
        "min_confidence": args.min_confidence,
        "monitoring_threshold": args.monitoring_threshold,
        "dry_run": bool(args.dry_run or not args.write_db),
        "write_db": bool(args.write_db),
        "write_observations": bool(args.write_observations),
        "single_slug": target_slug,
        "force_sign": bool(args.force_sign),
        "metrics": metrics,
        "near_miss_count": len(near_misses),
        "near_misses": _serialize_observations(near_misses),
        "archive_records": _serialize_archive_records(archive_records),
        "redirects": _serialize_candidates(candidates),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)
    args.orphan_output.parent.mkdir(parents=True, exist_ok=True)
    with args.orphan_output.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": payload["generated_at"],
                "source_blueprint": str(args.blueprint),
                "min_confidence": args.min_confidence,
                "monitoring_threshold": args.monitoring_threshold,
                "metrics": metrics,
                "orphan_analysis": orphan_report,
            },
            f,
            indent=2,
            ensure_ascii=True,
        )

    inserted = 0
    updated = 0
    observation_writes = 0
    if args.write_db:
        inserted, updated = await _persist_candidates(candidates)
    if args.write_observations:
        observation_writes = await _persist_observations(near_misses)

    print("SEO migration candidate generation complete.")
    print(f"Blueprint: {args.blueprint}")
    print(f"Output: {args.output}")
    print(f"Orphan report: {args.orphan_output}")
    print(f"Candidates: {len(candidates)}")
    print(f"Archive records: {len(archive_records)}")
    print(f"Archive output dir: {args.archive_output_dir}")
    if target_slug:
        print(f"Single slug: {target_slug}")
        print(f"Force sign: {bool(args.force_sign)}")
    print(f"Near misses: {len(near_misses)}")
    print(f"Orphans: {orphan_report['orphan_count']}")
    if args.write_db:
        print(f"DB upserts: inserted={inserted}, updated={updated}")
    if args.write_observations:
        print(f"Observation writes: {observation_writes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
