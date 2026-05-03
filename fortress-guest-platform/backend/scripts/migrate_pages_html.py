"""
migrate_pages_html.py — "The Content Heist"

Scrape the 4 final missing legacy Drupal pages and upsert their rich HTML
into the legacy_pages table so the Next.js frontend can serve them via
GET /api/v1/pages/slug/{slug}.

Usage:
    python3 -m backend.scripts.migrate_pages_html          # full scrape + upsert
    python3 -m backend.scripts.migrate_pages_html --dry-run # preview only
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from textwrap import shorten

import httpx

DRUPAL_BASE = "https://www.cabin-rentals-of-georgia.com"

TARGET_PAGES: list[dict[str, str]] = [
    {
        "slug": "specials-discounts",
        "path": "/specials-discounts",
        "title_fallback": "Specials & Discounts",
        "bundle": "page",
    },
    {
        "slug": "experience-north-georgia",
        "path": "/experience-north-georgia",
        "title_fallback": "The Blue Ridge Experience",
        "bundle": "landing_page",
    },
    {
        "slug": "north-georgia-cabin-rentals",
        "path": "/north-georgia-cabin-rentals",
        "title_fallback": "North Georgia Cabin Rentals",
        "bundle": "landing_page",
    },
    {
        "slug": "lady-bugs-blue-ridge-ga-cabins",
        "path": "/lady-bugs-blue-ridge-ga-cabins",
        "title_fallback": "Ladybugs in Blue Ridge GA Cabins",
        "bundle": "page",
    },
    {
        "slug": "large-groups-family-reunions",
        "path": "/large-groups-family-reunions",
        "title_fallback": "Planning Your Large Group Event in Blue Ridge, GA",
        "bundle": "page",
    },
    {
        "slug": "blue-ridge-georgia-activities",
        "path": "/blue-ridge-georgia-activities",
        "title_fallback": "Blue Ridge, Georgia Activities",
        "bundle": "landing_page",
    },
]

# ---------------------------------------------------------------------------
# HTML extraction — strip Drupal chrome, keep only the content body
# ---------------------------------------------------------------------------

# Ordered list of CSS-class selectors for the main content region.
# Drupal 7 themes vary; we try the most specific first.
CONTENT_SELECTORS = [
    r'<div[^>]*class="[^"]*field-name-body[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
    r'<div[^>]*class="[^"]*node-content[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*(?:region-sidebar|block-system))',
    r'<div[^>]*class="[^"]*field-item[^"]*even[^"]*"[^>]*>(.*?)</div>',
    r'<article[^>]*>(.*?)</article>',
]

# Regions to strip from extracted content
STRIP_REGIONS = [
    r'<div[^>]*id="(?:header|footer|navigation|sidebar)[^"]*"[^>]*>.*?</div>',
    r'<nav[^>]*>.*?</nav>',
    r'<div[^>]*class="[^"]*(?:region-sidebar|block-menu|breadcrumb|tabs|action-links)[^"]*"[^>]*>.*?</div>',
]


def _extract_page_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        title = re.sub(r"\s*\|.*$", "", title)
        return title.strip()
    return None


def _extract_h1(html: str) -> str | None:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if match:
        text = re.sub(r"<[^>]+>", "", match.group(1))
        return text.strip()
    return None


def _extract_content_body(html: str) -> str | None:
    """Extract the main content region from a full Drupal page.

    Tries structured selectors first, then falls back to extracting
    everything between the content wrapper and the sidebar/footer.
    """
    for pattern in CONTENT_SELECTORS:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            body = match.group(1).strip()
            if len(body) > 50:
                return body

    # Fallback: grab the #content or .content-area region
    content_match = re.search(
        r'<(?:div|section|main)[^>]*(?:id="content"|class="[^"]*content-area[^"]*")[^>]*>(.*)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if content_match:
        raw = content_match.group(1)
        # Trim at the sidebar/footer boundary
        for boundary in [
            r'<div[^>]*class="[^"]*region-sidebar',
            r'<div[^>]*id="footer"',
            r'<footer',
        ]:
            cut = re.search(boundary, raw, re.IGNORECASE)
            if cut:
                raw = raw[: cut.start()]
        if len(raw.strip()) > 50:
            return raw.strip()

    # Last resort: extract everything inside <main> or role="main"
    main_match = re.search(
        r'<(?:main|div)[^>]*role="main"[^>]*>(.*?)</(?:main|div)>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if main_match and len(main_match.group(1).strip()) > 50:
        return main_match.group(1).strip()

    return None


def _clean_content(html: str) -> str:
    """Clean up extracted content for storage."""
    cleaned = html

    # Rewrite legacy image paths
    cleaned = cleaned.replace(
        "https://www.cabin-rentals-of-georgia.com/sites/default/files/",
        "/images/drupal-media/",
    )
    cleaned = cleaned.replace(
        "/sites/default/files/",
        "/images/drupal-media/",
    )

    # Rewrite absolute links to relative
    cleaned = cleaned.replace("https://www.cabin-rentals-of-georgia.com", "")
    cleaned = cleaned.replace("http://www.cabin-rentals-of-georgia.com", "")

    # Strip inline styles (legacy CSS cruft)
    cleaned = re.sub(r' style="[^"]*"', "", cleaned)

    # Strip Drupal system regions that leaked in
    for pattern in STRIP_REGIONS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    # Collapse excessive whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _generate_summary(html: str) -> str:
    """Strip tags and produce a ≤300 char plain-text summary."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return shorten(text, width=300, placeholder="...")


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS legacy_pages (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        slug            VARCHAR(255) NOT NULL,
        title           VARCHAR(500) NOT NULL,
        body_value      TEXT,
        body_summary    TEXT,
        body_format     VARCHAR(50) DEFAULT 'full_html',
        entity_type     VARCHAR(50) DEFAULT 'node',
        bundle          VARCHAR(100) DEFAULT 'page',
        language        VARCHAR(10) DEFAULT 'en',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_legacy_pages_slug ON legacy_pages (slug)",
]

