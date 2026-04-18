#!/usr/bin/env python3
"""
OPERATION RED PEN — Classification Audit Sampler
=================================================
Fortress Prime | Constitution Article III (CFO Agent)

Generates a human-reviewable CSV with random samples from each
classification category so the CEO can spot-check the AI's work.

For each category, pulls 20 random vendor classifications with:
    - The vendor name/email
    - Number of invoices matched
    - Total extracted amount (WARNING: inflated by email extraction)
    - The AI's reasoning for the classification
    - A sample email subject/sender for context

Output: audit_sample.csv (open in Excel/Google Sheets)

Usage:
    python3 tools/audit_sample.py              # 20 samples per category
    python3 tools/audit_sample.py --samples 50 # 50 samples per category
    python3 tools/audit_sample.py --all        # Every classification
"""

from __future__ import annotations

import os
import sys
import csv
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
import psycopg2.extras

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT


def generate_audit(samples_per_cat: int = 20, output_all: bool = False):
    conn = psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASS, port=DB_PORT,
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Categories to audit (the ones with real money)
    categories = [
        "REAL_BUSINESS",
        "CONTRACTOR",
        "CROG_INTERNAL",
        "FAMILY_INTERNAL",
        "NOISE",
        "UNKNOWN",
        "FINANCIAL_SERVICE",
        "PROFESSIONAL_SERVICE",
        "GOVERNMENT",
        "OPERATIONAL_EXPENSE",
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = PROJECT_ROOT / f"audit_sample_{timestamp}.csv"

    print("=" * 65)
    print("  OPERATION RED PEN — Classification Audit Sample")
    print(f"  Output: {out_path}")
    print(f"  Samples: {'ALL' if output_all else f'{samples_per_cat} per category'}")
    print("=" * 65)

    total_rows = 0

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Category",
            "Classified By",
            "Vendor / Email Sender",
            "Invoice Count",
            "Extracted Amount ($)",
            "AI Reasoning",
            "Confidence",
            "Sample Invoice Date",
            "Classification Pattern",
        ])

        for cat in categories:
            # Join vendor_classifications with finance_invoices to get
            # the actual invoice data behind each classification
            limit_clause = "" if output_all else f"LIMIT {samples_per_cat}"

            cur.execute(f"""
                WITH vendor_stats AS (
                    SELECT
                        vc.vendor_pattern,
                        vc.vendor_label,
                        vc.classification,
                        vc.classified_by,
                        vc.titan_notes,
                        COUNT(fi.id) AS invoice_count,
                        COALESCE(ROUND(SUM(fi.amount)::numeric, 2), 0) AS total_amount,
                        MIN(fi.date) AS earliest_date,
                        MAX(fi.date) AS latest_date
                    FROM finance.vendor_classifications vc
                    LEFT JOIN public.finance_invoices fi
                        ON fi.vendor ILIKE vc.vendor_pattern
                    WHERE vc.classification = %s
                    GROUP BY vc.id, vc.vendor_pattern, vc.vendor_label,
                             vc.classification, vc.classified_by, vc.titan_notes
                    ORDER BY RANDOM()
                    {limit_clause}
                )
                SELECT * FROM vendor_stats
            """, (cat,))

            rows = cur.fetchall()

            if not rows:
                print(f"  {cat:25s}: 0 classifications (skipping)")
                continue

            for row in rows:
                # Extract confidence from titan_notes if present
                notes = row["titan_notes"] or ""
                confidence = ""
                reasoning = notes
                if "confidence=" in notes:
                    parts = notes.split("|", 1)
                    confidence = parts[0].strip().replace("confidence=", "")
                    reasoning = parts[1].strip() if len(parts) > 1 else ""

                writer.writerow([
                    cat,
                    row["classified_by"] or "manual",
                    row["vendor_label"] or row["vendor_pattern"],
                    row["invoice_count"],
                    f"${float(row['total_amount']):,.2f}",
                    reasoning[:200],
                    confidence,
                    str(row["earliest_date"] or "N/A"),
                    row["vendor_pattern"],
                ])
                total_rows += 1

            print(f"  {cat:25s}: {len(rows)} samples written")

    # Also generate a summary sheet
    summary_path = PROJECT_ROOT / f"audit_summary_{timestamp}.csv"
    cur2 = conn.cursor()
    cur2.execute("""
        SELECT
            COALESCE(fi.category, 'UNCLASSIFIED') AS category,
            COUNT(*) AS invoice_count,
            ROUND(SUM(fi.amount)::numeric, 2) AS total_amount,
            COUNT(DISTINCT fi.vendor) AS unique_vendors,
            MIN(fi.date) AS earliest,
            MAX(fi.date) AS latest
        FROM public.finance_invoices fi
        GROUP BY fi.category
        ORDER BY SUM(fi.amount) DESC NULLS LAST
    """)

    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Category", "Invoice Count", "Total Extracted ($)",
            "Unique Vendors", "Earliest Date", "Latest Date",
            "WARNING"
        ])
        for row in cur2.fetchall():
            cat = row[0]
            warning = ""
            if cat == "FAMILY_INTERNAL":
                warning = "INFLATED: Family emails with dollar mentions, not real spend"
            elif cat == "NOISE":
                warning = "GARBAGE: Newsletter/spam dollar figures, not transactions"
            elif cat == "UNKNOWN":
                warning = "NEEDS REVIEW: Ambiguous senders, may contain real vendors"

            writer.writerow([
                cat, row[1], f"${float(row[2]):,.2f}",
                row[3], str(row[4] or "N/A"), str(row[5] or "N/A"),
                warning,
            ])

    cur.close()
    cur2.close()
    conn.close()

    print(f"\n  Total audit rows:  {total_rows}")
    print(f"  Audit detail:      {out_path}")
    print(f"  Audit summary:     {summary_path}")
    print("=" * 65)
    print("  NEXT: Open these CSVs and spot-check the AI's reasoning.")
    print("  Look for: wrong categories, suspicious amounts, missing vendors.")
    print("=" * 65)

    return str(out_path), str(summary_path)


def main():
    parser = argparse.ArgumentParser(description="Generate classification audit CSV")
    parser.add_argument("--samples", type=int, default=20,
                        help="Samples per category (default: 20)")
    parser.add_argument("--all", action="store_true",
                        help="Export every classification (no sampling)")
    args = parser.parse_args()

    generate_audit(samples_per_cat=args.samples, output_all=args.all)


if __name__ == "__main__":
    main()
