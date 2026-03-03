"""
Strangler Reconciler -- Vector 4 Forensic Variance Engine

Parses Streamline owner statement PDFs (ground truth) and compares
per-reservation financials against the Iron Dome ledger to quantify
commission over-allocation.

Streamline calculates management commission (35%) on "Gross Rent" which
is base nightly rate + additional party fee ONLY. The Iron Dome's
revenue_consumer_daemon.py currently calculates 35% on
(total_amount - tax_amount), which includes cleaning fees, damage
waivers, processing fees, and DOT tax -- a systematically larger base.

This reconciler extracts both realities and produces the exact variance.

Usage:
    cd fortress-guest-platform && python3 -m tools.strangler_reconciler
"""

import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

import pdfplumber
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

NAS_STMT_DIR = "/mnt/fortress_nas/sectors/legal/owner-statements"

DB_DSN = os.getenv(
    "FGP_DB_DSN",
    "dbname=fortress_guest user=fgp_app password=F0rtr3ss_Gu3st_2026! host=localhost",
)

TWO = Decimal("0.01")


def _parse_amount(text: str) -> float:
    """Parse a dollar amount that may be negative (in parens) or positive."""
    text = text.strip()
    negative = text.startswith("(") or text.startswith("($")
    cleaned = text.replace("(", "").replace(")", "").replace("$", "").replace(",", "").strip()
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return 0.0


def parse_streamline_pdf(pdf_path: str) -> dict:
    """Extract financial ground truth from a Streamline owner statement PDF."""
    result = {
        "property_name": "",
        "period_start": "",
        "period_end": "",
        "summary": {
            "gross_revenue": 0.0,
            "mgmt_commission": 0.0,
            "owner_charges": 0.0,
            "ending_balance": 0.0,
            "opening_balance": 0.0,
        },
        "reservations": [],
    }

    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"

    lines = full_text.split("\n")

    for line in lines:
        if not result["property_name"]:
            m = re.search(r"(?:Toccoa River|Aska Adventure Area|Mountain View|Lake Blue Ridge|Blue Ridge|Morganton)\s+(.+?)\s+(?:APPROVED|UNAPPROVED)", line)
            if m:
                result["property_name"] = m.group(1).strip()

        m = re.search(r"Activity:\s+From\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", line)
        if m:
            result["period_start"] = m.group(1)
            result["period_end"] = m.group(2)

        m = re.match(r"Gross Reservation Revenue\s+\$([\d,]+\.\d{2})", line)
        if m:
            result["summary"]["gross_revenue"] = float(m.group(1).replace(",", ""))

        m = re.match(r"Less Management Commission\s+\(\$([\d,]+\.\d{2})\)", line)
        if m:
            result["summary"]["mgmt_commission"] = float(m.group(1).replace(",", ""))

        m = re.match(r"Owner Charges/Expenses\s+\(\$([\d,]+\.\d{2})\)", line)
        if m:
            result["summary"]["owner_charges"] = float(m.group(1).replace(",", ""))

        m = re.match(r"Balance as of \d{2}/\d{2}/\d{4} \(includes minimum", line)
        if m:
            amt_m = re.search(r'(\(?\$[\d,]+\.\d{2}\)?)\s*$', line)
            if amt_m:
                result["summary"]["ending_balance"] = _parse_amount(amt_m.group(1))

    res_section = re.search(
        r"Res #/Type\s+Guest\s+Start\s+End\s+Nights\s+Gross Rent\s+Mgmt Comm\s+Net Amount\s*\n(.*?)\nTotal",
        full_text,
        re.DOTALL,
    )
    if res_section:
        block = res_section.group(1).strip()
        joined = re.sub(r"\n(?!\d{4,6}\s)", " ", block)

        for line in joined.split("\n"):
            m = re.match(
                r"(\d{4,6})\s+\*?(\w+)\s+.*?"
                r"\$([0-9,]+\.\d{2})\s+"
                r"\(\$([0-9,]+\.\d{2})\)\s+"
                r"\$([0-9,]+\.\d{2})",
                line,
            )
            if m:
                result["reservations"].append({
                    "conf_code": m.group(1),
                    "res_type": m.group(2),
                    "pdf_gross_rent": float(m.group(3).replace(",", "")),
                    "pdf_mgmt_comm": float(m.group(4).replace(",", "")),
                    "pdf_net_amount": float(m.group(5).replace(",", "")),
                })
            else:
                m_zero = re.match(r"(\d{4,6})\s+\*?OWN\s+.*?\$0\.00\s+\$0\.00\s+\$0\.00", line)
                if m_zero:
                    result["reservations"].append({
                        "conf_code": m_zero.group(1),
                        "res_type": "OWN",
                        "pdf_gross_rent": 0.0,
                        "pdf_mgmt_comm": 0.0,
                        "pdf_net_amount": 0.0,
                    })

    return result


