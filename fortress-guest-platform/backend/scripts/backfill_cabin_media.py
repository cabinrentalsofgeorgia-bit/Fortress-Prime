"""
Level 46: Media Backfill — Populate rates_notes and video_urls from legacy Drupal.

Reads every active property from the local database, discovers its legacy
cabin‐detail URL on the Drupal site, scrapes the YouTube video iframes and
Rates paragraph, then writes the extracted data back into the new
`rates_notes` and `video_urls` columns.

Prerequisites:
    alembic upgrade head   (adds the columns first)

Usage:
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    python3 -m backend.scripts.backfill_cabin_media [--slug above-the-timberline] [--dry-run]

Requires: requests, beautifulsoup4, lxml, sqlalchemy, asyncpg
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Tag
from dotenv import dotenv_values

for key, value in dotenv_values(".env").items():
    if value is not None:
        os.environ.setdefault(key, value)

from sqlalchemy import select, update
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property

LEGACY_BASE = "https://www.cabin-rentals-of-georgia.com"
LISTING_URL = f"{LEGACY_BASE}/blue-ridge-cabins/above-the-timberline"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
REQUEST_DELAY = 1.0


def _fetch(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "lxml")
        print(f"    [WARN] HTTP {resp.status_code} for {url}")
    except requests.RequestException as e:
        print(f"    [ERROR] {e}")
    return None


def discover_cabin_urls() -> dict[str, str]:
    """Scrape the listing page to build a slug→detail URL map."""
    print(f"[DISCOVER] Fetching listing page: {LISTING_URL}")
    soup = _fetch(LISTING_URL)
    if not soup:
        print("[DISCOVER] FAILED to fetch listing page")
        return {}

    url_map: dict[str, str] = {}
    for a in soup.find_all("a", href=re.compile(r"^/cabin/")):
        href = a["href"]
        slug_part = href.rstrip("/").split("/")[-1]
        if slug_part and slug_part not in url_map:
            url_map[slug_part] = f"{LEGACY_BASE}{href}"

    print(f"[DISCOVER] Found {len(url_map)} cabin detail URLs:")
    for slug, url in sorted(url_map.items()):
        print(f"  {slug:50s} → {url}")
    return url_map


def _normalize_slug(db_slug: str) -> str:
    return db_slug.lower().replace(" ", "-").strip("-")


def _find_legacy_url(db_slug: str, url_map: dict[str, str]) -> str | None:
    """Match a database slug to a legacy URL, handling slug variations."""
    norm = _normalize_slug(db_slug)

    if norm in url_map:
        return url_map[norm]

    stripped = norm.replace("-on-", "-").replace("-of-", "-").replace("-the-", "-")
    for legacy_slug, url in url_map.items():
        legacy_stripped = legacy_slug.replace("-on-", "-").replace("-of-", "-").replace("-the-", "-")
        if stripped == legacy_stripped:
            return url
        if norm in legacy_slug or legacy_slug in norm:
            return url

    for legacy_slug, url in url_map.items():
        db_words = set(norm.split("-"))
        legacy_words = set(legacy_slug.split("-"))
        overlap = db_words & legacy_words
        if len(overlap) >= max(2, len(db_words) - 1):
            return url

    return None


def _extract_clean_youtube_url(raw_src: str) -> str:
    """Clean up Drupal's double-encoded YouTube embed URLs."""
    decoded = unquote(raw_src)
    match = re.search(r"youtube\.com/embed/([a-zA-Z0-9_-]+)", decoded)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
    return decoded.split("?")[0] if "?" in decoded else decoded


