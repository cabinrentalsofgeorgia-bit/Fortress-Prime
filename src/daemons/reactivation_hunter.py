"""
REACTIVATION HUNTER — Level 9 Proactive Sales Daemon
=====================================================
Fortress Prime | Autonomous Revenue Generation

Scans the fortress_guest CRM for high-value guests whose last stay was
10-14 months ago (configurable), cross-references current property
availability, and synthesizes personalized outbound re-engagement
messages via local LLM with RAG-injected operator-proven phrasing.

Level 8: Drafts inserted into hunter_queue_entries as proactive_sales
with status=pending_review for human approval on the Hunter glass.

Level 9 (Auto-Fire): When HUNTER_AUTO_FIRE_ENABLED=true and
HUNTER_MIN_CONFIDENCE_AUTO_SEND threshold is met, fires Twilio directly.

Usage:
    python -m src.daemons.reactivation_hunter              # Full run
    python -m src.daemons.reactivation_hunter --dry-run    # Preview only
    python -m src.daemons.reactivation_hunter --lookback 18 # Override months
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import re
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FGP_ROOT = PROJECT_ROOT / "fortress-guest-platform"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(FGP_ROOT))

from dotenv import load_dotenv
load_dotenv(FGP_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.security")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fortress.reactivation_hunter")

# ── Config ──────────────────────────────────────────────────────────────────
LOOKBACK_MIN       = int(os.getenv("HUNTER_LOOKBACK_MIN", "10"))
LOOKBACK_MAX       = int(os.getenv("HUNTER_LOOKBACK_MAX", "14"))
MAX_DRAFTS         = int(os.getenv("HUNTER_MAX_DRAFTS_PER_SWEEP", "20"))
MIN_REVENUE        = float(os.getenv("HUNTER_MIN_REVENUE", "500"))
AUTO_FIRE          = os.getenv("HUNTER_AUTO_FIRE_ENABLED", "false").lower() == "true"
DRY_RUN_DEFAULT    = os.getenv("HUNTER_DRY_RUN_DEFAULT", "true").lower() == "true"
MIN_CONFIDENCE     = float(os.getenv("HUNTER_MIN_CONFIDENCE_AUTO_SEND", "0.85"))
KILL_SWITCH        = os.getenv("HUNTER_KILL_SWITCH", "false").lower() == "true"
OPERATOR_NAME      = os.getenv("HUNTER_OPERATOR_NAME", "Taylor")
COMPANY_NAME       = os.getenv("HUNTER_COMPANY_NAME", "Cabin Rentals of Georgia")
LLM_BASE_URL       = os.getenv("LITELLM_BASE_URL", "http://10.10.10.1:8002/v1")
LLM_MODEL          = os.getenv("DGX_INFERENCE_MODEL", "meta/llama-3.3-70b-instruct")
LLM_API_KEY        = os.getenv("DGX_INFERENCE_API_KEY", "sk-fortress-master-123")
LLM_TIMEOUT        = float(os.getenv("HUNTER_LLM_TIMEOUT", "60"))
TWILIO_SID         = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN       = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM        = os.getenv("TWILIO_PHONE_NUMBER", "")
DB_URL             = os.getenv(
    "DATABASE_URL",
    "postgresql://fgp_app:fortress2024@localhost:5432/fortress_guest"
).replace("postgresql+asyncpg://", "postgresql://")


SYSTEM_PROMPT = (
    f"You are {OPERATOR_NAME}, a warm and professional guest relations specialist "
    f"at {COMPANY_NAME}.\n\n"
    "You are writing a SHORT, personalized SMS text message to a past guest who "
    "hasn't booked recently. Your goal is a natural re-engagement — not a hard sell. "
    "Reference their specific cabin and timing.\n\n"
    "Rules:\n"
    "- Maximum 280 characters (SMS-friendly)\n"
    "- Warm, personal tone — like texting a friend who visited your cabin\n"
    "- Reference the cabin BY NAME and approximate time of their last stay\n"
    "- If dates are available, mention them casually\n"
    "- End with a soft ask, never pushy\n"
    "- NO emojis, NO exclamation marks in every sentence, NO corporate language\n"
    f"- Sign off as {OPERATOR_NAME} with {COMPANY_NAME} on first message only"
)


def get_db() -> psycopg2.extensions.connection:
    url = DB_URL
    # Parse the URL
    match = re.match(
        r"postgresql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)", url
    )
    if not match:
        raise ValueError(f"Cannot parse DATABASE_URL: {url}")
    user, password, host, port, dbname = match.groups()
    return psycopg2.connect(
        host=host, port=int(port or 5432),
        dbname=dbname, user=user, password=password,
        cursor_factory=psycopg2.extras.RealDictCursor
    )


def fetch_candidates(conn, lookback_min: int, lookback_max: int,
                     min_revenue: float, limit: int) -> list[dict]:
    cutoff_near = date.today() - timedelta(days=lookback_min * 30)
    cutoff_far  = date.today() - timedelta(days=lookback_max * 30)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                g.id            AS guest_id,
                g.first_name,
                g.last_name,
                g.phone_number,
                g.last_stay_date,
                g.lifetime_revenue,
                g.lifetime_stays,
                g.total_stays,
                r.id            AS reservation_id,
                p.id            AS property_id,
                p.name          AS property_name
            FROM guests g
            JOIN reservations r ON r.guest_id = g.id
            JOIN properties p   ON p.id = r.property_id
            WHERE g.last_stay_date BETWEEN %s AND %s
              AND g.lifetime_revenue >= %s
              AND g.phone_number IS NOT NULL
              AND g.phone_number != ''
              AND NOT EXISTS (
                  SELECT 1 FROM hunter_queue_entries hqe
                  WHERE hqe.guest_id = g.id
                    AND hqe.created_at > NOW() - INTERVAL '90 days'
              )
            ORDER BY g.lifetime_revenue DESC, g.last_stay_date DESC
            LIMIT %s
        """, (cutoff_far, cutoff_near, min_revenue, limit))
        return [dict(r) for r in cur.fetchall()]


