#!/usr/bin/env python3
"""
OPERATION GLASS HOUSE — Vendor Classification via Wolfpack Swarm
=================================================================
Fortress Prime | Constitution Article III (CFO Agent)

Classifies unclassified vendors in finance_invoices by dispatching
each vendor to the Wolfpack Swarm (qwen2.5:7b x4, load-balanced)
for rapid AI classification. Uses R1-70B only on --deep flag.

Pipeline:
    1. Aggregate unclassified vendors from public.finance_invoices
    2. Skip vendors already matched by finance.vendor_classifications
    3. Send each vendor to qwen2.5:7b (or R1-70B) for classification
    4. Store results in finance.vendor_classifications
    5. Backfill finance_invoices.category using the new patterns

Categories (Constitution Article III):
    CROG_INTERNAL    — Cabin Rentals of Georgia operations
    REAL_ESTATE      — Property purchases, construction, CAPEX
    CONTRACTOR       — Service providers, maintenance, repairs
    OPS_EXPENSE      — Operational costs, utilities, supplies
    FINANCIAL_SVC    — Banking, insurance, investment services
    TAX_PROFESSIONAL — Accountants, tax prep, IRS
    LEGAL            — Attorneys, legal services
    FAMILY_TRANSFER  — Family member transactions (not revenue)
    NEWS_SPAM        — Newsletters, marketing, spam with dollar amounts
    PERSONAL         — Personal purchases, subscriptions
    UNKNOWN          — Cannot determine from vendor name alone

Usage:
    # Dry run (classify but don't write to DB)
    python3 tools/glass_house.py --dry-run

    # Full run — top 50 by spend
    python3 tools/glass_house.py --batch 50

    # Full blast — all unclassified vendors
    python3 tools/glass_house.py --batch 0

    # Resume from where we left off
    python3 tools/glass_house.py --batch 100 --skip-classified

Safety:
    - Constitution Rule IV.7: Raw finance_invoices.amount is inflated.
      This script classifies vendors, NOT amounts. Dollar totals are
      context for R1 but are not trusted as real revenue.
    - All classifications stored with classified_by='hydra-glass-house'
      for audit trail.
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import psycopg2
import psycopg2.extras

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT,
    HYDRA_ENDPOINT, HYDRA_MODEL, HYDRA_ENDPOINTS,
    SWARM_ENDPOINT, SWARM_MODEL,
    SPARK_01_IP, SPARK_02_IP, SPARK_03_IP, SPARK_04_IP,
)

# Default: qwen2.5:7b for speed (4.8s/vendor).  R1-70B with --deep (100s/vendor).
CLASSIFY_ENDPOINT = SWARM_ENDPOINT   # Nginx LB → all 4 Ollama nodes
CLASSIFY_MODEL = SWARM_MODEL         # qwen2.5:7b
CLASSIFY_ENDPOINTS = [               # Direct per-node (for parallel dispatch)
    f"http://{SPARK_01_IP}:11434/v1",
    f"http://{SPARK_02_IP}:11434/v1",
    f"http://{SPARK_03_IP}:11434/v1",
    f"http://{SPARK_04_IP}:11434/v1",
]

logger = logging.getLogger("glass_house")

# =============================================================================
# CONFIGURATION
# =============================================================================

# These MUST match the CHECK constraint on finance.vendor_classifications.classification
VALID_CATEGORIES = [
    "REAL_BUSINESS",           # Real estate, property transactions
    "FAMILY_INTERNAL",         # Knight family members
    "CROG_INTERNAL",           # Cabin Rentals of Georgia operations
    "NOISE",                   # Newsletters, spam, marketing
    "UNKNOWN",                 # Cannot determine
    "OPERATIONAL_EXPENSE",     # Utilities, supplies, office costs
    "PROFESSIONAL_SERVICE",    # Attorneys, CPAs, consultants
    "GOVERNMENT",              # IRS, county offices, permits
    "FINANCIAL_SERVICE",       # Banks, insurance, credit cards
    "CONTRACTOR",              # Service providers, maintenance, repairs
]

# Map from LLM-generated labels to valid DB categories
_CATEGORY_MAP = {
    "REAL_ESTATE": "REAL_BUSINESS",
    "REAL_ESTATE_CAPEX": "REAL_BUSINESS",
    "FAMILY_TRANSFER": "FAMILY_INTERNAL",
    "NEWS_SPAM": "NOISE",
    "OPS_EXPENSE": "OPERATIONAL_EXPENSE",
    "OPERATIONAL_EXPENSE": "OPERATIONAL_EXPENSE",
    "TAX_PROFESSIONAL": "PROFESSIONAL_SERVICE",
    "LEGAL": "PROFESSIONAL_SERVICE",
    "FINANCIAL_SVC": "FINANCIAL_SERVICE",
    "FINANCIAL_SERVICE": "FINANCIAL_SERVICE",
    "PERSONAL": "NOISE",
    "GOVERNMENT": "GOVERNMENT",
    "CONTRACTOR": "CONTRACTOR",
    "CROG_INTERNAL": "CROG_INTERNAL",
    "REAL_BUSINESS": "REAL_BUSINESS",
    "FAMILY_INTERNAL": "FAMILY_INTERNAL",
    "NOISE": "NOISE",
    "PROFESSIONAL_SERVICE": "PROFESSIONAL_SERVICE",
    "UNKNOWN": "UNKNOWN",
}

CLASSIFICATION_PROMPT = """Classify this email sender into one business category for "Cabin Rentals of Georgia" (CROG), a vacation rental company 100% owned by Gary M. Knight.

