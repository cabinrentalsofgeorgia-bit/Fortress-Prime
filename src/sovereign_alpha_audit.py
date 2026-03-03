"""
Sovereign Alpha Audit — The Brain Reads the Vault
==================================================
Division B (Hedge Fund): R1 reasons over extracted market signals.

MISSION:
    Feed the hedge_fund.market_signals dataset into the Sovereign (DeepSeek R1)
    and ask: "Which signal sources actually predicted price movements?"
    Turns raw ticker tape into Alpha — actionable intelligence for the fund.

FLOW:
    1. Query PostgreSQL: aggregates by source_sender, action, signal_type, time.
    2. Build a structured summary (no raw 18k rows — R1 gets a digest).
    3. Call Captain (DeepSeek-R1) with the Audit prompt.
    4. Persist the Sovereign's response to hedge_fund.sovereign_audit + NAS log.

RUN:
    python3 -m src.sovereign_alpha_audit              # One-shot audit
    python3 -m src.sovereign_alpha_audit --dry-run    # Build digest only, no R1 call

CRON (recommended after Trader backfill):
    0 7 * * 1-5  cd /home/admin/Fortress-Prime && python3 -m src.sovereign_alpha_audit >> /mnt/fortress_nas/fortress_data/ai_brain/logs/sovereign_alpha_audit.log 2>&1
"""

import os
import sys
import re
import json
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import psycopg2

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("ADMIN_DB_USER") or os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("ADMIN_DB_PASS") or os.getenv("DB_PASS", "")

CAPTAIN_IP = os.getenv("CAPTAIN_IP", "192.168.0.100")
CAPTAIN_CHAT = f"http://{CAPTAIN_IP}:11434/api/chat"
CAPTAIN_MODEL = os.getenv("CAPTAIN_MODEL", "deepseek-r1:70b")
BRAIN_NIM_BASE = os.getenv("BRAIN_NIM_URL", f"http://{CAPTAIN_IP}:8010")
BRAIN_CHAT = BRAIN_NIM_BASE + "/v1/chat/completions"
BRAIN_MODEL = os.getenv("BRAIN_MODEL", "Qwen/Qwen3-32B")

