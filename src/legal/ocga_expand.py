#!/usr/bin/env python3
"""
ocga_expand.py — Acquire OCGA statutes from Justia for GA corpus expansion.

Fetches OCGA titles 9, 13, 14, 33, 44, 51 from law.justia.com with correct
Title→Chapter→Article→Section hierarchy and proper session chaining.

Handles both 3-level (Chapter→Section) and 4-level (Chapter→Article→Section)
structures that appear on Justia.

Output:
  /mnt/fortress_nas/datasets/legal-corpus/ocga/{title-N}.jsonl
  Schema: {title, chapter, article, section, citation, heading, text,
           url, source, effective_date, fetched_at}

Usage:
  python -m src.legal.ocga_expand [--title N] [--dry-run] [--titles all]
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import logging
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"ocga_expand"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ocga_expand")

JUSTIA_BASE    = "https://law.justia.com"
JUSTIA_GA_BASE = f"{JUSTIA_BASE}/codes/georgia/"
OUT_ROOT       = Path("/mnt/fortress_nas/datasets/legal-corpus/ocga")
RAW_ROOT       = Path("/mnt/fortress_nas/datasets/legal-corpus/ocga/.raw")
SLEEP_S        = 3.0   # between page fetches within a session
SESSION_SLEEP  = 5.0   # between sections (outer loop)
CHAPTER_SLEEP  = 8.0   # between chapters (re-establish session)

# Target titles: {n: description}
TARGET_TITLES = {
    9:  "Civil Practice",
    13: "Contracts",
    14: "Corporations, Partnerships, and Associations",
    33: "Insurance",
    44: "Property",
    51: "Torts",
}

# Content div patterns (Justia has changed these over time)
_CONTENT_PATTERNS = [
    r'class="[^"]*has-text-primary[^"]*"[^>]*>(.*?)</div>',
    r'id="codes-content"[^>]*>(.*?)</div>',
    r'class="[^"]*content-box[^"]*"[^>]*>(.*?)</div>',
    r'<article[^>]*>(.*?)</article>',
]


def _make_opener() -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def _get(opener: urllib.request.OpenerDirector, url: str, referer: str = "") -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_links(html: str, pattern: str) -> list[str]:
    """Find href values matching pattern, deduplicated."""
    raw = re.findall(r'href=["\']([^"\']+)["\']', html)
    matches = [h for h in raw if re.search(pattern, h)]
    return list(dict.fromkeys(matches))


def _extract_text(html: str) -> str:
    """Extract statute text from section HTML."""
    for pat in _CONTENT_PATTERNS:
        m = re.search(pat, html, re.DOTALL)
        if m:
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"&amp;", "&", text)
            text = re.sub(r"&sect;", "§", text)
            text = re.sub(r"&#\d+;", " ", text)
            text = re.sub(r"&[a-zA-Z]+;", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 30:
                return text
    return ""


def _extract_heading(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if m:
        h = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # Strip trailing ":: 2024 Georgia Code ::" boilerplate
        h = re.split(r"::", h)[0].strip()
        return h
    return ""


def _section_number_from_url(url: str) -> str:
    """Extract '9-11-1' from URL like /codes/georgia/title-9/chapter-11/article-1/section-9-11-1/"""
    m = re.search(r"section-(\d[\d\-]+\d)", url)
    return m.group(1) if m else ""


def fetch_title(title_n: int, dry_run: bool = False) -> int:
    """Fetch all sections for a given title. Returns section count."""
    out_path = OUT_ROOT / f"title-{title_n}.jsonl"
    raw_dir = RAW_ROOT / f"title-{title_n}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Load already-fetched section URLs for idempotency
    fetched_urls: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    if r.get("url"):
                        fetched_urls.add(r["url"])
                except Exception:
                    pass
    log.info("title=%d already_fetched=%d", title_n, len(fetched_urls))

    if dry_run:
        log.info("[DRY RUN] title=%d would fetch from %s", title_n,
                 f"{JUSTIA_GA_BASE}title-{title_n}/")
        return 0

    title_url = f"{JUSTIA_GA_BASE}title-{title_n}/"
    ga_codes_url = JUSTIA_GA_BASE

    # Step 1: Title index → chapter links (fresh session per title, full referrer chain)
    log.info("fetching title index url=%s", title_url)
    opener = _make_opener()
    # Full referrer chain: root → ga codes → title
    _get(opener, JUSTIA_BASE + "/")
    time.sleep(SLEEP_S)
    _get(opener, ga_codes_url, referer=JUSTIA_BASE + "/")
    time.sleep(SLEEP_S)
    title_html = _get(opener, title_url, referer=ga_codes_url)
    time.sleep(SLEEP_S)

    chap_links = _extract_links(title_html, rf"title-{title_n}/chapter-[\w-]+/?$")
    if not chap_links:
        chap_links = _extract_links(title_html, rf"/title-{title_n}/chapter-")
    log.info("title=%d chapters=%d", title_n, len(chap_links))

    sections_written = 0

    for chap_idx, chap_path in enumerate(chap_links):
        chap_url = urljoin(JUSTIA_BASE, chap_path)
        chap_slug = chap_path.rstrip("/").split("/")[-1]

        # Re-establish fresh session for each chapter to avoid bot blocks
        chap_html_path = raw_dir / f"{chap_slug}.html"
        if chap_html_path.exists():
            chap_html = chap_html_path.read_text()
        else:
            log.info("fetching chapter=%s (chap %d/%d)", chap_slug, chap_idx+1, len(chap_links))
            # Fresh session: full referrer chain root → ga_codes → title → chapter
            chapter_opener = _make_opener()
            try:
                _get(chapter_opener, JUSTIA_BASE + "/")
                time.sleep(SLEEP_S)
                _get(chapter_opener, ga_codes_url, referer=JUSTIA_BASE + "/")
                time.sleep(SLEEP_S)
                _get(chapter_opener, title_url, referer=ga_codes_url)
                time.sleep(SLEEP_S)
                chap_html = _get(chapter_opener, chap_url, referer=title_url)
            except Exception as exc:
                log.warning("chapter_fetch_failed chap=%s error=%s", chap_slug, exc)
                time.sleep(CHAPTER_SLEEP)
                continue
            chap_html_path.write_text(chap_html)
            time.sleep(SLEEP_S)
            opener = chapter_opener  # reuse this session for the chapter's articles/sections

        # Check for article-level links first
        art_links = _extract_links(chap_html, rf"/title-{title_n}/chapter-[^/]+/article-")
        # Direct section links (no article level)
        sec_links_direct = _extract_links(chap_html, rf"/title-{title_n}/chapter-[^/]+/section-")

        if art_links:
            # 4-level hierarchy: Chapter → Article → Section
            for art_path in art_links:
                art_url = urljoin(JUSTIA_BASE, art_path)
                art_slug = art_path.rstrip("/").split("/")[-1]

                art_html_path = raw_dir / f"{chap_slug}-{art_slug}.html"
                if art_html_path.exists():
                    art_html = art_html_path.read_text()
                else:
                    log.info("fetching article=%s/%s", chap_slug, art_slug)
                    try:
                        art_html = _get(opener, art_url, referer=chap_url)
                    except Exception as exc:
                        log.warning("article_fetch_failed art=%s error=%s — retrying with new session", art_slug, exc)
                        time.sleep(CHAPTER_SLEEP)
                        opener = _make_opener()
                        try:
                            _get(opener, JUSTIA_BASE + "/")
                            time.sleep(SLEEP_S)
                            _get(opener, ga_codes_url, referer=JUSTIA_BASE + "/")
                            time.sleep(SLEEP_S)
                            _get(opener, title_url, referer=ga_codes_url)
                            time.sleep(SLEEP_S)
                            _get(opener, chap_url, referer=title_url)
                            time.sleep(SLEEP_S)
                            art_html = _get(opener, art_url, referer=chap_url)
                        except Exception as exc2:
                            log.warning("article_retry_failed art=%s error=%s", art_slug, exc2)
                            continue
                    art_html_path.write_text(art_html)
                    time.sleep(SLEEP_S)

                sec_links = _extract_links(art_html, rf"/title-{title_n}/chapter-[^/]+/article-[^/]+/section-")
                if not sec_links:
                    # Fallback: direct section links within article page
                    sec_links = _extract_links(art_html, rf"/title-{title_n}/chapter-[^/]+/section-")

                sections_written += _fetch_sections(
                    opener, sec_links, out_path, fetched_urls,
                    title_n, chap_slug, art_slug, art_url, raw_dir
                )
        else:
            # 3-level hierarchy: Chapter → Section directly
            sections_written += _fetch_sections(
                opener, sec_links_direct, out_path, fetched_urls,
                title_n, chap_slug, "", chap_url, raw_dir
            )

        # Rest between chapters to avoid bot detection
        if chap_idx < len(chap_links) - 1:
            time.sleep(CHAPTER_SLEEP)

    log.info("title=%d complete sections_written=%d", title_n, sections_written)
    return sections_written


def _fetch_sections(
    opener, sec_paths: list[str], out_path: Path,
    fetched_urls: set[str], title_n: int,
    chap_slug: str, art_slug: str, referer: str, raw_dir: Path,
) -> int:
    written = 0
    for sec_path in sec_paths:
        sec_url = urljoin(JUSTIA_BASE, sec_path)
        if sec_url in fetched_urls:
            continue

        sec_num = _section_number_from_url(sec_path)
        sec_slug = sec_path.rstrip("/").split("/")[-1]
        sec_html_path = raw_dir / f"{chap_slug}-{art_slug}-{sec_slug}.html" if art_slug else raw_dir / f"{chap_slug}-{sec_slug}.html"

        if sec_html_path.exists():
            sec_html = sec_html_path.read_text()
        else:
            log.info("fetching section=%s", sec_num)
            try:
                sec_html = _get(opener, sec_url, referer=referer)
            except Exception as exc:
                log.warning("section_fetch_failed sec=%s error=%s", sec_num, exc)
                time.sleep(SESSION_SLEEP)
                continue
            sec_html_path.write_text(sec_html)
            time.sleep(SESSION_SLEEP)

        text = _extract_text(sec_html)
        heading = _extract_heading(sec_html)

        if not text or len(text) < 20:
            log.debug("no_text sec=%s", sec_num)
            continue

        record = {
            "source": "ocga_justia",
            "title": title_n,
            "title_name": TARGET_TITLES.get(title_n, ""),
            "chapter": chap_slug.replace("chapter-", ""),
            "article": art_slug.replace("article-", "") if art_slug else "",
            "section": sec_num,
            "citation": f"O.C.G.A. § {sec_num}" if sec_num else "",
            "heading": heading,
            "text": text,
            "url": sec_url,
            "effective_date": "2024",
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fetched_urls.add(sec_url)
        written += 1

        if written % 50 == 0:
            log.info("title=%d sections_written=%d", title_n, written)

    return written


def run(titles: list[int], dry_run: bool = False) -> None:
    total = 0
    for t in titles:
        name = TARGET_TITLES.get(t, f"Title {t}")
        log.info("starting title=%d name=%s", t, name)
        n = fetch_title(t, dry_run=dry_run)
        log.info("finished title=%d sections=%d", t, n)
        total += n
        if not dry_run and t != titles[-1]:
            time.sleep(SESSION_SLEEP * 2)

    log.info("corpus_expansion_complete total_sections=%d", total)
    print(f"\nOCGA expansion complete: {total} sections across {len(titles)} titles")
    print(f"Output: {OUT_ROOT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", type=int, help="Single title number")
    parser.add_argument("--titles", default="all", help="Comma-separated titles or 'all'")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.title:
        target = [args.title]
    elif args.titles == "all":
        target = sorted(TARGET_TITLES.keys())
    else:
        target = [int(x) for x in args.titles.split(",")]

    run(target, dry_run=args.dry_run)
