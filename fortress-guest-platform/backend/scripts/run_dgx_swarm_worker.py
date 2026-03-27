#!/usr/bin/env python3
"""
DGX Swarm Worker V1
-------------------
Reads mapped SEO targets, scrapes legacy-rendered page content by source_alias,
generates SEO patch drafts with the local LLM, and submits to /api/seo/patches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")

from backend.core.config import settings


DEFAULT_TARGET_LIST_PATH = str(REPO_ROOT / "backend" / "scripts" / "swarm_target_list.json")
DEFAULT_LEGACY_PROXY_BASE_URL = "https://www.cabinrentalsofgeorgia.com"
DEFAULT_SEO_PATCH_API_BASE_URL = "http://127.0.0.1:8100"

AMENITY_KEYWORDS = [
    "hot tub",
    "pet friendly",
    "mountain view",
    "riverfront",
    "game room",
    "lake",
    "wifi",
    "fireplace",
    "pool table",
    "ev charger",
]


@dataclass
class WorkerConfig:
    target_list_path: Path
    storefront_base_url: str
    legacy_proxy_base_url: str
    seo_patch_api_base_url: str
    swarm_api_key: str
    max_targets: int
    rubric_version: str
    campaign: str
    dry_run: bool

def load_config(args: argparse.Namespace) -> WorkerConfig:
    return WorkerConfig(
        target_list_path=Path(os.getenv("SWARM_TARGET_LIST_PATH", DEFAULT_TARGET_LIST_PATH)),
        storefront_base_url=os.getenv("STOREFRONT_BASE_URL", settings.storefront_base_url).rstrip("/"),
        legacy_proxy_base_url=os.getenv("LEGACY_PROXY_BASE_URL", DEFAULT_LEGACY_PROXY_BASE_URL).rstrip("/"),
        seo_patch_api_base_url=os.getenv("SEO_PATCH_API_BASE_URL", DEFAULT_SEO_PATCH_API_BASE_URL).rstrip("/"),
        swarm_api_key=os.getenv("SWARM_API_KEY", settings.swarm_api_key).strip(),
        max_targets=int(os.getenv("SWARM_MAX_TARGETS", str(args.max_targets))),
        rubric_version=os.getenv("SWARM_RUBRIC_VERSION", "godhead-v1"),
        campaign=os.getenv("SWARM_CAMPAIGN", "default"),
        dry_run=bool(args.dry_run),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DGX Swarm SEO worker")
    parser.add_argument("--dry-run", action="store_true", help="Generate payloads but do not POST proposals")
    parser.add_argument("--max-targets", type=int, default=14, help="Max targets to process")
    return parser.parse_args()


def _extract_content_section(html: str) -> str:
    patterns = [
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<body\b[^>]*>(.*?)</body>",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return html


def extract_main_text(html: str) -> str:
    section = _extract_content_section(html)
    section = re.sub(r"<script\b[^>]*>.*?</script>", " ", section, flags=re.IGNORECASE | re.DOTALL)
    section = re.sub(r"<style\b[^>]*>.*?</style>", " ", section, flags=re.IGNORECASE | re.DOTALL)
    section = re.sub(r"<[^>]+>", " ", section)
    section = unescape(section)
    section = re.sub(r"\s+", " ", section).strip()
    return section


def extract_amenities(main_text: str) -> list[str]:
    lowered = main_text.lower()
    hits = [kw for kw in AMENITY_KEYWORDS if kw in lowered]
    return sorted(set(hits))


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM output")
    obj_text = raw_text[start : end + 1]
    return json.loads(obj_text)


def fallback_proposal(slug: str, target_keyword: str, amenities: list[str], source_alias: str, page_text: str) -> dict[str, Any]:
    amenity_phrase = f" featuring {', '.join(amenities[:3])}" if amenities else ""
    title = f"{slug.replace('-', ' ').title()} | {target_keyword.title()}"[:255]
    meta_description = (
        f"Explore {slug.replace('-', ' ')} in Blue Ridge, Georgia{amenity_phrase}. "
        "Plan your mountain stay with luxury cabin amenities and direct booking."
    )[:320]
    intro = (
        f"{slug.replace('-', ' ').title()} is a Blue Ridge cabin aligned to the keyword '{target_keyword}'. "
        f"Source alias: {source_alias}. "
        f"Extracted content snapshot: {page_text[:600]}"
    )
    return {
        "title": title,
        "meta_description": meta_description,
        "h1": slug.replace("-", " ").title(),
        "intro": intro,
        "faq": [],
        "json_ld": {
            "@context": "https://schema.org",
            "@type": "LodgingBusiness",
            "name": slug.replace("-", " ").title(),
            "description": meta_description,
        },
    }


async def generate_with_local_llm(
    client: httpx.AsyncClient,
    slug: str,
    target_keyword: str,
    source_alias: str,
    page_text: str,
    amenities: list[str],
) -> dict[str, Any]:
    prompt = (
        "You are an SEO copy generator for vacation rental cabin pages. "
        "Return ONLY JSON with keys: title, meta_description, h1, intro, faq, json_ld. "
        "Constraints: title<=255 chars, meta_description<=320 chars, h1<=255 chars. "
        "json_ld must be schema.org LodgingBusiness-compatible.\n\n"
        f"Target keyword: {target_keyword}\n"
        f"Slug: {slug}\n"
        f"Source alias: {source_alias}\n"
        f"Amenity hints: {', '.join(amenities) if amenities else 'none'}\n"
        f"Source text:\n{page_text[:8000]}"
    )
    payload = {
        "model": settings.ollama_fast_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1400},
    }
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    resp = await client.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    proposal = _extract_json_object(content)
    # Guarantee required keys
    for key in ("title", "meta_description", "h1", "intro", "faq", "json_ld"):
        proposal.setdefault(key, [] if key == "faq" else ({} if key == "json_ld" else ""))
    return proposal


def compute_grading(proposal: dict[str, Any], target_keyword: str, amenities: list[str]) -> dict[str, Any]:
    title = str(proposal.get("title") or "").lower()
    meta = str(proposal.get("meta_description") or "").lower()
    h1 = str(proposal.get("h1") or "").lower()
    keyword_lower = target_keyword.lower()
    keyword_alignment = 1.0 if keyword_lower in f"{title} {meta} {h1}" else 0.7
    amenity_coverage = 0.8 if amenities else 0.6
    schema_quality = 1.0 if isinstance(proposal.get("json_ld"), dict) and proposal.get("json_ld") else 0.6
    ctr_strength = 0.85 if len(title) >= 30 and len(meta) >= 80 else 0.7

    breakdown = {
        "keyword_alignment": round(keyword_alignment, 3),
        "factual_grounding": round(amenity_coverage, 3),
        "schema_quality": round(schema_quality, 3),
        "ctr_strength": round(ctr_strength, 3),
    }
    overall = round(sum(breakdown.values()) / len(breakdown) * 100, 2)
    return {"overall": overall, "breakdown": breakdown}


def build_source_snapshot(source_alias: str, scrape_url: str, page_text: str, amenities: list[str]) -> dict[str, Any]:
    return {
        "source_alias": source_alias,
        "scrape_url": scrape_url,
        "amenities": amenities,
        "text_excerpt": page_text[:1200],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def build_candidate_urls(cfg: WorkerConfig, source_alias: str) -> list[str]:
    alias_path = source_alias.strip().lstrip("/")
    storefront_url = urljoin(f"{cfg.storefront_base_url}/", alias_path)
    legacy_url = urljoin(f"{cfg.legacy_proxy_base_url}/", alias_path)
    return [storefront_url, legacy_url]


async def scrape_alias_content(client: httpx.AsyncClient, cfg: WorkerConfig, source_alias: str) -> tuple[str, str]:
    last_error = None
    for url in build_candidate_urls(cfg, source_alias):
        try:
            resp = await client.get(url, timeout=40, follow_redirects=True)
            if resp.status_code >= 400:
                last_error = f"{url} -> HTTP {resp.status_code}"
                continue
            text = extract_main_text(resp.text)
            if len(text) < 120:
                last_error = f"{url} -> extracted text too short"
                continue
            return url, text
        except Exception as exc:
            last_error = f"{url} -> {exc}"
    raise RuntimeError(last_error or "Failed to scrape alias")


def load_targets(path: Path, max_targets: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets", [])
    matched = [t for t in targets if t.get("property_id")]
    return matched[:max_targets]


async def post_proposal(
    client: httpx.AsyncClient,
    cfg: WorkerConfig,
    body: dict[str, Any],
) -> tuple[bool, str]:
    url = f"{cfg.seo_patch_api_base_url}/api/seo/patches"
    headers = {"Content-Type": "application/json"}
    if cfg.swarm_api_key:
        headers["Authorization"] = f"Bearer {cfg.swarm_api_key}"
    resp = await client.post(url, headers=headers, json=body, timeout=45)
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}: {resp.text[:400]}"
    return True, resp.text[:240]


async def run_worker(cfg: WorkerConfig) -> None:
    if not cfg.target_list_path.exists():
        raise FileNotFoundError(f"Target list not found: {cfg.target_list_path}")

    targets = load_targets(cfg.target_list_path, cfg.max_targets)
    if not targets:
        print("No matched targets found in swarm target list.")
        return

    print(
        f"Starting DGX worker: targets={len(targets)} dry_run={cfg.dry_run} "
        f"campaign={cfg.campaign} rubric={cfg.rubric_version}"
    )

    stats = {"attempted": 0, "generated": 0, "posted": 0, "failed": 0}
    async with httpx.AsyncClient() as client:
        for target in targets:
            stats["attempted"] += 1
            slug = str(target.get("slug") or "").strip()
            source_alias = str(target.get("source_alias") or "").strip("/")
            property_id = target.get("property_id")
            target_keyword = str(target.get("target_keyword") or "luxury cabin blue ridge")

            if not slug or not source_alias or not property_id:
                print(f"[SKIP] invalid target payload: {target}")
                stats["failed"] += 1
                continue

            try:
                scrape_url, page_text = await scrape_alias_content(client, cfg, source_alias)
                amenities = extract_amenities(page_text)
                generation_started_at = time.perf_counter()
                try:
                    proposal = await generate_with_local_llm(
                        client=client,
                        slug=slug,
                        target_keyword=target_keyword,
                        source_alias=source_alias,
                        page_text=page_text,
                        amenities=amenities,
                    )
                    generation_mode = "llm"
                except Exception as llm_exc:
                    proposal = fallback_proposal(
                        slug=slug,
                        target_keyword=target_keyword,
                        amenities=amenities,
                        source_alias=source_alias,
                        page_text=page_text,
                    )
                    generation_mode = f"fallback:{type(llm_exc).__name__}"

                grading = compute_grading(proposal, target_keyword, amenities)
                source_snapshot = build_source_snapshot(source_alias, scrape_url, page_text, amenities)
                generation_ms = max(1, int((time.perf_counter() - generation_started_at) * 1000))
                page_path = f"/cabins/{slug}"
                request_body = {
                    "property_id": property_id,
                    "page_path": page_path,
                    "title": str(proposal.get("title") or "")[:70],
                    "meta_description": str(proposal.get("meta_description") or "")[:320],
                    "og_title": str(proposal.get("title") or "")[:95] or None,
                    "og_description": str(proposal.get("meta_description") or "")[:200] or None,
                    "jsonld_payload": proposal.get("json_ld") if isinstance(proposal.get("json_ld"), dict) else {},
                    "canonical_url": urljoin(f"{cfg.storefront_base_url}/", page_path.lstrip("/")),
                    "h1_suggestion": str(proposal.get("h1") or "")[:255] or None,
                    "alt_tags": {},
                    "swarm_model": str(settings.ollama_fast_model or "unknown-model"),
                    "swarm_node": str(settings.node_ip or "unknown-node"),
                    "generation_ms": generation_ms,
                }

                stats["generated"] += 1
                if cfg.dry_run:
                    print(
                        f"[DRY] slug={slug} property_id={property_id} "
                        f"mode={generation_mode} title='{request_body['title'][:70]}' "
                        f"score={grading['overall']} source={source_snapshot['scrape_url']}"
                    )
                    continue

                ok, detail = await post_proposal(client, cfg, request_body)
                if ok:
                    stats["posted"] += 1
                    print(f"[OK] slug={slug} posted mode={generation_mode}")
                else:
                    stats["failed"] += 1
                    print(f"[FAIL] slug={slug} post_error={detail}")
            except Exception as exc:
                stats["failed"] += 1
                print(f"[FAIL] slug={slug} error={type(exc).__name__}: {exc}")

    print(
        "DGX worker complete: "
        f"attempted={stats['attempted']} generated={stats['generated']} "
        f"posted={stats['posted']} failed={stats['failed']}"
    )


def main() -> None:
    args = parse_args()
    cfg = load_config(args)
    asyncio.run(run_worker(cfg))


if __name__ == "__main__":
    main()

