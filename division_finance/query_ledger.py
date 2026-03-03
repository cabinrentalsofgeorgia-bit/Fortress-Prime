"""
Fortress Prime — DIVISION FINANCE: "Ledger" Query Interface
============================================================
The Sovereign CFO. Ask questions about your financial empire.

Can operate standalone (SQL queries) or with AI analysis
(DeepSeek-R1 interprets results in context of tax law).

Usage:
    python division_finance/query_ledger.py --summary
    python division_finance/query_ledger.py --cabins
    python division_finance/query_ledger.py --year 2024
    python division_finance/query_ledger.py --ask "How much did we spend on repairs?"
    python division_finance/query_ledger.py --war-chest
"""
import os
import sys
import json
import sqlite3
import requests

sys.stdout.reconfigure(line_buffering=True)

# --- CONFIG ---
DB_FILE = os.path.join(os.path.dirname(__file__), "fortress_ledger.db")
R1_URL = "http://localhost:11434/api/generate"
R1_MODEL = "deepseek-r1:8b"

# Optionally link to legal ChromaDB for tax law context
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "division_legal", "chroma_db")


def get_conn():
    if not os.path.exists(DB_FILE):
        print("   Ledger database not found. Run ingest_ledger.py first.")
        sys.exit(1)
    return sqlite3.connect(DB_FILE)


def summary():
    """Executive summary of the entire financial database."""
    conn = get_conn()
    c = conn.cursor()

    print("\n" + "=" * 70)
    print("  LEDGER — EXECUTIVE FINANCIAL SUMMARY")
    print("=" * 70)

    c.execute("SELECT COUNT(*) FROM general_ledger")
    total = c.fetchone()[0]
    print(f"\n  Total documents indexed: {total:,}")

    # Revenue by cabin
    print(f"\n  {'PROPERTY':<30} {'INVOICES':>8} {'RECEIPTS':>8}")
    print(f"  {'-'*48}")
    c.execute("""
        SELECT cabin,
               SUM(CASE WHEN doc_type = 'Invoice' THEN 1 ELSE 0 END) as invoices,
               SUM(CASE WHEN doc_type IN ('Receipt', 'Sales_Receipt') THEN 1 ELSE 0 END) as receipts
        FROM general_ledger
        WHERE cabin IS NOT NULL
        GROUP BY cabin ORDER BY invoices DESC
    """)
    for cabin, inv, rec in c.fetchall():
        print(f"  {cabin:<30} {inv:>8,} {rec:>8,}")

    # Tax filings
    print(f"\n  TAX DOCUMENTS:")
    c.execute("""
        SELECT doc_type, COUNT(*) FROM general_ledger
        WHERE category = 'Tax_Filing'
        GROUP BY doc_type ORDER BY COUNT(*) DESC
    """)
    for dtype, count in c.fetchall():
        print(f"    {dtype:<30} {count:>5}")

    # Revenue total
    c.execute("""
        SELECT SUM(amount) FROM general_ledger
        WHERE amount IS NOT NULL AND category = 'Rental_Income'
    """)
    rev = c.fetchone()[0]
    if rev:
        print(f"\n  💰 DETECTED RENTAL REVENUE: ${rev:,.2f}")

    c.execute("""
        SELECT SUM(amount) FROM general_ledger
        WHERE amount IS NOT NULL AND category = 'Operating_Expense'
    """)
    exp = c.fetchone()[0]
    if exp:
        print(f"  📉 DETECTED EXPENSES:        ${exp:,.2f}")
        if rev:
            print(f"  📊 NET (detected):           ${rev - exp:,.2f}")

    print(f"\n{'='*70}\n")
    conn.close()


def by_cabin():
    """Detailed breakdown per cabin property."""
    conn = get_conn()
    c = conn.cursor()

    print("\n" + "=" * 70)
    print("  LEDGER — PROPERTY PORTFOLIO ANALYSIS")
    print("=" * 70)

    c.execute("""
        SELECT cabin, COUNT(*),
               SUM(CASE WHEN doc_type = 'Invoice' THEN 1 ELSE 0 END),
               SUM(CASE WHEN doc_type IN ('Receipt', 'Sales_Receipt') THEN 1 ELSE 0 END),
               MIN(date_detected), MAX(date_detected)
        FROM general_ledger
        WHERE cabin IS NOT NULL
        GROUP BY cabin ORDER BY COUNT(*) DESC
    """)
    results = c.fetchall()

    for cabin, total, inv, rec, min_yr, max_yr in results:
        period = f"{min_yr or '?'} - {max_yr or '?'}"
        print(f"\n  📍 {cabin}")
        print(f"     Total docs: {total:,}  |  Invoices: {inv:,}  |  Receipts: {rec:,}")
        print(f"     Period: {period}")

    print(f"\n{'='*70}\n")
    conn.close()


def by_year(year):
    """Show all documents for a specific tax year."""
    conn = get_conn()
    c = conn.cursor()

    print(f"\n  LEDGER — TAX YEAR {year}")
    print(f"  {'-'*50}")

    c.execute("""
        SELECT doc_type, COUNT(*), SUM(amount)
        FROM general_ledger
        WHERE date_detected = ?
        GROUP BY doc_type ORDER BY COUNT(*) DESC
    """, (str(year),))

    for dtype, count, total in c.fetchall():
        total_str = f"${total:,.2f}" if total else "N/A"
        print(f"  {dtype:<25} {count:>6} docs    {total_str:>15}")

    conn.close()


