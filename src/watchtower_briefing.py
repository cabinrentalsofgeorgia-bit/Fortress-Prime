"""
PROJECT WATCHTOWER: THE MORNING INTERROGATION
===============================================
The Senior Partner doesn't read spreadsheets. He throws them on the desk
and asks: "Why is Riverview down 15%? Are we priced wrong, or is the hot
tub broken?"

This is not a report generator. This is a strategic intelligence engine
that INTERROGATES the data, finds the GAPS and RISKS, and delivers a set
of hard questions to the Managing Partner's inbox every morning.

Three Intelligence Streams:
    1. FINANCIAL — Shadow Ledger: Revenue, gaps, silent properties
    2. OPERATIONS — Groundskeeper: Turnovers, unassigned tasks, risks
    3. LEGAL — The Docket: Open matters, stale cases, exposure

Synthesizer:
    DeepSeek-R1:70b (Senior Partner) analyzes all streams and drafts
    The Morning Interrogation — questions that demand answers.

Delivery:
    - Markdown archive: logs/briefing_YYYYMMDD.md
    - HTML email: cabin.rentals.of.georgia@gmail.com

Schedule:
    0 6 * * *  (Every morning at 06:00)

Usage:
    python3 -m src.watchtower_briefing           # Full briefing + email
    python3 -m src.watchtower_briefing --dry-run  # Print only, no email
    python3 -m src.watchtower_briefing --no-ai    # Data only, skip R1

Module: CF-01 Guardian Ops — Project Watchtower
"""

import os
import re
import sys
import json
import time
import smtplib
import argparse
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests as http_requests

try:
    from dotenv import load_dotenv
    load_dotenv("/home/admin/Fortress-Prime/.env")
except ImportError:
    pass

# =============================================================================
# CONFIG
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHTOWER] %(message)s",
)
log = logging.getLogger("watchtower")

PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", "5432"))
PG_DB = os.getenv("DB_NAME", "fortress_db")
PG_USER = os.getenv("DB_USER", "miner_bot")
PG_PASS = os.getenv("DB_PASSWORD", "")

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

OLLAMA_URL = os.getenv("LLM_URL", "http://localhost:11434/api/chat")
MODEL = "deepseek-r1:70b"  # Full 70b — the Senior Partner doesn't send a clerk

LOCAL_LOGS = Path("/home/admin/Fortress-Prime/logs")
NAS_LOGS = Path("/mnt/fortress_nas/fortress_data/ai_brain/logs/watchtower")


def get_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def dec(val):
    """Safely convert Decimal/None to float."""
    if val is None:
        return 0.0
    return float(val)


# =============================================================================
# STREAM 1: FINANCIAL INTELLIGENCE (The Shadow Ledger)
# =============================================================================

def collect_financial_intel():
    """Revenue, rankings, silent assets, concentration risk."""
    log.info("Stream 1: Scanning Shadow Ledger...")
    conn = get_db()
    cur = conn.cursor()

    # Portfolio totals
    cur.execute("""
        SELECT COALESCE(SUM(total_revenue), 0) as total_revenue,
               COALESCE(SUM(base_rent), 0) as gross_rent,
               COALESCE(SUM(nights), 0) as total_nights,
               COUNT(*) as total_bookings
        FROM fin_reservations
        WHERE status != 'Cancelled'
    """)
    portfolio = dict(cur.fetchone())

    # Per-property performance (ranked by revenue)
    cur.execute("""
        SELECT property_name, bedrooms, estimated_rate,
               total_booked_nights, gross_revenue,
               mgmt_fee_amount, owner_payout
        FROM fin_owner_balances
        ORDER BY gross_revenue DESC
    """)
    ranked_properties = [dict(r) for r in cur.fetchall()]

    # ALL properties — find the silent ones
    cur.execute("""
        SELECT p.property_id, p.internal_name, p.bedrooms
        FROM ops_properties p
        WHERE p.property_id NOT IN (
            SELECT DISTINCT property_id FROM fin_reservations
            WHERE status != 'Cancelled'
        )
        ORDER BY p.internal_name
    """)
    raw_silent = [dict(r) for r in cur.fetchall()]

    # Check ops_overrides — separate suppressed from truly silent
    cur.execute("""
        SELECT entity_id, reason, override_type, effective_until
        FROM ops_overrides
        WHERE entity_type = 'property'
          AND active = TRUE
          AND (effective_until IS NULL OR effective_until > NOW())
    """)
    overrides = {r["entity_id"]: dict(r) for r in cur.fetchall()}

    silent_properties = []     # Genuinely alarming — no override
    suppressed_properties = [] # Silenced by Commander — known reason
    for p in raw_silent:
        pid = p["property_id"]
        if pid in overrides:
            p["override_reason"] = overrides[pid]["reason"]
            p["override_type"] = overrides[pid]["override_type"]
            p["override_until"] = overrides[pid].get("effective_until")
            suppressed_properties.append(p)
        else:
            silent_properties.append(p)

    # Revenue concentration
    total_rev = dec(portfolio["gross_rent"]) or 1
    top3 = ranked_properties[:3]
    top3_rev = sum(dec(p["gross_revenue"]) for p in top3)
    concentration_pct = round(top3_rev / total_rev * 100, 1)

    # Bottom performers (lowest revenue, still active)
    bottom3 = ranked_properties[-3:] if len(ranked_properties) >= 3 else ranked_properties

    mgmt_total = sum(dec(p["mgmt_fee_amount"]) for p in ranked_properties)
    owner_total = sum(dec(p["owner_payout"]) for p in ranked_properties)

    conn.close()

    return {
        "portfolio": portfolio,
        "ranked_properties": ranked_properties,
        "top_performers": top3,
        "bottom_performers": bottom3,
        "silent_properties": silent_properties,
        "suppressed_properties": suppressed_properties,
        "concentration_pct": concentration_pct,
        "mgmt_total": mgmt_total,
        "owner_total": owner_total,
        "active_count": len(ranked_properties),
        "silent_count": len(silent_properties),
        "suppressed_count": len(suppressed_properties),
    }


# =============================================================================
# STREAM 2: OPERATIONS INTELLIGENCE (The Groundskeeper)
# =============================================================================