def extract_videos(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract YouTube video URLs from the cabin detail page."""
    videos: list[dict[str, str]] = []
    seen: set[str] = set()

    for iframe in soup.find_all("iframe", src=re.compile(r"youtube", re.I)):
        url = _extract_clean_youtube_url(iframe["src"])
        if url not in seen:
            seen.add(url)
            videos.append({"url": url, "video_url": url})

    for div in soup.select(".video-embed-field-provider-youtube, .field-name-field-video"):
        for iframe in div.find_all("iframe", src=True):
            url = _extract_clean_youtube_url(iframe["src"])
            if url not in seen:
                seen.add(url)
                videos.append({"url": url, "video_url": url})

    return videos


def extract_rates(soup: BeautifulSoup) -> str | None:
    """Extract the Rates text block from the cabin detail page."""
    rates_div = soup.select_one("div.cabin-rates")
    if rates_div:
        for heading in rates_div.find_all(re.compile(r"^h[1-4]$")):
            heading.decompose()
        text = rates_div.get_text(separator="\n", strip=True)
        if len(text) > 10:
            return text

    heading = soup.find(re.compile(r"^h[2-4]$"), string=re.compile(r"^Rates?$", re.I))
    if heading:
        parent = heading.find_parent(["div", "section"])
        if parent:
            clone = BeautifulSoup(str(parent), "lxml")
            for h in clone.find_all(re.compile(r"^h[1-4]$")):
                h.decompose()
            text = clone.get_text(separator="\n", strip=True)
            if len(text) > 10:
                return text

        siblings_text: list[str] = []
        for sib in heading.find_next_siblings():
            if isinstance(sib, Tag) and sib.name in ("h2", "h3", "h4"):
                break
            txt = sib.get_text(strip=True) if isinstance(sib, Tag) else ""
            if txt:
                siblings_text.append(txt)
        if siblings_text:
            return "\n".join(siblings_text)

    return None


def scrape_cabin(url: str) -> dict[str, Any]:
    """Scrape a single cabin detail page for video and rates data."""
    soup = _fetch(url)
    if not soup:
        return {"videos": [], "rates": None, "error": "fetch_failed"}

    videos = extract_videos(soup)
    rates = extract_rates(soup)
    return {"videos": videos, "rates": rates}


async def backfill(slug_filter: str | None = None, dry_run: bool = False) -> None:
    url_map = discover_cabin_urls()
    if not url_map:
        print("[ABORT] Could not discover cabin URLs from the listing page.")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        query = select(Property).where(Property.is_active.is_(True)).order_by(Property.name)
        if slug_filter:
            query = query.where(Property.slug == slug_filter)

        result = await db.execute(query)
        properties = result.scalars().all()
        print(f"\n[BACKFILL] Processing {len(properties)} active properties\n")

        stats = {"updated": 0, "skipped": 0, "no_url": 0, "errors": 0}

        for prop in properties:
            print(f"  [{prop.name}] (slug={prop.slug})")
            legacy_url = _find_legacy_url(prop.slug, url_map)

            if not legacy_url:
                print(f"    ⚠ No legacy URL found — skipping")
                stats["no_url"] += 1
                continue

            print(f"    Legacy URL: {legacy_url}")
            time.sleep(REQUEST_DELAY)

            data = scrape_cabin(legacy_url)
            if data.get("error"):
                print(f"    ✗ Scrape error: {data['error']}")
                stats["errors"] += 1
                continue

            videos = data["videos"]
            rates = data["rates"]

            print(f"    Videos: {len(videos)} found", end="")
            if videos:
                for v in videos:
                    print(f"\n      → {v['url']}", end="")
            print()
            print(f"    Rates: {'YES' if rates else 'NONE'}", end="")
            if rates:
                print(f" ({len(rates)} chars): {rates[:100]}...")
            else:
                print()

            if not videos and not rates:
                print(f"    — Nothing to update")
                stats["skipped"] += 1
                continue

            if dry_run:
                print(f"    [DRY RUN] Would update rates_notes + video_urls")
                stats["updated"] += 1
                continue

            update_values: dict[str, Any] = {}
            if videos:
                update_values["video_urls"] = videos
            if rates:
                update_values["rates_notes"] = rates

            await db.execute(
                update(Property)
                .where(Property.id == prop.id)
                .values(**update_values)
            )
            await db.commit()
            print(f"    ✓ Database updated")
            stats["updated"] += 1

    print(f"\n{'=' * 60}")
    print(f"BACKFILL COMPLETE {'(DRY RUN)' if dry_run else ''}")
    print(f"{'=' * 60}")
    print(f"  Updated:  {stats['updated']}")
    print(f"  Skipped:  {stats['skipped']} (no video/rates data found)")
    print(f"  No URL:   {stats['no_url']} (could not match legacy URL)")
    print(f"  Errors:   {stats['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Level 46: Media Backfill — rates_notes + video_urls")
    parser.add_argument("--slug", help="Limit to a single property slug")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()
    asyncio.run(backfill(slug_filter=args.slug, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
