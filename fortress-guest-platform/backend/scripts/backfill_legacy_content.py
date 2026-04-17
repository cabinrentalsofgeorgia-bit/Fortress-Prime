"""
Level 47: Legacy Content Backfill — Rich descriptions, features, and reviews.

Scrapes the legacy Drupal site for each active property and populates
ota_metadata with: legacy_body (full HTML), legacy_features (list), legacy_reviews (list).

Usage:
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    python3 -m backend.scripts.backfill_legacy_content [--slug above-the-timberline] [--dry-run]
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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property

LEGACY_BASE = "https://www.cabin-rentals-of-georgia.com"
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
    """Scrape multiple listing pages to build a slug->detail URL map."""
    url_map: dict[str, str] = {}

    listing_urls = [
        f"{LEGACY_BASE}/blue-ridge-cabins/above-the-timberline",
        f"{LEGACY_BASE}/blue-ridge-cabins",
    ]

    for listing_url in listing_urls:
        print(f"[DISCOVER] Fetching: {listing_url}")
        soup = _fetch(listing_url)
        if not soup:
            continue
        for a in soup.find_all("a", href=re.compile(r"^/cabin/")):
            href = a["href"]
            slug_part = href.rstrip("/").split("/")[-1]
            if slug_part and slug_part not in url_map:
                url_map[slug_part] = f"{LEGACY_BASE}{href}"

    print(f"[DISCOVER] Found {len(url_map)} cabin detail URLs")
    return url_map


def _normalize_slug(db_slug: str) -> str:
    return db_slug.lower().replace(" ", "-").strip("-")


def _find_legacy_url(db_slug: str, url_map: dict[str, str]) -> str | None:
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


def extract_rich_body(soup: BeautifulSoup) -> str | None:
    """Extract the full rich HTML description from the legacy page."""
    desc_div = soup.find("div", class_="cabin-bottom-left")
    if not desc_div:
        return None

    body_div = desc_div.find("div", class_="body")
    if not body_div:
        return None

    full_div = body_div.find("div", class_="full")
    if full_div:
        inner = "".join(str(c) for c in full_div.children)
    else:
        teaser = body_div.find("div", class_="teaser")
        if teaser:
            inner = "".join(str(c) for c in teaser.children)
        else:
            inner = "".join(str(c) for c in body_div.children)

    if len(inner.strip()) < 50:
        return None

    inner = inner.replace("https://www.cabin-rentals-of-georgia.com", "")
    return inner.strip()


def extract_features(soup: BeautifulSoup) -> list[str]:
    """Extract unique property features from the legacy page."""
    feat_div = soup.find("div", class_="cabin-bottom-right")
    if not feat_div:
        return []

    items = feat_div.find_all("li")
    unique: list[str] = []
    seen: set[str] = set()
    for li in items:
        text = li.get_text(strip=True)
        if text and text not in seen:
            seen.add(text)
            unique.append(text)

    return unique


def extract_reviews(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract guest reviews/memories from the legacy page."""
    reviews: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for row in soup.find_all("div", class_="views-row"):
        title_el = row.find("span", class_="field-content")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        if not title or title in seen_titles or len(title) < 3:
            continue

        body_text = ""
        body_fields = row.find_all("div", class_="views-field-body")
        for bf in body_fields:
            full_div = bf.find("div", class_="full")
            if full_div:
                body_text = full_div.get_text(strip=True)
                break
            fc = bf.find("span", class_="field-content")
            if fc:
                body_text = fc.get_text(strip=True)
                break

        if body_text:
            body_text = body_text.replace("Read More", "").strip()

        if not body_text or len(body_text) < 20:
            continue

        seen_titles.add(title)
        reviews.append({"title": title, "body": body_text})

    return reviews


def extract_gallery_captions(soup: BeautifulSoup) -> dict[str, str]:
    """Extract richer gallery image captions from the legacy photo grid."""
    captions: dict[str, str] = {}

    photo_section = soup.find("div", class_="cabin-gallery-grid") or soup.find("div", class_="cabin-photos")
    if not photo_section:
        for div in soup.find_all("div"):
            if div.find("img", alt=lambda a: a and "Above the Timberline" in a):
                photo_section = div
                break

    if not photo_section:
        return captions

    for img in photo_section.find_all("img"):
        alt = img.get("alt", "").strip()
        src = img.get("src", "")
        if alt and src:
            captions[src] = alt

    return captions


def scrape_legacy_content(url: str) -> dict[str, Any]:
    """Scrape a single cabin page for rich body, features, and reviews."""
    soup = _fetch(url)
    if not soup:
        return {"error": "fetch_failed"}

    rich_body = extract_rich_body(soup)
    features = extract_features(soup)
    reviews = extract_reviews(soup)

    return {
        "rich_body": rich_body,
        "features": features,
        "reviews": reviews,
    }


async def backfill(slug_filter: str | None = None, dry_run: bool = False) -> None:
    url_map = discover_cabin_urls()
    if not url_map:
        print("[ABORT] Could not discover cabin URLs.")
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

            data = scrape_legacy_content(legacy_url)
            if data.get("error"):
                print(f"    ✗ Scrape error: {data['error']}")
                stats["errors"] += 1
                continue

            rich_body = data["rich_body"]
            features = data["features"]
            reviews = data["reviews"]

            print(f"    Rich body: {'YES' if rich_body else 'NONE'} ({len(rich_body or '')} chars)")
            print(f"    Features: {len(features)} items")
            print(f"    Reviews: {len(reviews)} items")

            if not rich_body and not features and not reviews:
                print(f"    — Nothing new to update")
                stats["skipped"] += 1
                continue

            if dry_run:
                print(f"    [DRY RUN] Would update ota_metadata")
                stats["updated"] += 1
                continue

            meta = dict(prop.ota_metadata) if prop.ota_metadata else {}
            if rich_body:
                meta["legacy_body"] = rich_body
            if features:
                meta["legacy_features"] = features
            if reviews:
                meta["legacy_reviews"] = reviews

            await db.execute(
                update(Property)
                .where(Property.id == prop.id)
                .values(ota_metadata=meta)
            )
            await db.commit()
            print(f"    ✓ Database updated")
            stats["updated"] += 1

    print(f"\n{'=' * 60}")
    print(f"LEGACY CONTENT BACKFILL COMPLETE {'(DRY RUN)' if dry_run else ''}")
    print(f"{'=' * 60}")
    print(f"  Updated:  {stats['updated']}")
    print(f"  Skipped:  {stats['skipped']}")
    print(f"  No URL:   {stats['no_url']}")
    print(f"  Errors:   {stats['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Level 47: Legacy Content Backfill")
    parser.add_argument("--slug", help="Limit to a single property slug")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()
    asyncio.run(backfill(slug_filter=args.slug, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