def collect_ops_intel():
    """Turnovers, open tasks, unassigned work, overdue items."""
    log.info("Stream 2: Scanning Operations...")
    conn = get_db()
    cur = conn.cursor()

    now = datetime.now()
    week_out = now + timedelta(days=7)

    # Upcoming turnovers (next 7 days)
    cur.execute("""
        SELECT t.id, t.property_id, t.checkout_time, t.checkin_time,
               t.window_hours, t.status, t.cleanliness_score,
               p.internal_name as property_name
        FROM ops_turnovers t
        LEFT JOIN ops_properties p ON t.property_id = p.property_id
        WHERE t.checkout_time BETWEEN %s AND %s
        ORDER BY t.checkout_time
    """, (now, week_out))
    upcoming_turnovers = [dict(r) for r in cur.fetchall()]

    # Open tasks (not completed)
    cur.execute("""
        SELECT tk.id, tk.type, tk.priority, tk.property_id, tk.assigned_to,
               tk.description, tk.deadline, tk.status,
               p.internal_name as property_name
        FROM ops_tasks tk
        LEFT JOIN ops_properties p ON tk.property_id = p.property_id
        WHERE tk.status NOT IN ('COMPLETED', 'CANCELLED')
        ORDER BY
            CASE tk.priority
                WHEN 'URGENT' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'NORMAL' THEN 3
                WHEN 'LOW' THEN 4
            END,
            tk.deadline
    """)
    open_tasks = [dict(r) for r in cur.fetchall()]

    # Unassigned tasks
    unassigned = [t for t in open_tasks if not t["assigned_to"]]

    # Overdue tasks
    overdue = [t for t in open_tasks if t["deadline"] and t["deadline"] < now]

    # Urgent tasks
    urgent = [t for t in open_tasks if t["priority"] == "URGENT"]

    conn.close()

    return {
        "upcoming_turnovers": upcoming_turnovers,
        "open_tasks": open_tasks,
        "unassigned_tasks": unassigned,
        "overdue_tasks": overdue,
        "urgent_tasks": urgent,
        "total_open": len(open_tasks),
        "total_unassigned": len(unassigned),
    }


# =============================================================================
# STREAM 3: LEGAL INTELLIGENCE (The Docket)
# =============================================================================

def collect_legal_intel():
    """Open matters, priority, stale cases, recent activity."""
    log.info("Stream 3: Scanning Legal Docket...")
    conn = get_db()
    cur = conn.cursor()

    # Open matters with priority ranking
    cur.execute("""
        SELECT m.matter_id, m.title, m.practice_area, m.status,
               m.priority, m.updated_at, c.name as client_name
        FROM legal_matters m
        LEFT JOIN legal_clients c ON m.client_id = c.client_id
        WHERE m.status = 'Open'
        ORDER BY
            CASE m.priority WHEN 'Critical' THEN 1
                WHEN 'High' THEN 2 WHEN 'Normal' THEN 3
                WHEN 'Low' THEN 4 END,
            m.updated_at DESC
    """)
    active_matters = [dict(r) for r in cur.fetchall()]

    # Stale matters (no notes in 14+ days)
    stale_cutoff = date.today() - timedelta(days=14)
    stale_matters = []
    for m in active_matters:
        cur.execute("""
            SELECT MAX(created_at) as last_note
            FROM legal_matter_notes WHERE matter_id = %s
        """, (m["matter_id"],))
        row = cur.fetchone()
        last_note = row["last_note"] if row else None
        if last_note is None or last_note.date() < stale_cutoff:
            m["days_stale"] = (date.today() - last_note.date()).days if last_note else 999
            stale_matters.append(m)

    # Recent notes (last 7 days)
    week_ago = date.today() - timedelta(days=7)
    cur.execute("""
        SELECT n.matter_id, n.agent, n.content, n.note_type, n.created_at,
               m.title as matter_title
        FROM legal_matter_notes n
        JOIN legal_matters m ON n.matter_id = m.matter_id
        WHERE n.created_at >= %s
        ORDER BY n.created_at DESC LIMIT 10
    """, (week_ago,))
    recent_notes = [dict(r) for r in cur.fetchall()]

    # Docket items
    cur.execute("SELECT COUNT(*) as cnt FROM legal_docket")
    docket_count = cur.fetchone()["cnt"]

    conn.close()

    high_priority = [m for m in active_matters if m["priority"] in ("Critical", "High")]

    return {
        "active_matters": active_matters,
        "stale_matters": stale_matters,
        "high_priority": high_priority,
        "recent_notes": recent_notes,
        "docket_count": docket_count,
    }


# =============================================================================
# STREAM 4: PRICING INTELLIGENCE (QuantRevenue CF-02)
# =============================================================================