UPSERT_SQL = """
INSERT INTO legacy_pages (id, slug, title, body_value, body_summary, body_format, entity_type, bundle, language, created_at, updated_at)
VALUES (gen_random_uuid(), :slug, :title, :body_value, :body_summary, :body_format, 'node', :bundle, 'en', NOW(), NOW())
ON CONFLICT (slug)
DO UPDATE SET
    title       = EXCLUDED.title,
    body_value  = EXCLUDED.body_value,
    body_summary= EXCLUDED.body_summary,
    body_format = EXCLUDED.body_format,
    bundle      = EXCLUDED.bundle,
    updated_at  = NOW()
"""


async def run_heist(dry_run: bool = False) -> None:
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    raw_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_API_URI", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL or POSTGRES_API_URI env var required")
    db_url = (
        raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "asyncpg" not in raw_url
        else raw_url
    )
    engine = create_async_engine(db_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("=" * 70)
    print("FORTRESS PRIME — THE CONTENT HEIST")
    print(f"Target: {DRUPAL_BASE}")
    print(f"Pages:  {len(TARGET_PAGES)}")
    print(f"Mode:   {'DRY RUN' if dry_run else 'LIVE FIRE'}")
    print("=" * 70)
    print(f"[DB] {raw_url.split('@')[1] if '@' in raw_url else raw_url}\n")

    if not dry_run:
        async with SessionLocal() as db:
            for ddl in DDL_STATEMENTS:
                await db.execute(sa_text(ddl))
            await db.commit()
        print("[DB] legacy_pages table ensured\n")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
        headers={
            "User-Agent": "FortressPrime-ContentHeist/1.0 (+migration-audit)",
            "Accept": "text/html",
        },
    )

    scraped = 0
    errors: list[str] = []

    for page_def in TARGET_PAGES:
        url = f"{DRUPAL_BASE}{page_def['path']}"
        slug = page_def["slug"]
        print(f"  [{slug:40s}] Scraping ... ", end="", flush=True)

        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                msg = f"{slug}: HTTP {resp.status_code}"
                errors.append(msg)
                print(f"HTTP {resp.status_code}")
                continue

            full_html = resp.text

            title = _extract_page_title(full_html) or _extract_h1(full_html) or page_def["title_fallback"]
            raw_body = _extract_content_body(full_html)

            if not raw_body or len(raw_body) < 30:
                print("WARN: Structured extraction failed, using full-page fallback")
                # Fallback: grab everything between the first <h1> and the footer
                h1_match = re.search(r"<h1", full_html, re.IGNORECASE)
                footer_match = re.search(r'<div[^>]*id="footer"|<footer', full_html, re.IGNORECASE)
                if h1_match:
                    start = h1_match.start()
                    end = footer_match.start() if footer_match else len(full_html)
                    raw_body = full_html[start:end]

            if not raw_body:
                errors.append(f"{slug}: No content extracted")
                print("NO CONTENT")
                continue

            body_value = _clean_content(raw_body)
            body_summary = _generate_summary(body_value)

            print(f"OK ({len(body_value):,} chars)")
            print(f"    Title:   {title}")
            print(f"    Summary: {body_summary[:100]}...")

            if dry_run:
                print(f"    Preview: {body_value[:200]}...\n")
                scraped += 1
                continue

            async with SessionLocal() as db:
                await db.execute(
                    sa_text(UPSERT_SQL),
                    {
                        "slug": slug,
                        "title": title,
                        "body_value": body_value,
                        "body_summary": body_summary,
                        "body_format": "full_html",
                        "bundle": page_def["bundle"],
                    },
                )
                await db.commit()

            scraped += 1
            print(f"    → UPSERTED into legacy_pages\n")

        except Exception as exc:
            msg = f"{slug}: {exc}"
            errors.append(msg)
            print(f"ERROR: {exc}")

    await client.aclose()

    print("=" * 70)
    print(f"{'[DRY RUN] ' if dry_run else ''}HEIST COMPLETE: {scraped}/{len(TARGET_PAGES)} pages captured")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")

    if not dry_run and scraped > 0:
        async with SessionLocal() as db:
            row_count = (await db.execute(sa_text("SELECT COUNT(*) FROM legacy_pages"))).scalar()
            rows = (
                await db.execute(
                    sa_text("SELECT slug, title, LENGTH(body_value) as body_len FROM legacy_pages ORDER BY slug")
                )
            ).fetchall()
            print(f"\nlegacy_pages table: {row_count} rows")
            print("-" * 60)
            for r in rows:
                print(f"  {r[0]:40s}  {r[2]:>7,} chars  {r[1]}")

    await engine.dispose()
    print("\nThe Content Heist is complete. The pages are now sovereign.")


def main() -> None:
    parser = argparse.ArgumentParser(description="The Content Heist — scrape missing legacy pages")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    args = parser.parse_args()
    asyncio.run(run_heist(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
