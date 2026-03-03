#!/usr/bin/env python3
"""
FORTRESS PRIME — INTELLIGENCE SENTINEL
========================================
Event-driven trigger daemon that monitors market conditions and auto-triggers
Council votes when significant events are detected.

Trigger Sources:
    1. VIX level — polls yfinance; if VIX > 25, auto-trigger Council vote
    2. FRED rate decisions — polls FRED API on FOMC schedule days
    3. RSS breaking news — checks persona feeds every 30 minutes for breaking content
    4. Persona trigger_events — matches detected events to persona configs

Architecture:
    Runs as a persistent daemon (cron @reboot or systemd).
    Each trigger fires a Council vote via the intelligence_engine module,
    persists results to PostgreSQL, and optionally sends an alert email.

Usage:
    python3 -m src.intelligence_sentinel                # Run daemon
    python3 -m src.intelligence_sentinel --once         # Single poll cycle
    python3 -m src.intelligence_sentinel --check-vix    # VIX check only
    python3 -m src.intelligence_sentinel --check-fred   # FRED check only

Schedule (crontab):
    @reboot cd /home/admin/Fortress-Prime && python3 -m src.intelligence_sentinel >> /var/log/fortress/sentinel.log 2>&1
"""

import os
import sys
import json
import time
import logging
import argparse
import hashlib
import smtplib
from datetime import datetime, date, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import requests

# Add project paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SENTINEL] %(message)s",
)
log = logging.getLogger("sentinel")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

VIX_THRESHOLD = float(os.getenv("SENTINEL_VIX_THRESHOLD", "25"))
VIX_POLL_INTERVAL = int(os.getenv("SENTINEL_VIX_INTERVAL", "7200"))  # 2 hours
RSS_POLL_INTERVAL = int(os.getenv("SENTINEL_RSS_INTERVAL", "1800"))  # 30 minutes
FRED_POLL_INTERVAL = int(os.getenv("SENTINEL_FRED_INTERVAL", "7200"))  # 2 hours

STATE_DIR = Path("/home/admin/Fortress-Prime/data/sentinel")
STATE_DIR.mkdir(parents=True, exist_ok=True)

# FOMC meeting dates for 2025-2026 (update annually)
FOMC_DATES = {
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 17),
    # 2026
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 5, 6),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 16),
}

# RSS feeds to monitor for breaking content
MONITOR_FEEDS = [
    ("https://feeds.feedburner.com/zerohedge/feed", "ZeroHedge"),
    ("https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT Business"),
    ("https://feeds.bloomberg.com/markets/news.rss", "Bloomberg Markets"),
]

# Keywords that trigger automatic Council votes
BREAKING_KEYWORDS = [
    "rate cut", "rate hike", "emergency meeting", "bank failure",
    "black swan", "liquidity crisis", "default", "recession",
    "circuit breaker", "flash crash", "quantitative easing",
    "quantitative tightening", "yield curve", "inversion",
    "crypto crash", "bitcoin crash", "defi hack", "stablecoin depeg",
]


# ---------------------------------------------------------------------------
# State Management (dedup triggers)
# ---------------------------------------------------------------------------