def collect_pricing_intel():
    """Latest QuantRevenue rate card signals and revenue delta."""
    log.info("Stream 4: Scanning QuantRevenue...")
    conn = get_db()
    cur = conn.cursor()

    try:
        # Find the latest v2.0+ engine run
        cur.execute("""
            SELECT run_id, MAX(generated_at) as last_run
            FROM revenue_ledger
            WHERE engine_version >= '2.0.0'
            GROUP BY run_id
            ORDER BY last_run DESC LIMIT 1
        """)
        latest = cur.fetchone()
        if not latest:
            conn.close()
            return {"available": False}

        run_id = latest["run_id"]
        last_run = latest["last_run"]

        # Get all future-dated rate entries for this run
        cur.execute("""
            SELECT cabin_name, target_date, target_dow, base_rate,
                   adjusted_rate, rate_change_pct, trading_signal,
                   confidence, event_name, tier
            FROM revenue_ledger
            WHERE run_id = %s AND target_date >= CURRENT_DATE
            ORDER BY cabin_name, target_date
        """, (run_id,))
        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            conn.close()
            return {"available": False}

        # Aggregate per-property
        properties = {}
        for r in rows:
            name = r["cabin_name"]
            if name not in properties:
                properties[name] = {
                    "name": name,
                    "base_rate": float(r["base_rate"]),
                    "tier": r["tier"],
                    "rates": [],
                    "signals": {},
                }
            p = properties[name]
            p["rates"].append(float(r["adjusted_rate"]))
            sig = r["trading_signal"]
            p["signals"][sig] = p["signals"].get(sig, 0) + 1

        # Compute summaries
        total_base = 0
        total_optimized = 0
        buy_properties = []
        sell_properties = []
        signal_counts = {"STRONG_BUY": 0, "BUY": 0, "HOLD": 0, "SELL": 0, "STRONG_SELL": 0}

        for name, p in properties.items():
            n = len(p["rates"])
            avg_rate = sum(p["rates"]) / n
            p["avg_rate"] = round(avg_rate, 2)
            p["period_base"] = round(p["base_rate"] * n, 2)
            p["period_optimized"] = round(sum(p["rates"]), 2)
            p["delta"] = round(p["period_optimized"] - p["period_base"], 2)
            p["dominant_signal"] = max(p["signals"], key=p["signals"].get) if p["signals"] else "HOLD"

            total_base += p["period_base"]
            total_optimized += p["period_optimized"]
            signal_counts[p["dominant_signal"]] = signal_counts.get(p["dominant_signal"], 0) + 1

            if p["dominant_signal"] in ("STRONG_BUY", "BUY"):
                buy_properties.append(p)
            elif p["dominant_signal"] in ("SELL", "STRONG_SELL"):
                sell_properties.append(p)

        conn.close()

        return {
            "available": True,
            "run_id": run_id,
            "last_run": str(last_run),
            "properties": properties,
            "total_base": round(total_base, 2),
            "total_optimized": round(total_optimized, 2),
            "portfolio_delta": round(total_optimized - total_base, 2),
            "signal_counts": signal_counts,
            "buy_properties": buy_properties,
            "sell_properties": sell_properties,
            "total_priced": len(properties),
        }

    except Exception as e:
        log.warning(f"Pricing intel error: {e}")
        conn.close()
        return {"available": False}


# =============================================================================
# STREAM 5: MARKET EMAIL INTELLIGENCE (CF-02 — Email Archive)
# =============================================================================

def collect_market_email_intel():
    """
    Scans email_archive for recent Market Club signals, trade alerts,
    and key market intelligence from the IMAP pipeline.
    Feeds into the Morning Interrogation so R1 can factor market moves
    into property pricing and strategic decisions.
    """
    log.info("Stream 5: Scanning Market Email Intelligence...")
    conn = get_db()
    cur = conn.cursor()

    try:
        # Total archive stats
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE is_mined = TRUE) as mined,
                   COUNT(*) FILTER (WHERE is_mined = FALSE) as unmined,
                   MAX(sent_at) as latest_email
            FROM email_archive
            WHERE category = 'Market Intelligence'
        """)
        stats = dict(cur.fetchone())

        # Last 24 hours: key market senders and their signals
        cur.execute("""
            SELECT sender, subject, sent_at
            FROM email_archive
            WHERE category = 'Market Intelligence'
              AND sent_at >= NOW() - INTERVAL '24 hours'
            ORDER BY sent_at DESC
            LIMIT 50
        """)
        recent_emails = [dict(r) for r in cur.fetchall()]

        # Trade Triangle alerts (MarketClub core signals) from last 48 hours
        cur.execute("""
            SELECT subject, sent_at
            FROM email_archive
            WHERE category = 'Market Intelligence'
              AND sent_at >= NOW() - INTERVAL '48 hours'
              AND (subject ILIKE '%Trade Triangle%' OR subject ILIKE '%Alert%')
              AND sender ILIKE '%marketclub%'
            ORDER BY sent_at DESC
            LIMIT 20
        """)
        trade_triangles = [dict(r) for r in cur.fetchall()]

        # Key market senders activity (last 24h)
        cur.execute("""
            SELECT
                CASE
                    WHEN sender ILIKE '%marketclub%' OR sender ILIKE '%ino.com%' THEN 'MarketClub'
                    WHEN sender ILIKE '%seekingalpha%' THEN 'Seeking Alpha'
                    WHEN sender ILIKE '%goldfix%' THEN 'GoldFix'
                    WHEN sender ILIKE '%carnivoretrading%' THEN 'Carnivore Trading'
                    WHEN sender ILIKE '%patreon%' AND sender ILIKE '%market%' THEN 'MarketMaestro'
                    WHEN sender ILIKE '%analystratings%' THEN 'Analyst Ratings'
                    WHEN sender ILIKE '%investors.com%' THEN 'IBD'
                    WHEN sender ILIKE '%coinbits%' THEN 'Coinbits'
                    WHEN sender ILIKE '%substack%' THEN 'Substack Finance'
                    ELSE 'Other'
                END as source_group,
                COUNT(*) as cnt
            FROM email_archive
            WHERE category = 'Market Intelligence'
              AND sent_at >= NOW() - INTERVAL '24 hours'
            GROUP BY source_group
            ORDER BY cnt DESC
        """)
        source_activity = [dict(r) for r in cur.fetchall()]

        # Extracted trade signals (from Mining Rig)
        cur.execute("""
            SELECT ticker, action, price, confidence_score, created_at
            FROM market_signals
            WHERE ticker IS NOT NULL
              AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        recent_signals = [dict(r) for r in cur.fetchall()]

        # Pipeline health: is IMAP ingestion current?
        pipeline_stale = False
        if stats["latest_email"]:
            hours_since_last = (datetime.now() - stats["latest_email"]).total_seconds() / 3600
            pipeline_stale = hours_since_last > 6  # Alert if no email in 6+ hours

        conn.close()

        return {
            "available": True,
            "total_archive": stats["total"],
            "mined": stats["mined"],
            "unmined": stats["unmined"],
            "latest_email": stats["latest_email"],
            "pipeline_stale": pipeline_stale,
            "recent_emails_24h": recent_emails,
            "trade_triangles_48h": trade_triangles,
            "source_activity": source_activity,
            "recent_signals": recent_signals,
            "email_count_24h": len(recent_emails),
        }

    except Exception as e:
        log.warning(f"Market email intel error: {e}")
        conn.close()
        return {"available": False}


# =============================================================================
# STREAM 6: COUNCIL INTELLIGENCE (Council of Giants)
# =============================================================================

