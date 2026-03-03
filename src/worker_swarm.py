#!/usr/bin/env python3
"""
DEPRECATED — 2026-02-22
========================
This module is archived. Its email-processing function has been absorbed by
fortress-refinery-agent (src/mining_rig_with_router.py + src/data_router.py).
The swarm_worker Docker Swarm service has been decommissioned.
See .cursor/rules/011-autonomous-swarm-directive.mdc for the replacement architecture.

Original description below for historical reference.

FORTRESS PRIME — Swarm Worker (The Bee)
========================================
A Redis-driven worker that runs inside Docker Swarm.
It doesn't know IPs. It asks the queue for work and processes it.

Task Types (pushed to Redis by the feeder):
    classify   — Route an email into a Core Division (HEDGE_FUND, REAL_ESTATE, etc.)
    trade      — Extract market signals from a HEDGE_FUND email
    ingest     — Read a raw .eml file from NAS and insert into email_archive
    vectorize  — Embed an email via Ollama (nomic-embed-text) and store in Qdrant

Architecture:
    Queue  : Redis at fortress_redis:6379  (Swarm DNS)
    DB     : Postgres at CAPTAIN_IP:5432   (physical IP)
    LLM    : Nginx LB at CAPTAIN_IP:80    (load-balanced across 4 GPUs)
    Vector : Qdrant at CAPTAIN_IP:6333     (standalone container)

Usage (inside Swarm):
    docker service create --name swarm_worker --network fortress_net \
        --replicas 24 fortress-swarm-worker:latest

Environment Variables:
    CAPTAIN_IP      — Captain's physical IP (default: 192.168.0.100)
    REDIS_HOST      — Redis hostname (default: fortress_redis — Swarm DNS)
    DB_HOST         — Postgres host (default: CAPTAIN_IP)
    LLM_ENDPOINT    — LLM API endpoint (default: http://CAPTAIN_IP/v1/chat/completions)
    WORKER_QUEUE    — Redis queue name (default: ingest_queue)
    LLM_MODEL       — Model name for inference (default: qwen2.5:7b)
"""

import os
import sys
import json
import time
import re
import signal
import traceback
from datetime import datetime

import redis
import requests
import psycopg2
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# =============================================================================
# CONFIGURATION — Everything comes from env vars (Swarm-native)
# =============================================================================
CAPTAIN_IP = os.getenv("CAPTAIN_IP", "192.168.0.100")
REDIS_HOST = os.getenv("REDIS_HOST", "fortress_redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", CAPTAIN_IP)
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", f"http://{CAPTAIN_IP}/v1/chat/completions")
EMBED_ENDPOINT = os.getenv("EMBED_ENDPOINT", f"http://{CAPTAIN_IP}/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
QDRANT_HOST = os.getenv("QDRANT_HOST", CAPTAIN_IP)
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "email_embeddings")
WORKER_QUEUE = os.getenv("WORKER_QUEUE", "ingest_queue")
WORKER_ID = os.getenv("HOSTNAME", "unknown")

# Quality gates (Data Hygiene Phase 3)
MARKET_PRICE_CEILING = 100_000
MIN_TICKER_LENGTH = 2

# Sender blocklist (inline subset for containerized workers)
# Full list is in config.py; this is the hot path for container isolation.
SENDER_BLOCKLIST_LOWER = [
    "noreply@mail.authorize.net", "mailer-daemon@ips201.securednshost.com",
    "newsletter@theepochtimes.com", "notify@ringcentral.com",
    "adwords-noreply@google.com", "info@twitter.com", "notify@twitter.com",
    "uspsinformeddelivery", "costco@digital.costco.com", "us.travelzoo.com",
    "nobody@e.feedspot.com", "alert@pollen.com", "help@walmart.com",
    "walmartcustomerexperience", "order.homedepot.com",
    "mytotalconnectcomfort@alarmnet.com", "noreply@august.com",
    "sns@synology.com", "tlgkw@buyinfla.com", "recommendations@mail.zillow.com",
    "tdscustomerserviceepay@tdstelecom.com", "billpay@paymentus.com",
    "discover@services.discover.com", "newsletter@zerohedge.com",
    "noreply@sharylattkisson.com", "no-reply@accounts.google.com",
    "noreply@nextgen.com",
]