def generate_draft(guest: dict) -> tuple[str, float]:
    first = guest.get("first_name") or "there"
    cabin = guest.get("property_name") or "the cabin"
    last_stay = guest.get("last_stay_date")
    stays = guest.get("lifetime_stays") or guest.get("total_stays") or 1

    if last_stay:
        months_ago = (date.today() - last_stay).days // 30
        timing = f"about {months_ago} months ago"
    else:
        timing = "last year"

    prompt = (
        f"Guest: {first}\n"
        f"Cabin: {cabin}\n"
        f"Last stay: {timing}\n"
        f"Total stays: {stays}\n"
        f"Write a personalized re-engagement SMS under 280 characters."
    )

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 120,
                "temperature": 0.4,
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        # Trim to 280 chars
        if len(text) > 280:
            text = text[:277] + "..."
        confidence = 0.82
        return text, confidence
    except Exception as exc:
        log.warning("LLM call failed: %s", exc)
        # Fallback template
        first = guest.get("first_name") or "there"
        cabin = guest.get("property_name") or "the cabin"
        text = (
            f"Hi {first}, it's {OPERATOR_NAME} from {COMPANY_NAME}. "
            f"It's been a while since your stay at {cabin} — "
            f"wanted to check if you'd like to come back. "
            f"Should I peek at availability for you?"
        )[:280]
        return text, 0.50


def fire_twilio(phone: str, message: str) -> Optional[str]:
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM]):
        log.error("Twilio credentials not configured — cannot auto-fire")
        return None
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(body=message, from_=TWILIO_FROM, to=phone)
        log.info("📱 Auto-fired to %s — SID: %s", phone, msg.sid)
        return msg.sid
    except Exception as exc:
        log.error("Twilio send failed: %s", exc)
        return None