def collect_council_intel():
    """
    Run a fast Council vote on overnight macro conditions.
    Returns consensus signal, top bulls/bears, and dissenter analysis.
    """
    log.info("Stream 6: Polling Council of Giants...")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from persona_template import Persona, Council

        slugs = sorted(Persona.list_all())
        if not slugs:
            log.warning("No personas found — skipping Council intelligence")
            return {"available": False, "reason": "no_personas"}

        personas = [Persona.load(s) for s in slugs]
        council = Council(personas)

        event = (
            f"Overnight market conditions {datetime.now().strftime('%Y-%m-%d')}: "
            "Summarize positioning based on current macro signals — "
            "rates, equities, crypto, commodities, real estate sentiment."
        )

        t0 = time.time()
        result = council.vote_on(event, model="qwen2.5:7b")
        elapsed = time.time() - t0

        # Sort by conviction for top bulls/bears
        opinions = result.get("opinions", [])
        bulls = sorted(
            [o for o in opinions if o.get("signal") in ("BUY", "STRONG_BUY")],
            key=lambda x: x.get("conviction", 0), reverse=True
        )
        bears = sorted(
            [o for o in opinions if o.get("signal") in ("SELL", "STRONG_SELL")],
            key=lambda x: x.get("conviction", 0), reverse=True
        )

        return {
            "available": True,
            "consensus_signal": result.get("consensus_signal", "NEUTRAL"),
            "conviction": round(result.get("consensus_conviction", 0), 2),
            "agreement_rate": round(result.get("agreement_rate", 0) * 100, 1),
            "bullish_count": result.get("bullish_count", 0),
            "bearish_count": result.get("bearish_count", 0),
            "neutral_count": result.get("neutral_count", 0),
            "top_bulls": [
                {"name": o["persona"], "reasoning": o.get("reasoning", "")[:120]}
                for o in bulls[:2]
            ],
            "top_bears": [
                {"name": o["persona"], "reasoning": o.get("reasoning", "")[:120]}
                for o in bears[:2]
            ],
            "dissenters": [
                {"name": o["persona"], "signal": o["signal"],
                 "reasoning": o.get("reasoning", "")[:100]}
                for o in result.get("dissenters", [])[:2]
            ],
            "elapsed_seconds": round(elapsed, 1),
            "total_voters": result.get("total_voters", 0),
        }

    except Exception as e:
        log.error(f"Council intelligence failed: {e}")
        return {"available": False, "reason": str(e)}


# =============================================================================
# SYSTEM HEALTH
# =============================================================================

def collect_system_health():
    log.info("Checking system health...")
    health = {"chromadb": False, "ollama": False, "vectors": 0, "tunnel": None}
    try:
        r = http_requests.get("http://localhost:8002/api/v2/heartbeat", timeout=5)
        health["chromadb"] = r.status_code == 200
        r2 = http_requests.get(
            "http://localhost:8002/api/v2/tenants/default_tenant/databases/default_database/"
            "collections/dd96e5dd-679f-4b83-9579-fef9eb83ea02/count", timeout=10)
        if r2.status_code == 200:
            health["vectors"] = int(r2.text)
    except Exception:
        pass
    try:
        r = http_requests.get("http://localhost:11434/api/tags", timeout=5)
        health["ollama"] = r.status_code == 200
    except Exception:
        pass

    # Cloudflare Tunnel health
    try:
        from config import tunnel_status
        tun = tunnel_status()
        health["tunnel"] = tun
        health["tunnel_up"] = tun["status"] in ("OPERATIONAL", "DEGRADED")
        log.info(f"Tunnel: {tun['status']} (service={tun['service']}, "
                 f"id={tun['tunnel_id'][:12]}...)")
    except Exception as e:
        log.warning(f"Tunnel health check failed: {e}")
        health["tunnel_up"] = False

    return health


# =============================================================================
# THE SENIOR PARTNER (DeepSeek-R1:70b)
# =============================================================================

