#!/usr/bin/env python3
"""
FORTRESS PRIME — Vendor Reclassification Sweep
=================================================
Re-processes all UNKNOWN vendors in finance.vendor_classifications
through the local Ollama cluster (qwen2.5:7b via Nginx LB).

Fixes the 384+ vendors that got 404 errors during the original batch
because AI nodes (Ocular/Sovereign) were offline.

Usage:
    cd /home/admin/Fortress-Prime
    ./venv/bin/python tools/vendor_reclassify.py

    # Dry-run (just prints what it would do):
    ./venv/bin/python tools/vendor_reclassify.py --dry-run
"""

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get_inference_url

# ─── Configuration ────────────────────────────────────────────────────────────

OLLAMA_URL = get_inference_url()
MODEL = "qwen2.5:7b"
BATCH_SIZE = 5   # Concurrent-ish, but we do them serially for DB safety
TIMEOUT = 60     # Per-vendor timeout

DB_CONFIG = {
    "dbname": "fortress_db",
    "user": "admin",
    # No host= → uses Unix domain socket with peer auth (matches OS user 'admin')
}

VALID_CLASSIFICATIONS = [
    "REAL_BUSINESS",
    "CONTRACTOR",
    "CROG_INTERNAL",
    "FAMILY_INTERNAL",
    "FINANCIAL_SERVICE",
    "PROFESSIONAL_SERVICE",
    "OPERATIONAL_EXPENSE",
    "GOVERNMENT",
    "NOISE",
    "UNKNOWN",
]

SYSTEM_PROMPT = """You are a forensic financial auditor classifying email senders/vendors for a small business called "Cabin Rentals of Georgia" (CROG), which is a vacation cabin rental company.

CROG LLC is 100% owned by **Gary M. Knight** (sole member). The Knight family: Gary M. Knight (Primary/Owner), Barbara Knight, Taylor Knight, Lissa Knight, Travis Knight, Amanda Knight, Gregg Knight, Joshua Knight.

Classify the vendor into EXACTLY ONE of these categories:
- REAL_BUSINESS: Legitimate business contact with significant transaction volume
- CONTRACTOR: Individual or company providing services (construction, cleaning, maintenance, repair)
- CROG_INTERNAL: Internal CROG operations (Airbnb, VRBO, booking platforms, property management software, internal transfers)
- FAMILY_INTERNAL: Knight family members or known family associates
- FINANCIAL_SERVICE: Banks, credit cards, payment processors, investment platforms
- PROFESSIONAL_SERVICE: Lawyers, accountants, CPAs, insurance agents
- OPERATIONAL_EXPENSE: SaaS tools, utilities, telecom, software subscriptions, office supplies, fuel
- GOVERNMENT: IRS, county/state agencies, tax authorities, permits
- NOISE: Newsletters, marketing emails, spam, social media notifications, noreply automated messages with no financial relevance
- UNKNOWN: Cannot determine with reasonable confidence

Respond with ONLY a JSON object in this exact format (no other text):
{"classification": "CATEGORY", "confidence": 0.85, "reasoning": "Brief explanation"}"""

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SWEEP] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sweep")

# ─── Core ─────────────────────────────────────────────────────────────────────

