"""
Vision Pipeline — DOM & Asset Mapper (Level 45)

Scrapes a legacy Drupal cabin detail page and produces a sequential
layout_map.json describing every UI section from top to bottom.

Usage:
    python -m backend.scripts.visual_recon \
        --url "https://www.cabin-rentals-of-georgia.com/cabin/above-the-timberline" \
        --out backend/scripts/layout_map.json

Requires: requests, beautifulsoup4, lxml  (all already in the stack)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

DEFAULT_URL = "https://www.cabin-rentals-of-georgia.com/blue-ridge-cabins/above-the-timberline"
DEFAULT_OUT = "backend/scripts/layout_map.json"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass
class Section:
    order: int
    section_id: str
    label: str
    selector: str = ""
    html_tag: str = ""
    classes: list[str] = field(default_factory=list)
    text_preview: str = ""
    children_count: int = 0
    assets: list[dict[str, str]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


def _text(el: Tag, limit: int = 300) -> str:
    txt = el.get_text(separator=" ", strip=True)
    return (txt[:limit] + "…") if len(txt) > limit else txt


def _collect_assets(el: Tag) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    for img in el.find_all("img", src=True):
        assets.append({"type": "image", "src": img["src"], "alt": img.get("alt", "")})
    for iframe in el.find_all("iframe", src=True):
        assets.append({"type": "iframe", "src": iframe["src"]})
    for video in el.find_all("video"):
        src = video.get("src") or ""
        for source in video.find_all("source"):
            src = src or source.get("src", "")
        if src:
            assets.append({"type": "video", "src": src})
    for a in el.find_all("a", href=True):
        href = a["href"]
        if "youtube.com" in href or "youtu.be" in href or "vimeo.com" in href:
            assets.append({"type": "video_link", "src": href, "text": a.get_text(strip=True)})
    return assets


def _cls(el: Tag) -> list[str]:
    c = el.get("class")
    return list(c) if c else []


# ---------------------------------------------------------------------------
# Pattern detectors — each returns a Section or None
# ---------------------------------------------------------------------------

def _detect_header(soup: BeautifulSoup) -> Section | None:
    for sel in ("header", "#header", ".header", "#block-system-main-menu", "nav"):
        el = soup.select_one(sel)
        if el:
            return Section(
                order=0, section_id="header", label="Header / Navigation",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=_text(el, 200),
                children_count=len(list(el.children)),
                assets=_collect_assets(el),
            )
    return None


def _detect_title(soup: BeautifulSoup) -> Section | None:
    for sel in ("h1.page-title", "#page-title", "h1.title", "article h1", "h1"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return Section(
                order=0, section_id="title", label="Cabin Title",
                selector=sel, html_tag="h1", classes=_cls(el),
                text_preview=_text(el),
                data={"title_text": el.get_text(strip=True)},
            )
    return None


def _detect_like_save(soup: BeautifulSoup) -> Section | None:
    patterns = [
        ("a.flag-link", "flag"),
        ("a[href*='flag/']", "flag"),
        (".flag", "flag"),
        (".flag-bookmarks", "flag"),
        ("a.bookmark", "bookmark"),
        (".save-button", "save"),
        ("[class*='favorite']", "favorite"),
        ("[class*='save']", "save"),
    ]
    for sel, kind in patterns:
        els = soup.select(sel)
        if els:
            return Section(
                order=0, section_id="like_save_buttons", label="Like / Save Buttons",
                selector=sel, html_tag=els[0].name, classes=_cls(els[0]),
                text_preview=" | ".join(_text(e, 80) for e in els[:3]),
                children_count=len(els),
                data={"button_type": kind, "count": len(els)},
            )
    return None


def _detect_description(soup: BeautifulSoup) -> Section | None:
    for sel in (
        ".field-name-body", ".node-body", ".body-field",
        "article .field-item", ".field--name-body",
        ".cabin-description", "#cabin-description",
    ):
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 40:
            return Section(
                order=0, section_id="description", label="Description / Body Text",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=_text(el, 500),
                children_count=len(el.find_all(True, recursive=False)),
                assets=_collect_assets(el),
            )
    body_div = soup.find("div", class_=re.compile(r"body|description", re.I))
    if body_div and len(body_div.get_text(strip=True)) > 40:
        return Section(
            order=0, section_id="description", label="Description / Body Text",
            selector="div[class~=body]", html_tag="div", classes=_cls(body_div),
            text_preview=_text(body_div, 500),
            children_count=len(body_div.find_all(True, recursive=False)),
            assets=_collect_assets(body_div),
        )
    return None


def _detect_amenities(soup: BeautifulSoup) -> Section | None:
    for sel in (
        ".field-name-field-amenities", ".amenities",
        "[class*='amenity']", ".features-list",
        "#amenities",
    ):
        el = soup.select_one(sel)
        if el:
            items = [_text(li, 60) for li in el.find_all("li")][:20]
            return Section(
                order=0, section_id="amenities", label="Amenities / Features",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=_text(el, 400),
                children_count=len(items),
                data={"amenity_items": items},
            )
    heading = soup.find(re.compile(r"^h[2-4]$"), string=re.compile(r"amenit|feature", re.I))
    if heading:
        parent = heading.find_parent(["div", "section"])
        if parent:
            items = [_text(li, 60) for li in parent.find_all("li")][:20]
            return Section(
                order=0, section_id="amenities", label="Amenities / Features",
                selector=f"{heading.name}:contains('Amenit')", html_tag=parent.name,
                classes=_cls(parent),
                text_preview=_text(parent, 400),
                children_count=len(items),
                data={"amenity_items": items},
            )
    return None


def _detect_calendar(soup: BeautifulSoup) -> Section | None:
    for sel in (
        ".availability-calendar", "#availability-calendar",
        "[class*='calendar']", ".field-name-field-calendar",
        "#calendar", ".streamline-calendar",
        "iframe[src*='calendar']",
    ):
        el = soup.select_one(sel)
        if el:
            return Section(
                order=0, section_id="calendar", label="Availability Calendar",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=_text(el, 200),
                assets=_collect_assets(el),
            )
    heading = soup.find(re.compile(r"^h[2-4]$"), string=re.compile(r"availab|calendar", re.I))
    if heading:
        return Section(
            order=0, section_id="calendar", label="Availability Calendar",
            selector=f"{heading.name}:contains('Availab')",
            html_tag=heading.name, classes=_cls(heading),
            text_preview=_text(heading),
        )
    return None


def _detect_rates(soup: BeautifulSoup) -> Section | None:
    for sel in (
        ".field-name-field-rates", ".rates-section", "#rates",
        "[class*='rate']",
    ):
        el = soup.select_one(sel)
        if el and "rate" in el.get_text(strip=True).lower():
            return Section(
                order=0, section_id="rates_text", label="Rates Text / Pricing Notes",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=_text(el, 600),
                data={"rates_html": str(el)[:2000]},
            )
    heading = soup.find(re.compile(r"^h[2-4]$"), string=re.compile(r"^rates?$|pricing|nightly rate", re.I))
    if heading:
        parent = heading.find_parent(["div", "section"])
        block = parent or heading
        return Section(
            order=0, section_id="rates_text", label="Rates Text / Pricing Notes",
            selector=f"{heading.name}:contains('Rate')",
            html_tag=block.name, classes=_cls(block),
            text_preview=_text(block, 600),
            data={"rates_html": str(block)[:2000]},
        )
    for div in soup.find_all("div"):
        txt = div.get_text(strip=True)
        if re.search(r"Rates?\b", txt) and len(txt) > 20 and len(txt) < 2000:
            if any(kw in txt.lower() for kw in ("per night", "nightly", "seasonal", "holiday", "rate")):
                return Section(
                    order=0, section_id="rates_text", label="Rates Text / Pricing Notes",
                    selector="div (fuzzy match on rates keywords)",
                    html_tag="div", classes=_cls(div),
                    text_preview=_text(div, 600),
                    data={"rates_html": str(div)[:2000]},
                )
    return None


def _detect_videos(soup: BeautifulSoup) -> Section | None:
    video_iframes = soup.find_all("iframe", src=re.compile(r"youtube|vimeo", re.I))
    video_embeds = soup.select(".field-name-field-video, .video-embed-field, .embedded-video, [class*='video']")
    heading = soup.find(re.compile(r"^h[2-4]$"), string=re.compile(r"video", re.I))

    urls: list[str] = []
    for iframe in video_iframes:
        urls.append(iframe["src"])
    for embed in video_embeds:
        for iframe in embed.find_all("iframe", src=True):
            urls.append(iframe["src"])
    for a in soup.find_all("a", href=re.compile(r"youtube\.com|youtu\.be|vimeo\.com")):
        urls.append(a["href"])

    if urls or video_embeds or heading:
        el = video_embeds[0] if video_embeds else (heading or video_iframes[0] if video_iframes else None)
        return Section(
            order=0, section_id="videos", label="Videos Section",
            selector=".video-embed-field or iframe[youtube]",
            html_tag=el.name if el else "iframe",
            classes=_cls(el) if el else [],
            text_preview=heading.get_text(strip=True) if heading else "Video Embeds",
            children_count=len(urls),
            assets=[{"type": "video_embed", "src": u} for u in urls],
            data={"video_urls": urls},
        )
    return None


def _detect_photo_grid(soup: BeautifulSoup) -> Section | None:
    for sel in (
        ".field-name-field-gallery", ".gallery", "#gallery",
        ".photo-grid", ".image-gallery", "[class*='gallery']",
        ".field-name-field-images",
    ):
        el = soup.select_one(sel)
        if el:
            imgs = _collect_assets(el)
            return Section(
                order=0, section_id="photo_grid", label="Photo Gallery / Grid",
                selector=sel, html_tag=el.name, classes=_cls(el),
                text_preview=f"{len(imgs)} images found",
                children_count=len(imgs),
                assets=imgs,
            )
    all_imgs = soup.find_all("img", src=True)
    gallery_imgs = [
        img for img in all_imgs
        if any(kw in (img.get("src", "") + " ".join(_cls(img))).lower()
               for kw in ("gallery", "photo", "cabin", "property"))
    ]
    if len(gallery_imgs) > 4:
        return Section(
            order=0, section_id="photo_grid", label="Photo Gallery / Grid",
            selector="img[gallery|photo|cabin] (heuristic)",
            html_tag="img", classes=[],
            text_preview=f"{len(gallery_imgs)} gallery-like images found",
            children_count=len(gallery_imgs),
            assets=[{"type": "image", "src": img["src"], "alt": img.get("alt", "")} for img in gallery_imgs[:30]],
        )
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

CANONICAL_ORDER = [
    "header", "title", "like_save_buttons", "description",
    "amenities", "calendar", "rates_text", "videos", "photo_grid",
]

DETECTORS = {
    "header": _detect_header,
    "title": _detect_title,
    "like_save_buttons": _detect_like_save,
    "description": _detect_description,
    "amenities": _detect_amenities,
    "calendar": _detect_calendar,
    "rates_text": _detect_rates,
    "videos": _detect_videos,
    "photo_grid": _detect_photo_grid,
}


def scrape_layout(url: str) -> dict[str, Any]:
    print(f"[RECON] Fetching {url} …")
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    page_title = soup.title.get_text(strip=True) if soup.title else ""

    sections: list[Section] = []
    found: dict[str, Section] = {}
    missing: list[str] = []

    for section_id in CANONICAL_ORDER:
        detector = DETECTORS[section_id]
        result = detector(soup)
        if result:
            found[section_id] = result
        else:
            missing.append(section_id)

    for i, section_id in enumerate(CANONICAL_ORDER):
        if section_id in found:
            s = found[section_id]
            s.order = i + 1
            sections.append(s)

    layout_map = {
        "url": url,
        "page_title": page_title,
        "scraped_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "canonical_order": CANONICAL_ORDER,
        "sections_found": [s.section_id for s in sections],
        "sections_missing": missing,
        "section_count": len(sections),
        "sections": [asdict(s) for s in sections],
    }

    print(f"[RECON] Found {len(sections)}/{len(CANONICAL_ORDER)} sections")
    if missing:
        print(f"[RECON] MISSING: {', '.join(missing)}")
    for s in sections:
        status = "✓"
        print(f"  {status} [{s.order}] {s.label} — {s.selector}")
        if s.assets:
            print(f"        {len(s.assets)} assets detected")
        if s.data.get("video_urls"):
            print(f"        Video URLs: {s.data['video_urls']}")
        if s.data.get("rates_html"):
            preview = s.text_preview[:120]
            print(f"        Rates preview: {preview}")

    return layout_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Vision Pipeline — DOM & Asset Mapper")
    parser.add_argument("--url", default=DEFAULT_URL, help="Legacy cabin URL to scrape")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output JSON path")
    args = parser.parse_args()

    layout = scrape_layout(args.url)

    with open(args.out, "w") as f:
        json.dump(layout, f, indent=2, ensure_ascii=False)
    print(f"\n[RECON] Layout map written to {args.out}")

    print("\n" + "=" * 60)
    print("ALIGNMENT REPORT — Legacy vs Next.js")
    print("=" * 60)
    nextjs_has = {"header", "title", "description", "amenities", "calendar", "photo_grid"}
    nextjs_partial = {"like_save_buttons"}
    nextjs_missing_known = {"rates_text", "videos"}

    for section_id in CANONICAL_ORDER:
        legacy = "FOUND" if section_id in layout["sections_found"] else "MISSING"
        if section_id in nextjs_has:
            njs = "PRESENT"
        elif section_id in nextjs_partial:
            njs = "PARTIAL (button exists but no flag/save logic)"
        elif section_id in nextjs_missing_known:
            njs = "MISSING (API returns null)"
        else:
            njs = "UNKNOWN"
        drift = "OK" if legacy == "FOUND" and njs == "PRESENT" else "DRIFT"
        print(f"  [{drift:5s}] {section_id:20s}  Legacy={legacy:7s}  NextJS={njs}")

    print("\nACTION ITEMS:")
    print("  1. Backend must populate rates_description from ota_metadata or Drupal scrape")
    print("  2. Backend must populate video[] from Drupal field_video or ota_metadata")
    print("  3. Frontend Like/Save button needs flag/bookmark integration")


if __name__ == "__main__":
    main()