def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def consult_senior_partner(fin, ops, legal, pricing=None, market_emails=None, council=None):
    """
    Feed all intelligence streams to R1.
    Instruction: Find the weak points. Ask the hard questions.
    """
    log.info(f"Waking the Senior Partner ({MODEL})...")

    # ── Build the intelligence dossier ──
    report_date = datetime.now().strftime("%Y-%m-%d")
    portfolio = fin["portfolio"]

    dossier = f"CURRENT DATE: {report_date}\n\n"

    # Financial
    dossier += "═══ FINANCIAL INTELLIGENCE (Shadow Ledger) ═══\n"
    dossier += f"Gross Rent on Books: ${dec(portfolio['gross_rent']):,.2f}\n"
    dossier += f"Total Revenue (incl. tax/cleaning): ${dec(portfolio['total_revenue']):,.2f}\n"
    dossier += f"Total Booked Nights: {portfolio['total_nights']}\n"
    dossier += f"Active Bookings: {portfolio['total_bookings']}\n"
    dossier += f"CROG Management Fees: ${fin['mgmt_total']:,.2f}\n"
    dossier += f"Owner Payouts: ${fin['owner_total']:,.2f}\n"
    dossier += f"Revenue Concentration: Top 3 properties = {fin['concentration_pct']}% of revenue\n\n"

    dossier += "PROPERTY PERFORMANCE (ranked by revenue):\n"
    for i, p in enumerate(fin["ranked_properties"]):
        dossier += (f"  #{i+1} {p['property_name']} ({p['bedrooms']}BR) — "
                    f"${dec(p['gross_revenue']):,.2f} gross, "
                    f"{p['total_booked_nights']} nights, "
                    f"${dec(p['estimated_rate']):,.0f}/night\n")

    dossier += f"\nSILENT PROPERTIES ($0 REVENUE — NO BOOKINGS — UNEXPLAINED):\n"
    if fin["silent_properties"]:
        for p in fin["silent_properties"]:
            br = f"{p['bedrooms']}BR" if p['bedrooms'] else "Unknown size"
            dossier += f"  ⚠ {p['internal_name']} ({br}) — ZERO bookings, NO OVERRIDE\n"
    else:
        dossier += "  None — all silent assets have been accounted for.\n"

    if fin.get("suppressed_properties"):
        dossier += f"\nSUPPRESSED PROPERTIES (Commander Override — Known Reason):\n"
        for p in fin["suppressed_properties"]:
            br = f"{p['bedrooms']}BR" if p['bedrooms'] else "Unknown size"
            reason = p.get("override_reason", "No reason given")
            until = p.get("override_until")
            until_str = f" until {until.strftime('%b %d')}" if until else " (permanent)"
            dossier += f"  ✓ {p['internal_name']} ({br}) — {reason}{until_str}\n"

    # Pricing Intelligence (QuantRevenue)
    if pricing and pricing.get("available"):
        dossier += f"\n═══ PRICING INTELLIGENCE (QuantRevenue Engine) ═══\n"
        dossier += f"Engine Run: {pricing['last_run']}\n"
        dossier += f"Properties Priced: {pricing['total_priced']}\n"
        dossier += f"Portfolio Base Revenue (period): ${pricing['total_base']:,.2f}\n"
        dossier += f"Optimized Revenue (period): ${pricing['total_optimized']:,.2f}\n"
        dossier += f"Portfolio Delta: ${pricing['portfolio_delta']:+,.2f}\n"
        sc = pricing["signal_counts"]
        dossier += f"Signal Distribution: STRONG_BUY={sc.get('STRONG_BUY',0)}, BUY={sc.get('BUY',0)}, HOLD={sc.get('HOLD',0)}, SELL={sc.get('SELL',0)}, STRONG_SELL={sc.get('STRONG_SELL',0)}\n"

        if pricing["buy_properties"]:
            dossier += "\nUNDERPRICED — RAISE RATES (BUY/STRONG_BUY):\n"
            buy_uplift = 0
            for p in pricing["buy_properties"]:
                dossier += (f"  ▲ {p['name'].replace('_', ' ').title()} — "
                            f"base ${p['base_rate']}/night, avg recommended ${p['avg_rate']}/night, "
                            f"signal: {p['dominant_signal']}\n")
                buy_uplift += p.get("delta", 0)
            if buy_uplift > 0:
                dossier += f"  → Uplift if accepted: +${buy_uplift:,.0f} for the forecast period\n"

        if pricing["sell_properties"]:
            dossier += "\nOVERPRICED / LOW DEMAND — CONSIDER DISCOUNTS (SELL/STRONG_SELL):\n"
            for p in pricing["sell_properties"]:
                dossier += (f"  ▼ {p['name'].replace('_', ' ').title()} — "
                            f"base ${p['base_rate']}/night, avg recommended ${p['avg_rate']}/night, "
                            f"signal: {p['dominant_signal']}, period delta: ${p['delta']:+,.0f}\n")

        # Revenue uplift potential — total benefit of accepting all recommendations
        portfolio_delta = pricing['portfolio_delta']
        dossier += f"\nREVENUE UPLIFT POTENTIAL:\n"
        dossier += f"  If ALL QuantRevenue recommendations are accepted: ${portfolio_delta:+,.0f} vs. base rates\n"
        dossier += f"  Base revenue (period): ${pricing['total_base']:,.0f} → Optimized: ${pricing['total_optimized']:,.0f}\n"

    # Market Email Intelligence
    if market_emails and market_emails.get("available"):
        dossier += f"\n═══ MARKET EMAIL INTELLIGENCE (CF-02 Email Pipeline) ═══\n"
        dossier += f"Archive: {market_emails['total_archive']:,} total emails\n"
        dossier += f"Emails (last 24h): {market_emails['email_count_24h']}\n"
        dossier += f"Latest Email: {market_emails['latest_email']}\n"
        if market_emails["pipeline_stale"]:
            dossier += f"⚠ PIPELINE STALE — No new emails in 6+ hours. Check IMAP ingestion.\n"

        if market_emails.get("trade_triangles_48h"):
            dossier += "\nMARKETCLUB TRADE TRIANGLE ALERTS (48h):\n"
            for tt in market_emails["trade_triangles_48h"]:
                dossier += f"  {tt['sent_at'].strftime('%b %d %H:%M')} — {tt['subject']}\n"

        if market_emails.get("source_activity"):
            dossier += "\nMARKET SOURCE ACTIVITY (24h):\n"
            for sa in market_emails["source_activity"]:
                if sa["source_group"] != "Other":
                    dossier += f"  {sa['source_group']}: {sa['cnt']} emails\n"

        if market_emails.get("recent_signals"):
            dossier += "\nEXTRACTED TRADE SIGNALS (Mining Rig, 7 days):\n"
            for sig in market_emails["recent_signals"]:
                price_str = f"${float(sig['price']):.2f}" if sig.get("price") else "N/A"
                dossier += f"  {sig['ticker']} {sig['action']} @ {price_str} (confidence: {sig.get('confidence_score', 'N/A')})\n"

    # Operations
    dossier += f"\n═══ OPERATIONS INTELLIGENCE (Groundskeeper) ═══\n"
    dossier += f"Open Tasks: {ops['total_open']}\n"
    dossier += f"Unassigned Tasks: {ops['total_unassigned']}\n"
    dossier += f"Overdue Tasks: {len(ops['overdue_tasks'])}\n"
    dossier += f"Urgent Tasks: {len(ops['urgent_tasks'])}\n"
    dossier += f"Upcoming Turnovers (7 days): {len(ops['upcoming_turnovers'])}\n"

    if ops["upcoming_turnovers"]:
        dossier += "\nNEXT 7 DAYS TURNOVER SCHEDULE:\n"
        for t in ops["upcoming_turnovers"]:
            name = t["property_name"] or t["property_id"]
            co = t["checkout_time"].strftime("%b %d %H:%M") if t["checkout_time"] else "TBD"
            ci = t["checkin_time"].strftime("%H:%M") if t["checkin_time"] else "TBD"
            dossier += f"  {name}: checkout {co}, check-in {ci} ({t['status']})\n"

    if ops["unassigned_tasks"]:
        dossier += f"\nUNASSIGNED TASKS (NO CREW MEMBER):\n"
        for t in ops["unassigned_tasks"][:10]:
            name = t["property_name"] or t["property_id"]
            deadline = t["deadline"].strftime("%b %d") if t["deadline"] else "No deadline"
            dossier += f"  [{t['priority']}] {name}: {t['description']} (due {deadline})\n"

    # Legal
    dossier += f"\n═══ LEGAL INTELLIGENCE (The Docket) ═══\n"
    dossier += f"Open Matters: {len(legal['active_matters'])}\n"
    dossier += f"High Priority: {len(legal['high_priority'])}\n"
    dossier += f"Work Product Items: {legal['docket_count']}\n"

    if legal["active_matters"]:
        dossier += "\nACTIVE CASES:\n"
        for m in legal["active_matters"]:
            dossier += f"  [{m['priority']}] {m['title']} ({m['practice_area']}) — {m['matter_id']}\n"

    if legal["stale_matters"]:
        dossier += "\n⚠ STALE CASES (NO ACTIVITY IN 14+ DAYS):\n"
        for m in legal["stale_matters"]:
            dossier += f"  {m['title']} — {m['days_stale']} days since last note\n"

    # Council Intelligence
    if council and council.get("available"):
        dossier += f"\n═══ COUNCIL INTELLIGENCE (Council of Giants — {council['total_voters']} Personas) ═══\n"
        dossier += f"Consensus Signal: {council['consensus_signal']} "
        dossier += f"(Conviction: {council['conviction']:.0%}, Agreement: {council['agreement_rate']}%)\n"
        dossier += f"Bullish: {council['bullish_count']}  Bearish: {council['bearish_count']}  Neutral: {council['neutral_count']}\n"
        if council.get("top_bulls"):
            dossier += "Top Bulls:\n"
            for b in council["top_bulls"]:
                dossier += f"  {b['name']}: {b['reasoning']}\n"
        if council.get("top_bears"):
            dossier += "Top Bears:\n"
            for b in council["top_bears"]:
                dossier += f"  {b['name']}: {b['reasoning']}\n"
        if council.get("dissenters"):
            dossier += "Key Dissenters:\n"
            for d in council["dissenters"]:
                dossier += f"  {d['name']} ({d['signal']}): {d['reasoning']}\n"

    # ── The Prompt ──
    system_prompt = """You are the Senior Managing Partner and Chief Strategy Officer of Cabin Rentals of Georgia, a vacation rental management firm.

Your job is NOT to summarize data. Your job is to INTERROGATE the owner (Gary M. Knight).

THINKING PROCESS:
1. ANALYZE the financial data. Is revenue growing or concentrated? Which assets are underperforming?
2. IDENTIFY "Silent" properties — assets generating $0. Are they mothballed? Mispriced? Broken?
3. REVIEW the QuantRevenue pricing signals. Are we overpriced in this season? Which properties need rate adjustments? Is the engine recommending BUY (raise rates) or SELL (discount to fill)?
4. REVIEW MARKET EMAIL INTELLIGENCE — What are MarketClub Trade Triangles signaling? Are gold/crypto/equities flashing BUY or SELL? How do macro moves (Fed, GDP, inflation) affect Blue Ridge tourism and property demand? Connect market signals to pricing strategy.
5. REVIEW operations — are turnovers covered? Tasks assigned? Anything falling through cracks?
6. AUDIT the legal docket — any stale cases where liability is festering?
7. FIND the anomalies, gaps, and risks that the numbers don't scream about.

OUTPUT FORMAT (use exactly these headers):

## 1. THE STATE OF THE UNION
(2-3 sentences. The health of the firm. Be blunt. Cite specific numbers.)

## 2. EXHAUSTIVE THREAT ASSESSMENT
(Bullet points. Revenue gaps. Silent properties. Operational risks. Legal exposure. Unassigned work. Concentration risk. Name specific properties and specific dollar amounts.)

## 3. STRATEGIC INTERROGATION (THE MORNING QUESTIONS)
(3-5 hard, specific questions directed at Gary. These should force decisions. Not "how is business?" but "Why has Restoration Luxury generated $0 in February? Is this a deliberate hold or a $2,500/week leak?")

## 4. RECOMMENDED ACTIONS
(2-3 immediate tactical moves the firm should make THIS WEEK.)

ADDRESS THE OWNER AS "GARY". Be direct. No corporate fluff. No compliments. Numbers only."""

    user_prompt = f"""Analyze this intelligence dossier and deliver The Morning Interrogation.

{dossier}

Be exhaustive. Miss nothing. Ask the questions Gary doesn't want to hear."""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 4096},
    }

    try:
        t0 = time.time()
        resp = http_requests.post(OLLAMA_URL, json=payload, timeout=1800)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        answer = strip_think_tags(raw)
        elapsed = time.time() - t0
        log.info(f"Senior Partner delivered in {elapsed:.1f}s")
        return answer
    except Exception as e:
        log.error(f"Senior Partner failed: {e}")
        return None


