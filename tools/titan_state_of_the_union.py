#!/usr/bin/env python3
"""
FORTRESS PRIME — TITAN State of the Union Briefing
====================================================
Deep cross-sector analysis using TITAN-tuned context injection.
Connects to all sectors, collects metrics, and generates a comprehensive
executive briefing through the DeepSeek-R1 reasoning engine.

In SWARM mode, uses qwen2.5:7b for a faster (less deep) briefing.
In TITAN mode, uses DeepSeek-R1-671B for strategic-depth analysis.

Usage:
    ./venv/bin/python tools/titan_state_of_the_union.py           # Full briefing
    ./venv/bin/python tools/titan_state_of_the_union.py --quick   # Metrics only
    ./venv/bin/python tools/titan_state_of_the_union.py --save    # Save to NAS
"""

import json
import os
import sys
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_inference_client, FORTRESS_DEFCON

log = logging.getLogger("fortress.briefing")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BRIEF] %(message)s")

DB_CONFIG = {"dbname": os.getenv("DB_NAME", "fortress_db"), "user": os.getenv("LEGAL_DB_USER", "admin")}


def collect_metrics() -> dict:
    """Collect cross-sector metrics for the briefing."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    metrics = {"timestamp": datetime.now(timezone.utc).isoformat(), "sectors": {}}

    # Email stats
    cur.execute("SELECT count(*) as total FROM email_archive")
    metrics["email_total"] = cur.fetchone()["total"]
    cur.execute("""
        SELECT division, count(*) as cnt
        FROM email_archive WHERE division IS NOT NULL
        GROUP BY division ORDER BY cnt DESC
    """)
    metrics["email_by_division"] = {r["division"]: r["cnt"] for r in cur.fetchall()}

    # Finance
    cur.execute("SELECT count(*) as total, sum(amount) as total_amount FROM finance_invoices")
    row = cur.fetchone()
    metrics["sectors"]["comp"] = {
        "invoices": row["total"],
        "total_amount": float(row["total_amount"]) if row["total_amount"] else 0,
    }

    cur.execute("""
        SELECT classification, count(*) as cnt
        FROM finance.vendor_classifications
        GROUP BY classification ORDER BY cnt DESC LIMIT 10
    """)
    metrics["sectors"]["comp"]["top_classifications"] = {r["classification"]: r["cnt"] for r in cur.fetchall()}

    # Legal
    cur.execute("SELECT case_name, status, case_number FROM legal.cases")
    metrics["sectors"]["legal"] = {
        "cases": [dict(r) for r in cur.fetchall()],
    }
    cur.execute("SELECT count(*) as cnt FROM legal.case_evidence")
    metrics["sectors"]["legal"]["evidence_count"] = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) as cnt FROM legal.case_watchdog WHERE is_active = true")
    metrics["sectors"]["legal"]["active_watchdog_terms"] = cur.fetchone()["cnt"]

    # Market intel
    cur.execute("SELECT count(*) as cnt FROM hedge_fund.market_signals")
    metrics["sectors"]["comp"]["market_signals"] = cur.fetchone()["cnt"]

    cur.close()
    conn.close()
    return metrics


def generate_briefing(metrics: dict, use_llm: bool = True) -> str:
    """Generate the State of the Union briefing."""
    context = json.dumps(metrics, indent=2, default=str)

    if not use_llm:
        return f"FORTRESS PRIME — State of the Union (Metrics Only)\n{'='*60}\n{context}"

    system_prompt = (
        "You are the Titan Executive — the Sovereign AI overseeing all divisions of "
        "Fortress Prime, a vertically-integrated holding company. You are generating "
        "the daily State of the Union briefing for the CEO (Gary M. Knight).\n\n"
        "Be concise, strategic, and direct. Highlight:\n"
        "1. Key metrics and trends\n"
        "2. Legal exposure and deadlines\n"
        "3. Financial health indicators\n"
        "4. Operational risks and opportunities\n"
        "5. Recommended actions for the next 24 hours\n\n"
        f"Current DEFCON mode: {FORTRESS_DEFCON}"
    )

    user_prompt = (
        f"Generate the State of the Union briefing based on these live metrics:\n\n{context}\n\n"
        "Format as a professional executive briefing with sections."
    )

    client, model = get_inference_client()
    log.info(f"Generating briefing via {model} ({FORTRESS_DEFCON} mode)...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        return response.choices[0].message.content or "Briefing generation failed."
    except Exception as e:
        log.error(f"LLM failed: {e}")
        return f"BRIEFING GENERATION FAILED: {e}\n\nRaw metrics:\n{context}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Titan State of the Union")
    parser.add_argument("--quick", action="store_true", help="Metrics only, no LLM")
    parser.add_argument("--save", action="store_true", help="Save to logs/")
    args = parser.parse_args()

    log.info("Collecting cross-sector metrics...")
    metrics = collect_metrics()

    briefing = generate_briefing(metrics, use_llm=not args.quick)
    print(briefing)

    if args.save:
        out_dir = Path(__file__).resolve().parent.parent / "logs"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"briefing_{datetime.now().strftime('%Y%m%d')}.md"
        with open(out_path, "w") as f:
            f.write(briefing)
        log.info(f"Saved to {out_path}")