RULES:
- These are EMAIL SENDERS, not invoices. Dollar amounts were extracted by AI from email bodies and are often inflated/fake.
- The "vendor" field is an email sender: "Display Name <email@domain>"
- Knight family members (Barbara, Taylor, Lissa, Gary) = FAMILY_INTERNAL
- CROG/cabin rental references = CROG_INTERNAL
- Contractors/handymen/cleaners with personal emails = CONTRACTOR
- News/newsletters/market alerts (Summa Money, Breaking News, Epoch Times, Zerohedge, SA, Motley Fool, Travelzoo) = NOISE
- Banks/credit cards/insurance/Discover/PayPal/Authorize.net = FINANCIAL_SERVICE
- Home Depot/Lowes/Amazon/Walmart/Costco = OPERATIONAL_EXPENSE
- Attorneys/legal/court/CPA/accountant = PROFESSIONAL_SERVICE
- IRS/county offices/government agencies = GOVERNMENT
- Zillow/Redfin/MLS/title company/real estate agent = REAL_BUSINESS
- Everything else where you cannot determine = UNKNOWN

CATEGORIES: CROG_INTERNAL, REAL_BUSINESS, CONTRACTOR, OPERATIONAL_EXPENSE, FINANCIAL_SERVICE, PROFESSIONAL_SERVICE, GOVERNMENT, FAMILY_INTERNAL, NOISE, UNKNOWN

SENDER: {vendor_name}
EMAILS: {txn_count} emails, extracted amount: ${total_spend:,.2f}

Return ONLY this JSON (no markdown, no explanation):
{{"classification": "<CATEGORY>", "confidence": <0.0-1.0>, "reasoning": "<10 words max>"}}"""


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_connection():
    """Get a Postgres connection."""
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASS, port=DB_PORT,
    )


def fetch_unclassified_vendors(limit: int = 50) -> list[dict]:
    """
    Fetch unclassified vendors aggregated by spend.
    Excludes vendors already matched by vendor_classifications patterns.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = """
        WITH classified_vendors AS (
            SELECT DISTINCT fi.vendor
            FROM public.finance_invoices fi
            JOIN finance.vendor_classifications vc
              ON fi.vendor ILIKE vc.vendor_pattern
        )
        SELECT
            fi.vendor AS vendor_name,
            COUNT(*) AS transaction_count,
            ROUND(SUM(fi.amount)::numeric, 2) AS total_spend
        FROM public.finance_invoices fi
        LEFT JOIN classified_vendors cv ON fi.vendor = cv.vendor
        WHERE fi.category IS NULL
          AND cv.vendor IS NULL
          AND fi.vendor IS NOT NULL
          AND fi.vendor != ''
        GROUP BY fi.vendor
        ORDER BY SUM(fi.amount) DESC
    """

    if limit > 0:
        query += f" LIMIT {limit}"

    cur.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    logger.info(f"Fetched {len(rows)} unclassified vendors")
    return rows