def ai_ask(question):
    """Ask Ledger a natural language question about your finances."""
    conn = get_conn()
    c = conn.cursor()

    # Gather context from the database
    c.execute("SELECT COUNT(*) FROM general_ledger")
    total = c.fetchone()[0]

    c.execute("""
        SELECT doc_type, COUNT(*), SUM(amount)
        FROM general_ledger GROUP BY doc_type ORDER BY COUNT(*) DESC LIMIT 15
    """)
    type_breakdown = "\n".join([
        f"  {r[0]}: {r[1]} docs, total_amount=${r[2] or 0:,.2f}" for r in c.fetchall()
    ])

    c.execute("""
        SELECT cabin, COUNT(*), SUM(amount)
        FROM general_ledger WHERE cabin IS NOT NULL
        GROUP BY cabin ORDER BY COUNT(*) DESC LIMIT 15
    """)
    cabin_breakdown = "\n".join([
        f"  {r[0]}: {r[1]} docs, revenue=${r[2] or 0:,.2f}" for r in c.fetchall()
    ])

    c.execute("""
        SELECT date_detected, COUNT(*), SUM(amount)
        FROM general_ledger WHERE date_detected IS NOT NULL
        GROUP BY date_detected ORDER BY date_detected
    """)
    year_breakdown = "\n".join([
        f"  {r[0]}: {r[1]} docs, ${r[2] or 0:,.2f}" for r in c.fetchall()
    ])

    # Try to get tax law context from legal division
    tax_context = ""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_collection("law_library")
        # Get embedding
        embed_res = requests.post("http://localhost:11434/api/embeddings", json={
            "model": "nomic-embed-text:latest",
            "prompt": question
        }, timeout=10)
        if embed_res.status_code == 200:
            embedding = embed_res.json().get("embedding")
            results = collection.query(query_embeddings=[embedding], n_results=3)
            if results and results["documents"]:
                tax_context = "\n\n".join(results["documents"][0])
    except Exception:
        tax_context = "(Tax code not yet indexed. Run Title 48 ingestion.)"

    prompt = f"""[SYSTEM]
You are LEDGER, the Sovereign CFO of Fortress Prime. You manage the financial
intelligence for a cabin rental company (Cabin Rentals of Georgia / CROG).
Answer the question using ONLY the data provided. Be precise. Cite numbers.

[FINANCIAL DATABASE OVERVIEW]
Total documents: {total:,}

Document Types:
{type_breakdown}

Properties (Cabins):
{cabin_breakdown}

By Year:
{year_breakdown}

[RELEVANT TAX LAW (O.C.G.A.)]
{tax_context[:1500]}

[QUESTION]
{question}"""

    print(f"\n  💰 LEDGER ANALYSIS: {question}")
    print(f"  {'-'*60}\n")

    payload = {
        "model": R1_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1000}
    }

    try:
        res = requests.post(R1_URL, json=payload, timeout=300)
        if res.status_code == 200:
            response = res.json().get("response", "")
            if "<think>" in response:
                parts = response.split("</think>")
                response = parts[-1].strip() if len(parts) > 1 else response
            print(response)
        else:
            print(f"  (AI returned HTTP {res.status_code})")
    except Exception as e:
        print(f"  (AI error: {e})")

    print(f"\n  {'-'*60}\n")
    conn.close()


def war_chest():
    """Estimate the total liquid capital based on detected amounts."""
    conn = get_conn()
    c = conn.cursor()

    print("\n" + "=" * 70)
    print("  LEDGER — WAR CHEST ANALYSIS")
    print("=" * 70)

    c.execute("""
        SELECT category, SUM(amount), COUNT(amount)
        FROM general_ledger WHERE amount IS NOT NULL
        GROUP BY category ORDER BY SUM(amount) DESC
    """)
    results = c.fetchall()

    total_in = 0
    total_out = 0
    for cat, total, count in results:
        prefix = "+" if cat in ("Rental_Income", "Financial") else "-"
        print(f"  {prefix} {cat:<25} ${total:>14,.2f}  ({count:,} entries)")
        if cat in ("Rental_Income", "Financial"):
            total_in += total
        else:
            total_out += total

    print(f"\n  {'='*50}")
    print(f"  GROSS INCOME (detected):  ${total_in:>14,.2f}")
    print(f"  EXPENSES (detected):      ${total_out:>14,.2f}")
    print(f"  NET POSITION (detected):  ${total_in - total_out:>14,.2f}")
    print(f"\n  ⚠️  These numbers are from AI-extracted amounts only.")
    print(f"     Run --phase2 on more PDFs to improve accuracy.")
    print(f"\n{'='*70}\n")
    conn.close()


def main():
    if "--summary" in sys.argv:
        summary()
    elif "--cabins" in sys.argv:
        by_cabin()
    elif "--year" in sys.argv:
        idx = sys.argv.index("--year")
        by_year(sys.argv[idx + 1])
    elif "--ask" in sys.argv:
        idx = sys.argv.index("--ask")
        question = " ".join(sys.argv[idx + 1:])
        ai_ask(question)
    elif "--war-chest" in sys.argv:
        war_chest()
    else:
        print("\nUsage:")
        print("  --summary              Executive financial summary")
        print("  --cabins               Per-property breakdown")
        print("  --year 2024            Documents for tax year")
        print("  --ask 'question'       Ask Ledger anything (AI-powered)")
        print("  --war-chest            Capital position analysis")
        summary()


if __name__ == "__main__":
    main()
