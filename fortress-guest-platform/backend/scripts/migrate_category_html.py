"""
migrate_category_html.py — Scrape legacy Drupal category pages and populate
the taxonomy_categories table with rich marketing HTML.

Usage:
    python3 -m backend.scripts.migrate_category_html          # full scrape + upsert
    python3 -m backend.scripts.migrate_category_html --dry-run # preview only
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

import httpx
import structlog

logger = structlog.get_logger(service="migrate_category_html")

DRUPAL_BASE = "https://www.cabin-rentals-of-georgia.com"

CATEGORY_SLUGS: list[dict[str, str]] = [
    {"slug": "family-reunion", "path": "/cabins/all/family-reunion", "name": "Family Reunion"},
    {"slug": "mountain-view", "path": "/cabins/all/mountain-view", "name": "Mountain View"},
    {"slug": "pet-friendly", "path": "/cabins/all/pet-friendly", "name": "Pet Friendly"},
    {"slug": "river-front", "path": "/cabins/all/river-front", "name": "River Front"},
    {"slug": "river-view", "path": "/cabins/all/river-view", "name": "River View"},
    {"slug": "lake-view", "path": "/cabins/all/lake-view", "name": "Lake View"},
    {"slug": "blue-ridge-luxury", "path": "/cabins/all/blue-ridge-luxury", "name": "Blue Ridge Luxury"},
    {"slug": "corporate-retreats", "path": "/cabins/all/corporate-retreats", "name": "Corporate Retreats"},
    {"slug": "cabin-in-the-woods", "path": "/cabins/all/cabin-in-the-woods", "name": "Cabin In The Woods"},
    {"slug": "toccoa-river-luxury-cabin-rentals", "path": "/cabins/all/toccoa-river-luxury-cabin-rentals", "name": "Toccoa River Luxury Cabin Rentals"},
    {"slug": "blue-ridge-cabins", "path": "/cabins/all/blue-ridge-cabins", "name": "Blue Ridge Cabins"},
    {"slug": "hot-tub", "path": "/cabins/amenities/hot-tub", "name": "Hot Tub"},
    {"slug": "game-room", "path": "/cabins/amenities/game-room", "name": "Game Room"},
    {"slug": "fire-pit", "path": "/cabins/amenities/fire-pit", "name": "Fire Pit"},
    {"slug": "pool-table", "path": "/cabins/amenities/pool-table", "name": "Pool Table"},
    {"slug": "creek", "path": "/cabins/amenities/creek", "name": "Creek"},
    {"slug": "fireplace", "path": "/cabins/amenities/fireplace", "name": "Fireplace"},
    {"slug": "fishing", "path": "/cabins/amenities/fishing", "name": "Fishing"},
    {"slug": "internet", "path": "/cabins/amenities/internet", "name": "Internet"},
    {"slug": "grill", "path": "/cabins/amenities/grill", "name": "Grill"},
    {"slug": "arcade", "path": "/cabins/amenities/arcade", "name": "Arcade"},
    {"slug": "pool-access", "path": "/cabins/amenities/pool-access", "name": "Pool Access"},
]


def _extract_view_header(html: str) -> str | None:
    """Pull the rich HTML out of Drupal's view-header div."""
    match = re.search(
        r'<div[^>]*class="view-header"[^>]*>(.*?)</div>\s*(?:</div>)?\s*<div[^>]*class="view-content"',
        html,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    match2 = re.search(r'<div[^>]*class="view-header"[^>]*>(.*?)</div>', html, re.DOTALL)
    if match2:
        return match2.group(1).strip()
    return None


def _extract_page_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
    if match:
        title = match.group(1).strip()
        title = re.sub(r"\s*\|.*$", "", title)
        return title
    return None


def _clean_html(html: str) -> str:
    """Normalize legacy Drupal image paths and strip CMS cruft."""
    cleaned = html.replace("/sites/default/files/", "/images/drupal-media/")
    cleaned = re.sub(r' style="[^"]*"', "", cleaned)
    cleaned = re.sub(r'<div class="view-filters">.*$', "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


async def scrape_categories(dry_run: bool = False) -> None:
    import os
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL env var required")
    db_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1) if "asyncpg" not in raw_url else raw_url
    engine = create_async_engine(db_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10))
    print(f"[DB] Connected to {raw_url.split('@')[1] if '@' in raw_url else raw_url}\n")

    scraped = 0
    errors: list[str] = []

    for cat in CATEGORY_SLUGS:
        url = f"{DRUPAL_BASE}{cat['path']}"
        print(f"  Scraping {cat['slug']:40s} ... ", end="", flush=True)

        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                msg = f"{cat['slug']}: HTTP {resp.status_code}"
                errors.append(msg)
                print(f"HTTP {resp.status_code}")
                continue

            body = resp.text
            raw_html = _extract_view_header(body)
            page_title = _extract_page_title(body)

            if not raw_html or len(raw_html) < 20:
                print("NO CONTENT (view-header empty)")
                continue

            description = _clean_html(raw_html)
            meta_title = page_title or cat["name"]

            if dry_run:
                print(f"OK ({len(description)} chars) — {meta_title}")
                print(f"    Preview: {description[:120]}...\n")
                scraped += 1
                continue

            async with SessionLocal() as db:
                await db.execute(
                    sa_text("""
                        INSERT INTO taxonomy_categories (id, name, slug, description, meta_title, created_at, updated_at)
                        VALUES (gen_random_uuid(), :name, :slug, :desc, :meta_title, NOW(), NOW())
                        ON CONFLICT (slug)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            meta_title = EXCLUDED.meta_title,
                            updated_at = NOW()
                    """),
                    {"name": cat["name"], "slug": cat["slug"], "desc": description, "meta_title": meta_title},
                )
                await db.commit()

            scraped += 1
            print(f"OK ({len(description)} chars)")

        except Exception as exc:
            msg = f"{cat['slug']}: {exc}"
            errors.append(msg)
            print(f"ERROR: {exc}")

    await client.aclose()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scraped: {scraped}/{len(CATEGORY_SLUGS)}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    if not dry_run and scraped > 0:
        async with SessionLocal() as db:
            row = (await db.execute(sa_text("SELECT COUNT(*) FROM taxonomy_categories"))).scalar()
            print(f"\ntaxonomy_categories rows: {row}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Drupal category HTML to taxonomy_categories")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    args = parser.parse_args()
    asyncio.run(scrape_categories(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