def store_classification(vendor_name: str, classification: str,
                         confidence: float, reasoning: str):
    """Store a vendor classification in finance.vendor_classifications."""
    conn = get_connection()
    cur = conn.cursor()

    # Build a ILIKE pattern from the vendor name
    # Escape special chars and use % wildcard for partial matching
    pattern = vendor_name.replace("'", "''").replace("%", "\\%")
    # Use first 40 chars + wildcard for pattern matching
    if len(pattern) > 40:
        pattern = pattern[:40] + "%"

    cur.execute("""
        INSERT INTO finance.vendor_classifications
            (vendor_pattern, vendor_label, classification, is_revenue, is_expense,
             titan_notes, classified_at, classified_by)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
        ON CONFLICT (vendor_pattern) DO UPDATE SET
            classification = EXCLUDED.classification,
            titan_notes = EXCLUDED.titan_notes,
            classified_at = NOW(),
            classified_by = EXCLUDED.classified_by
    """, (
        pattern,
        vendor_name[:100],
        classification,
        classification in ("CROG_INTERNAL", "REAL_BUSINESS"),  # Revenue-generating
        classification in ("CONTRACTOR", "OPERATIONAL_EXPENSE",
                           "PROFESSIONAL_SERVICE", "FINANCIAL_SERVICE", "GOVERNMENT"),
        f"confidence={confidence:.2f} | {reasoning}",
        "hydra-glass-house",
    ))

    conn.commit()
    cur.close()
    conn.close()


def backfill_categories():
    """Update finance_invoices.category using vendor_classifications patterns."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE public.finance_invoices fi
        SET category = vc.classification,
            updated_at = NOW()
        FROM finance.vendor_classifications vc
        WHERE fi.vendor ILIKE vc.vendor_pattern
          AND fi.category IS NULL
    """)

    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Backfilled {updated} invoice rows with categories")
    return updated


# =============================================================================
# HYDRA INFERENCE
# =============================================================================