# =============================================================================
# ARCHIVE
# =============================================================================

def archive_report(report_text, fin, ops, legal, report_date):
    """Save to local markdown + NAS audit log."""
    # Local markdown (for dashboard pickup)
    LOCAL_LOGS.mkdir(parents=True, exist_ok=True)
    md_file = LOCAL_LOGS / f"briefing_{report_date.strftime('%Y%m%d')}.md"
    with open(md_file, "w") as f:
        f.write(f"# Fortress JD — Morning Briefing\n")
        f.write(f"**{report_date.strftime('%A, %B %d, %Y %H:%M')}**\n\n")
        f.write(report_text or "_R1 was not consulted._")
    log.info(f"Archived: {md_file}")

    # NAS audit JSONL
    try:
        NAS_LOGS.mkdir(parents=True, exist_ok=True)
        entry = {
            "date": report_date.isoformat(),
            "gross_rent": dec(fin["portfolio"]["gross_rent"]),
            "total_revenue": dec(fin["portfolio"]["total_revenue"]),
            "total_nights": fin["portfolio"]["total_nights"],
            "properties_active": fin["active_count"],
            "properties_silent": fin["silent_count"],
            "open_tasks": ops["total_open"],
            "unassigned_tasks": ops["total_unassigned"],
            "open_matters": len(legal["active_matters"]),
            "stale_matters": len(legal["stale_matters"]),
            "timestamp": datetime.now().isoformat(),
        }
        log_file = NAS_LOGS / f"briefings_{report_date.year}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# =============================================================================
# EMAIL DELIVERY
# =============================================================================