LOG_DIR = Path(os.getenv("FORTRESS_LOG_DIR", "/mnt/fortress_nas/fortress_data/ai_brain/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sovereign_alpha_audit")

# -----------------------------------------------------------------------------
# Audit prompt — R1's job
# -----------------------------------------------------------------------------
AUDIT_SYSTEM_PROMPT = """You are the Sovereign Analyst for a private hedge fund. Your role is Capital Preservation and Alpha Generation.

You have been given a digest of market signals extracted from emails (Trade Triangle alerts, Seeking Alpha, brokerage notices, etc.). The digest includes:
- Which senders produced the most signals
- The mix of BUY vs SELL vs WATCH
- Average confidence and sentiment by source
- Top tickers and signal types

TASK:
1. Identify which signal SOURCES (senders/domains) are most credible — e.g. which ones tend to have high confidence and coherent sentiment.
2. Note which sources appear noisy or contradictory (many signals but low average confidence or mixed BUY/SELL on the same ticker).
3. Recommend 1–3 concrete actions: e.g. "Weight MarketClub Red Triangles more when confidence > 75%", "Ignore source X for ticker Y", "Create a watchlist rule for Z".
4. If the data is too sparse or recent, say so and recommend when to re-run the audit (e.g. after 1,000+ signals).

Respond in clear sections: SOURCES TO TRUST, SOURCES TO DOWNWEIGHT, RECOMMENDED ACTIONS, and DATA QUALITY NOTE. Be concise. No <think> tags."""


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def ensure_audit_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hedge_fund.sovereign_audit (
            id SERIAL PRIMARY KEY,
            signal_count INT,
            digest_summary TEXT,
            prompt_snapshot TEXT,
            response_text TEXT,
            model_used VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()


def build_digest(conn) -> str:
    """Aggregate hedge_fund.market_signals into a short text digest for R1."""
    cur = conn.cursor()

    # Total signals
    cur.execute("SELECT COUNT(*) FROM hedge_fund.market_signals")
    total = cur.fetchone()[0]

    if total == 0:
        cur.close()
        return "No signals in the vault yet. Run the Trader Rig (mining_rig_trader) to backfill."

    lines = [
        f"Total signals in vault: {total}",
        "",
        "--- BY SOURCE SENDER (top 15) ---",
    ]

    cur.execute("""
        SELECT source_sender, COUNT(*) AS cnt,
               ROUND(AVG(confidence_score)::numeric, 1) AS avg_conf,
               ROUND(AVG(sentiment_score)::numeric, 3) AS avg_sent,
               COUNT(CASE WHEN action = 'BUY' THEN 1 END) AS buys,
               COUNT(CASE WHEN action = 'SELL' THEN 1 END) AS sells,
               COUNT(CASE WHEN action = 'WATCH' THEN 1 END) AS watches
        FROM hedge_fund.market_signals
        WHERE source_sender IS NOT NULL
        GROUP BY source_sender
        ORDER BY cnt DESC
        LIMIT 15
    """)
    for row in cur.fetchall():
        sender = (row[0] or "unknown")[:50]
        cnt, avg_conf, avg_sent, buys, sells, watches = row[1], row[2], row[3], row[4], row[5], row[6]
        lines.append(f"  {sender}: signals={cnt}, avg_conf={avg_conf}%, avg_sent={avg_sent}, BUY={buys} SELL={sells} WATCH={watches}")

    lines.append("")
    lines.append("--- BY ACTION ---")
    cur.execute("""
        SELECT action, COUNT(*), ROUND(AVG(confidence_score)::numeric, 1), ROUND(AVG(sentiment_score)::numeric, 3)
        FROM hedge_fund.market_signals GROUP BY action ORDER BY COUNT(*) DESC
    """)
    for row in cur.fetchall():
        lines.append(f"  {row[0]}: {row[1]} signals, avg_conf={row[2]}%, avg_sent={row[3]}")

    lines.append("")
    lines.append("--- TOP TICKERS (by volume) ---")
    cur.execute("""
        SELECT ticker, COUNT(*) AS cnt FROM hedge_fund.market_signals
        GROUP BY ticker ORDER BY cnt DESC LIMIT 20
    """)
    tickers = ", ".join(f"{r[0]}({r[1]})" for r in cur.fetchall())
    lines.append(f"  {tickers}")

    lines.append("")
    lines.append("--- SIGNAL TYPES ---")
    cur.execute("""
        SELECT COALESCE(signal_type, 'Unknown'), COUNT(*) FROM hedge_fund.market_signals
        GROUP BY signal_type ORDER BY COUNT(*) DESC LIMIT 10
    """)
    for row in cur.fetchall():
        lines.append(f"  {row[0]}: {row[1]}")

    cur.close()
    return "\n".join(lines)


def captain_think_ollama(prompt: str, system_role: str, temperature: float = 0.3) -> str:
    """Call Captain Ollama /api/chat (DeepSeek-R1)."""
    import requests
    payload = {
        "model": CAPTAIN_MODEL,
        "messages": [
            {"role": "system", "content": system_role},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        r = requests.post(CAPTAIN_CHAT, json=payload, timeout=300)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    except Exception as e:
        log.warning(f"Ollama call failed: {e}")
        return ""


def captain_think_nim(prompt: str, system_role: str, temperature: float = 0.3) -> str:
    """Call Captain NIM (OpenAI-compatible)."""
    import requests
    payload = {
        "model": BRAIN_MODEL,
        "messages": [
            {"role": "system", "content": system_role},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    try:
        r = requests.post(BRAIN_CHAT, json=payload, timeout=300)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"NIM call failed: {e}")
        return ""


def captain_think(prompt: str, system_role: str, temperature: float = 0.3) -> tuple:
    """Try config.captain_think, then NIM, then Ollama. Returns (response_text, model_used)."""
    try:
        from config import captain_think as cfg_think
        out = cfg_think(prompt, system_role=system_role, temperature=temperature)
        return (out, getattr(sys.modules.get("config"), "CAPTAIN_MODEL", CAPTAIN_MODEL))
    except ImportError:
        pass

    text = captain_think_nim(prompt, system_role, temperature)
    if text:
        return (text, BRAIN_MODEL)

    text = captain_think_ollama(prompt, system_role, temperature)
    if text:
        return (text, CAPTAIN_MODEL)

    return ("", "none")


def strip_think_tags(raw: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def run_audit(dry_run: bool = False) -> None:
    conn = get_db_connection()
    ensure_audit_table(conn)

    digest = build_digest(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM hedge_fund.market_signals")
    signal_count = cur.fetchone()[0]
    cur.close()
    log.info("Digest built (%s chars)", len(digest))

    if dry_run:
        log.info("DRY RUN — digest only (no R1 call):\n%s", digest[:2000])
        conn.close()
        return

    user_prompt = (
        "Below is a digest of all market signals currently in the Alpha Vault.\n"
        "Analyze it and produce the Sovereign Alpha Audit (SOURCES TO TRUST, SOURCES TO DOWNWEIGHT, RECOMMENDED ACTIONS, DATA QUALITY NOTE).\n\n"
        "--- DIGEST ---\n"
        + digest
    )

    log.info("Calling Sovereign (R1)...")
    response, model_used = captain_think(user_prompt, AUDIT_SYSTEM_PROMPT, temperature=0.3)
    response = strip_think_tags(response)

    if not response:
        log.error("No response from Sovereign")
        conn.close()
        return

    log.info("Sovereign responded (%s chars, model=%s)", len(response), model_used)

    # Persist
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO hedge_fund.sovereign_audit
            (signal_count, digest_summary, prompt_snapshot, response_text, model_used)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            signal_count,
            digest[:10000],
            user_prompt[:15000],
            response[:50000],
            model_used,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()

    # Also append to log file for easy reading
    audit_log = LOG_DIR / "sovereign_alpha_audit_latest.txt"
    with open(audit_log, "w") as f:
        f.write(f"# Sovereign Alpha Audit — {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Model: {model_used}\n\n")
        f.write(response)
    log.info("Audit written to %s", audit_log)


def main():
    p = argparse.ArgumentParser(description="Sovereign Alpha Audit — R1 reasons over the Alpha Vault")
    p.add_argument("--dry-run", action="store_true", help="Build digest only, no R1 call")
    args = p.parse_args()

    log.info("=" * 60)
    log.info("  SOVEREIGN ALPHA AUDIT — The Brain Reads the Vault")
    log.info("=" * 60)
    run_audit(dry_run=args.dry_run)
    log.info("Done.")


if __name__ == "__main__":
    main()