# Graceful shutdown
_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    print(f"\n[{WORKER_ID}] Shutdown signal received. Finishing current task...")
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# =============================================================================
# CONNECTIONS
# =============================================================================
def get_redis():
    """Connect to Redis with retry."""
    for attempt in range(10):
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                            password=REDIS_PASSWORD or None,
                            decode_responses=True, socket_timeout=10)
            r.ping()
            return r
        except Exception as e:
            wait = min(2 ** attempt, 30)
            print(f"[{WORKER_ID}] Redis connection failed (attempt {attempt+1}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise ConnectionError("Cannot connect to Redis after 10 attempts")


def get_db():
    """Connect to Postgres."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS,
        connect_timeout=10,
    )


def get_qdrant():
    """Connect to Qdrant vector store."""
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)


def is_sender_blocked(sender):
    """Check sender against blocklist."""
    if not sender:
        return False
    sender_lower = sender.lower()
    return any(blocked in sender_lower for blocked in SENDER_BLOCKLIST_LOWER)


# =============================================================================
# LLM INTERFACE
# =============================================================================
def call_llm(system_prompt, user_content, max_tokens=300):
    """Call the LLM via the Nginx load balancer."""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content[:4000]},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    for attempt in range(2):
        try:
            resp = requests.post(LLM_ENDPOINT, json=payload, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    return msg.get("content") or msg.get("text")
            else:
                print(f"[{WORKER_ID}] LLM returned {resp.status_code}")
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"[{WORKER_ID}] LLM error: {e}")
    return None


def extract_json_from_llm(raw):
    """Robustly extract JSON from LLM output."""
    if not raw:
        return None
    # Strip <think> tags
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1].strip()
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# =============================================================================
# TASK HANDLERS
# =============================================================================

# --- Router System Prompt (same as mining_rig_router.py) ---
ROUTER_PROMPT = """You are the Chief of Staff for Fortress-Prime.
Your ONLY job is to route incoming emails into one of 4 Core Divisions.

[DIVISIONS]
1. HEDGE_FUND — Stocks, Crypto, Bitcoin, Trading, Market News, Options, Mining Rigs, NVDA, Earnings, IPO, ETF, Coinbase, Robinhood, Schwab, E*Trade, Fidelity, Seeking Alpha, Motley Fool, Bloomberg.
2. REAL_ESTATE — Cabin Rentals, Guests, Bookings, Maintenance, Septic, Surveyors, Fannin County, Property Tax, Land, Realtors, Streamline VRS, VRBO, Airbnb, HomeAway, Vacation Rentals, HOA.
3. LEGAL_ADMIN — Contracts, LLCs, Banks, Taxes, Insurance, Compliance, Invoices, Attorneys, IRS, CPA, QuickBooks, Corporate, Legal notices, Payroll, Business Formation, Annual Reports.
4. PERSONAL — Family, Health, Travel, Shopping, Spam, Newsletters, Social Media, Amazon, Art, Recipes, Subscriptions, Personal correspondence.

[INSTRUCTIONS]
- Analyze the From, Subject, and Body together.
- If it overlaps divisions, pick the STRONGEST match.
- JSON output ONLY: {"division": "DIVISION_NAME", "confidence": 0-100, "summary": "1 sentence why"}
"""

VALID_DIVISIONS = {"HEDGE_FUND", "REAL_ESTATE", "LEGAL_ADMIN", "PERSONAL"}


def normalize_division(raw):
    d = (raw or "UNKNOWN").upper().strip()
    mapping = {
        "HEDGE": "HEDGE_FUND", "HEDGE FUND": "HEDGE_FUND", "HEDGEFUND": "HEDGE_FUND",
        "REAL ESTATE": "REAL_ESTATE", "REALESTATE": "REAL_ESTATE",
        "LEGAL": "LEGAL_ADMIN", "ADMIN": "LEGAL_ADMIN", "LEGAL ADMIN": "LEGAL_ADMIN",
        "PERSONAL": "PERSONAL", "FAMILY": "PERSONAL", "SPAM": "PERSONAL",
    }
    return mapping.get(d, d if d in VALID_DIVISIONS else "UNKNOWN")


def handle_classify(task, rconn):
    """Classify an email into a Core Division."""
    email_id = task.get("email_id")
    if not email_id:
        return

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT sender, subject, content FROM email_archive WHERE id = %s",
            (email_id,),
        )
        row = cur.fetchone()
        if not row:
            return

        sender, subject, content = row[0] or "", row[1] or "", row[2] or ""

        # Blocklist gate
        if is_sender_blocked(sender):
            cur.execute(
                "UPDATE email_archive SET division = %s, division_confidence = %s, division_summary = %s WHERE id = %s",
                ("PERSONAL", 99, "Blocked sender (SENDER_BLOCKLIST)", email_id),
            )
            conn.commit()
            rconn.hincrby("swarm:stats", "blocked", 1)
            return

        email_text = f"From: {sender}\nSubject: {subject}\n\n{content[:3000]}"
        raw = call_llm(ROUTER_PROMPT, email_text, max_tokens=200)
        result = extract_json_from_llm(raw)

        if result:
            division = normalize_division(result.get("division"))
            confidence = max(0, min(100, int(result.get("confidence", 50))))
            summary = (result.get("summary") or "")[:500]
        else:
            division, confidence, summary = "UNKNOWN", 0, "Classification failed"

        cur.execute(
            "UPDATE email_archive SET division = %s, division_confidence = %s, division_summary = %s WHERE id = %s",
            (division, confidence, summary, email_id),
        )
        conn.commit()
        rconn.hincrby("swarm:stats", f"classified:{division}", 1)

    except Exception as e:
        conn.rollback()
        print(f"[{WORKER_ID}] classify error email {email_id}: {e}")
        rconn.hincrby("swarm:stats", "errors", 1)
    finally:
        cur.close()
        conn.close()


# --- Trader System Prompt ---
TRADER_PROMPT = """You are a Quantitative Analyst for a Hedge Fund.
Mission: Extract MATERIAL market signals from email text.
Rules:
1. Ignore marketing, spam, and newsletters with no specific tickers.
2. Look for: Earnings (EPS/Rev), Insider Buying, Analyst Upgrades, Macro Data.
3. Output JSON ONLY: {"signals": [{"ticker": "NVDA", "action": "BUY", "confidence": 90, "reason": "Earnings beat"}]}
4. If no signal, return {"signals": []}
"""


def handle_trade(task, rconn):
    """Extract market signals from a HEDGE_FUND email."""
    email_id = task.get("email_id")
    if not email_id:
        return

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT content, sender FROM email_archive WHERE id = %s", (email_id,),
        )
        row = cur.fetchone()
        if not row:
            return

        content, sender = row[0] or "", row[1] or ""

        if is_sender_blocked(sender):
            cur.execute("UPDATE email_archive SET is_mined = TRUE WHERE id = %s", (email_id,))
            conn.commit()
            return

        raw = call_llm(TRADER_PROMPT, content, max_tokens=500)
        result = extract_json_from_llm(raw)
        signals_inserted = 0

        if result:
            for sig in result.get("signals", []):
                ticker = (sig.get("ticker") or "").strip().upper()
                ticker = re.sub(r"[^A-Z]", "", ticker)
                if not ticker or len(ticker) < MIN_TICKER_LENGTH or len(ticker) > 6:
                    continue

                action = (sig.get("action") or "BUY").upper()
                if action not in ("BUY", "SELL", "WATCH"):
                    action = "BUY"

                conf = sig.get("confidence")
                if conf is not None:
                    conf = min(100.0, max(0.0, float(conf)))

                # Quality gate: price ceiling
                price = sig.get("price")
                if price is not None:
                    try:
                        if float(price) > MARKET_PRICE_CEILING:
                            continue
                    except (ValueError, TypeError):
                        pass

                sentiment = 1.0 if action == "BUY" else (-1.0 if action == "SELL" else 0.0)
                reason = (sig.get("reason") or "")[:500]

                cur.execute("""
                    INSERT INTO hedge_fund.market_signals
                    (ticker, signal_type, action, confidence_score, sentiment_score,
                     raw_text, source_sender, source_email_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (ticker, sig.get("type", "Unknown"), action, conf,
                      sentiment, reason or None, sender, email_id))
                signals_inserted += 1

        cur.execute("UPDATE email_archive SET is_mined = TRUE WHERE id = %s", (email_id,))
        conn.commit()
        rconn.hincrby("swarm:stats", "signals_extracted", signals_inserted)
        rconn.hincrby("swarm:stats", "traded", 1)

    except Exception as e:
        conn.rollback()
        print(f"[{WORKER_ID}] trade error email {email_id}: {e}")
        rconn.hincrby("swarm:stats", "errors", 1)
    finally:
        cur.close()
        conn.close()


def handle_ingest(task, rconn):
    """Ingest a raw email file from NAS into email_archive."""
    file_path = task.get("path")
    category = task.get("category", "Market Intelligence")
    if not file_path:
        return

    import email as email_lib
    from email.policy import default as email_default

    try:
        with open(file_path, 'rb') as f:
            msg = email_lib.message_from_binary_file(f, policy=email_default)

        subject = msg['subject'] or "No Subject"
        sender = msg['from'] or "Unknown"
        date_str = msg['date']
        try:
            sent_at = email_lib.utils.parsedate_to_datetime(date_str)
        except Exception:
            sent_at = datetime.now()

        # Blocklist gate
        if is_sender_blocked(sender):
            rconn.hincrby("swarm:stats", "ingest_blocked", 1)
            return

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(errors='ignore')
                elif ctype == "text/html" and not body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode(errors='ignore')
                        body += re.sub(r'<[^>]+>', ' ', html)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors='ignore')

        if len(body) < 50:
            return

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM email_archive WHERE file_path = %s", (file_path,))
            if cur.fetchone():
                return  # Already ingested

            cur.execute("""
                INSERT INTO email_archive (category, file_path, sender, subject, content, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (category, file_path, sender, subject, body, sent_at))
            conn.commit()
            rconn.hincrby("swarm:stats", "ingested", 1)
        except Exception as e:
            conn.rollback()
            if "duplicate key" not in str(e).lower():
                print(f"[{WORKER_ID}] ingest DB error: {e}")
                rconn.hincrby("swarm:stats", "errors", 1)
        finally:
            cur.close()
            conn.close()

    except FileNotFoundError:
        rconn.hincrby("swarm:stats", "file_not_found", 1)
    except Exception as e:
        print(f"[{WORKER_ID}] ingest error {file_path}: {e}")
        rconn.hincrby("swarm:stats", "errors", 1)


# --- Vectorize (Embed & Store in Qdrant) ---

def get_embedding(text):
    """Call Ollama embedding endpoint via LB to get a 768-dim vector."""
    payload = {"model": EMBED_MODEL, "prompt": text[:2000]}
    for attempt in range(3):
        try:
            resp = requests.post(EMBED_ENDPOINT, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("embedding")
                if emb and len(emb) > 0:
                    return emb
            else:
                if attempt < 2:
                    time.sleep(1)
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"[{WORKER_ID}] Embedding error: {e}")
    return None


def handle_vectorize(task, rconn):
    """Embed an email and store the vector in Qdrant."""
    email_id = task.get("email_id")
    if not email_id:
        return

    conn = get_db()
    cur = conn.cursor()
    try:
        # Skip if already vectorized
        cur.execute(
            "SELECT sender, subject, content, division, is_vectorized FROM email_archive WHERE id = %s",
            (email_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        if row[4]:  # is_vectorized = True
            rconn.hincrby("swarm:stats", "already_vectorized", 1)
            return

        sender, subject, content, division = row[0] or "", row[1] or "", row[2] or "", row[3] or "UNKNOWN"

        # Skip junk
        if is_sender_blocked(sender):
            cur.execute("UPDATE email_archive SET is_vectorized = TRUE WHERE id = %s", (email_id,))
            conn.commit()
            rconn.hincrby("swarm:stats", "vectorize_blocked", 1)
            return

        if len(content.strip()) < 50:
            cur.execute("UPDATE email_archive SET is_vectorized = TRUE WHERE id = %s", (email_id,))
            conn.commit()
            rconn.hincrby("swarm:stats", "vectorize_too_short", 1)
            return

        # Build embedding text: structured context for better semantic search
        # nomic-embed-text has 8192 token limit but HTML remnants inflate token count
        # Aggressive truncation: 1500 chars of content fits any tokenization scheme
        clean_content = " ".join(content.split())[:1500]  # collapse whitespace then truncate
        embed_text = f"From: {sender[:100]}\nSubject: {subject[:200]}\nDivision: {division}\n\n{clean_content}"

        # Get embedding from Ollama (via Nginx LB)
        embedding = get_embedding(embed_text)
        if not embedding:
            rconn.hincrby("swarm:stats", "embed_failures", 1)
            # Re-queue for retry (don't lose the task)
            retry_task = json.dumps({"type": "vectorize", "email_id": email_id})
            rconn.rpush(WORKER_QUEUE, retry_task)
            return

        # Store in Qdrant
        qclient = get_qdrant()
        point = PointStruct(
            id=email_id,
            vector=embedding,
            payload={
                "email_id": email_id,
                "sender": sender[:200],
                "subject": subject[:500],
                "division": division,
                "preview": content[:500],
            },
        )
        qclient.upsert(collection_name=QDRANT_COLLECTION, points=[point])

        # Mark as vectorized in Postgres
        cur.execute("UPDATE email_archive SET is_vectorized = TRUE WHERE id = %s", (email_id,))
        conn.commit()
        rconn.hincrby("swarm:stats", "vectorized", 1)

    except Exception as e:
        conn.rollback()
        print(f"[{WORKER_ID}] vectorize error email {email_id}: {e}")
        rconn.hincrby("swarm:stats", "errors", 1)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# TASK DISPATCHER
# =============================================================================
HANDLERS = {
    "classify": handle_classify,
    "trade": handle_trade,
    "ingest": handle_ingest,
    "vectorize": handle_vectorize,
}


# =============================================================================
# MAIN LOOP
# =============================================================================
def main():
    print(f"[{WORKER_ID}] Swarm Worker Online")
    print(f"  Queue    : {REDIS_HOST}:{REDIS_PORT}/{WORKER_QUEUE}")
    print(f"  Database : {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"  LLM      : {LLM_ENDPOINT} ({LLM_MODEL})")
    print(f"  Embed    : {EMBED_ENDPOINT} ({EMBED_MODEL})")
    print(f"  Qdrant   : {QDRANT_HOST}:{QDRANT_PORT}/{QDRANT_COLLECTION}")
    print(f"  Blocklist: {len(SENDER_BLOCKLIST_LOWER)} patterns")
    print(f"  Waiting for tasks...")
    sys.stdout.flush()

    rconn = get_redis()
    rconn.hincrby("swarm:stats", "workers_started", 1)

    tasks_processed = 0

    while not _shutdown:
        try:
            # Blocking pop — waits up to 30s for a task, then loops (allows shutdown check)
            result = rconn.blpop(WORKER_QUEUE, timeout=30)
            if result is None:
                continue  # Timeout, check shutdown flag

            _, task_json = result
            try:
                task = json.loads(task_json)
            except json.JSONDecodeError:
                print(f"[{WORKER_ID}] Invalid task JSON: {task_json[:100]}")
                rconn.hincrby("swarm:stats", "invalid_tasks", 1)
                continue

            task_type = task.get("type", "classify")
            handler = HANDLERS.get(task_type)

            if handler is None:
                print(f"[{WORKER_ID}] Unknown task type: {task_type}")
                rconn.hincrby("swarm:stats", "unknown_type", 1)
                continue

            handler(task, rconn)
            tasks_processed += 1

            if tasks_processed % 100 == 0:
                print(f"[{WORKER_ID}] Processed {tasks_processed} tasks")
                sys.stdout.flush()

        except redis.ConnectionError as e:
            print(f"[{WORKER_ID}] Redis lost: {e}. Reconnecting...")
            time.sleep(5)
            try:
                rconn = get_redis()
            except Exception:
                pass

        except Exception as e:
            print(f"[{WORKER_ID}] Unexpected error: {e}")
            traceback.print_exc()
            time.sleep(2)

    # Graceful shutdown
    print(f"[{WORKER_ID}] Shutting down. Processed {tasks_processed} tasks total.")
    rconn.hincrby("swarm:stats", "workers_stopped", 1)


if __name__ == "__main__":
    main()