def _build_council_html(council):
    """Generate the Council Intelligence section for the morning email."""
    if not council or not council.get("available"):
        return ""

    sig = council["consensus_signal"]
    sig_color = "#22c55e" if "BUY" in sig else "#ef4444" if "SELL" in sig else "#f59e0b"
    conviction_pct = f"{council['conviction']:.0%}"

    bulls_html = ""
    for b in council.get("top_bulls", []):
        bulls_html += (
            f'<div style="padding:4px 0 4px 16px;color:#22c55e;font-size:13px;">'
            f'&#8226; <strong>{b["name"]}</strong>: {b["reasoning"]}</div>'
        )

    bears_html = ""
    for b in council.get("top_bears", []):
        bears_html += (
            f'<div style="padding:4px 0 4px 16px;color:#ef4444;font-size:13px;">'
            f'&#8226; <strong>{b["name"]}</strong>: {b["reasoning"]}</div>'
        )

    dissenters_html = ""
    for d in council.get("dissenters", []):
        dissenters_html += (
            f'<div style="padding:4px 0 4px 16px;color:#f59e0b;font-size:13px;">'
            f'&#8226; <strong>{d["name"]}</strong> ({d["signal"]}): {d["reasoning"]}</div>'
        )

    return f"""
  <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:24px;margin-bottom:20px;">
    <div style="font-size:11px;color:#a78bfa;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:16px;">
      Council Intelligence — {council['total_voters']} Personas Voted
    </div>
    <table style="width:100%;border-collapse:separate;border-spacing:6px;margin-bottom:16px;">
      <tr>
        <td style="background:#0a0e17;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Signal</div>
          <div style="font-size:20px;font-weight:900;color:{sig_color};margin-top:4px;">{sig}</div>
        </td>
        <td style="background:#0a0e17;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Conviction</div>
          <div style="font-size:20px;font-weight:900;color:#e2e8f0;margin-top:4px;">{conviction_pct}</div>
        </td>
        <td style="background:#0a0e17;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Agreement</div>
          <div style="font-size:20px;font-weight:900;color:#e2e8f0;margin-top:4px;">{council['agreement_rate']}%</div>
        </td>
        <td style="background:#0a0e17;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Bull/Bear</div>
          <div style="font-size:20px;font-weight:900;margin-top:4px;">
            <span style="color:#22c55e">{council['bullish_count']}</span>
            <span style="color:#475569">/</span>
            <span style="color:#ef4444">{council['bearish_count']}</span>
          </div>
        </td>
      </tr>
    </table>
    {f'<div style="margin-bottom:8px;font-size:12px;font-weight:700;color:#22c55e;">Top Bulls</div>{bulls_html}' if bulls_html else ''}
    {f'<div style="margin-top:8px;margin-bottom:8px;font-size:12px;font-weight:700;color:#ef4444;">Top Bears</div>{bears_html}' if bears_html else ''}
    {f'<div style="margin-top:8px;margin-bottom:8px;font-size:12px;font-weight:700;color:#f59e0b;">Key Dissenters</div>{dissenters_html}' if dissenters_html else ''}
    <div style="font-size:10px;color:#475569;margin-top:12px;text-align:right;">
      Computed in {council.get('elapsed_seconds', '--')}s via Hydra cluster
    </div>
  </div>"""


def send_briefing(subject, report_text, fin, ops, legal, health, report_date, pricing=None, council=None):
    """Format and deliver via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.warning("Email not configured")
        return False

    # Convert markdown-ish report to HTML
    html_report = ""
    if report_text:
        # Convert ## headers
        lines = report_text.split("\n")
        html_lines = []
        for line in lines:
            if line.startswith("## "):
                html_lines.append(
                    f'<h2 style="color:#a78bfa;font-size:16px;margin-top:24px;'
                    f'margin-bottom:12px;border-bottom:1px solid #334155;'
                    f'padding-bottom:8px;">{line[3:]}</h2>')
            elif line.startswith("- "):
                html_lines.append(
                    f'<div style="padding:4px 0 4px 16px;color:#e2e8f0;'
                    f'font-size:14px;line-height:1.6;">&#8226; {line[2:]}</div>')
            elif line.strip():
                html_lines.append(
                    f'<p style="color:#e2e8f0;font-size:14px;'
                    f'line-height:1.7;margin:8px 0;">{line}</p>')
        html_report = "\n".join(html_lines)

    # Quick stats bar
    p = fin["portfolio"]
    chroma_ok = health["chromadb"]
    status_dot = lambda ok: f'<span style="color:{"#22c55e" if ok else "#ef4444"};">{"●" if ok else "○"}</span>'
    rate_alerts = "N/A"
    if pricing and pricing.get("available"):
        sc = pricing.get("signal_counts", {})
        rate_alerts = sc.get("SELL", 0) + sc.get("STRONG_SELL", 0)

    tunnel_ok = health.get("tunnel_up", False)
    tunnel_label = "Tunnel"
    if health.get("tunnel") and health["tunnel"].get("tunnel_id"):
        tunnel_label = f"Tunnel ({health['tunnel']['tunnel_id'][:8]}...)"

    html = f"""<html>