def classify_vendor(vendor_label: str, vendor_pattern: str, invoice_count: int, amount: float) -> dict:
    """Send a single vendor to Ollama for classification."""
    prompt = f"""Classify this vendor/email sender:

- Vendor: {vendor_label}
- Email pattern: {vendor_pattern}
- Invoice count: {invoice_count}
- Total extracted amount: ${amount:,.2f}

Remember: Respond with ONLY the JSON object."""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Parse JSON from response (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        classification = result.get("classification", "UNKNOWN").upper()

        # Validate
        if classification not in VALID_CLASSIFICATIONS:
            classification = "UNKNOWN"

        return {
            "classification": classification,
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", "No reasoning provided"),
        }

    except json.JSONDecodeError:
        # Try to extract classification from free text
        content_upper = content.upper() if 'content' in dir() else ""
        for cat in VALID_CLASSIFICATIONS:
            if cat in content_upper:
                return {"classification": cat, "confidence": 0.5, "reasoning": f"Extracted from free-text: {content[:100]}"}
        return {"classification": "UNKNOWN", "confidence": 0.0, "reasoning": f"JSON parse error: {content[:100] if 'content' in dir() else 'no response'}"}

    except requests.exceptions.Timeout:
        return {"classification": "UNKNOWN", "confidence": 0.0, "reasoning": "Ollama timeout (60s)"}

    except Exception as e:
        return {"classification": "UNKNOWN", "confidence": 0.0, "reasoning": f"Error: {str(e)[:100]}"}


def get_invoice_stats(cur, vendor_pattern: str) -> tuple:
    """Get invoice count and total amount for a vendor pattern."""
    try:
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM public.finance_invoices
            WHERE vendor LIKE %s
        """, (vendor_pattern,))
        row = cur.fetchone()
        return (row[0] or 0, float(row[1] or 0))
    except Exception:
        return (0, 0.0)


def main():
    parser = argparse.ArgumentParser(description="Re-classify UNKNOWN vendors via Ollama")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    parser.add_argument("--limit", type=int, default=0, help="Process only N vendors (0=all)")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch all UNKNOWNs
    cur.execute("""
        SELECT id, vendor_pattern, vendor_label, titan_notes
        FROM finance.vendor_classifications
        WHERE classification = 'UNKNOWN'
        ORDER BY id
    """)
    unknowns = cur.fetchall()

    total = len(unknowns)
    if args.limit > 0:
        unknowns = unknowns[:args.limit]

    log.info(f"{'DRY RUN — ' if args.dry_run else ''}Processing {len(unknowns)} of {total} UNKNOWN vendors")
    log.info(f"Model: {MODEL} via {OLLAMA_URL}")

    if args.dry_run:
        for v in unknowns[:20]:
            print(f"  [{v['id']:4d}] {v['vendor_label'][:50]}")
        if len(unknowns) > 20:
            print(f"  ... and {len(unknowns) - 20} more")
        print(f"\nRun without --dry-run to execute.")
        return

    # ── Process ──
    stats = {"classified": 0, "still_unknown": 0, "errors": 0}
    t0 = time.time()

    # Use a separate read cursor for invoice lookups
    inv_cur = conn.cursor()

    for i, vendor in enumerate(unknowns, 1):
        vid = vendor["id"]
        label = vendor["vendor_label"] or ""
        pattern = vendor["vendor_pattern"] or ""

        # Get invoice stats for context
        inv_count, inv_amount = get_invoice_stats(inv_cur, pattern)

        # Classify
        result = classify_vendor(label, pattern, inv_count, inv_amount)
        classification = result["classification"]
        confidence = result["confidence"]
        reasoning = result["reasoning"]

        # Determine is_revenue / is_expense
        is_revenue = classification in ("REAL_BUSINESS", "CROG_INTERNAL")
        is_expense = classification in (
            "CONTRACTOR", "OPERATIONAL_EXPENSE", "PROFESSIONAL_SERVICE",
            "GOVERNMENT", "CROG_INTERNAL", "FINANCIAL_SERVICE",
        )

        if classification == "NOISE" or classification == "FAMILY_INTERNAL":
            is_revenue = False
            is_expense = False

        # Update DB
        try:
            cur.execute("""
                UPDATE finance.vendor_classifications
                SET classification = %s,
                    is_revenue = %s,
                    is_expense = %s,
                    classified_by = %s,
                    titan_notes = %s
                WHERE id = %s
            """, (
                classification,
                is_revenue,
                is_expense,
                "SWEEP-QWEN-20260215",
                f"confidence={confidence:.2f} | {reasoning}",
                vid,
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error(f"  DB error for [{vid}]: {e}")
            stats["errors"] += 1
            continue

        if classification != "UNKNOWN":
            stats["classified"] += 1
        else:
            stats["still_unknown"] += 1

        # Progress
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (len(unknowns) - i) / rate if rate > 0 else 0

        if i % 10 == 0 or i == len(unknowns):
            log.info(
                f"  [{i}/{len(unknowns)}] "
                f"classified={stats['classified']} "
                f"unknown={stats['still_unknown']} "
                f"err={stats['errors']} "
                f"rate={rate:.1f}/s "
                f"ETA={eta:.0f}s"
            )

        # Brief label log
        status_icon = "✓" if classification != "UNKNOWN" else "?"
        log.info(f"  {status_icon} [{vid}] {label[:40]:40s} → {classification} ({confidence:.0%})")

    # ── Summary ──
    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info(f"  SWEEP COMPLETE in {elapsed:.1f}s")
    log.info(f"  Classified:     {stats['classified']}")
    log.info(f"  Still unknown:  {stats['still_unknown']}")
    log.info(f"  Errors:         {stats['errors']}")
    log.info("=" * 60)

    # Final DB state
    cur.execute("""
        SELECT classification, COUNT(*)
        FROM finance.vendor_classifications
        GROUP BY classification
        ORDER BY COUNT(*) DESC
    """)
    for row in cur.fetchall():
        log.info(f"    {row['classification']:25s} {row['count']:5d}")

    inv_cur.close()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