def classify_vendor(vendor: dict, endpoint: str = None,
                    model: str = None) -> dict:
    """
    Send a vendor to the Wolfpack/Hydra for classification.

    Args:
        vendor: dict with vendor_name, transaction_count, total_spend
        endpoint: Override inference endpoint (default: Nginx LB)
        model: Override model name (default: CLASSIFY_MODEL)

    Returns:
        dict with classification, confidence, reasoning
    """
    import re

    use_model = model or CLASSIFY_MODEL
    url = (endpoint or CLASSIFY_ENDPOINT).rstrip("/") + "/chat/completions"
    is_r1 = "r1" in use_model.lower()

    prompt = CLASSIFICATION_PROMPT.format(
        vendor_name=vendor["vendor_name"],
        txn_count=vendor["transaction_count"],
        total_spend=float(vendor["total_spend"]),
    )

    try:
        resp = requests.post(
            url,
            json={
                "model": use_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 16384 if is_r1 else 256,
                "temperature": 0.1,
            },
            timeout=300 if is_r1 else 30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Strip <think> tags (R1 chain-of-thought) and markdown fences
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        content = content.strip()

        # Extract JSON from response
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if not json_match:
            return {
                "classification": "UNKNOWN",
                "confidence": 0.0,
                "reasoning": f"No JSON in response: {content[:100]}",
            }

        result = json.loads(json_match.group())

        # Validate and map classification to DB-allowed values
        raw_cat = result.get("classification", "UNKNOWN").upper().replace(" ", "_")
        cat = _CATEGORY_MAP.get(raw_cat, "UNKNOWN")
        if cat not in VALID_CATEGORIES:
            cat = "UNKNOWN"

        return {
            "classification": cat,
            "confidence": min(float(result.get("confidence", 0.5)), 1.0),
            "reasoning": result.get("reasoning", "")[:200],
        }

    except requests.exceptions.Timeout:
        return {
            "classification": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"Timeout ({300 if is_r1 else 30}s)",
        }
    except json.JSONDecodeError:
        return {
            "classification": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"JSON parse error: {content[:100]}",
        }
    except Exception as e:
        return {
            "classification": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"Error: {str(e)[:100]}",
        }


def classify_batch_parallel(vendors: list, max_workers: int = 4,
                            model: str = None) -> list:
    """
    Classify vendors in parallel across all 4 GPU nodes.

    Uses ThreadPoolExecutor to dispatch to different endpoints,
    maximizing GPU utilization across the cluster.
    """
    results = [None] * len(vendors)
    endpoints = CLASSIFY_ENDPOINTS  # Direct to each node, bypassing LB

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, vendor in enumerate(vendors):
            # Round-robin across endpoints
            ep = endpoints[i % len(endpoints)]
            future = pool.submit(classify_vendor, vendor, ep, model)
            futures[future] = i

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {
                    "classification": "UNKNOWN",
                    "confidence": 0.0,
                    "reasoning": f"Thread error: {e}",
                }

    return results


# =============================================================================
# MAIN OPERATION
# =============================================================================

def run_operation(batch_size: int = 50, dry_run: bool = False,
                  parallel: bool = True, backfill: bool = True,
                  deep: bool = False) -> dict:
    """
    Execute Operation Glass House.

    Args:
        batch_size: Number of vendors to classify (0 = all)
        dry_run: If True, classify but don't write to DB
        parallel: If True, use all 4 heads simultaneously
        backfill: If True, update finance_invoices.category after classifying
        deep: If True, use R1-70B instead of qwen2.5:7b (20x slower)

    Returns:
        Summary dict with counts and timing
    """
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    use_model = HYDRA_MODEL if deep else CLASSIFY_MODEL

    logger.info("=" * 65)
    logger.info(f"OPERATION GLASS HOUSE — Vendor Classification Sweep")
    logger.info(f"Started: {timestamp}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | "
                f"Parallel: {parallel} | Batch: {batch_size or 'ALL'}")
    logger.info(f"Model: {use_model} {'(DEEP MODE)' if deep else '(FAST MODE)'}")
    logger.info("=" * 65)

    # 1. Fetch unclassified vendors
    vendors = fetch_unclassified_vendors(batch_size)
    if not vendors:
        logger.info("No unclassified vendors found. Operation complete.")
        return {"classified": 0, "elapsed": 0}

    total_spend = sum(float(v["total_spend"]) for v in vendors)
    logger.info(f"Targets: {len(vendors)} vendors | ${total_spend:,.2f} in unclassified spend")

    # 2. Classify via Wolfpack/Hydra
    logger.info(f"\nDispatching to {'Hydra (R1-70B)' if deep else 'Wolfpack (qwen2.5:7b)'}...")

    if parallel and len(vendors) > 1:
        results = classify_batch_parallel(vendors, max_workers=4, model=use_model)
    else:
        results = []
        for i, vendor in enumerate(vendors):
            logger.info(f"  [{i+1}/{len(vendors)}] {vendor['vendor_name'][:50]}...")
            result = classify_vendor(vendor, model=use_model)
            results.append(result)

    # 3. Process results
    classified = 0
    unknown = 0
    category_counts = {}

    logger.info(f"\n{'─' * 65}")
    logger.info(f"{'Vendor':40s} {'Category':20s} {'Conf':>5s}")
    logger.info(f"{'─' * 65}")

    for vendor, result in zip(vendors, results):
        cat = result["classification"]
        conf = result["confidence"]
        name = vendor["vendor_name"][:40]

        logger.info(f"{name:40s} {cat:20s} {conf:5.2f}")

        category_counts[cat] = category_counts.get(cat, 0) + 1

        if cat != "UNKNOWN":
            classified += 1
        else:
            unknown += 1

        # 4. Store classification
        if not dry_run:
            store_classification(
                vendor["vendor_name"],
                cat,
                conf,
                result["reasoning"],
            )

    # 5. Backfill invoices
    backfilled = 0
    if not dry_run and backfill:
        logger.info("\nBackfilling finance_invoices.category...")
        backfilled = backfill_categories()

    # Summary
    elapsed = time.time() - start_time
    logger.info(f"\n{'=' * 65}")
    logger.info(f"OPERATION GLASS HOUSE — COMPLETE")
    logger.info(f"{'=' * 65}")
    logger.info(f"  Vendors processed:  {len(vendors)}")
    logger.info(f"  Classified:         {classified}")
    logger.info(f"  Unknown:            {unknown}")
    logger.info(f"  Invoices backfilled: {backfilled}")
    logger.info(f"  Time:               {elapsed:.1f}s ({elapsed/len(vendors):.1f}s per vendor)")
    logger.info(f"\n  Category breakdown:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {cat:20s}: {count}")

    if dry_run:
        logger.info("\n  ** DRY RUN — no changes written to database **")

    return {
        "classified": classified,
        "unknown": unknown,
        "backfilled": backfilled,
        "elapsed": elapsed,
        "categories": category_counts,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Operation Glass House — Vendor classification via Hydra Swarm"
    )
    parser.add_argument(
        "--batch", type=int, default=50,
        help="Number of vendors to process (0 = all, default: 50)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify vendors but don't write to database",
    )
    parser.add_argument(
        "--deep", action="store_true",
        help="Use R1-70B instead of qwen2.5:7b (20x slower, deeper reasoning)",
    )
    parser.add_argument(
        "--sequential", action="store_true",
        help="Process one at a time instead of parallel dispatch",
    )
    parser.add_argument(
        "--no-backfill", action="store_true",
        help="Don't update finance_invoices.category after classifying",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    run_operation(
        batch_size=args.batch,
        dry_run=args.dry_run,
        parallel=not args.sequential,
        backfill=not args.no_backfill,
        deep=args.deep,
    )


if __name__ == "__main__":
    main()