<body style="margin:0;padding:0;background:#0a0e17;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;">
<div style="max-width:700px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:24px;margin-bottom:20px;">
    <div style="font-size:24px;font-weight:800;color:white;letter-spacing:-0.5px;">
      FORTRESS <span style="color:#3b82f6;">JD</span>
    </div>
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:2px;margin-top:2px;">
      The Morning Interrogation
    </div>
    <div style="margin-top:16px;font-size:12px;color:#94a3b8;">
      {report_date.strftime('%A, %B %d, %Y')} &nbsp;|&nbsp;
      {status_dot(health["chromadb"])} ChromaDB ({health['vectors']:,} vectors) &nbsp;|&nbsp;
      {status_dot(health["ollama"])} Ollama &nbsp;|&nbsp;
      {status_dot(tunnel_ok)} {tunnel_label}
    </div>
  </div>

  <!-- Quick Stats -->
  <table style="width:100%;border-collapse:separate;border-spacing:8px;margin-bottom:20px;">
    <tr>
      <td style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Revenue</div>
        <div style="font-size:22px;font-weight:800;color:#22c55e;margin-top:4px;">${dec(p['gross_rent']):,.0f}</div>
      </td>
      <td style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">CROG Fees</div>
        <div style="font-size:22px;font-weight:800;color:#3b82f6;margin-top:4px;">${fin['mgmt_total']:,.0f}</div>
      </td>
      <td style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Silent</div>
        <div style="font-size:22px;font-weight:800;color:#ef4444;margin-top:4px;">{fin['silent_count']}</div>
      </td>
      <td style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Open Tasks</div>
        <div style="font-size:22px;font-weight:800;color:#f59e0b;margin-top:4px;">{ops['total_open']}</div>
      </td>
      <td style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Rate Alerts</div>
        <div style="font-size:22px;font-weight:800;color:#f97316;margin-top:4px;">{rate_alerts}</div>
      </td>
    </tr>
  </table>

  <!-- R1 Analysis -->
  <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:24px;margin-bottom:20px;">
    <div style="font-size:11px;color:#a78bfa;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:16px;">
      Senior Partner Analysis — DeepSeek R1
    </div>
    {html_report if html_report else '<p style="color:#64748b;">R1 was not consulted.</p>'}
  </div>

  <!-- Council Intelligence -->
  {_build_council_html(council) if council and council.get("available") else ""}

  <!-- Footer -->
  <div style="text-align:center;padding:20px;font-size:11px;color:#475569;">
    Generated by Project Watchtower &nbsp;|&nbsp;
    <a href="http://192.168.0.100:9800" style="color:#3b82f6;text-decoration:none;">Command Center</a> &nbsp;|&nbsp;
    <a href="http://192.168.0.100:9800/intelligence" style="color:#3b82f6;text-decoration:none;">Intelligence</a>
  </div>

</div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Fortress JD — Senior Partner <{GMAIL_ADDRESS}>"
    msg["To"] = GMAIL_ADDRESS
    msg["Subject"] = subject

    # Plain text = raw report
    plain = f"FORTRESS JD — THE MORNING INTERROGATION\n"
    plain += f"{report_date.strftime('%A, %B %d, %Y')}\n"
    plain += "=" * 55 + "\n\n"
    plain += report_text or "R1 was not consulted.\n"
    plain += f"\n\nDashboard: http://192.168.0.100:8005\n"

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        log.info(f"Briefing delivered to {GMAIL_ADDRESS}")
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Project Watchtower — The Morning Interrogation")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no email")
    parser.add_argument("--no-ai", action="store_true", help="Data collection only, skip R1")
    args = parser.parse_args()

    report_date = datetime.now()

    log.info("=" * 55)
    log.info("  PROJECT WATCHTOWER — THE MORNING INTERROGATION")
    log.info(f"  {report_date.strftime('%A, %B %d, %Y %H:%M')}")
    log.info("=" * 55)

    # ── Gather all six intelligence streams ──
    fin = collect_financial_intel()
    ops = collect_ops_intel()
    legal = collect_legal_intel()
    pricing = collect_pricing_intel()
    market_emails = collect_market_email_intel()
    council = collect_council_intel()
    health = collect_system_health()

    log.info(f"Financial: ${dec(fin['portfolio']['gross_rent']):,.0f} revenue, "
             f"{fin['active_count']} active, {fin['silent_count']} silent")
    log.info(f"Operations: {ops['total_open']} tasks, {ops['total_unassigned']} unassigned, "
             f"{len(ops['upcoming_turnovers'])} turnovers this week")
    log.info(f"Legal: {len(legal['active_matters'])} open matters, "
             f"{len(legal['stale_matters'])} stale")
    if pricing.get("available"):
        log.info(f"Pricing: {pricing['total_priced']} properties priced, "
                 f"delta ${pricing['portfolio_delta']:+,.0f}, "
                 f"signals: {pricing['signal_counts']}")
    else:
        log.info("Pricing: No QuantRevenue data available")
    if market_emails.get("available"):
        log.info(f"Market Emails: {market_emails['email_count_24h']} in last 24h, "
                 f"{len(market_emails.get('trade_triangles_48h', []))} Trade Triangles, "
                 f"{market_emails['total_archive']:,} total archive")
    else:
        log.info("Market Emails: Pipeline not available")
    if council.get("available"):
        log.info(f"Council: {council['consensus_signal']} "
                 f"(conviction={council['conviction']:.0%}, "
                 f"agreement={council['agreement_rate']}%, "
                 f"bull={council['bullish_count']}/bear={council['bearish_count']})")
    else:
        log.info(f"Council: Not available ({council.get('reason', 'unknown')})")

    # ── Consult the Senior Partner ──
    report = None
    if not args.no_ai:
        report = consult_senior_partner(fin, ops, legal, pricing, market_emails, council)

    # ── Archive ──
    archive_report(report, fin, ops, legal, report_date)

    # ── Deliver ──
    pricing_tag = ""
    if pricing.get("available"):
        sc = pricing["signal_counts"]
        sells = sc.get("SELL", 0) + sc.get("STRONG_SELL", 0)
        if sells > 0:
            pricing_tag = f" | {sells} Rate Alerts"

    if report:
        subject = (f"Morning Interrogation | "
                   f"${dec(fin['portfolio']['gross_rent']):,.0f} Revenue | "
                   f"{fin['silent_count']} Silent{pricing_tag} | "
                   f"{report_date.strftime('%b %d')}")
    else:
        subject = (f"Watchtower Data Report | "
                   f"${dec(fin['portfolio']['gross_rent']):,.0f} Revenue | "
                   f"{report_date.strftime('%b %d')}")

    if args.dry_run:
        log.info("DRY RUN — no email sent")
        print()
        if report:
            print(report)
        else:
            print(f"Revenue: ${dec(fin['portfolio']['gross_rent']):,.2f}")
            print(f"Silent Properties: {fin['silent_count']}")
            print(f"Open Tasks: {ops['total_open']}")
            print(f"Open Matters: {len(legal['active_matters'])}")
            if pricing.get("available"):
                print(f"Pricing Delta: ${pricing['portfolio_delta']:+,.2f}")
                print(f"Rate Signals: {pricing['signal_counts']}")
    else:
        send_briefing(subject, report, fin, ops, legal, health, report_date, pricing, council)

    log.info("Watchtower complete.")


if __name__ == "__main__":
    main()
