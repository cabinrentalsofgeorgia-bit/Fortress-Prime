"""
mass_extract_content.py — "The Mass Extraction"

Reads legacy_map.json (produced by the Cartographer spider), scrapes the
rich HTML body from every Activity (206) and Blog Post (73) on the legacy
Drupal site, and upserts them into the `activities` and `blogs` PostgreSQL
tables so the Next.js storefront can serve them via /api/v1/activities and
/api/v1/blogs.

Usage:
    python3 -m backend.scripts.mass_extract_content          # full extraction
    python3 -m backend.scripts.mass_extract_content --dry-run # preview only
    python3 -m backend.scripts.mass_extract_content --type activity  # activities only
    python3 -m backend.scripts.mass_extract_content --type blog      # blogs only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten

import httpx

DRUPAL_BASE = "https://www.cabin-rentals-of-georgia.com"
LEGACY_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "legacy_map.json"
REQUEST_DELAY = 0.5  # seconds between requests

# ── HTML extraction (reused from migrate_pages_html.py) ──────────────────

CONTENT_SELECTORS = [
    r'<div[^>]*class="[^"]*field-name-body[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
    r'<div[^>]*class="[^"]*node-content[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*(?:region-sidebar|block-system))',
    r'<div[^>]*class="[^"]*field-item[^"]*even[^"]*"[^>]*>(.*?)</div>',
    r'<article[^>]*>(.*?)</article>',
]

STRIP_REGIONS = [
    r'<div[^>]*id="(?:header|footer|navigation|sidebar)[^"]*"[^>]*>.*?</div>',
    r'<nav[^>]*>.*?</nav>',
    r'<div[^>]*class="[^"]*(?:region-sidebar|block-menu|breadcrumb|tabs|action-links)[^"]*"[^>]*>.*?</div>',
]


def _extract_page_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        title = re.sub(r"\s*\|.*$", "", m.group(1).strip())
        return title.strip() or None
    return None


def _extract_h1(html: str) -> str | None:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None
    return None


def _extract_featured_image(html: str) -> str | None:
    """Pull the first significant image URL from the content area."""
    for pattern in [
        r'<img[^>]*class="[^"]*field-slideshow[^"]*"[^>]*src="([^"]+)"',
        r'<div[^>]*class="[^"]*field-name-field-image[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"',
        r'<img[^>]*src="([^"]+/files/styles/[^"]+)"',
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            url = m.group(1)
            if "/default/files/" in url or "/styles/" in url:
                return url
    return None


def _extract_content_body(html: str) -> str | None:
    for pattern in CONTENT_SELECTORS:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) > 50:
            return m.group(1).strip()

    content_match = re.search(
        r'<(?:div|section|main)[^>]*(?:id="content"|class="[^"]*content-area[^"]*")[^>]*>(.*)',
        html, re.DOTALL | re.IGNORECASE,
    )
    if content_match:
        raw = content_match.group(1)
        for boundary in [r'<div[^>]*class="[^"]*region-sidebar', r'<div[^>]*id="footer"', r'<footer']:
            cut = re.search(boundary, raw, re.IGNORECASE)
            if cut:
                raw = raw[:cut.start()]
        if len(raw.strip()) > 50:
            return raw.strip()

    main_match = re.search(
        r'<(?:main|div)[^>]*role="main"[^>]*>(.*?)</(?:main|div)>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if main_match and len(main_match.group(1).strip()) > 50:
        return main_match.group(1).strip()

    # Last resort: h1 to footer
    h1_m = re.search(r"<h1", html, re.IGNORECASE)
    footer_m = re.search(r'<div[^>]*id="footer"|<footer', html, re.IGNORECASE)
    if h1_m:
        start = h1_m.start()
        end = footer_m.start() if footer_m else len(html)
        chunk = html[start:end]
        if len(chunk.strip()) > 50:
            return chunk.strip()

    return None


def _clean_content(html: str) -> str:
    cleaned = html
    cleaned = cleaned.replace("https://www.cabin-rentals-of-georgia.com/sites/default/files/", "/images/drupal-media/")
    cleaned = cleaned.replace("/sites/default/files/", "/images/drupal-media/")
    cleaned = cleaned.replace("https://www.cabin-rentals-of-georgia.com", "")
    cleaned = cleaned.replace("http://www.cabin-rentals-of-georgia.com", "")
    cleaned = re.sub(r' style="[^"]*"', "", cleaned)
    for pattern in STRIP_REGIONS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _generate_summary(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return shorten(text, width=300, placeholder="...")


# ── Slug + metadata parsing ──────────────────────────────────────────────

def _parse_activity_meta(page: dict) -> dict:
    """Extract slug, activity_slug, activity_type, and drupal_nid from legacy_map entry."""
    path: str = page["path"]
    # /activity/arts-entertainment/blue-ridge/blue-ridge-community-theatre
    segments = path.strip("/").split("/")
    # segments[0] = "activity", segments[1] = category, rest = location/name
    slug = segments[-1]
    activity_slug = "/".join(segments[1:])  # everything after /activity/

    activity_type = None
    if len(segments) > 1:
        activity_type = segments[1].replace("-", " ").title()

    area = None
    if len(segments) > 3:
        area = segments[2].replace("-", " ").title()

    drupal_nid = None
    for cls in page.get("body_classes", []):
        m = re.match(r"page-node-(\d+)$", cls)
        if m:
            drupal_nid = int(m.group(1))
            break

    return {
        "slug": slug,
        "activity_slug": activity_slug,
        "activity_type": activity_type,
        "area": area,
        "drupal_nid": drupal_nid,
    }


def _parse_blog_meta(page: dict) -> dict:
    """Extract slug and published_at from a blog legacy_map entry."""
    path: str = page["path"]
    # /blog/2010/11/11/happy-veterans-day
    segments = path.strip("/").split("/")
    slug = segments[-1]

    published_at = None
    if len(segments) >= 4:
        try:
            y, mo, d = int(segments[1]), int(segments[2]), int(segments[3])
            published_at = datetime(y, mo, d, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            pass

    drupal_nid = None
    for cls in page.get("body_classes", []):
        m = re.match(r"page-node-(\d+)$", cls)
        if m:
            drupal_nid = int(m.group(1))
            break

    return {
        "slug": slug,
        "published_at": published_at,
        "drupal_nid": drupal_nid,
    }


# ── DDL ──────────────────────────────────────────────────────────────────

ACTIVITIES_DDL = [
    """
    CREATE TABLE IF NOT EXISTS activities (
        id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title                 VARCHAR(500) NOT NULL,
        slug                  VARCHAR(255) NOT NULL,
        activity_slug         VARCHAR(500),
        body                  TEXT,
        body_summary          TEXT,
        address               TEXT,
        activity_type         VARCHAR(255),
        activity_type_tid     INTEGER,
        area                  VARCHAR(255),
        area_tid              INTEGER,
        people                VARCHAR(255),
        people_tid            INTEGER,
        difficulty_level      VARCHAR(255),
        difficulty_level_tid  INTEGER,
        season                VARCHAR(255),
        season_tid            INTEGER,
        featured_image_url    TEXT,
        featured_image_alt    VARCHAR(500),
        featured_image_title  VARCHAR(500),
        video_urls            JSONB,
        latitude              DOUBLE PRECISION,
        longitude             DOUBLE PRECISION,
        status                VARCHAR(50) DEFAULT 'published',
        is_featured           BOOLEAN DEFAULT false,
        display_order         INTEGER DEFAULT 0,
        drupal_nid            INTEGER,
        drupal_vid            INTEGER,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        published_at          TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_activities_slug ON activities (slug)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_activities_activity_slug ON activities (activity_slug)",
]

