#!/usr/bin/env python3
"""
ingest_reservations_imap.py — Reservations mailbox IMAP watcher

Pattern: poll-based (NOT IDLE). Invoked by cron every 10 minutes.
Source:  reservations@cabin-rentals-of-georgia.com on mail.cabin-rentals-of-georgia.com (cPanel)
Sink:    email_messages table via EmailMessageService (backend/services/email_message_service.py)

On startup:
  - First run of the day (or empty queue): scan last 24h for UNSEEN messages
  - Subsequent runs: scan only UNSEEN messages since last run's max UID
Idempotency: imap_uid UNIQUE constraint on email_messages — re-inserts are no-ops

Environment variables (required):
  RESERVATIONS_IMAP_HOST    e.g. "mail.cabin-rentals-of-georgia.com"
  RESERVATIONS_IMAP_PORT    e.g. "993"
  RESERVATIONS_IMAP_USER    e.g. "reservations@cabin-rentals-of-georgia.com"
  RESERVATIONS_IMAP_PASS    cPanel mailbox password

Environment variables (optional):
  RESERVATIONS_IMAP_FOLDER  default "INBOX"
  RESERVATIONS_LOOKBACK_HOURS  default 24 (first run per day)
  RESERVATIONS_MAX_PER_RUN  default 50 (cap per invocation)
  AI_ROUTER_BACKEND_DIR     path to fortress-guest-platform root

Usage:
  python3 -m src.ingest_reservations_imap                    # production poll
  python3 -m src.ingest_reservations_imap --dry-run          # fetch + classify, don't write to DB
  python3 -m src.ingest_reservations_imap --no-ai            # ingest only, skip draft generation
  python3 -m src.ingest_reservations_imap --since-hours 48   # override lookback

DEPRECATED (still present, not removed yet): reservations_draft_queue write path.
Drop in follow-up PR after email pipeline is proven in production for >=48 hours.
"""
from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"reservations_imap"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("reservations_imap")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

IMAP_HOST = os.getenv("RESERVATIONS_IMAP_HOST", "")
IMAP_PORT = int(os.getenv("RESERVATIONS_IMAP_PORT", "993"))
IMAP_USER = os.getenv("RESERVATIONS_IMAP_USER", "")
IMAP_PASS = os.getenv("RESERVATIONS_IMAP_PASS", "")
IMAP_FOLDER = os.getenv("RESERVATIONS_IMAP_FOLDER", "INBOX")
LOOKBACK_HOURS = int(os.getenv("RESERVATIONS_LOOKBACK_HOURS", "24"))
MAX_PER_RUN = int(os.getenv("RESERVATIONS_MAX_PER_RUN", "50"))

# v5 ai_router integration
AI_ROUTER_TASK_TYPE = os.getenv("RESERVATIONS_TASK_TYPE", "vrs_concierge")
AI_ROUTER_SOURCE_MODULE = "reservations_imap_watcher"
AI_ROUTER_MAX_TOKENS = int(os.getenv("RESERVATIONS_AI_MAX_TOKENS", "800"))
AI_ROUTER_TEMPERATURE = float(os.getenv("RESERVATIONS_AI_TEMPERATURE", "0.4"))
AI_ROUTER_SYSTEM_PROMPT = os.getenv(
    "RESERVATIONS_AI_SYSTEM_PROMPT",
    "You are the concierge for Cabin Rentals of Georgia. "
    "Draft a warm, professional, accurate reply to this guest email. "
    "If the guest asks something that requires checking availability, pricing, "
    "or specific cabin details you don't have, say you'll confirm and follow up "
    "rather than guessing. Sign as the Cabin Rentals of Georgia team."
)
AI_ROUTER_BACKEND_DIR = os.path.expanduser(
    os.getenv("AI_ROUTER_BACKEND_DIR", "~/Fortress-Prime/fortress-guest-platform")
)
AI_ROUTER_TIMEOUT_S = int(os.getenv("RESERVATIONS_AI_TIMEOUT_S", "120"))