def _extract_unit_id_from_filename(filename: str) -> str:
    """Extract unit_id from filename like '2025-10_70220_23416304.pdf'."""
    parts = os.path.basename(filename).split("_")
    if len(parts) >= 2:
        return parts[1]
    return ""


def run_reconciliation():
    print("=" * 78)
    print("  VECTOR 4: STRANGLER RECONCILER -- FORENSIC VARIANCE ENGINE")
    print("=" * 78)

    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    all_pdfs = []
    for root, _, files in os.walk(NAS_STMT_DIR):
        for f in sorted(files):
            if f.endswith(".pdf"):
                all_pdfs.append(os.path.join(root, f))

    print(f"\n  Found {len(all_pdfs)} statement PDFs on NAS")
    print(f"  Iron Dome database: {DB_DSN.split('dbname=')[1].split(' ')[0]}")
    print()

    report = {
        "pdfs_scanned": 0,
        "pdfs_with_revenue": 0,
        "reservations_matched": 0,
        "reservations_with_variance": 0,
        "total_pdf_commission": 0.0,
        "total_iron_dome_commission": 0.0,
        "total_over_allocation": 0.0,
        "statements": [],
        "variances": [],
    }

    print(f"  {'PROPERTY':<28} {'PERIOD':<18} {'PDF GROSS':>12} {'PDF COMM':>12} {'DOME COMM':>12} {'VARIANCE':>12}")
    print("  " + "-" * 94)

    for pdf_path in all_pdfs:
        filename = os.path.basename(pdf_path)
        unit_id = _extract_unit_id_from_filename(filename)

        pdf_data = parse_streamline_pdf(pdf_path)
        report["pdfs_scanned"] += 1

        stmt_record = {
            "file": filename,
            "property": pdf_data["property_name"],
            "unit_id": unit_id,
            "period": f"{pdf_data['period_start']} - {pdf_data['period_end']}",
            "summary": pdf_data["summary"],
            "reservation_count": len(pdf_data["reservations"]),
            "revenue_reservations": 0,
            "reservation_details": [],
        }

        revenue_res = [r for r in pdf_data["reservations"] if r["pdf_gross_rent"] > 0]
        stmt_record["revenue_reservations"] = len(revenue_res)

        if not revenue_res:
            stmt_period = pdf_data["period_start"][:7].replace("/", "-") if pdf_data["period_start"] else "N/A"
            print(
                f"  {pdf_data['property_name'] or filename:<28} "
                f"{stmt_period:<18} "
                f"{'$0.00':>12} {'$0.00':>12} {'---':>12} {'N/A':>12}"
            )
            report["statements"].append(stmt_record)
            continue

        report["pdfs_with_revenue"] += 1

        stmt_pdf_comm = 0.0
        stmt_dome_comm = 0.0

        for res in revenue_res:
            conf_code = res["conf_code"]

            cur.execute("""
                SELECT jli.credit as dome_comm
                FROM journal_entries je
                JOIN journal_line_items jli ON jli.journal_entry_id = je.id
                JOIN accounts a ON a.id = jli.account_id
                WHERE je.reference_id = %s
                  AND je.reference_type = 'reservation_revenue'
                  AND a.code = '4100'
            """, (conf_code,))
            dome_row = cur.fetchone()

            cur.execute("""
                SELECT
                    r.total_amount,
                    r.cleaning_fee,
                    r.tax_amount,
                    r.damage_waiver_fee,
                    (r.streamline_financial_detail->>'price')::numeric as base_price,
                    r.streamline_financial_detail->'required_fees' as req_fees_json
                FROM reservations r
                JOIN properties p ON p.id = r.property_id
                WHERE r.confirmation_code = %s
                  AND p.streamline_property_id = %s
            """, (conf_code, unit_id))
            res_row = cur.fetchone()

            iron_dome_comm = float(dome_row["dome_comm"]) if dome_row else None

            additional_party = Decimal("0")
            if res_row and res_row["req_fees_json"]:
                try:
                    fees = res_row["req_fees_json"]
                    if isinstance(fees, str):
                        fees = json.loads(fees)
                    for fee in fees:
                        name = (fee.get("name") or "").lower()
                        if "additional party" in name:
                            additional_party += Decimal(str(fee.get("value", 0)))
                except (json.JSONDecodeError, TypeError):
                    pass

            base_price = Decimal(str(res_row["base_price"])) if res_row and res_row["base_price"] else Decimal("0")
            computed_gross_rent = float((base_price + additional_party).quantize(TWO))

            detail = {
                "conf_code": conf_code,
                "pdf_gross_rent": res["pdf_gross_rent"],
                "pdf_mgmt_comm": res["pdf_mgmt_comm"],
                "pdf_net_amount": res["pdf_net_amount"],
                "iron_dome_comm": iron_dome_comm,
                "db_total_amount": float(res_row["total_amount"]) if res_row else None,
                "db_base_price": float(base_price),
                "db_additional_party": float(additional_party),
                "computed_sl_gross_rent": computed_gross_rent,
                "gross_rent_match": abs(res["pdf_gross_rent"] - computed_gross_rent) < 0.02 if computed_gross_rent else None,
            }

            if iron_dome_comm is not None:
                variance = iron_dome_comm - res["pdf_mgmt_comm"]
                detail["variance"] = round(variance, 2)
                report["reservations_matched"] += 1
                report["total_pdf_commission"] += res["pdf_mgmt_comm"]
                report["total_iron_dome_commission"] += iron_dome_comm

                stmt_pdf_comm += res["pdf_mgmt_comm"]
                stmt_dome_comm += iron_dome_comm

                if abs(variance) > 0.01:
                    report["reservations_with_variance"] += 1
                    report["total_over_allocation"] += variance
                    report["variances"].append(detail)
            else:
                detail["variance"] = None
                detail["note"] = "No Iron Dome JE found"

            stmt_record["reservation_details"].append(detail)

        stmt_period = pdf_data["period_start"][:7].replace("/", "-") if pdf_data["period_start"] else "N/A"
        stmt_variance = stmt_dome_comm - stmt_pdf_comm
        status = "OK" if abs(stmt_variance) < 0.02 else f"+${stmt_variance:,.2f}"

        print(
            f"  {pdf_data['property_name']:<28} "
            f"{stmt_period:<18} "
            f"${pdf_data['summary']['gross_revenue']:>10,.2f} "
            f"${pdf_data['summary']['mgmt_commission']:>10,.2f} "
            f"${stmt_dome_comm:>10,.2f} "
            f"{'$' + f'{stmt_variance:,.2f}':>12}"
        )

        report["statements"].append(stmt_record)

    conn.close()

    print()
    print("=" * 78)
    print("  VARIANCE REPORT SUMMARY")
    print("=" * 78)
    print(f"  PDFs Scanned:                  {report['pdfs_scanned']}")
    print(f"  Statements with Revenue:       {report['pdfs_with_revenue']}")
    print(f"  Reservations Matched:          {report['reservations_matched']}")
    print(f"  Reservations with Variance:    {report['reservations_with_variance']}")
    print(f"  Total PDF Commission (SL):     ${report['total_pdf_commission']:>12,.2f}")
    print(f"  Total Iron Dome Commission:    ${report['total_iron_dome_commission']:>12,.2f}")
    print(f"  TOTAL OVER-ALLOCATION:         ${report['total_over_allocation']:>12,.2f}")
    print()

    if report["variances"]:
        print("  TOP VARIANCES BY RESERVATION:")
        print(f"  {'CONF':>6} {'PDF GROSS':>12} {'PDF COMM':>12} {'DOME COMM':>12} {'VARIANCE':>12}")
        print("  " + "-" * 54)
        sorted_var = sorted(report["variances"], key=lambda x: abs(x.get("variance", 0)), reverse=True)
        for v in sorted_var[:20]:
            print(
                f"  {v['conf_code']:>6} "
                f"${v['pdf_gross_rent']:>10,.2f} "
                f"${v['pdf_mgmt_comm']:>10,.2f} "
                f"${v['iron_dome_comm']:>10,.2f} "
                f"${v['variance']:>10,.2f}"
            )

    print()
    if report["total_over_allocation"] > 0.01:
        print("  FINDING: The Iron Dome over-allocates PM commission because it")
        print("  calculates 35% on (total_amount - tax), which includes cleaning")
        print("  fees, damage waivers, processing fees, and DOT tax. Streamline")
        print("  only commissions base rent + additional party fees.")
        print(f"\n  Corrective journal entry needed: ${report['total_over_allocation']:,.2f}")
    elif report["reservations_matched"] > 0:
        print("  FINDING: Iron Dome commission matches Streamline ground truth.")
    else:
        print("  FINDING: No revenue reservations could be matched. Check PDF parsing.")

    print("=" * 78)

    out_path = os.path.join(os.path.dirname(__file__), "variance_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Full audit report saved: {out_path}")


if __name__ == "__main__":
    run_reconciliation()
