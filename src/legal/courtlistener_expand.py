#!/usr/bin/env python3
"""
CourtListener expanded corpus acquisition.
Fetches additional GA opinions using broader civil law keywords,
deduplicating against the existing opinions-full.jsonl corpus.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("COURTLISTENER_API_TOKEN", "")
BASE_URL = "https://www.courtlistener.com/api/rest/v4"
GA_COURTS = ["gactapp", "ga"]
DATE_AFTER = "2015-01-01"
DATE_BEFORE = "2026-04-01"
RATE_LIMIT = 0.5  # seconds between API calls
MAX_PER_GROUP = 100  # max new opinions per keyword group
MAX_TOTAL = 300

EXISTING_CORPUS = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-full.jsonl")
OUTPUT_FILE = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-expanded.jsonl")

LOG_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M")
LOG_FILE = Path(f"/home/admin/Fortress-Prime/logs/cl_expand_{LOG_TIMESTAMP}.log")

KEYWORD_GROUPS = [
    {
        "name": "contract_breach",
        "query": "contract breach damages",
    },
    {
        "name": "civil_procedure_ocga9",
        "query": "O.C.G.A. § 9",
    },
    {
        "name": "landlord_tenant_property",
        "query": "landlord tenant real property",
    },
    {
        "name": "negligence_tort",
        "query": "negligence tort damages",
    },
]

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_log_fh = open(LOG_FILE, "w", buffering=1, encoding="utf-8")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_fh.write(line + "\n")


# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(url: str, params: dict = None) -> dict | None:
    """Make an authenticated GET to CourtListener API. Returns parsed JSON or None."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {API_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "FortressPrime-LegalCorpus/1.0 (research)",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log(f"  HTTP {e.code} from {url}: {body[:300]}")
        return None
    except Exception as e:
        log(f"  Request error for {url}: {e}")
        return None


def fetch_opinion_text(opinion_id: str) -> tuple[str, str]:
    """Fetch plain_text and html_with_citations for an opinion. Returns (plain_text, html)."""
    url = f"{BASE_URL}/opinions/{opinion_id}/"
    data = api_get(url)
    time.sleep(RATE_LIMIT)
    if not data:
        return "", ""
    plain_text = data.get("plain_text", "") or data.get("html_lawbox", "") or ""
    html = data.get("html_with_citations", "") or data.get("html", "") or ""
    return plain_text, html


def search_opinions(query: str, court: str, page: int = 1) -> dict | None:
    """Search CourtListener opinions endpoint."""
    params = {
        "q": query,
        "court": court,
        "filed_after": DATE_AFTER,
        "filed_before": DATE_BEFORE,
        "order_by": "score desc",
        "page": page,
        "page_size": 20,
        "type": "o",  # opinions
    }
    url = f"{BASE_URL}/search/"
    return api_get(url, params)


# ── Load existing corpus cluster IDs ─────────────────────────────────────────