def _state_file(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def _load_state(name: str) -> dict:
    f = _state_file(name)
    if f.exists():
        return json.loads(f.read_text())
    return {}


def _save_state(name: str, data: dict):
    _state_file(name).write_text(json.dumps(data, indent=2, default=str))


def _event_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _already_triggered(category: str, event_hash: str) -> bool:
    state = _load_state("triggers")
    triggered = state.get(category, {})
    today = date.today().isoformat()
    return triggered.get(event_hash) == today


def _mark_triggered(category: str, event_hash: str):
    state = _load_state("triggers")
    if category not in state:
        state[category] = {}
    state[category][event_hash] = date.today().isoformat()
    # Prune entries older than 7 days
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    state[category] = {k: v for k, v in state[category].items() if v >= cutoff}
    _save_state("triggers", state)


# ---------------------------------------------------------------------------
# VIX Monitor
# ---------------------------------------------------------------------------

def check_vix() -> dict:
    """Check current VIX level. Trigger if above threshold."""
    log.info("Checking VIX level...")
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1d")
        if hist.empty:
            return {"triggered": False, "reason": "no_data"}

        current_vix = float(hist["Close"].iloc[-1])
        log.info(f"VIX: {current_vix:.2f} (threshold: {VIX_THRESHOLD})")

        if current_vix > VIX_THRESHOLD:
            event = f"VIX spike alert: VIX at {current_vix:.1f} (above {VIX_THRESHOLD} threshold)"
            ehash = _event_hash(f"vix-{date.today()}-{int(current_vix)}")

            if _already_triggered("vix", ehash):
                return {"triggered": False, "reason": "already_triggered", "vix": current_vix}

            result = _fire_council_vote(event, f"VIX={current_vix:.2f}")
            _mark_triggered("vix", ehash)

            if GMAIL_ADDRESS:
                _send_alert(
                    f"VIX ALERT: {current_vix:.1f}",
                    f"VIX has spiked to {current_vix:.1f} (threshold: {VIX_THRESHOLD}).\n\n"
                    f"Council consensus: {result.get('consensus_signal', 'N/A')}\n"
                    f"Conviction: {result.get('consensus_conviction', 0):.0%}"
                )

            return {"triggered": True, "vix": current_vix, "result": result}

        return {"triggered": False, "vix": current_vix}

    except ImportError:
        log.warning("yfinance not installed — VIX monitoring disabled")
        return {"triggered": False, "reason": "yfinance_missing"}
    except Exception as e:
        log.error(f"VIX check failed: {e}")
        return {"triggered": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# FRED Rate Decision Monitor
# ---------------------------------------------------------------------------

def check_fred() -> dict:
    """Check FRED for rate decisions on FOMC days."""
    log.info("Checking FRED for rate decisions...")
    today = date.today()

    # Only check on FOMC days and the day after
    fomc_window = any(
        today == d or today == d + timedelta(days=1)
        for d in FOMC_DATES
    )

    if not fomc_window:
        return {"triggered": False, "reason": "not_fomc_day"}

    if not FRED_API_KEY:
        return {"triggered": False, "reason": "no_api_key"}

    try:
        # Fetch Federal Funds Rate (DFF)
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "DFF",
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])

        if len(observations) < 2:
            return {"triggered": False, "reason": "insufficient_data"}

        current_rate = float(observations[0]["value"])
        prev_rate = float(observations[1]["value"])
        change = current_rate - prev_rate

        log.info(f"Fed Funds Rate: {current_rate}% (prev: {prev_rate}%, change: {change:+.2f}%)")

        if abs(change) > 0.001:
            direction = "cut" if change < 0 else "hike"
            event = (
                f"FOMC rate decision: Fed {direction}s rates by {abs(change)*100:.0f}bps "
                f"to {current_rate:.2f}%"
            )
            ehash = _event_hash(f"fred-{today}-{current_rate}")

            if _already_triggered("fred", ehash):
                return {"triggered": False, "reason": "already_triggered"}

            result = _fire_council_vote(event, f"Previous rate: {prev_rate}%")
            _mark_triggered("fred", ehash)

            if GMAIL_ADDRESS:
                _send_alert(
                    f"FOMC: Rate {direction} to {current_rate}%",
                    f"The Fed has {direction} rates by {abs(change)*100:.0f}bps.\n"
                    f"New rate: {current_rate}%\n\n"
                    f"Council consensus: {result.get('consensus_signal', 'N/A')}"
                )

            return {"triggered": True, "rate": current_rate, "change": change, "result": result}

        return {"triggered": False, "rate": current_rate, "reason": "no_change"}

    except Exception as e:
        log.error(f"FRED check failed: {e}")
        return {"triggered": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# RSS Breaking News Monitor
# ---------------------------------------------------------------------------

def check_rss() -> dict:
    """Scan RSS feeds for breaking news matching trigger keywords."""
    log.info("Scanning RSS feeds for breaking news...")
    triggered_events = []

    try:
        import feedparser
    except ImportError:
        log.warning("feedparser not installed — RSS monitoring disabled")
        return {"triggered": False, "reason": "feedparser_missing"}

    for feed_url, feed_name in MONITOR_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = f"{title} {summary}".lower()

                matched = [kw for kw in BREAKING_KEYWORDS if kw in text]
                if not matched:
                    continue

                ehash = _event_hash(title)
                if _already_triggered("rss", ehash):
                    continue

                event = f"Breaking ({feed_name}): {title}"
                log.info(f"RSS trigger: {event[:80]} [keywords: {', '.join(matched)}]")

                result = _fire_council_vote(event[:300], f"Source: {feed_name}")
                _mark_triggered("rss", ehash)
                triggered_events.append({
                    "source": feed_name,
                    "title": title,
                    "keywords": matched,
                    "result": result,
                })

                if GMAIL_ADDRESS:
                    _send_alert(
                        f"BREAKING: {title[:60]}",
                        f"Source: {feed_name}\n{title}\n\n"
                        f"Matched keywords: {', '.join(matched)}\n"
                        f"Council consensus: {result.get('consensus_signal', 'N/A')}"
                    )

        except Exception as e:
            log.warning(f"RSS feed {feed_name} failed: {e}")

    return {
        "triggered": len(triggered_events) > 0,
        "events": triggered_events,
        "feeds_checked": len(MONITOR_FEEDS),
    }


# ---------------------------------------------------------------------------
# Council Vote Trigger
# ---------------------------------------------------------------------------

def _fire_council_vote(event: str, context: str = "") -> dict:
    """Fire a Council vote and persist the result."""
    try:
        from persona_template import Persona, Council

        slugs = sorted(Persona.list_all())
        if not slugs:
            log.warning("No personas — cannot fire Council vote")
            return {"error": "no_personas"}

        personas = [Persona.load(s) for s in slugs]
        council = Council(personas)

        result = council.vote_on(event, context=context, model="qwen2.5:7b")

        # Persist to database
        try:
            from intelligence_engine import _persist_vote
            import uuid
            vote_id = str(uuid.uuid4())
            _persist_vote(vote_id, result, "qwen2.5:7b")
            result["vote_id"] = vote_id
        except Exception as db_err:
            log.warning(f"Could not persist sentinel vote: {db_err}")

        return result

    except Exception as e:
        log.error(f"Council vote failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Alert Email
# ---------------------------------------------------------------------------

def _send_alert(subject: str, body: str):
    """Send an alert email."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.warning("Gmail not configured — skipping alert email")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = f"Fortress Sentinel <{GMAIL_ADDRESS}>"
        msg["To"] = GMAIL_ADDRESS
        msg["Subject"] = f"[SENTINEL] {subject}"

        html = f"""<html><body style="background:#0a0e17;color:#e2e8f0;font-family:system-ui;padding:20px;">
        <div style="max-width:600px;margin:0 auto;">
          <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:24px;">
            <div style="font-size:11px;color:#a78bfa;font-weight:700;text-transform:uppercase;
              letter-spacing:1.5px;margin-bottom:12px;">Intelligence Sentinel Alert</div>
            <div style="font-size:16px;font-weight:700;margin-bottom:16px;">{subject}</div>
            <pre style="color:#94a3b8;font-size:13px;line-height:1.6;white-space:pre-wrap;">{body}</pre>
            <div style="margin-top:16px;font-size:10px;color:#475569;">
              {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
              <a href="http://192.168.0.100:9800/intelligence" style="color:#3b82f6;">Open Intelligence Dashboard</a>
            </div>
          </div>
        </div>
        </body></html>"""

        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        log.info(f"Alert sent: {subject}")
    except Exception as e:
        log.error(f"Alert email failed: {e}")


# ---------------------------------------------------------------------------
# Daemon Loop
# ---------------------------------------------------------------------------

def run_once():
    """Run a single poll cycle of all monitors."""
    log.info("=" * 55)
    log.info("  INTELLIGENCE SENTINEL — Poll Cycle")
    log.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 55)

    results = {}

    results["vix"] = check_vix()
    results["fred"] = check_fred()
    results["rss"] = check_rss()

    triggered = sum(1 for r in results.values() if r.get("triggered"))
    log.info(f"Poll cycle complete. Triggers fired: {triggered}")

    return results


def run_daemon():
    """Run the sentinel as a persistent daemon with staggered polling."""
    log.info("=" * 55)
    log.info("  INTELLIGENCE SENTINEL — Daemon Mode")
    log.info("  Monitoring VIX, FRED, RSS for trigger events")
    log.info(f"  VIX interval: {VIX_POLL_INTERVAL}s | RSS: {RSS_POLL_INTERVAL}s | FRED: {FRED_POLL_INTERVAL}s")
    log.info("=" * 55)

    last_vix = 0
    last_fred = 0
    last_rss = 0

    while True:
        now = time.time()

        try:
            if now - last_vix >= VIX_POLL_INTERVAL:
                check_vix()
                last_vix = now

            if now - last_fred >= FRED_POLL_INTERVAL:
                check_fred()
                last_fred = now

            if now - last_rss >= RSS_POLL_INTERVAL:
                check_rss()
                last_rss = now

        except Exception as e:
            log.error(f"Daemon cycle error: {e}")

        time.sleep(60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fortress Intelligence Sentinel")
    parser.add_argument("--once", action="store_true", help="Single poll cycle then exit")
    parser.add_argument("--check-vix", action="store_true", help="VIX check only")
    parser.add_argument("--check-fred", action="store_true", help="FRED check only")
    parser.add_argument("--check-rss", action="store_true", help="RSS check only")
    args = parser.parse_args()

    if args.check_vix:
        result = check_vix()
        print(json.dumps(result, indent=2, default=str))
    elif args.check_fred:
        result = check_fred()
        print(json.dumps(result, indent=2, default=str))
    elif args.check_rss:
        result = check_rss()
        print(json.dumps(result, indent=2, default=str))
    elif args.once:
        results = run_once()
        print(json.dumps(results, indent=2, default=str))
    else:
        run_daemon()


if __name__ == "__main__":
    main()