# DEPRECATED: fortress_db / miner_bot credentials used by the old reservations_draft_queue path.
# Keep until email pipeline is verified in production (>= 48h). Then remove.
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", "")


# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------

@dataclass
class FetchedEmail:
    imap_uid: int
    message_id: str
    sender: str
    sender_name: str
    recipient: str
    subject: str
    received_at: datetime
    body_text: str
    body_excerpt: str  # first ~2000 chars for queue preview


# -----------------------------------------------------------------------------
# IMAP helpers
# -----------------------------------------------------------------------------

def _decode(value: Optional[str]) -> str:
    """Decode RFC 2047 encoded-word headers safely."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_body(msg: EmailMessage) -> str:
    """Extract text/plain body. Falls back to text/html stripped."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
        # fallback: first text/html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    html = payload.decode(errors="replace") if payload else ""
                return _strip_html(html)
        return ""
    try:
        content = msg.get_content()
    except Exception:
        payload = msg.get_payload(decode=True)
        content = payload.decode(errors="replace") if payload else ""
    if msg.get_content_type() == "text/html":
        return _strip_html(content)
    return content


def _strip_html(html: str) -> str:
    """Minimal HTML -> text. Good enough for email previews."""
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_sender(raw: str) -> tuple[str, str]:
    """Return (email_address, display_name)."""
    from email.utils import parseaddr
    name, addr = parseaddr(raw or "")
    return (addr.lower().strip(), _decode(name).strip())


def connect_imap() -> imaplib.IMAP4_SSL:
    if not all([IMAP_HOST, IMAP_USER, IMAP_PASS]):
        log.error("IMAP credentials missing — set RESERVATIONS_IMAP_{HOST,USER,PASS} in .env")
        sys.exit(2)
    log.info(f"Connecting to {IMAP_HOST}:{IMAP_PORT} as {IMAP_USER}")
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
    conn.login(IMAP_USER, IMAP_PASS)
    return conn


def search_unseen_since(conn: imaplib.IMAP4_SSL, since_dt: datetime) -> list[int]:
    """Return list of IMAP UIDs for unseen messages since `since_dt`."""
    since_str = since_dt.strftime("%d-%b-%Y")  # IMAP date format
    typ, data = conn.uid("SEARCH", None, f'(UNSEEN SINCE "{since_str}")')
    if typ != "OK":
        log.warning(f"IMAP search failed: {typ} {data}")
        return []
    if not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]


def fetch_by_uid(conn: imaplib.IMAP4_SSL, uid: int) -> Optional[FetchedEmail]:
    typ, data = conn.uid("FETCH", str(uid), "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        log.warning(f"Fetch failed for UID {uid}")
        return None
    raw_bytes = data[0][1]
    if not isinstance(raw_bytes, (bytes, bytearray)):
        return None
    msg = email.message_from_bytes(bytes(raw_bytes), policy=email.policy.default)

    sender_raw = msg.get("From", "")
    sender_addr, sender_name = _parse_sender(sender_raw)
    recipient_addr, _ = _parse_sender(msg.get("To", ""))
    subject = _decode(msg.get("Subject", ""))
    message_id = (msg.get("Message-ID", "") or "").strip("<>").strip()

    date_hdr = msg.get("Date", "")
    try:
        received_at = parsedate_to_datetime(date_hdr) if date_hdr else datetime.now(timezone.utc)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
    except Exception:
        received_at = datetime.now(timezone.utc)

    body_text = _extract_body(msg).strip()
    excerpt = body_text[:2000]

    return FetchedEmail(
        imap_uid=uid,
        message_id=message_id,
        sender=sender_addr,
        sender_name=sender_name,
        recipient=recipient_addr,
        subject=subject,
        received_at=received_at,
        body_text=body_text,
        body_excerpt=excerpt,
    )


# -----------------------------------------------------------------------------
# Postgres queue
# -----------------------------------------------------------------------------

def get_db_connection():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def ensure_table(conn) -> None:
    """Idempotent table creation. Safe to call every run."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reservations_draft_queue (
                id            BIGSERIAL PRIMARY KEY,
                imap_uid      BIGINT NOT NULL UNIQUE,
                message_id    TEXT,
                sender        TEXT NOT NULL,
                sender_name   TEXT,
                recipient     TEXT,
                subject       TEXT,
                received_at   TIMESTAMPTZ NOT NULL,
                body_excerpt  TEXT,
                body_full     TEXT,
                ai_draft      TEXT,
                ai_confidence REAL,
                ai_meta       JSONB,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed_at  TIMESTAMPTZ
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reservations_queue_status
              ON reservations_draft_queue(status, received_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reservations_queue_sender
              ON reservations_draft_queue(sender);
        """)
    conn.commit()