def load_existing_cluster_ids() -> set:
    log(f"Loading existing cluster IDs from {EXISTING_CORPUS}")
    ids = set()
    if not EXISTING_CORPUS.exists():
        log("  Existing corpus file not found — starting fresh")
        return ids
    try:
        with open(EXISTING_CORPUS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid = str(rec.get("cluster_id", "")).strip()
                    if cid:
                        ids.add(cid)
                except Exception:
                    pass
    except Exception as e:
        log(f"  Error reading existing corpus: {e}")
    log(f"  Loaded {len(ids)} existing cluster IDs")
    return ids


# ── Also load IDs already in expanded output (if resuming) ───────────────────

def load_expanded_cluster_ids() -> set:
    ids = set()
    if not OUTPUT_FILE.exists():
        return ids
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid = str(rec.get("cluster_id", "")).strip()
                    if cid:
                        ids.add(cid)
                except Exception:
                    pass
    except Exception as e:
        log(f"  Error reading expanded file: {e}")
    log(f"  {len(ids)} cluster IDs already in expanded output")
    return ids


# ── Extract cluster ID from search result ─────────────────────────────────────

def extract_cluster_id(result: dict) -> str:
    """Extract cluster_id from a search result item."""
    # CourtListener search results have a 'cluster_id' field or we parse from URL
    if "cluster_id" in result:
        return str(result["cluster_id"])
    # Sometimes it's in the 'absolute_url' or 'cluster' field
    cluster = result.get("cluster", "")
    if cluster:
        # URL like /api/rest/v4/clusters/12345/
        m = __import__("re").search(r"/clusters/(\d+)/", str(cluster))
        if m:
            return m.group(1)
    # Try 'id' field
    if "id" in result:
        return str(result["id"])
    return ""


def extract_opinion_id(result: dict) -> str:
    """Extract opinion_id from a search result item."""
    if "id" in result:
        return str(result["id"])
    return ""


def build_record(result: dict, plain_text: str, html: str, group_name: str) -> dict:
    """Build a standardized opinion record from search result + fetched text."""
    fetched_at = datetime.now(timezone.utc).isoformat()

    cluster_id = extract_cluster_id(result)
    opinion_id = extract_opinion_id(result)

    case_name = result.get("caseName", "") or result.get("case_name", "") or ""
    court = result.get("court_id", "") or result.get("court", "") or ""
    date_filed = result.get("dateFiled", "") or result.get("date_filed", "") or ""
    citation = ""
    citations = result.get("citation", []) or result.get("citations", [])
    if isinstance(citations, list) and citations:
        citation = citations[0]
    elif isinstance(citations, str):
        citation = citations

    return {
        "cluster_id": cluster_id,
        "opinion_id": opinion_id,
        "case_name": case_name,
        "court": court,
        "date_filed": date_filed,
        "citation": citation,
        "plain_text": plain_text,
        "html_with_citations": html,
        "plain_text_chars": len(plain_text),
        "fetched_at": fetched_at,
        "keyword_group": group_name,
    }


# ── Main fetch loop ───────────────────────────────────────────────────────────

def fetch_group(group: dict, existing_ids: set, seen_ids: set, outfile, total_fetched: int) -> int:
    """Fetch up to MAX_PER_GROUP new opinions for a keyword group. Returns count fetched."""
    group_name = group["name"]
    query = group["query"]
    log(f"\n--- Group: {group_name} | Query: '{query}' ---")

    group_count = 0
    page = 1

    while group_count < MAX_PER_GROUP and total_fetched < MAX_TOTAL:
        log(f"  Page {page} | group={group_count}/{MAX_PER_GROUP} total={total_fetched}/{MAX_TOTAL}")

        page_results = []
        for court in GA_COURTS:
            time.sleep(RATE_LIMIT)
            data = search_opinions(query, court, page)
            if not data:
                log(f"    No data returned for court={court} page={page}")
                continue
            results = data.get("results", [])
            log(f"    court={court}: {len(results)} results (count={data.get('count', '?')})")
            page_results.extend(results)

        if not page_results:
            log(f"  No results on page {page}, stopping group")
            break

        new_this_page = 0
        for result in page_results:
            if total_fetched >= MAX_TOTAL or group_count >= MAX_PER_GROUP:
                break

            cluster_id = extract_cluster_id(result)
            if not cluster_id:
                log(f"    [SKIP] Could not extract cluster_id from result")
                continue

            if cluster_id in existing_ids or cluster_id in seen_ids:
                continue

            opinion_id = extract_opinion_id(result)
            log(f"    [FETCH] cluster={cluster_id} opinion={opinion_id} | {result.get('caseName', '')[:60]}")

            # Fetch full text
            plain_text, html = fetch_opinion_text(opinion_id) if opinion_id else ("", "")

            record = build_record(result, plain_text, html, group_name)
            outfile.write(json.dumps(record, ensure_ascii=False) + "\n")
            outfile.flush()

            seen_ids.add(cluster_id)
            group_count += 1
            total_fetched += 1
            new_this_page += 1

            if total_fetched % 25 == 0:
                log(f"  *** Progress: {total_fetched} total opinions fetched so far ***")

        log(f"  Page {page}: {new_this_page} new opinions added")
        if new_this_page == 0:
            log(f"  No new opinions on page {page}, moving to next group")
            break

        page += 1
        time.sleep(RATE_LIMIT)

    log(f"  Group '{group_name}' complete: {group_count} new opinions")
    return group_count


def main():
    log(f"CourtListener Expand starting at {datetime.now().isoformat()}")
    log(f"Output: {OUTPUT_FILE}")
    log(f"Log: {LOG_FILE}")

    existing_ids = load_existing_cluster_ids()
    seen_ids = load_expanded_cluster_ids()
    all_seen = existing_ids | seen_ids

    # Open output file in append mode
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    total_fetched = 0
    group_results = {}

    with open(OUTPUT_FILE, "a", encoding="utf-8", buffering=1) as outfile:
        for group in KEYWORD_GROUPS:
            if total_fetched >= MAX_TOTAL:
                log(f"Reached MAX_TOTAL={MAX_TOTAL}, stopping")
                break
            count = fetch_group(group, existing_ids, seen_ids, outfile, total_fetched)
            group_results[group["name"]] = count
            total_fetched += count
            log(f"Running total: {total_fetched} new opinions")
            time.sleep(1)

    log(f"\n{'='*60}")
    log(f"FINAL SUMMARY:")
    for name, count in group_results.items():
        log(f"  {name}: {count} new opinions")
    log(f"  TOTAL NEW OPINIONS: {total_fetched}")
    log(f"  Output file: {OUTPUT_FILE}")
    log(f"  Log file: {LOG_FILE}")

    # Count lines in output
    try:
        total_lines = sum(1 for _ in open(OUTPUT_FILE))
        log(f"  Total lines in expanded file: {total_lines}")
    except Exception:
        pass

    _log_fh.close()


if __name__ == "__main__":
    main()
