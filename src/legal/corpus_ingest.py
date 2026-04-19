#!/usr/bin/env python3
"""
corpus_ingest.py — Phase 4d Part 1: Georgia insurance defense corpus acquisition.

Downloads and filters public legal data from:
  1. CourtListener bulk data — Georgia appellate court opinions, insurance-filtered
  2. OCGA Title 33 — Georgia Insurance Code (via Justia mirror)

No training data is prepared here — that is Phase 4d Part 2.

Usage:
  python -m src.legal.corpus_ingest courtlistener-bulk [--court COURTS] [--filter FILTER]
  python -m src.legal.corpus_ingest ocga [--title N] [--dry-run]
  python -m src.legal.corpus_ingest verify

  COURTS   Comma-separated CourtListener court IDs (default: ga,gactapp)
  FILTER   Keyword filter preset (default: insurance)

Environment (read from .env.legal — not committed):
  COURTLISTENER_API_TOKEN  Optional; only needed for future API queries.
                           Bulk downloads are anonymous and do NOT require it.

Storage:
  /mnt/fortress_nas/legal-corpus/
  ├── courtlistener/raw/          Downloaded CSVs, gzip-compressed, unmodified
  ├── courtlistener/filtered/     Our filtered outputs (Georgia insurance cases, JSON-L)
  ├── courtlistener/manifest.json Download manifest (pulled_at, sha256, row counts)
  ├── ocga/raw/                   Raw HTML/text fetched from Justia
  ├── ocga/title-33/              Parsed OCGA Title 33 sections (JSON)
  └── README.md                   Licensing and provenance notes

SAFETY:
  - Corpus data stays on NAS only — never committed to the repo.
  - CourtListener opinions are public domain (court opinions).
  - OCGA is published law — public domain.
  - OCGA scraper sleeps between requests; respects rate limits.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import urllib.request

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("corpus_ingest")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CORPUS_ROOT = Path(os.getenv("LEGAL_CORPUS_ROOT", "/mnt/fortress_nas/legal-corpus"))

COURTLISTENER_BULK_BASE = "https://storage.courtlistener.com/bulk-data/"

# Georgia court IDs on CourtListener
GEORGIA_COURTS = ["ga", "gactapp"]

# Insurance-defense relevant keywords (case-insensitive substring match on case name / plain text)
INSURANCE_KEYWORDS: frozenset[str] = frozenset({
    "insurance", "insurer", "insured", "coverage", "policy", "policyholder",
    "subrogation", "bad faith", "bad-faith", "first-party", "third-party",
    "liability", "underwriting", "premium", "claim", "adjuster", "denial",
    "exclusion", "indemnity", "indemnification", "duty to defend",
    "duty to indemnify", "uninsured", "underinsured", "uim", "um/uim",
    "homeowner", "auto insurance", "medical payments", "collision",
    "comprehensive coverage", "property damage",
})

YEAR_MIN = 2010
YEAR_MAX = 2026

# Justia OCGA mirror
OCGA_JUSTIA_BASE = "https://law.justia.com/codes/georgia/"
OCGA_RATE_LIMIT_SLEEP = 2.5  # seconds between Justia requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_dotenv_legal() -> None:
    """Load .env.legal from repo root if present (COURTLISTENER_API_TOKEN etc.)."""
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env.legal"
    if not env_path.exists():
        log.debug(".env.legal not found — bulk downloads don't need a token.")
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    log.debug(".env.legal loaded")


def _http_get(url: str, dest: Path, desc: str = "") -> bool:
    """Download url → dest. Returns True if downloaded, False if skipped (already exists)."""
    if dest.exists():
        log.info("skip_existing file=%s", dest.name)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("download url=%s dest=%s %s", url, dest, desc)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FortressPrime-LegalCorpus/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        dest.write_bytes(data)
        log.info("downloaded bytes=%d sha256=%s", len(data), hashlib.sha256(data).hexdigest()[:12])
        return True
    except Exception as exc:
        log.error("download_failed url=%s error=%s", url, exc)
        raise


def _is_insurance_relevant(text: str) -> bool:
    """Return True if text contains any insurance-defense keyword."""
    lower = text.lower()
    return any(kw in lower for kw in INSURANCE_KEYWORDS)


def _year_in_range(date_str: str) -> bool:
    """Return True if the year in an ISO date string is in [YEAR_MIN, YEAR_MAX]."""
    if not date_str:
        return False
    try:
        year = int(date_str[:4])
        return YEAR_MIN <= year <= YEAR_MAX
    except (ValueError, IndexError):
        return False


# ---------------------------------------------------------------------------
# Sub-command: courtlistener-bulk
# ---------------------------------------------------------------------------

def cmd_courtlistener_bulk(courts: list[str], filter_preset: str) -> None:
    """
    Download CourtListener bulk CSV files for Georgia courts and filter for
    insurance-defense relevant opinions.

    Bulk data manifest: https://www.courtlistener.com/help/api/bulk-data/
    Files are gzip-compressed CSVs updated monthly.
    """
    _load_dotenv_legal()
    raw_dir = CORPUS_ROOT / "courtlistener" / "raw"
    filtered_dir = CORPUS_ROOT / "courtlistener" / "filtered"
    raw_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    log.info("courtlistener_bulk courts=%s filter=%s", courts, filter_preset)

    manifest_path = CORPUS_ROOT / "courtlistener" / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    pulled_at = datetime.now(tz=timezone.utc).isoformat()
    total_filtered = 0

    for court in courts:
        log.info("processing court=%s", court)
        court_manifest: dict[str, Any] = manifest.get(court, {})

        # CourtListener bulk files are at:
        # https://storage.courtlistener.com/bulk-data/opinions/{court}.csv.gz
        # https://storage.courtlistener.com/bulk-data/clusters/{court}.csv.gz
        # https://storage.courtlistener.com/bulk-data/dockets/{court}.csv.gz
        for file_type in ("opinions", "clusters"):
            fname = f"{court}.csv.gz"
            url = f"{COURTLISTENER_BULK_BASE}{file_type}/{fname}"
            dest = raw_dir / file_type / fname
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                downloaded = _http_get(url, dest, desc=f"{file_type}/{court}")
                sha = _sha256_file(dest)
                court_manifest[file_type] = {
                    "file": str(dest.relative_to(CORPUS_ROOT)),
                    "sha256": sha,
                    "pulled_at": pulled_at if downloaded else court_manifest.get(file_type, {}).get("pulled_at"),
                    "url": url,
                }
            except Exception:
                log.warning("skipping %s/%s — will retry next run", file_type, court)
                continue

        # Filter opinions for insurance-defense relevance
        opinions_gz = raw_dir / "opinions" / f"{court}.csv.gz"
        if not opinions_gz.exists():
            log.warning("opinions file missing for court=%s — run again after download", court)
            continue

        filtered_out = filtered_dir / f"{court}_insurance_filtered.jsonl"
        if filtered_out.exists():
            log.info("filtered output already exists court=%s — skipping filter step", court)
            total_filtered += sum(1 for _ in filtered_out.open())
            continue

        log.info("filtering opinions court=%s", court)
        count_total = 0
        count_matched = 0

        with gzip.open(opinions_gz, "rt", encoding="utf-8", errors="replace") as gf, \
             filtered_out.open("w", encoding="utf-8") as out:
            reader = csv.DictReader(gf)
            for row in reader:
                count_total += 1
                if count_total % 100 == 0:
                    log.info("progress court=%s total=%d matched=%d", court, count_total, count_matched)

                # Date filter
                date_filed = row.get("date_filed") or row.get("date_created") or ""
                if not _year_in_range(date_filed):
                    continue

                # Insurance keyword filter across name fields and plain text snippet
                searchable = " ".join([
                    row.get("case_name", ""),
                    row.get("case_name_short", ""),
                    row.get("plain_text", "")[:2000],  # limit search window
                    row.get("html_with_citations", "")[:500],
                ])
                if not _is_insurance_relevant(searchable):
                    continue

                count_matched += 1
                json.dump({
                    "court": court,
                    "cluster_id": row.get("cluster_id"),
                    "case_name": row.get("case_name"),
                    "date_filed": date_filed,
                    "download_url": row.get("download_url"),
                    "plain_text_snippet": row.get("plain_text", "")[:500],
                }, out)
                out.write("\n")

        log.info(
            "filter_complete court=%s total_rows=%d matched=%d rate=%.1f%%",
            court, count_total, count_matched,
            (100 * count_matched / count_total) if count_total else 0,
        )
        court_manifest["filtered"] = {
            "file": str(filtered_out.relative_to(CORPUS_ROOT)),
            "rows": count_matched,
            "total_scanned": count_total,
            "filtered_at": pulled_at,
        }
        total_filtered += count_matched
        manifest[court] = court_manifest

    manifest["_meta"] = {"last_run": pulled_at, "total_filtered_rows": total_filtered}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("courtlistener_bulk_complete total_filtered=%d manifest=%s", total_filtered, manifest_path)


# ---------------------------------------------------------------------------
# Sub-command: ocga
# ---------------------------------------------------------------------------

def cmd_ocga(title: int, dry_run: bool = False) -> None:
    """
    Scrape OCGA Title {title} from Justia's Georgia Code mirror.

    Justia publishes OCGA openly. We scrape with polite rate limiting.
    Georgia law is public domain.

    Output: /mnt/fortress_nas/legal-corpus/ocga/title-{title}/<section>.json
    """
    raw_dir = CORPUS_ROOT / "ocga" / "raw" / f"title-{title}"
    out_dir = CORPUS_ROOT / "ocga" / f"title-{title}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("ocga_ingest title=%d dry_run=%s", title, dry_run)

    # Step 1: fetch the title index page to discover chapters
    title_url = f"{OCGA_JUSTIA_BASE}title-{title}/"
    index_raw = raw_dir / "index.html"

    if not index_raw.exists():
        if dry_run:
            log.info("[DRY RUN] would fetch: %s", title_url)
            return
        log.info("fetching title index url=%s", title_url)
        req = urllib.request.Request(title_url, headers={"User-Agent": "FortressPrime-LegalCorpus/1.0 (research)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        index_raw.write_text(html)
        time.sleep(OCGA_RATE_LIMIT_SLEEP)
    else:
        html = index_raw.read_text()

    # Parse chapter links from the index
    chapter_links: list[str] = re.findall(
        rf'href="(/codes/georgia/title-{title}/chapter-[^"]+/)"',
        html,
    )
    chapter_links = list(dict.fromkeys(chapter_links))  # dedupe, preserve order
    log.info("found chapters=%d for title=%d", len(chapter_links), title)

    sections_saved = 0
    for chap_path in chapter_links:
        chap_url = urljoin("https://law.justia.com", chap_path)
        chap_slug = chap_path.strip("/").split("/")[-1]
        chap_raw = raw_dir / f"{chap_slug}.html"

        if not chap_raw.exists():
            if dry_run:
                log.info("[DRY RUN] would fetch chapter: %s", chap_url)
                continue
            log.info("fetching chapter=%s", chap_slug)
            req = urllib.request.Request(chap_url, headers={"User-Agent": "FortressPrime-LegalCorpus/1.0 (research)"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    chap_html = resp.read().decode("utf-8", errors="replace")
                chap_raw.write_text(chap_html)
            except Exception as exc:
                log.warning("chapter_fetch_failed chap=%s error=%s", chap_slug, exc)
                continue
            time.sleep(OCGA_RATE_LIMIT_SLEEP)
        else:
            chap_html = chap_raw.read_text()

        # Parse section links within chapter
        section_links: list[str] = re.findall(
            rf'href="(/codes/georgia/title-{title}/chapter-[^"]+/section-[^"]+/)"',
            chap_html,
        )
        section_links = list(dict.fromkeys(section_links))

        for sec_path in section_links:
            sec_url = urljoin("https://law.justia.com", sec_path)
            # Extract section number from path like /codes/georgia/title-33/chapter-5/section-33-5-1/
            sec_slug = sec_path.strip("/").split("/")[-1]  # e.g. section-33-5-1
            sec_num = sec_slug.replace("section-", "")     # e.g. 33-5-1
            sec_raw = raw_dir / f"{sec_slug}.html"
            sec_out = out_dir / f"{sec_num}.json"

            if sec_out.exists():
                sections_saved += 1
                continue  # idempotent

            if not sec_raw.exists():
                if dry_run:
                    log.info("[DRY RUN] would fetch section: %s", sec_url)
                    continue
                log.info("fetching section=%s", sec_num)
                req = urllib.request.Request(sec_url, headers={"User-Agent": "FortressPrime-LegalCorpus/1.0 (research)"})
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        sec_html = resp.read().decode("utf-8", errors="replace")
                    sec_raw.write_text(sec_html)
                except Exception as exc:
                    log.warning("section_fetch_failed sec=%s error=%s", sec_num, exc)
                    continue
                time.sleep(OCGA_RATE_LIMIT_SLEEP)
            else:
                sec_html = sec_raw.read_text()

            # Extract section title and text via simple regex
            title_match = re.search(r'<h1[^>]*>(.*?)</h1>', sec_html, re.DOTALL)
            sec_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""

            # Extract main content — Justia wraps in <div class="has-text-primary">
            content_match = re.search(
                r'<div[^>]*class="[^"]*has-text-primary[^"]*"[^>]*>(.*?)</div>',
                sec_html, re.DOTALL
            )
            if not content_match:
                content_match = re.search(r'<div id="codes-content"[^>]*>(.*?)</div>', sec_html, re.DOTALL)
            raw_text = ""
            if content_match:
                raw_text = re.sub(r'<[^>]+>', ' ', content_match.group(1))
                raw_text = re.sub(r'\s+', ' ', raw_text).strip()

            section_data = {
                "source": "ocga",
                "title": title,
                "section": sec_num,
                "heading": sec_title,
                "text": raw_text,
                "url": sec_url,
                "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            sec_out.write_text(json.dumps(section_data, ensure_ascii=False, indent=2))
            sections_saved += 1

            if sections_saved % 100 == 0:
                log.info("ocga_progress title=%d sections_saved=%d", title, sections_saved)

    log.info("ocga_complete title=%d sections_saved=%d out_dir=%s", title, sections_saved, out_dir)


# ---------------------------------------------------------------------------
# Sub-command: verify
# ---------------------------------------------------------------------------

def cmd_verify() -> None:
    """Report what corpus data is present on the NAS."""
    if not CORPUS_ROOT.exists():
        log.warning("corpus root does not exist: %s", CORPUS_ROOT)
        log.warning("Run 'courtlistener-bulk' or 'ocga' to populate it.")
        return

    def _dir_size(path: Path) -> tuple[float, str]:
        total: float = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        for unit in ("B", "KB", "MB", "GB"):
            if total < 1024:
                return total, f"{total:.1f} {unit}"
            total /= 1024
        return total, f"{total:.1f} TB"

    print("\n=== Legal Corpus Inventory ===")
    print(f"Root: {CORPUS_ROOT}\n")

    # CourtListener
    cl_dir = CORPUS_ROOT / "courtlistener"
    manifest_path = cl_dir / "manifest.json"
    if cl_dir.exists():
        raw_files = list((cl_dir / "raw").rglob("*.gz")) if (cl_dir / "raw").exists() else []
        filtered_files = list((cl_dir / "filtered").rglob("*.jsonl")) if (cl_dir / "filtered").exists() else []
        _, size = _dir_size(cl_dir)
        print(f"CourtListener:  {size}")
        print(f"  raw CSVs:     {len(raw_files)} files")
        if filtered_files:
            total_rows = sum(sum(1 for _ in f.open()) for f in filtered_files)
            print(f"  filtered:     {len(filtered_files)} files, ~{total_rows:,} Georgia insurance opinions")
        if manifest_path.exists():
            meta = json.loads(manifest_path.read_text()).get("_meta", {})
            print(f"  last_run:     {meta.get('last_run', 'unknown')}")
    else:
        print("CourtListener:  not yet acquired")

    # OCGA
    ocga_dir = CORPUS_ROOT / "ocga"
    if ocga_dir.exists():
        _, size = _dir_size(ocga_dir)
        titles = [d for d in ocga_dir.iterdir() if d.is_dir() and d.name.startswith("title-")]
        print(f"\nOCGA:           {size}")
        for t in sorted(titles):
            secs = list(t.rglob("*.json"))
            print(f"  {t.name}:  {len(secs)} sections")
    else:
        print("\nOCGA:           not yet acquired")

    print()


# ---------------------------------------------------------------------------
# NAS README
# ---------------------------------------------------------------------------

def _ensure_nas_readme() -> None:
    readme = CORPUS_ROOT / "README.md"
    if readme.exists():
        return
    CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    readme.write_text(
        "# Fortress Legal Corpus\n\n"
        "Public legal data staged for Georgia insurance defense judge training.\n\n"
        "## Sources\n\n"
        "### CourtListener\n"
        "- Provider: Free Law Project (https://free.law/)\n"
        "- Coverage: Georgia appellate courts (ga, gactapp)\n"
        "- Filter: Insurance-defense keywords, 2010–2026\n"
        "- License: Court opinions are public domain.\n"
        "  CourtListener data is CC-BY (attribution to Free Law Project).\n\n"
        "### OCGA Title 33\n"
        "- Provider: Georgia General Assembly (via Justia mirror)\n"
        "- Coverage: Georgia Insurance Code, all chapters\n"
        "- License: Published law — public domain.\n\n"
        "## Directory Layout\n\n"
        "```\n"
        "courtlistener/\n"
        "  raw/          Downloaded CSVs, gzip-compressed, unmodified\n"
        "  filtered/     Georgia insurance opinions (JSONL, one per line)\n"
        "  manifest.json Download manifest\n"
        "ocga/\n"
        "  raw/          Raw HTML fetched from Justia\n"
        "  title-33/     Parsed OCGA Title 33 sections (JSON)\n"
        "```\n\n"
        "## Usage\n\n"
        "```bash\n"
        "# From Fortress-Prime repo root:\n"
        "python -m src.legal.corpus_ingest courtlistener-bulk\n"
        "python -m src.legal.corpus_ingest ocga --title 33\n"
        "python -m src.legal.corpus_ingest verify\n"
        "```\n\n"
        "## Notes\n\n"
        "- This directory is NOT in the git repo. Code is in src/legal/.\n"
        "- Do not store client work product or privileged material here.\n"
        "- Training pair preparation is Phase 4d Part 2.\n"
    )
    log.info("created NAS README at %s", readme)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _ensure_nas_readme()

    parser = argparse.ArgumentParser(
        prog="python -m src.legal.corpus_ingest",
        description="Fortress legal corpus acquisition pipeline (Phase 4d Part 1)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # courtlistener-bulk
    cl = sub.add_parser("courtlistener-bulk", help="Download + filter CourtListener bulk CSVs")
    cl.add_argument("--court", default=",".join(GEORGIA_COURTS),
                    help=f"Comma-separated court IDs (default: {','.join(GEORGIA_COURTS)})")
    cl.add_argument("--filter", default="insurance",
                    help="Keyword filter preset: insurance (default)")

    # ocga
    og = sub.add_parser("ocga", help="Scrape OCGA from Justia mirror")
    og.add_argument("--title", type=int, default=33, help="OCGA title number (default: 33)")
    og.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched without downloading")

    # verify
    sub.add_parser("verify", help="Report corpus inventory on NAS")

    args = parser.parse_args()

    if args.cmd == "courtlistener-bulk":
        courts = [c.strip() for c in args.court.split(",") if c.strip()]
        cmd_courtlistener_bulk(courts, args.filter)
    elif args.cmd == "ocga":
        cmd_ocga(args.title, dry_run=args.dry_run)
    elif args.cmd == "verify":
        cmd_verify()

    return 0


if __name__ == "__main__":
    sys.exit(main())