BLOGS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS blogs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title           VARCHAR(500) NOT NULL,
        slug            VARCHAR(255) NOT NULL,
        body            TEXT,
        author_name     VARCHAR(255),
        status          VARCHAR(50) DEFAULT 'published',
        is_promoted     BOOLEAN DEFAULT false,
        is_sticky       BOOLEAN DEFAULT false,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        published_at    TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_blogs_slug ON blogs (slug)",
]

ACTIVITY_UPSERT = """
INSERT INTO activities (
    id, title, slug, activity_slug, body, body_summary,
    activity_type, area, featured_image_url, drupal_nid,
    status, created_at, updated_at, published_at
)
VALUES (
    gen_random_uuid(), :title, :slug, :activity_slug, :body, :body_summary,
    :activity_type, :area, :featured_image_url, :drupal_nid,
    'published', NOW(), NOW(), NOW()
)
ON CONFLICT (slug) DO UPDATE SET
    title              = EXCLUDED.title,
    activity_slug      = EXCLUDED.activity_slug,
    body               = EXCLUDED.body,
    body_summary       = EXCLUDED.body_summary,
    activity_type      = EXCLUDED.activity_type,
    area               = EXCLUDED.area,
    featured_image_url = EXCLUDED.featured_image_url,
    drupal_nid         = EXCLUDED.drupal_nid,
    updated_at         = NOW()
"""

