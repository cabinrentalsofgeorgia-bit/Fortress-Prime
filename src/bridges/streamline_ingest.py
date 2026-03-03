"""
STREAMLINE BRIDGE — Streamline VRS Export → CF-04 Audit Ledger
===============================================================
Fortress Prime | Cabin Rentals of Georgia
Lead Architect: Gary M. Knight

PURPOSE:
    Ingest Streamline VRS financial exports (CSV) and convert single-entry
    "Nightly Audit" / "Owner Statement" rows into strict GAAP-compliant
    double-entry journal entries via the Audit Ledger engine.

THE PROBLEM:
    Streamline exports are SINGLE-ENTRY. They show:
      "Total Rent: $1,200, Cleaning Fee: $150, Tax: $96, Owner Payout: $850"
    But they DON'T show the other side of each transaction.

THE SOLUTION:
    This bridge reconstructs the double-entry using the mapping config
    (streamline_mapping.yaml) which defines the debit/credit pairs for
    every known Streamline column.

USAGE:
    # Detect headers in a CSV
    python3 src/bridges/streamline_ingest.py --detect export.csv

    # Dry run (shows what WOULD be posted, posts nothing)
    python3 src/bridges/streamline_ingest.py --dry-run export.csv

    # Live ingest
    python3 src/bridges/streamline_ingest.py --ingest export.csv

    # Reconcile (verify totals match)
    python3 src/bridges/streamline_ingest.py --reconcile export.csv
"""

import os
import sys
import csv
import json
import yaml
import logging
import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict

# Fortress imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import importlib

from config import captain_think

# CF-04 directory has a hyphen — use importlib for the import
_cf04 = importlib.import_module("Modules.CF-04_AuditLedger")
AuditLedger = _cf04.AuditLedger

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("StreamlineBridge")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "streamline_bridge.log"))
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_ch)


# ===========================================================================
# MAPPING LOADER
# ===========================================================================