def already_queued(conn, imap_uid: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM reservations_draft_queue WHERE imap_uid = %s", (imap_uid,))
        return cur.fetchone() is not None


def insert_draft(conn, fe: FetchedEmail, ai_draft: Optional[str],
                 ai_confidence: Optional[float], ai_meta: Optional[dict]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO reservations_draft_queue
              (imap_uid, message_id, sender, sender_name, recipient, subject,
               received_at, body_excerpt, body_full, ai_draft, ai_confidence,
               ai_meta, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (imap_uid) DO NOTHING
        """, (
            fe.imap_uid, fe.message_id, fe.sender, fe.sender_name, fe.recipient,
            fe.subject, fe.received_at, fe.body_excerpt, fe.body_text,
            ai_draft, ai_confidence,
            json.dumps(ai_meta) if ai_meta else None,
            "pending" if ai_draft else "pending_no_draft",
        ))
    conn.commit()


# -----------------------------------------------------------------------------
# Email pipeline — ingest via EmailMessageService
# -----------------------------------------------------------------------------

def ingest_to_email_pipeline(fe: FetchedEmail, skip_ai: bool) -> Optional[str]:
    """
    Persist the email into email_messages via EmailMessageService (subprocess).

    Returns the EmailMessage UUID string on success, None on failure.
    Every failure mode logs an error but never drops the email silently —
    the caller should log a warning so ops can retry.
    """
    import subprocess

    venv_py = os.path.join(AI_ROUTER_BACKEND_DIR, ".uv-venv/bin/python3")
    if not os.path.exists(venv_py):
        log.error("email_pipeline_unavailable: backend venv missing at %s", venv_py)
        return None

    payload = {
        "email_from": fe.sender,
        "email_to": fe.recipient,
        "subject": fe.subject,
        "body_text": fe.body_text,
        "imap_uid": fe.imap_uid,
        "message_id": fe.message_id,
        "received_at": fe.received_at.isoformat(),
        "skip_ai": skip_ai,
    }

    runner = (
        "import asyncio, json, sys\n"
        "from backend.core.database import async_session_factory\n"
        "from backend.services.email_message_service import EmailMessageService\n"
        "from datetime import datetime, timezone\n"
        "from uuid import UUID\n"
        "p = json.loads(sys.stdin.read())\n"
        "async def _run():\n"
        "    async with async_session_factory() as db:\n"
        "        svc = EmailMessageService(db)\n"
        "        msg = await svc.receive_email(\n"
        "            email_from=p['email_from'],\n"
        "            email_to=p['email_to'],\n"
        "            subject=p['subject'],\n"
        "            body_text=p['body_text'],\n"
        "            imap_uid=int(p['imap_uid']),\n"
        "            message_id=p['message_id'],\n"
        "            received_at=datetime.fromisoformat(p['received_at']),\n"
        "        )\n"
        "        if not p['skip_ai']:\n"
        "            msg = await svc.generate_draft_for_inbound(msg.id)\n"
        "        print(json.dumps({'message_id': str(msg.id), 'status': msg.approval_status}))\n"
        "asyncio.run(_run())\n"
    )

    try:
        proc = subprocess.run(
            [venv_py, "-c", runner],
            input=json.dumps(payload),
            cwd=AI_ROUTER_BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=AI_ROUTER_TIMEOUT_S,
        )
        if proc.returncode != 0:
            log.error(
                "email_pipeline_subprocess_failed uid=%s returncode=%s stderr=%s",
                fe.imap_uid, proc.returncode, (proc.stderr or "")[-1000:],
            )
            return None
        out_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if not out_lines:
            log.error(
                "email_pipeline_no_output uid=%s stderr=%s",
                fe.imap_uid, (proc.stderr or "")[-500:],
            )
            return None
        result = json.loads(out_lines[-1])
        return result.get("message_id")
    except subprocess.TimeoutExpired:
        log.error("email_pipeline_timeout uid=%s timeout_s=%s", fe.imap_uid, AI_ROUTER_TIMEOUT_S)
        return None
    except Exception as exc:
        log.exception("email_pipeline_exception uid=%s err=%s", fe.imap_uid, exc)
        return None


# -----------------------------------------------------------------------------
# AI draft generation (wraps guest_reply_engine if available)
# DEPRECATED: replaced by EmailMessageService.generate_draft_for_inbound.
# Keep until reservations_draft_queue path is fully retired.
# -----------------------------------------------------------------------------

def generate_draft(fe: FetchedEmail, skip_ai: bool) -> tuple:
    """
    Call ai_router (v5) to generate a draft reply.

    Returns (draft_text, confidence, meta_dict). Failure is non-fatal: email
    still gets queued with no draft. Routes through
    backend.services.ai_router.execute_resilient_inference, which handles
    sovereign->godhead escalation, judging, and v5 capture.

    We invoke ai_router via subprocess in the backend's venv because:
      1. backend.* modules are not on this script's PYTHONPATH
      2. ai_router is async; subprocess avoids importing asyncio here
      3. Subprocess gives clean isolation per-email
    Cost: ~100-300ms fork overhead per email. Acceptable for cron cadence.
    """
    if skip_ai:
        return (None, None, {"ai_skipped": True})

    import subprocess

    venv_py = os.path.join(AI_ROUTER_BACKEND_DIR, ".uv-venv/bin/python3")
    if not os.path.exists(venv_py):
        return (None, None, {"ai_unavailable": "backend venv missing", "expected": venv_py})

    prompt = (
        "From: " + (fe.sender_name or "") + " <" + fe.sender + ">\n"
        "Subject: " + fe.subject + "\n\n"
        + fe.body_text
    )

    payload = {
        "prompt": prompt,
        "task_type": AI_ROUTER_TASK_TYPE,
        "system_message": AI_ROUTER_SYSTEM_PROMPT,
        "max_tokens": AI_ROUTER_MAX_TOKENS,
        "temperature": AI_ROUTER_TEMPERATURE,
        "source_module": AI_ROUTER_SOURCE_MODULE,
    }

    # Inline runner script. Reads payload from stdin (avoids shell-quoting hell),
    # awaits ai_router, prints single-line JSON result on stdout.
    runner = (
        "import asyncio, json, sys\n"
        "from backend.services.ai_router import execute_resilient_inference\n"
        "p = json.loads(sys.stdin.read())\n"
        "r = asyncio.run(execute_resilient_inference(\n"
        "    prompt=p['prompt'],\n"
        "    task_type=p['task_type'],\n"
        "    system_message=p['system_message'],\n"
        "    max_tokens=p['max_tokens'],\n"
        "    temperature=p['temperature'],\n"
        "    source_module=p['source_module'],\n"
        "))\n"
        "print(json.dumps({\n"
        "    'text': getattr(r, 'text', None),\n"
        "    'source': getattr(r, 'source', None),\n"
        "    'breaker_state': getattr(r, 'breaker_state', None),\n"
        "    'latency_ms': getattr(r, 'latency_ms', None),\n"
        "}))\n"
    )

    try:
        proc = subprocess.run(
            [venv_py, "-c", runner],
            input=json.dumps(payload),
            cwd=AI_ROUTER_BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=AI_ROUTER_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return (None, None, {
                "ai_subprocess_failed": True,
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
            })
        # ai_router may print log lines; the JSON is on the LAST non-empty stdout line.
        out_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if not out_lines:
            return (None, None, {"ai_no_output": True, "stderr_tail": (proc.stderr or "")[-1000:]})
        try:
            result = json.loads(out_lines[-1])
        except json.JSONDecodeError as je:
            return (None, None, {
                "ai_parse_error": str(je),
                "stdout_tail": (proc.stdout or "")[-1000:],
            })
        meta = {
            "task_type": AI_ROUTER_TASK_TYPE,
            "ai_source": result.get("source"),
            "breaker_state": result.get("breaker_state"),
            "latency_ms": result.get("latency_ms"),
            "via": "ai_router_v5",
        }
        return (result.get("text"), None, meta)
    except subprocess.TimeoutExpired:
        return (None, None, {"ai_timeout": True, "timeout_s": AI_ROUTER_TIMEOUT_S})
    except Exception as e:
        log.exception("ai_router subprocess failed: %s", e)
        return (None, None, {"ai_exception": str(e)})


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def run(since_hours: int, dry_run: bool, skip_ai: bool) -> int:
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    log.info(f"Starting run. lookback={since_hours}h dry_run={dry_run} skip_ai={skip_ai}")

    conn_imap = connect_imap()
    try:
        typ, _ = conn_imap.select(IMAP_FOLDER, readonly=False)
        if typ != "OK":
            log.error(f"Cannot select folder {IMAP_FOLDER}")
            return 3

        uids = search_unseen_since(conn_imap, since_dt)
        log.info(f"Found {len(uids)} unseen messages since {since_dt.isoformat()}")
        if not uids:
            return 0
        uids = uids[-MAX_PER_RUN:]  # cap to most recent MAX_PER_RUN

        # DEPRECATED: reservations_draft_queue DB connection — kept for safety, no longer written to.
        # Remove after email pipeline is proven in production for >=48h.
        conn_db = None

        processed = 0
        for uid in uids:
            fe = fetch_by_uid(conn_imap, uid)
            if not fe:
                continue
            log.info(f"UID {uid} from={fe.sender} subject={fe.subject[:80]!r}")

            if dry_run:
                log.info(f"  DRY-RUN: would ingest uid={uid} into email_messages")
                processed += 1
                continue

            message_uuid = ingest_to_email_pipeline(fe, skip_ai=skip_ai)
            if message_uuid:
                log.info(
                    "  ingested uid=%s message_id=%s skip_ai=%s",
                    uid, message_uuid, skip_ai,
                )
            else:
                log.error(
                    "  FAILED to ingest uid=%s — email NOT lost (IMAP still unread), "
                    "will retry on next cron run",
                    uid,
                )
            processed += 1

        # DEPRECATED: conn_db (reservations_draft_queue) no longer used.
        # Remove after email pipeline is proven in production for >=48h.
        if conn_db:
            conn_db.close()
        log.info(f"Run complete. processed={processed}")
        return 0
    finally:
        try:
            conn_imap.logout()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Reservations IMAP watcher")
    ap.add_argument("--since-hours", type=int, default=LOOKBACK_HOURS,
                    help=f"Lookback window in hours (default {LOOKBACK_HOURS})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + classify but do not write to Postgres")
    ap.add_argument("--no-ai", action="store_true",
                    help="Skip guest_reply_engine — queue emails with no draft")
    args = ap.parse_args()
    try:
        return run(since_hours=args.since_hours, dry_run=args.dry_run, skip_ai=args.no_ai)
    except imaplib.IMAP4.error as e:
        log.error(f"IMAP error: {e}")
        return 4
    except Exception as e:
        log.exception(f"Unhandled error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
