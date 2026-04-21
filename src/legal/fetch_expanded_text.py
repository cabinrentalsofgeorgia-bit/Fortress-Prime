#!/usr/bin/env python3
import os
"""
fetch_expanded_text.py — Fetch full text for expanded CourtListener opinions
and paginate to find more unique ones.

Fixes:
1. Fetches text for 138 existing records using cluster→opinion lookup
2. Continues searching with pagination to find more unique opinions

Usage:
  python -m src.legal.fetch_expanded_text [--max-new N]
"""
from __future__ import annotations
import json, sys, time, re, logging
import urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"fetch_expanded"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("fetch_expanded")

API_TOKEN   = os.getenv("COURTLISTENER_API_TOKEN", "")
BASE_URL    = "https://www.courtlistener.com/api/rest/v4"
RATE_SLEEP  = 0.5
PAGE_SLEEP  = 1.5

EXISTING    = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-full.jsonl")
EXPANDED    = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-expanded.jsonl")

QUERIES = [
    ("contract_breach", "contract breach damages", ["gactapp", "ga"]),
    ("civil_procedure", "summary judgment civil practice", ["gactapp", "ga"]),
    ("landlord_tenant", "landlord tenant", ["gactapp", "ga"]),
    ("tort_negligence", "negligence duty of care", ["gactapp", "ga"]),
    ("property_dispute", "real property title deed", ["gactapp", "ga"]),
]

DATE_AFTER  = "2015-01-01"
DATE_BEFORE = "2026-04-01"


def api_get(url: str, params: dict | None = None) -> dict | None:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Token {API_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "FortressPrime-LegalCorpus/1.0 (research)",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            if attempt == 2:
                log.warning("api_get_failed url=%s error=%s", url[:80], exc)
                return None
            time.sleep(2 ** attempt)
    return None


def fetch_text_for_cluster(cluster_id: str) -> tuple[str, str]:
    """Get plain_text + html for a cluster via opinions endpoint."""
    url = f"{BASE_URL}/opinions/"
    data = api_get(url, {"cluster": cluster_id, "format": "json"})
    time.sleep(RATE_SLEEP)
    if not data:
        return "", ""
    results = data.get("results", [])
    if not results:
        return "", ""
    op = results[0]
    plain = op.get("plain_text", "") or ""
    html  = op.get("html_with_citations", "") or op.get("html", "") or ""
    return plain, html


def load_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.exists():
        return ids
    with open(path) as f:
        for l in f:
            if l.strip():
                try:
                    ids.add(str(json.loads(l).get("cluster_id", "")))
                except Exception:
                    pass
    return ids


def backfill_text(max_backfill: int = 200) -> int:
    """Fetch text for existing expanded records that have no text."""
    if not EXPANDED.exists():
        return 0
    records = [json.loads(l) for l in EXPANDED.open() if l.strip()]
    need_text = [r for r in records if not r.get("plain_text")]
    log.info("backfilling text for %d records", min(len(need_text), max_backfill))

    updated = 0
    records_by_cluster = {r["cluster_id"]: r for r in records}

    for rec in need_text[:max_backfill]:
        cluster = rec.get("cluster_id", "")
        if not cluster:
            continue
        plain, html = fetch_text_for_cluster(cluster)
        if plain:
            rec["plain_text"] = plain
            rec["html_with_citations"] = html[:50_000] if html else ""
            rec["plain_text_chars"] = len(plain)
            updated += 1
        else:
            rec["plain_text"] = ""
            rec["html_with_citations"] = ""
            rec["plain_text_chars"] = 0

    # Rewrite expanded file with updated text
    with EXPANDED.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log.info("backfill_complete updated=%d", updated)
    return updated


def fetch_more(max_new: int = 200) -> int:
    existing_ids = load_ids(EXISTING)
    expanded_ids = load_ids(EXPANDED)
    all_known = existing_ids | expanded_ids
    log.info("known_ids existing=%d expanded=%d", len(existing_ids), len(expanded_ids))

    fetched = 0
    out_fh = EXPANDED.open("a", encoding="utf-8")

    for group_name, query, courts in QUERIES:
        if fetched >= max_new:
            break
        log.info("group=%s query=%s", group_name, query)

        for page in range(1, 20):  # up to 20 pages
            if fetched >= max_new:
                break

            page_new = 0
            for court in courts:
                params = {
                    "q": query, "court": court,
                    "filed_after": DATE_AFTER, "filed_before": DATE_BEFORE,
                    "order_by": "score desc", "page": page, "page_size": 20,
                    "type": "o",
                }
                data = api_get(f"{BASE_URL}/search/", params)
                time.sleep(RATE_SLEEP)
                if not data:
                    continue

                for result in data.get("results", []):
                    if fetched >= max_new:
                        break
                    # Extract cluster_id from search result
                    cluster = str(result.get("cluster_id", ""))
                    if not cluster:
                        # Try parsing from cluster URL
                        m = re.search(r"/clusters/(\d+)/", str(result.get("cluster", "")))
                        cluster = m.group(1) if m else ""
                    if not cluster or cluster in all_known:
                        continue

                    # Fetch text via cluster
                    plain, html = fetch_text_for_cluster(cluster)
                    if not plain:
                        # Still add metadata-only for future backfill
                        pass

                    case_name = result.get("caseName", result.get("case_name", ""))
                    record = {
                        "cluster_id": cluster,
                        "opinion_id": "",
                        "case_name": case_name,
                        "court": result.get("court_id", court),
                        "date_filed": result.get("dateFiled", result.get("date_filed", "")),
                        "citation": "",
                        "plain_text": plain,
                        "html_with_citations": html[:50_000] if html else "",
                        "plain_text_chars": len(plain),
                        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
                        "keyword_group": group_name,
                    }
                    out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out_fh.flush()
                    all_known.add(cluster)
                    fetched += 1
                    page_new += 1
                    log.info("fetched cluster=%s case=%s text_chars=%d group=%s",
                             cluster, case_name[:50], len(plain), group_name)

            if page_new == 0 and page > 1:
                log.info("no_new_on_page page=%d group=%s stopping", page, group_name)
                break
            time.sleep(PAGE_SLEEP)

    out_fh.close()
    log.info("fetch_more_complete fetched=%d", fetched)
    return fetched


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-new", type=int, default=200)
    p.add_argument("--no-backfill", action="store_true")
    args = p.parse_args()

    if not args.no_backfill:
        log.info("step1: backfill text for existing 138 records")
        n = backfill_text()
        log.info("backfilled %d records", n)

    log.info("step2: fetch more opinions")
    n2 = fetch_more(max_new=args.max_new)
    log.info("step2_done fetched=%d", n2)

    # Summary
    all_recs = [json.loads(l) for l in EXPANDED.open() if l.strip()]
    with_text = sum(1 for r in all_recs if r.get("plain_text_chars", 0) > 100)
    print(f"\nExpanded corpus: {len(all_recs)} records, {with_text} with text")