def load_mapping(mapping_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the Streamline → GAAP column mapping configuration."""
    if mapping_path is None:
        mapping_path = os.path.join(os.path.dirname(__file__), "streamline_mapping.yaml")

    if not os.path.exists(mapping_path):
        raise FileNotFoundError(f"Mapping config not found: {mapping_path}")

    with open(mapping_path, "r") as f:
        return yaml.safe_load(f)


def _build_alias_index(mapping: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build a case-insensitive index from all known column aliases
    to their mapping definitions.

    Returns:
        dict mapping lowercase alias → mapping entry
    """
    index = {}

    # Identity columns
    for field, cfg in mapping.get("identity_columns", {}).items():
        for alias in cfg.get("aliases", []):
            index[alias.strip().lower()] = {"type": "identity", "field": field}

    # Financial columns
    for entry in mapping.get("column_maps", []):
        primary = entry.get("streamline_column", "")
        all_names = [primary] + entry.get("aliases", [])
        for alias in all_names:
            index[alias.strip().lower()] = {"type": "financial", "mapping": entry}

    return index


def _normalize_property(raw_name: str, mapping: Dict[str, Any]) -> str:
    """Normalize a Streamline property name to the canonical Fortress cabin ID."""
    if not raw_name:
        return "unknown"

    prop_aliases = mapping.get("property_aliases", {})
    raw_lower = raw_name.strip().lower()

    for canonical, aliases in prop_aliases.items():
        for alias in aliases:
            if alias.strip().lower() == raw_lower:
                return canonical

    # Fallback: slugify the raw name
    return raw_name.strip().lower().replace(" ", "_").replace("'", "")


def _parse_amount(raw: str) -> Optional[Decimal]:
    """Parse a dollar amount from a Streamline CSV cell."""
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()
    # Remove currency symbols, commas, parentheses (negative)
    is_negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1]
    if cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:]

    cleaned = cleaned.replace("$", "").replace(",", "").strip()

    if not cleaned or cleaned == "-" or cleaned == "0":
        return None

    try:
        amount = Decimal(cleaned)
        if is_negative:
            amount = -amount
        if amount == 0:
            return None
        return amount
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: str) -> Optional[date]:
    """Parse a date from common Streamline export formats."""
    if not raw or not raw.strip():
        return None

    raw = raw.strip()
    formats = [
        "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p",
        "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ===========================================================================
# HEADER DETECTION
# ===========================================================================

def detect_headers(csv_path: str, mapping: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Read the first row of a CSV and match headers against the mapping config.

    Returns:
        dict with:
          - matched: list of (csv_header, mapped_field_or_account)
          - unmatched: list of csv headers with no mapping
          - identity_fields: dict of identity field → csv header
          - financial_fields: list of financial mapping dicts with their csv headers
    """
    if mapping is None:
        mapping = load_mapping()

    alias_index = _build_alias_index(mapping)

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)

    # Also grab a few sample rows for preview
    sample_rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= 3:
                break
            sample_rows.append(dict(row))

    matched = []
    unmatched = []
    identity_fields = {}
    financial_fields = []

    for header in headers:
        header_clean = header.strip()
        lookup = header_clean.lower()

        if lookup in alias_index:
            entry = alias_index[lookup]
            if entry["type"] == "identity":
                identity_fields[entry["field"]] = header_clean
                matched.append({
                    "csv_header": header_clean,
                    "mapped_to": entry["field"],
                    "type": "identity",
                })
            elif entry["type"] == "financial":
                m = entry["mapping"]
                if m.get("reconciliation_only"):
                    matched.append({
                        "csv_header": header_clean,
                        "mapped_to": f"RECONCILIATION: {m['streamline_column']}",
                        "type": "reconciliation",
                    })
                else:
                    financial_fields.append({
                        "csv_header": header_clean,
                        "mapping": m,
                    })
                    matched.append({
                        "csv_header": header_clean,
                        "mapped_to": f"DR {m['debit_account']} / CR {m['credit_account']}",
                        "type": "financial",
                        "streamline_field": m["streamline_column"],
                    })
        else:
            unmatched.append(header_clean)

    return {
        "file": csv_path,
        "total_columns": len(headers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": matched,
        "unmatched": unmatched,
        "identity_fields": identity_fields,
        "financial_fields": financial_fields,
        "sample_rows": sample_rows,
    }


# ===========================================================================
# INGESTION ENGINE
# ===========================================================================

class StreamlineBridge:
    """
    Converts Streamline VRS CSV exports into Audit Ledger journal entries.

    Each CSV row (a reservation) becomes multiple journal entries:
      Row: Res #1234, $1200 rent, $150 cleaning, $96 tax, $850 owner payout
      Produces:
        Entry 1: DR Cash $1,200 / CR Rental Revenue $1,200
        Entry 2: DR Cash $150   / CR Cleaning Fee Revenue $150
        Entry 3: DR Cash $96    / CR Sales Tax Payable $96
        Entry 4: DR Trust Liability $850 / CR Cash-Trust $850
    """

    def __init__(self, mapping_path: Optional[str] = None):
        self.mapping = load_mapping(mapping_path)
        self.alias_index = _build_alias_index(self.mapping)
        self.ledger = AuditLedger()
        self.stats = {
            "rows_processed": 0,
            "rows_skipped": 0,
            "entries_posted": 0,
            "entries_failed": 0,
            "anomalies_flagged": 0,
            "total_debits": Decimal("0"),
            "total_credits": Decimal("0"),
            "errors": [],
            "unmapped_columns": set(),
        }

    def close(self):
        self.ledger.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -----------------------------------------------------------------------
    # CORE: Ingest a CSV file
    # -----------------------------------------------------------------------

    def ingest(
        self,
        csv_path: str,
        dry_run: bool = False,
        batch_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a Streamline VRS CSV export into the Audit Ledger.

        Args:
            csv_path:    Path to the Streamline CSV export
            dry_run:     If True, parse and validate but don't post to DB
            batch_label: Optional label for this import batch

        Returns:
            dict with ingestion statistics and any errors/anomalies
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        # Reset stats
        self.stats = {
            "rows_processed": 0,
            "rows_skipped": 0,
            "entries_posted": 0,
            "entries_failed": 0,
            "anomalies_flagged": 0,
            "total_debits": Decimal("0"),
            "total_credits": Decimal("0"),
            "errors": [],
            "unmapped_columns": set(),
        }

        if batch_label is None:
            batch_label = f"streamline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.info(f"[BRIDGE] Starting Streamline ingest: {csv_path} (dry_run={dry_run})")

        # Detect and map headers
        detection = detect_headers(csv_path, self.mapping)
        identity_map = detection["identity_fields"]
        financial_maps = detection["financial_fields"]
        self.stats["unmapped_columns"] = set(detection["unmatched"])

        if not financial_maps:
            logger.error("[BRIDGE] No financial columns mapped. Cannot proceed.")
            return {**self.stats, "status": "FAILED", "reason": "No financial columns found"}

        logger.info(
            f"[BRIDGE] Mapped {len(financial_maps)} financial columns, "
            f"{len(identity_map)} identity columns, "
            f"{len(detection['unmatched'])} unmapped"
        )

        # Process each row
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):  # Row 2 = first data row
                try:
                    result = self._process_row(
                        row, row_num, identity_map, financial_maps,
                        batch_label, dry_run
                    )
                    if result == "skipped":
                        self.stats["rows_skipped"] += 1
                    else:
                        self.stats["rows_processed"] += 1
                except Exception as e:
                    self.stats["rows_skipped"] += 1
                    error_msg = f"Row {row_num}: {e}"
                    self.stats["errors"].append(error_msg)
                    logger.error(f"[BRIDGE] {error_msg}")

        # Run reconciliation
        recon = self._reconcile(csv_path, detection)

        status = "DRY_RUN" if dry_run else "COMPLETED"
        self.stats["unmapped_columns"] = list(self.stats["unmapped_columns"])

        result = {
            **self.stats,
            "status": status,
            "batch_label": batch_label,
            "file": csv_path,
            "reconciliation": recon,
        }

        logger.info(
            f"[BRIDGE] Ingest {status}: {self.stats['rows_processed']} rows, "
            f"{self.stats['entries_posted']} entries posted, "
            f"{self.stats['entries_failed']} failed, "
            f"{self.stats['anomalies_flagged']} anomalies"
        )

        return result

    # -----------------------------------------------------------------------
    # Process a single CSV row → multiple journal entries
    # -----------------------------------------------------------------------

    def _process_row(
        self,
        row: Dict[str, str],
        row_num: int,
        identity_map: Dict[str, str],
        financial_maps: List[Dict],
        batch_label: str,
        dry_run: bool,
    ) -> str:
        """
        Process one CSV row. Each financial column that has a nonzero value
        becomes a separate journal entry.
        """
        # Extract identity fields
        res_id = row.get(identity_map.get("reservation_id", ""), "").strip()
        property_raw = row.get(identity_map.get("property_name", ""), "").strip()
        guest = row.get(identity_map.get("guest_name", ""), "").strip()
        checkin_raw = row.get(identity_map.get("checkin_date", ""), "").strip()

        # Normalize
        property_id = _normalize_property(property_raw, self.mapping)
        entry_date = _parse_date(checkin_raw) or date.today()
        reference_id = res_id or f"row_{row_num}"

        # Track if we posted anything for this row
        posted_any = False

        for fm in financial_maps:
            csv_header = fm["csv_header"]
            m = fm["mapping"]

            raw_value = row.get(csv_header, "").strip()
            amount = _parse_amount(raw_value)

            if amount is None:
                continue

            # Handle sign convention
            if m.get("sign") == "negative":
                amount = abs(amount)

            if amount <= 0:
                continue

            # Build the description from template
            desc_template = m.get("description_template", "{streamline_column}")
            description = desc_template.format(
                property_name=property_raw or property_id,
                reservation_id=reference_id,
                guest_name=guest,
                streamline_column=m.get("streamline_column", csv_header),
            )

            if dry_run:
                logger.info(
                    f"[DRY RUN] Row {row_num}: "
                    f"DR {m['debit_account']} / CR {m['credit_account']} — "
                    f"${amount:,.2f} — {description}"
                )
                self.stats["entries_posted"] += 1
                self.stats["total_debits"] += amount
                self.stats["total_credits"] += amount
                posted_any = True
                continue

            try:
                result = self.ledger.post_transaction(
                    debit_acct=m["debit_account"],
                    credit_acct=m["credit_account"],
                    amount=float(amount),
                    description=description,
                    property_id=property_id,
                    reference_id=reference_id,
                    reference_type=m.get("transaction_type"),
                    entry_date=entry_date,
                    posted_by="streamline_bridge",
                    source_system="streamline_import",
                    memo=f"Batch: {batch_label} | Row: {row_num} | Guest: {guest}",
                )

                self.stats["entries_posted"] += 1
                self.stats["total_debits"] += amount
                self.stats["total_credits"] += amount
                posted_any = True

                if result.get("anomaly_flag"):
                    self.stats["anomalies_flagged"] += 1

            except Exception as e:
                self.stats["entries_failed"] += 1
                error_msg = f"Row {row_num}, {csv_header}: {e}"
                self.stats["errors"].append(error_msg)
                logger.error(f"[BRIDGE] Post failed — {error_msg}")

        return "processed" if posted_any else "skipped"

    # -----------------------------------------------------------------------
    # Reconciliation: Verify totals match the CSV
    # -----------------------------------------------------------------------

    def _reconcile(
        self,
        csv_path: str,
        detection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compare the total amounts posted against reconciliation columns
        in the CSV (e.g., "Total Charges", "Total Payments").
        """
        recon = {"status": "NO_RECON_COLUMNS", "details": []}

        # Find reconciliation columns
        recon_columns = [
            m for m in detection["matched"]
            if m.get("type") == "reconciliation"
        ]

        if not recon_columns:
            return recon

        recon["status"] = "CHECKED"

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for col_info in recon_columns:
                header = col_info["csv_header"]
                csv_total = Decimal("0")

                f.seek(0)
                reader = csv.DictReader(f)

                for row in reader:
                    amt = _parse_amount(row.get(header, ""))
                    if amt:
                        csv_total += amt

                posted_total = self.stats["total_debits"]
                delta = abs(csv_total - posted_total)

                recon["details"].append({
                    "column": header,
                    "csv_total": str(csv_total),
                    "posted_total": str(posted_total),
                    "delta": str(delta),
                    "balanced": delta < Decimal("0.01"),
                })

                if delta >= Decimal("0.01"):
                    logger.warning(
                        f"[RECON] Delta on '{header}': "
                        f"CSV=${csv_total:,.2f} vs Posted=${posted_total:,.2f} "
                        f"(delta=${delta:,.2f})"
                    )

        return recon

    # -----------------------------------------------------------------------
    # AI: Analyze unmapped columns
    # -----------------------------------------------------------------------

    def ai_analyze_unmapped(
        self,
        csv_path: str,
        detection: Optional[Dict] = None,
    ) -> str:
        """
        Ask DeepSeek R1 to analyze unmapped columns and suggest GAAP mappings.
        """
        if detection is None:
            detection = detect_headers(csv_path, self.mapping)

        if not detection["unmatched"]:
            return "All columns are mapped. No analysis needed."

        # Grab sample values for unmapped columns
        samples = {}
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                for col in detection["unmatched"]:
                    if col not in samples:
                        samples[col] = []
                    val = row.get(col, "").strip()
                    if val:
                        samples[col].append(val)

        prompt = f"""You are a forensic accountant mapping Streamline VRS export columns to a GAAP chart of accounts.

UNMAPPED COLUMNS (with sample values):
{json.dumps(samples, indent=2)}

AVAILABLE GAAP ACCOUNTS:
- 1000: Cash - Operating (Asset, debit)
- 1010: Cash - Trust (Asset, debit)
- 1020: Cash - Security Deposits (Asset, debit)
- 1100: Accounts Receivable (Asset, debit)
- 2000: Trust Liability - Owners (Liability, credit)
- 2010: Security Deposit Liability (Liability, credit)
- 2100: Accounts Payable (Liability, credit)
- 2200: Sales Tax Payable (Liability, credit)
- 2210: Occupancy Tax Payable (Liability, credit)
- 2300: Deferred Revenue (Liability, credit)
- 4000: Rental Revenue (Revenue, credit)
- 4010: Cleaning Fee Revenue (Revenue, credit)
- 4020: Pet Fee Revenue (Revenue, credit)
- 4100: Management Fee Revenue (Revenue, credit)
- 4200: Other Income (Revenue, credit)
- 5000-5900: Various Expense accounts (Expense, debit)

For each unmapped column, provide:
1. Recommended debit account code
2. Recommended credit account code
3. Whether it's financial or identity/informational
4. Confidence level (high/medium/low)
5. Brief explanation

Format as a clean list. Be specific to cabin rental / property management context."""

        import re
        response = captain_think(
            prompt,
            system_role="You are the CFO AI for a cabin rental company. Map financial columns with precision.",
            temperature=0.3,
        )
        # Strip DeepSeek <think> tags
        return re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()


# ===========================================================================
# CLI
# ===========================================================================

def _print_detection(detection: Dict[str, Any]):
    """Pretty-print header detection results."""
    print("=" * 72)
    print("  STREAMLINE BRIDGE — HEADER DETECTION")
    print("=" * 72)
    print(f"  File: {detection['file']}")
    print(f"  Columns: {detection['total_columns']}")
    print(f"  Matched: {detection['matched_count']}")
    print(f"  Unmapped: {detection['unmatched_count']}")

    print(f"\n  --- IDENTITY FIELDS ---")
    for field, header in detection["identity_fields"].items():
        print(f"    {field:20s} ← \"{header}\"")

    print(f"\n  --- FINANCIAL MAPPINGS ---")
    for m in detection["matched"]:
        if m["type"] == "financial":
            print(f"    \"{m['csv_header']}\"")
            print(f"      → {m['mapped_to']}  ({m.get('streamline_field', '')})")

    if any(m["type"] == "reconciliation" for m in detection["matched"]):
        print(f"\n  --- RECONCILIATION COLUMNS ---")
        for m in detection["matched"]:
            if m["type"] == "reconciliation":
                print(f"    \"{m['csv_header']}\" → {m['mapped_to']}")

    if detection["unmatched"]:
        print(f"\n  --- UNMAPPED COLUMNS (need review) ---")
        for col in detection["unmatched"]:
            print(f"    ??? \"{col}\"")

    if detection["sample_rows"]:
        print(f"\n  --- SAMPLE DATA (first row) ---")
        for k, v in detection["sample_rows"][0].items():
            if v and v.strip():
                print(f"    {k:30s}: {v}")

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Streamline VRS → Fortress Audit Ledger Bridge"
    )
    parser.add_argument("csv_file", nargs="?", help="Path to Streamline CSV export")
    parser.add_argument("--detect", action="store_true",
                        help="Detect and map CSV headers (recon only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate without posting to DB")
    parser.add_argument("--ingest", action="store_true",
                        help="Live ingest into the Audit Ledger")
    parser.add_argument("--reconcile", action="store_true",
                        help="Reconcile CSV totals against posted entries")
    parser.add_argument("--ai-analyze", action="store_true",
                        help="Ask AI to analyze unmapped columns")
    parser.add_argument("--mapping", type=str, default=None,
                        help="Path to custom mapping YAML")
    parser.add_argument("--batch", type=str, default=None,
                        help="Batch label for this import")

    args = parser.parse_args()

    if not args.csv_file:
        # Show the expected staging path
        print("=" * 72)
        print("  STREAMLINE BRIDGE — Awaiting Export File")
        print("=" * 72)
        print()
        print("  No CSV file provided. To use the Streamline Bridge:")
        print()
        print("  1. Export from Streamline VRS:")
        print("     → Reports → Nightly Audit (or Owner Statement)")
        print("     → Select date range → Export as CSV")
        print()
        print("  2. Upload to the NAS staging directory:")
        print("     /mnt/fortress_nas/Financial_Ledger/Streamline_Exports/")
        print()
        print("  3. Run detection:")
        print("     python3 src/bridges/streamline_ingest.py --detect <file.csv>")
        print()
        print("  4. Dry run (no DB changes):")
        print("     python3 src/bridges/streamline_ingest.py --dry-run <file.csv>")
        print()
        print("  5. Live ingest:")
        print("     python3 src/bridges/streamline_ingest.py --ingest <file.csv>")
        print()
        print("  Staging directory contents:")
        staging = "/mnt/fortress_nas/Financial_Ledger/Streamline_Exports/"
        if os.path.exists(staging):
            files = [f for f in os.listdir(staging) if not f.startswith(".")]
            if files:
                for f in sorted(files):
                    size = os.path.getsize(os.path.join(staging, f))
                    print(f"    {f} ({size:,} bytes)")
            else:
                print("    (empty — upload your Streamline export here)")
        else:
            print(f"    {staging} does not exist")
        print("=" * 72)
        return

    csv_path = args.csv_file
    if not os.path.exists(csv_path):
        print(f"ERROR: File not found: {csv_path}")
        sys.exit(1)

    mapping = load_mapping(args.mapping) if args.mapping else load_mapping()

    if args.detect:
        detection = detect_headers(csv_path, mapping)
        _print_detection(detection)

        if args.ai_analyze and detection["unmatched"]:
            print("\n  Asking the Captain to analyze unmapped columns...\n")
            with StreamlineBridge(args.mapping) as bridge:
                analysis = bridge.ai_analyze_unmapped(csv_path, detection)
                print(analysis)

    elif args.dry_run:
        print("=" * 72)
        print("  STREAMLINE BRIDGE — DRY RUN")
        print("=" * 72)
        with StreamlineBridge(args.mapping) as bridge:
            result = bridge.ingest(csv_path, dry_run=True, batch_label=args.batch)
            print(f"\n  Status:           {result['status']}")
            print(f"  Rows processed:   {result['rows_processed']}")
            print(f"  Rows skipped:     {result['rows_skipped']}")
            print(f"  Entries (would):  {result['entries_posted']}")
            print(f"  Total debits:     ${result['total_debits']:,.2f}")
            print(f"  Total credits:    ${result['total_credits']:,.2f}")
            if result["errors"]:
                print(f"\n  --- ERRORS ({len(result['errors'])}) ---")
                for e in result["errors"][:10]:
                    print(f"    {e}")
            if result["unmapped_columns"]:
                print(f"\n  --- UNMAPPED COLUMNS ---")
                for col in result["unmapped_columns"]:
                    print(f"    ??? {col}")
            print("=" * 72)

    elif args.ingest:
        print("=" * 72)
        print("  STREAMLINE BRIDGE — LIVE INGEST")
        print("=" * 72)
        confirm = input("  This will post journal entries to the Audit Ledger. Continue? [y/N]: ")
        if confirm.lower() != "y":
            print("  Aborted.")
            return

        with StreamlineBridge(args.mapping) as bridge:
            result = bridge.ingest(csv_path, dry_run=False, batch_label=args.batch)
            print(f"\n  Status:           {result['status']}")
            print(f"  Rows processed:   {result['rows_processed']}")
            print(f"  Entries posted:   {result['entries_posted']}")
            print(f"  Entries failed:   {result['entries_failed']}")
            print(f"  Anomalies:        {result['anomalies_flagged']}")
            print(f"  Total debits:     ${result['total_debits']:,.2f}")
            print(f"  Total credits:    ${result['total_credits']:,.2f}")
            if result.get("reconciliation", {}).get("details"):
                print(f"\n  --- RECONCILIATION ---")
                for r in result["reconciliation"]["details"]:
                    icon = "OK" if r["balanced"] else "DELTA"
                    print(f"    [{icon}] {r['column']}: CSV=${r['csv_total']} vs Posted=${r['posted_total']}")
            if result["errors"]:
                print(f"\n  --- ERRORS ({len(result['errors'])}) ---")
                for e in result["errors"][:10]:
                    print(f"    {e}")
            print("=" * 72)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
