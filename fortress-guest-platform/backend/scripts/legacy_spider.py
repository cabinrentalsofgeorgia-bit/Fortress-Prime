#!/usr/bin/env python3
"""
Legacy Spider — Total site mapping operation for the Drupal→Next.js migration.

Crawls the legacy Drupal site via sitemap.xml (with recursive crawl fallback),
scrapes every discovered page, and produces:

  1. backend/data/legacy_map.json   — structured page inventory
  2. backend/data/missing_routes.txt — gap analysis vs Next.js frontend routes
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.cabin-rentals-of-georgia.com"
SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap"]
REQUEST_TIMEOUT = 30
CRAWL_DELAY = 0.25  # politeness delay between requests (seconds)
MAX_PAGES = 5000
USER_AGENT = (
    "FortressPrime-LegacySpider/1.0 "
    "(+https://cabin-rentals-of-georgia.com; migration-audit)"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_JSON = DATA_DIR / "legacy_map.json"
OUTPUT_MISSING = DATA_DIR / "missing_routes.txt"

NEXTJS_APP_DIR = Path("/home/admin/cabin-rentals-of-georgia/app")

# ---------------------------------------------------------------------------
# Page type inference rules (order matters — first match wins)
# ---------------------------------------------------------------------------

PAGE_TYPE_RULES: list[tuple[str, re.Pattern]] = [
    ("Blog Post",       re.compile(r"^/blog/")),
    ("Blog Listing",    re.compile(r"^/blogs?$")),
    ("Activity",        re.compile(r"^/activit(y|ies)/")),
    ("Activities Hub",  re.compile(r"^/blue-ridge-georgia-activities$")),
    ("Cabin Detail",    re.compile(r"^/cabin/")),
    ("Cabin Listing",   re.compile(r"^/cabins/")),
    ("Cabin Listing",   re.compile(r"^/blue-ridge-cabins$")),
    ("Availability",    re.compile(r"^/availability")),
    ("Checkout",        re.compile(r"^/checkout")),
    ("Reservation",     re.compile(r"^/reservations?")),
    ("Property Mgmt",   re.compile(r"^/blue-ridge-property-management$")),
    ("About",           re.compile(r"^/about")),
    ("FAQ",             re.compile(r"^/faq$")),
    ("Policy",          re.compile(r"^/(rental-policies|terms|privacy|cancellation)")),
    ("Map",             re.compile(r"^/cabin-map$")),
    ("Compare",         re.compile(r"^/compare$")),
    ("Memories",        re.compile(r"^/blue-ridge-memories$")),
    ("Experience",      re.compile(r"^/blue-ridge-experience$")),
    ("Contact",         re.compile(r"^/contact")),
    ("Gallery",         re.compile(r"^/gallery")),
    ("Specials",        re.compile(r"^/(specials|deals|coupon|promo)")),
    ("Review",          re.compile(r"^/reviews?")),
    ("Events",          re.compile(r"^/events?")),
    ("Node (Drupal)",   re.compile(r"^/node/")),
    ("Taxonomy",        re.compile(r"^/taxonomy/")),
    ("User",            re.compile(r"^/user")),
    ("Search",          re.compile(r"^/search")),
    ("Admin/System",    re.compile(r"^/(admin|cron|batch|filter|rss)")),
    ("Drupal File",     re.compile(r"^/sites/")),
]

DRUPAL_WIDGET_CLASSES = [
    "webform-client-form",
    "views-exposed-form",
    "entityform",
    "field-collection",
    "media-element",
    "flexslider",
    "owl-carousel",
    "colorbox",
    "lightbox",
    "fancybox",
    "gmap",
    "leaflet-map",
    "availability-calendar",
    "commerce-add-to-cart",
    "booking-form",
]


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return s


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _fetch_sitemap_urls(session: requests.Session, base: str) -> set[str]:
    """Try each known sitemap path; parse XML sitemaps and sitemap indexes."""
    urls: set[str] = set()

    for path in SITEMAP_PATHS:
        sitemap_url = urljoin(base, path)
        try:
            resp = session.get(sitemap_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
        except requests.RequestException:
            continue

        content_type = resp.headers.get("Content-Type", "")
        if "xml" not in content_type and "<?xml" not in resp.text[:200]:
            continue

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            continue

        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        if tag == "sitemapindex":
            for sitemap_el in root.findall("sm:sitemap/sm:loc", SITEMAP_NS):
                child_url = (sitemap_el.text or "").strip()
                if child_url:
                    urls.update(_fetch_child_sitemap(session, child_url))
        elif tag == "urlset":
            for url_el in root.findall("sm:url/sm:loc", SITEMAP_NS):
                loc = (url_el.text or "").strip()
                if loc:
                    urls.add(loc)

        if urls:
            print(f"  [sitemap] Found {len(urls)} URLs from {sitemap_url}")
            break

    return urls


def _fetch_child_sitemap(session: requests.Session, url: str) -> set[str]:
    urls: set[str] = set()
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return urls
        root = ElementTree.fromstring(resp.content)
        for url_el in root.findall("sm:url/sm:loc", SITEMAP_NS):
            loc = (url_el.text or "").strip()
            if loc:
                urls.add(loc)
        print(f"  [sitemap] +{len(urls)} from child: {url}")
    except Exception:
        pass
    return urls


# ---------------------------------------------------------------------------
# Recursive crawl fallback
# ---------------------------------------------------------------------------

def _crawl_discover(session: requests.Session, base: str, max_pages: int) -> set[str]:
    """BFS crawl from base URL, collecting internal links."""
    parsed_base = urlparse(base)
    base_host = parsed_base.netloc.lower().replace("www.", "")
    visited: set[str] = set()
    queue: list[str] = [base]
    found: set[str] = set()

    print("  [crawl] Sitemap empty or unavailable — falling back to BFS crawl")

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        normalized = url.split("#")[0].split("?")[0].rstrip("/")
        if normalized in visited:
            continue
        visited.add(normalized)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                continue
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                continue
        except requests.RequestException:
            continue

        found.add(resp.url)
        soup = BeautifulSoup(resp.text, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            abs_url = urljoin(resp.url, href).split("#")[0].split("?")[0].rstrip("/")
            link_host = urlparse(abs_url).netloc.lower().replace("www.", "")

            if link_host != base_host:
                continue
            if abs_url in visited:
                continue
            if any(abs_url.endswith(ext) for ext in (".pdf", ".jpg", ".png", ".gif", ".zip", ".css", ".js")):
                continue

            queue.append(abs_url)

        if len(found) % 50 == 0 and len(found) > 0:
            print(f"  [crawl] Discovered {len(found)} pages so far...")

        time.sleep(CRAWL_DELAY)

    return found


# ---------------------------------------------------------------------------
# Page scraper
# ---------------------------------------------------------------------------

def _infer_page_type(path: str, soup: BeautifulSoup) -> str:
    for label, pattern in PAGE_TYPE_RULES:
        if pattern.search(path):
            return label

    body = soup.find("body")
    if isinstance(body, Tag):
        classes = " ".join(body.get("class", []))
        if "node-type-" in classes:
            node_type = re.search(r"node-type-(\S+)", classes)
            if node_type:
                return f"Drupal Node: {node_type.group(1).replace('-', '_')}"
        if "page-taxonomy" in classes:
            return "Taxonomy"

    if path == "/" or path == "":
        return "Homepage"

    return "Unknown"


def _detect_features(soup: BeautifulSoup) -> list[str]:
    features: list[str] = []

    if soup.find("form"):
        form_ids = [f.get("id", "") for f in soup.find_all("form")]
        form_classes = []
        for f in soup.find_all("form"):
            form_classes.extend(f.get("class", []))
        form_desc = "Form"
        if any("search" in (fid or "").lower() for fid in form_ids):
            form_desc = "Search Form"
        elif any("webform" in c for c in form_classes):
            form_desc = "Webform"
        elif any("contact" in (fid or "").lower() for fid in form_ids):
            form_desc = "Contact Form"
        elif any("commerce" in c for c in form_classes):
            form_desc = "Commerce Form"
        features.append(form_desc)

    if soup.find("iframe"):
        srcs = [iframe.get("src", "") for iframe in soup.find_all("iframe")]
        for src in srcs:
            if "youtube" in src or "vimeo" in src:
                features.append("Embedded Video")
            elif "google.com/maps" in src or "maps.google" in src:
                features.append("Google Map Embed")
            elif "calendar" in src.lower():
                features.append("Calendar Embed")
            else:
                features.append("iFrame")

    if soup.find("video") or soup.find("source", attrs={"type": re.compile(r"video/")}):
        features.append("HTML5 Video")

    if soup.find("audio"):
        features.append("Audio Player")

    all_classes = set()
    for el in soup.find_all(attrs={"class": True}):
        if isinstance(el, Tag):
            all_classes.update(el.get("class", []))

    class_string = " ".join(all_classes)
    for widget_class in DRUPAL_WIDGET_CLASSES:
        if widget_class in class_string:
            features.append(f"Drupal Widget: {widget_class}")

    if "slideshow" in class_string or "slider" in class_string or "carousel" in class_string:
        features.append("Slideshow/Carousel")

    if "gallery" in class_string or "lightbox" in class_string:
        features.append("Image Gallery")

    if soup.find("div", class_=re.compile(r"view-")) or soup.find("div", class_="views-row"):
        features.append("Drupal Views List")

    if soup.find(attrs={"data-drupal-selector": True}):
        features.append("Drupal AJAX Element")

    return sorted(set(features))


def _scrape_page(session: requests.Session, url: str) -> dict[str, Any] | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return {"url": url, "error": str(exc), "status_code": None}

    if resp.status_code != 200:
        return {"url": url, "error": f"HTTP {resp.status_code}", "status_code": resp.status_code}

    ct = resp.headers.get("Content-Type", "")
    if "text/html" not in ct:
        return {"url": url, "error": f"Non-HTML content: {ct}", "status_code": resp.status_code}

    soup = BeautifulSoup(resp.text, "lxml")
    parsed = urlparse(resp.url)
    path = parsed.path.rstrip("/") or "/"

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(strip=True) if h1_tag else None

    meta_desc = None
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if isinstance(meta_tag, Tag):
        meta_desc = meta_tag.get("content", "")

    canonical = None
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if isinstance(canonical_tag, Tag):
        canonical = canonical_tag.get("href", "")

    page_type = _infer_page_type(path, soup)
    features = _detect_features(soup)

    internal_links = set()
    base_host = parsed.netloc.lower().replace("www.", "")
    for a in soup.find_all("a", href=True):
        abs_link = urljoin(resp.url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
        link_parsed = urlparse(abs_link)
        link_host = link_parsed.netloc.lower().replace("www.", "")
        if link_host == base_host and link_parsed.path:
            internal_links.add(link_parsed.path.rstrip("/") or "/")

    img_count = len(soup.find_all("img"))

    body_tag = soup.find("body")
    body_classes = []
    if isinstance(body_tag, Tag):
        body_classes = body_tag.get("class", [])

    return {
        "url": resp.url,
        "path": path,
        "status_code": resp.status_code,
        "title": title,
        "h1": h1,
        "meta_description": meta_desc,
        "canonical_url": canonical,
        "page_type": page_type,
        "features": features,
        "internal_link_count": len(internal_links),
        "internal_links": sorted(internal_links),
        "image_count": img_count,
        "body_classes": body_classes,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Next.js route discovery
# ---------------------------------------------------------------------------

def _discover_nextjs_routes() -> list[str]:
    """Walk the Next.js app directory and extract public route patterns."""
    routes: list[str] = []

    if not NEXTJS_APP_DIR.exists():
        print(f"  [routes] Warning: Next.js app dir not found at {NEXTJS_APP_DIR}")
        return routes

    for page_file in sorted(NEXTJS_APP_DIR.rglob("page.tsx")):
        rel = page_file.relative_to(NEXTJS_APP_DIR)
        parts = list(rel.parts)

        cleaned: list[str] = []
        is_public = True
        for part in parts:
            if part == "page.tsx":
                continue
            if part.startswith("(") and part.endswith(")"):
                group_name = part[1:-1]
                if group_name == "admin":
                    is_public = False
                    break
                continue
            cleaned.append(part)

        if not is_public:
            continue

        route = "/" + "/".join(cleaned) if cleaned else "/"
        routes.append(route)

    return sorted(set(routes))


def _match_route(path: str, route_patterns: list[str]) -> str | None:
    """Check if a scraped path matches any Next.js route pattern."""
    path_clean = path.rstrip("/") or "/"

    for pattern in route_patterns:
        pattern_clean = pattern.rstrip("/") or "/"
        if path_clean == pattern_clean:
            return pattern

        pat_parts = pattern_clean.strip("/").split("/")
        path_parts = path_clean.strip("/").split("/")

        if _segments_match(path_parts, pat_parts):
            return pattern

    return None


def _segments_match(path_parts: list[str], pat_parts: list[str]) -> bool:
    pi = 0
    for i, pat_seg in enumerate(pat_parts):
        if pat_seg.startswith("[...") and pat_seg.endswith("]"):
            return pi < len(path_parts)
        if pat_seg.startswith("[[...") and pat_seg.endswith("]]"):
            return True
        if pat_seg.startswith("[") and pat_seg.endswith("]"):
            if pi >= len(path_parts):
                return False
            pi += 1
            continue
        if pi >= len(path_parts) or path_parts[pi] != pat_seg:
            return False
        pi += 1
    return pi == len(path_parts)


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def _generate_missing_routes(
    pages: list[dict[str, Any]],
    nextjs_routes: list[str],
) -> str:
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("LEGACY SITE → NEXT.JS ROUTE GAP ANALYSIS")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append("=" * 80)
    lines.append("")

    lines.append("KNOWN NEXT.JS FRONTEND ROUTES:")
    lines.append("-" * 40)
    for r in nextjs_routes:
        lines.append(f"  {r}")
    lines.append(f"\nTotal Next.js routes: {len(nextjs_routes)}")
    lines.append("")

    matched: list[tuple[str, str, str]] = []
    unmatched: list[dict[str, Any]] = []

    for page in pages:
        if page.get("error"):
            continue
        path = page.get("path", "")
        if not path:
            continue
        route = _match_route(path, nextjs_routes)
        if route:
            matched.append((path, route, page.get("page_type", "Unknown")))
        else:
            unmatched.append(page)

    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for page in unmatched:
        type_buckets[page.get("page_type", "Unknown")].append(page)

    lines.append("MISSING ROUTES — NOT YET BUILT IN NEXT.JS")
    lines.append("=" * 60)
    lines.append(f"Total missing: {len(unmatched)}")
    lines.append("")

    for page_type in sorted(type_buckets.keys()):
        bucket = type_buckets[page_type]
        lines.append(f"  [{page_type}] ({len(bucket)} pages)")
        for page in sorted(bucket, key=lambda p: p.get("path", "")):
            path = page.get("path", "")
            title = page.get("title", "")
            features_str = ", ".join(page.get("features", []))
            lines.append(f"    {path}")
            if title:
                lines.append(f"      Title: {title}")
            if features_str:
                lines.append(f"      Features: {features_str}")
        lines.append("")

    lines.append("MATCHED ROUTES — ALREADY COVERED BY NEXT.JS")
    lines.append("=" * 60)
    lines.append(f"Total matched: {len(matched)}")
    lines.append("")
    for path, route, ptype in sorted(matched, key=lambda x: x[0]):
        lines.append(f"  {path}  →  {route}  ({ptype})")

    lines.append("")
    lines.append("COVERAGE SUMMARY")
    lines.append("=" * 60)
    total = len(matched) + len(unmatched)
    pct = (len(matched) / total * 100) if total > 0 else 0
    lines.append(f"  Total legacy pages scraped: {total}")
    lines.append(f"  Matched to Next.js routes:  {len(matched)} ({pct:.1f}%)")
    lines.append(f"  MISSING (need to build):    {len(unmatched)} ({100 - pct:.1f}%)")
    lines.append("")

    for page_type in sorted(type_buckets.keys()):
        count = len(type_buckets[page_type])
        lines.append(f"    {page_type}: {count} missing")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base_url = BASE_URL
    if len(sys.argv) > 1:
        base_url = sys.argv[1].rstrip("/")

    print(f"{'=' * 60}")
    print(f"FORTRESS PRIME — LEGACY SPIDER v1.0")
    print(f"Target: {base_url}")
    print(f"{'=' * 60}")
    print()

    session = _make_session()

    # Phase 1: Discover URLs
    print("[Phase 1] Discovering URLs...")
    urls = _fetch_sitemap_urls(session, base_url)

    if not urls:
        urls = _crawl_discover(session, base_url, MAX_PAGES)

    if not urls:
        print("  FATAL: No URLs discovered. Check that the site is reachable.")
        sys.exit(1)

    urls_sorted = sorted(urls)
    print(f"\n  Total URLs discovered: {len(urls_sorted)}")
    print()

    # Phase 2: Scrape every page
    print(f"[Phase 2] Scraping {len(urls_sorted)} pages...")
    pages: list[dict[str, Any]] = []
    errors = 0
    start_time = time.time()

    for i, url in enumerate(urls_sorted, 1):
        if i % 25 == 0 or i == len(urls_sorted):
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{len(urls_sorted)}] {rate:.1f} pages/sec — {url[:80]}")

        result = _scrape_page(session, url)
        if result:
            pages.append(result)
            if result.get("error"):
                errors += 1

        time.sleep(CRAWL_DELAY)

    elapsed_total = time.time() - start_time
    print(f"\n  Scraping complete: {len(pages)} pages in {elapsed_total:.1f}s ({errors} errors)")
    print()

    # Phase 3: Discover Next.js routes
    print("[Phase 3] Mapping Next.js frontend routes...")
    nextjs_routes = _discover_nextjs_routes()
    print(f"  Found {len(nextjs_routes)} Next.js routes")
    print()

    # Phase 4: Write outputs
    print("[Phase 4] Writing outputs...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Aggregate stats
    type_counts: dict[str, int] = defaultdict(int)
    feature_counts: dict[str, int] = defaultdict(int)
    for page in pages:
        if not page.get("error"):
            type_counts[page.get("page_type", "Unknown")] += 1
            for feat in page.get("features", []):
                feature_counts[feat] += 1

    legacy_map = {
        "meta": {
            "base_url": base_url,
            "crawl_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_urls_discovered": len(urls_sorted),
            "total_pages_scraped": len(pages),
            "total_errors": errors,
            "scrape_duration_seconds": round(elapsed_total, 1),
        },
        "summary": {
            "page_types": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "features_detected": dict(sorted(feature_counts.items(), key=lambda x: -x[1])),
            "nextjs_route_count": len(nextjs_routes),
            "nextjs_routes": nextjs_routes,
        },
        "pages": pages,
    }

    OUTPUT_JSON.write_text(
        json.dumps(legacy_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    json_size = OUTPUT_JSON.stat().st_size
    print(f"  → {OUTPUT_JSON} ({json_size:,} bytes)")

    missing_report = _generate_missing_routes(pages, nextjs_routes)
    OUTPUT_MISSING.write_text(missing_report, encoding="utf-8")
    missing_size = OUTPUT_MISSING.stat().st_size
    print(f"  → {OUTPUT_MISSING} ({missing_size:,} bytes)")
    print()

    # Final report
    print("=" * 60)
    print("RECON COMPLETE — CARTOGRAPHER'S SUMMARY")
    print("=" * 60)
    print(f"  URLs discovered:    {len(urls_sorted)}")
    print(f"  Pages scraped:      {len(pages)}")
    print(f"  Errors:             {errors}")
    print(f"  Next.js routes:     {len(nextjs_routes)}")
    print()
    print("  Page Types:")
    for ptype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {ptype:25s} {count}")
    print()
    if feature_counts:
        print("  Interactive Features Detected:")
        for feat, count in sorted(feature_counts.items(), key=lambda x: -x[1]):
            print(f"    {feat:35s} {count}")
        print()

    valid_pages = [p for p in pages if not p.get("error")]
    matched = sum(1 for p in valid_pages if _match_route(p.get("path", ""), nextjs_routes))
    unmatched = len(valid_pages) - matched
    pct = (matched / len(valid_pages) * 100) if valid_pages else 0
    print(f"  COVERAGE: {matched}/{len(valid_pages)} pages matched ({pct:.1f}%)")
    print(f"  GAP:      {unmatched} pages have NO Next.js route")
    print()
    print("The Cartographer's Ledger has been written. The Commander has full visibility.")


if __name__ == "__main__":
    main()