BLOG_UPSERT = """
INSERT INTO blogs (
    id, title, slug, body, author_name, status,
    is_promoted, is_sticky, created_at, updated_at, published_at
)
VALUES (
    gen_random_uuid(), :title, :slug, :body, :author_name, 'published',
    false, false, NOW(), NOW(), :published_at
)
ON CONFLICT (slug) DO UPDATE SET
    title        = EXCLUDED.title,
    body         = EXCLUDED.body,
    author_name  = EXCLUDED.author_name,
    published_at = EXCLUDED.published_at,
    updated_at   = NOW()
"""


# ── Main extraction loop ─────────────────────────────────────────────────

async def run_extraction(
    dry_run: bool = False,
    target_type: str | None = None,
) -> None:
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

    # Load the Cartographer's map
    if not LEGACY_MAP_PATH.exists():
        print(f"ERROR: {LEGACY_MAP_PATH} not found. Run the legacy spider first.")
        sys.exit(1)

    with open(LEGACY_MAP_PATH) as f:
        legacy_data = json.load(f)

    all_pages = legacy_data.get("pages", [])

    # Filter by type
    activity_pages = [p for p in all_pages if p.get("page_type") == "Activity"]
    blog_pages = [p for p in all_pages if p.get("page_type") == "Blog Post"]

    if target_type == "activity":
        blog_pages = []
    elif target_type == "blog":
        activity_pages = []

    total_targets = len(activity_pages) + len(blog_pages)

    print("=" * 70)
    print("FORTRESS PRIME — THE MASS EXTRACTION")
    print(f"Legacy map:  {LEGACY_MAP_PATH.name} ({len(all_pages)} total pages)")
    print(f"Activities:  {len(activity_pages)}")
    print(f"Blog Posts:  {len(blog_pages)}")
    print(f"Total:       {total_targets}")
    print(f"Mode:        {'DRY RUN' if dry_run else 'LIVE FIRE'}")
    print(f"DB:          {raw_url.split('@')[1] if '@' in raw_url else raw_url}")
    print("=" * 70)

    # Create tables
    if not dry_run:
        async with SessionLocal() as db:
            for ddl in ACTIVITIES_DDL + BLOGS_DDL:
                await db.execute(sa_text(ddl))
            await db.commit()
        print("[DB] activities + blogs tables ensured\n")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
        headers={
            "User-Agent": "FortressPrime-MassExtraction/1.0 (+migration-audit)",
            "Accept": "text/html",
        },
    )

    stats = {"activity_ok": 0, "activity_err": 0, "blog_ok": 0, "blog_err": 0}
    errors: list[str] = []
    start_time = time.time()

    # ── Activities ────────────────────────────────────────────────────────
    if activity_pages:
        print(f"\n{'─' * 40} ACTIVITIES ({len(activity_pages)}) {'─' * 40}\n")

    for i, page in enumerate(activity_pages, 1):
        url = page["url"]
        meta = _parse_activity_meta(page)
        slug = meta["slug"]
        label = f"[{i:>3}/{len(activity_pages)}] {slug}"

        print(f"  {label:60s} ", end="", flush=True)

        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                errors.append(f"Activity {slug}: HTTP {resp.status_code}")
                stats["activity_err"] += 1
                print(f"HTTP {resp.status_code}")
                time.sleep(REQUEST_DELAY)
                continue

            full_html = resp.text
            title = page.get("h1") or _extract_page_title(full_html) or _extract_h1(full_html) or slug.replace("-", " ").title()
            body = _extract_content_body(full_html)
            featured_img = _extract_featured_image(full_html)

            if not body or len(body) < 30:
                errors.append(f"Activity {slug}: No content extracted")
                stats["activity_err"] += 1
                print("NO CONTENT")
                time.sleep(REQUEST_DELAY)
                continue

            body = _clean_content(body)
            summary = _generate_summary(body)

            if featured_img:
                if featured_img.startswith("/"):
                    featured_img = DRUPAL_BASE + featured_img

            print(f"OK ({len(body):>6,} chars)")

            if not dry_run:
                async with SessionLocal() as db:
                    await db.execute(sa_text(ACTIVITY_UPSERT), {
                        "title": title,
                        "slug": slug,
                        "activity_slug": meta["activity_slug"],
                        "body": body,
                        "body_summary": summary,
                        "activity_type": meta["activity_type"],
                        "area": meta["area"],
                        "featured_image_url": featured_img,
                        "drupal_nid": meta["drupal_nid"],
                    })
                    await db.commit()

            stats["activity_ok"] += 1

        except Exception as exc:
            errors.append(f"Activity {slug}: {exc}")
            stats["activity_err"] += 1
            print(f"ERROR: {exc}")

        time.sleep(REQUEST_DELAY)

    # ── Blog Posts ────────────────────────────────────────────────────────
    if blog_pages:
        print(f"\n{'─' * 40} BLOG POSTS ({len(blog_pages)}) {'─' * 40}\n")

    for i, page in enumerate(blog_pages, 1):
        url = page["url"]
        meta = _parse_blog_meta(page)
        slug = meta["slug"]
        label = f"[{i:>3}/{len(blog_pages)}] {slug}"

        print(f"  {label:60s} ", end="", flush=True)

        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                errors.append(f"Blog {slug}: HTTP {resp.status_code}")
                stats["blog_err"] += 1
                print(f"HTTP {resp.status_code}")
                time.sleep(REQUEST_DELAY)
                continue

            full_html = resp.text
            title = page.get("h1") or _extract_page_title(full_html) or _extract_h1(full_html) or slug.replace("-", " ").title()
            body = _extract_content_body(full_html)

            if not body or len(body) < 30:
                errors.append(f"Blog {slug}: No content extracted")
                stats["blog_err"] += 1
                print("NO CONTENT")
                time.sleep(REQUEST_DELAY)
                continue

            body = _clean_content(body)

            print(f"OK ({len(body):>6,} chars)")

            if not dry_run:
                async with SessionLocal() as db:
                    await db.execute(sa_text(BLOG_UPSERT), {
                        "title": title,
                        "slug": slug,
                        "body": body,
                        "author_name": "Cabin Rentals of Georgia",
                        "published_at": meta["published_at"],
                    })
                    await db.commit()

            stats["blog_ok"] += 1

        except Exception as exc:
            errors.append(f"Blog {slug}: {exc}")
            stats["blog_err"] += 1
            print(f"ERROR: {exc}")

        time.sleep(REQUEST_DELAY)

    await client.aclose()
    elapsed = time.time() - start_time

    # ── Report ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'[DRY RUN] ' if dry_run else ''}MASS EXTRACTION COMPLETE in {elapsed:.0f}s")
    print(f"  Activities: {stats['activity_ok']}/{len(activity_pages)} captured, {stats['activity_err']} errors")
    print(f"  Blogs:      {stats['blog_ok']}/{len(blog_pages)} captured, {stats['blog_err']} errors")
    print(f"  Total:      {stats['activity_ok'] + stats['blog_ok']}/{total_targets} captured")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  ✗ {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    if not dry_run:
        async with SessionLocal() as db:
            act_count = (await db.execute(sa_text("SELECT COUNT(*) FROM activities"))).scalar()
            blog_count = (await db.execute(sa_text("SELECT COUNT(*) FROM blogs"))).scalar()
            print(f"\n[DB] activities table: {act_count} rows")
            print(f"[DB] blogs table:     {blog_count} rows")

    await engine.dispose()
    print("\nThe Mass Extraction is complete. The dead links will now come alive.")


def main() -> None:
    parser = argparse.ArgumentParser(description="The Mass Extraction — scrape all legacy activities + blogs")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--type", choices=["activity", "blog"], help="Extract only one type")
    args = parser.parse_args()
    asyncio.run(run_extraction(dry_run=args.dry_run, target_type=args.type))


if __name__ == "__main__":
    main()