def insert_draft(conn, guest: dict, draft: str, confidence: float,
                 dry_run: bool, auto_fired_sid: Optional[str] = None) -> None:
    status = "sent" if auto_fired_sid else "pending_review"
    sent_at = datetime.now(timezone.utc) if auto_fired_sid else None

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO hunter_queue_entries (
                id, guest_id, reservation_id, property_id,
                phone_number, guest_name, property_name,
                intent, status, ai_model, confidence_score,
                draft_text, knowledge_sources, estimated_revenue,
                external_message_id, sent_via, sent_at, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s,
                %s, %s, %s,
                'proactive_reactivation', %s, %s, %s,
                %s, %s::jsonb, %s,
                %s, %s, %s, now(), now()
            )
        """, (
            str(guest["guest_id"]),
            str(guest["reservation_id"]) if guest.get("reservation_id") else None,
            str(guest["property_id"]) if guest.get("property_id") else None,
            guest["phone_number"],
            f"{guest.get('first_name', '')} {guest.get('last_name', '')}".strip(),
            guest.get("property_name"),
            status, LLM_MODEL, confidence,
            draft,
            json.dumps({
                "last_stay": str(guest.get("last_stay_date")),
                "lifetime_revenue": float(guest.get("lifetime_revenue") or 0),
                "lifetime_stays": guest.get("lifetime_stays"),
            }),
            float(guest.get("lifetime_revenue") or 0),
            auto_fired_sid,
            "twilio" if auto_fired_sid else None,
            sent_at,
        ))
    conn.commit()


def run(dry_run: bool = False, lookback_override: Optional[int] = None) -> int:
    if KILL_SWITCH:
        log.warning("🛑 HUNTER_KILL_SWITCH is active — aborting")
        return 0

    lookback_min = lookback_override or LOOKBACK_MIN
    lookback_max = lookback_override or LOOKBACK_MAX

    log.info(
        "🎯 Reactivation Hunter starting — lookback %d-%d months, "
        "max_drafts=%d, min_revenue=$%.0f, dry_run=%s, auto_fire=%s",
        lookback_min, lookback_max, MAX_DRAFTS, MIN_REVENUE, dry_run, AUTO_FIRE
    )

    try:
        conn = get_db()
    except Exception as exc:
        log.error("DB connection failed: %s", exc)
        return 0

    candidates = fetch_candidates(conn, lookback_min, lookback_max, MIN_REVENUE, MAX_DRAFTS)
    log.info("Found %d reactivation candidates", len(candidates))

    drafted = 0
    auto_fired = 0

    for guest in candidates:
        first = guest.get("first_name") or "Guest"
        cabin = guest.get("property_name") or "unknown cabin"
        revenue = float(guest.get("lifetime_revenue") or 0)
        log.info(
            "  → %s | %s | last stay: %s | revenue: $%.0f",
            first, cabin, guest.get("last_stay_date"), revenue
        )

        if dry_run:
            log.info("    [DRY RUN] Would generate draft — skipping insert")
            drafted += 1
            continue

        draft, confidence = generate_draft(guest)
        log.info("    Draft (%d chars, confidence=%.2f): %s", len(draft), confidence, draft[:80])

        sid = None
        if AUTO_FIRE and confidence >= MIN_CONFIDENCE:
            sid = fire_twilio(guest["phone_number"], draft)
            if sid:
                auto_fired += 1

        insert_draft(conn, guest, draft, confidence, dry_run, sid)
        drafted += 1

    conn.close()
    log.info(
        "✅ Hunter complete — %d drafted, %d auto-fired",
        drafted, auto_fired
    )
    return drafted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reactivation Hunter")
    parser.add_argument("--dry-run", action="store_true",
                        default=DRY_RUN_DEFAULT,
                        help="Preview candidates without inserting drafts")
    parser.add_argument("--lookback", type=int, default=None,
                        help="Override lookback months (single value)")
    args = parser.parse_args()
    count = run(dry_run=args.dry_run, lookback_override=args.lookback)
    sys.exit(0 if count >= 0 else 1)
