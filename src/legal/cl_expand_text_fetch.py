#!/usr/bin/env python3
"""
Second-pass text fetcher for opinions-expanded.jsonl.
For each record with no opinion text, fetch the cluster details to get the
primary opinion ID, then fetch the opinion text.
Updates the records in-place.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

API_TOKEN = "1e8f8581c60a9cf6357dafcdc0c0ee8aa62b0c92"
BASE_URL = "https://www.courtlistener.com/api/rest/v4"
RATE_LIMIT = 0.5

INPUT_FILE = Path("/mnt/fortress_nas/legal-corpus/courtlistener/opinions-expanded.jsonl")
LOG_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M")
LOG_FILE = Path(f"/home/admin/Fortress-Prime/logs/cl_expand_text_{LOG_TIMESTAMP}.log")

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_log_fh = open(LOG_FILE, "w", buffering=1)


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_fh.write(line + "\n")


def api_get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {API_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "FortressPrime-LegalCorpus/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log(f"  HTTP {e.code}: {body[:200]}")
        return None
    except Exception as e:
        log(f"  Error: {e}")
        return None


def fetch_cluster(cluster_id):
    """Fetch cluster details to get list of opinions."""
    url = f"{BASE_URL}/clusters/{cluster_id}/"
    return api_get(url)


def fetch_opinion(opinion_id):
    """Fetch opinion text."""
    url = f"{BASE_URL}/opinions/{opinion_id}/"
    return api_get(url)


def main():
    log(f"Text fetch pass starting at {datetime.now().isoformat()}")

    # Load all records
    records = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    log(f"Loaded {len(records)} records")

    needs_text = [i for i, r in enumerate(records) if r.get("plain_text_chars", 0) == 0]
    log(f"Records needing text: {len(needs_text)}")

    updated = 0
    failed = 0

    for idx, rec_idx in enumerate(needs_text):
        rec = records[rec_idx]
        cluster_id = rec.get("cluster_id", "")
        if not cluster_id:
            continue

        if idx % 25 == 0 and idx > 0:
            log(f"*** Progress: {idx}/{len(needs_text)} processed, {updated} updated, {failed} failed ***")

        # Fetch cluster to get opinion IDs
        time.sleep(RATE_LIMIT)
        cluster_data = fetch_cluster(cluster_id)
        if not cluster_data:
            log(f"  [{idx}] Failed to fetch cluster {cluster_id}")
            failed += 1
            continue

        # Extract opinion URLs from cluster
        # Cluster has 'sub_opinions' list with opinion URLs
        sub_opinions = cluster_data.get("sub_opinions", [])
        if not sub_opinions:
            # Try 'opinions' field
            sub_opinions = cluster_data.get("opinions", [])

        if not sub_opinions:
            log(f"  [{idx}] No opinions in cluster {cluster_id}")
            failed += 1
            continue

        # Get first (primary) opinion
        opinion_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else sub_opinions[0].get("resource_uri", "")
        # Extract ID from URL like /api/rest/v4/opinions/12345/
        import re
        m = re.search(r"/opinions/(\d+)/", opinion_url)
        if not m:
            log(f"  [{idx}] Cannot extract opinion ID from {opinion_url}")
            failed += 1
            continue

        opinion_id = m.group(1)
        rec["opinion_id"] = opinion_id

        # Fetch opinion text
        time.sleep(RATE_LIMIT)
        opinion_data = fetch_opinion(opinion_id)
        if not opinion_data:
            log(f"  [{idx}] Failed to fetch opinion {opinion_id}")
            failed += 1
            continue

        plain_text = (opinion_data.get("plain_text", "") or
                      opinion_data.get("html_lawbox", "") or
                      opinion_data.get("html_columbia", "") or
                      "")
        html = opinion_data.get("html_with_citations", "") or opinion_data.get("html", "") or ""

        rec["plain_text"] = plain_text
        rec["html_with_citations"] = html
        rec["plain_text_chars"] = len(plain_text)
        rec["fetched_at"] = datetime.now(timezone.utc).isoformat()

        updated += 1

        # Extract case metadata from cluster if missing
        if not rec.get("case_name"):
            rec["case_name"] = cluster_data.get("case_name", "")
        if not rec.get("date_filed"):
            rec["date_filed"] = cluster_data.get("date_filed", "")
        if not rec.get("citation"):
            citations = cluster_data.get("citations", [])
            if citations:
                cite = citations[0]
                if isinstance(cite, dict):
                    rec["citation"] = f"{cite.get('volume','')} {cite.get('reporter','')} {cite.get('page','')}".strip()
                else:
                    rec["citation"] = str(cite)

        log(f"  [{idx}] OK cluster={cluster_id} opinion={opinion_id} chars={len(plain_text)} case={rec.get('case_name','')[:50]}")

    log(f"\nDone: {updated} updated, {failed} failed out of {len(needs_text)} attempted")

    # Write updated records back
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log(f"Wrote {len(records)} records back to {INPUT_FILE}")

    # Summary stats
    with_text = sum(1 for r in records if r.get("plain_text_chars", 0) > 0)
    log(f"Records with text: {with_text}/{len(records)}")

    _log_fh.close()


if __name__ == "__main__":
    main()
