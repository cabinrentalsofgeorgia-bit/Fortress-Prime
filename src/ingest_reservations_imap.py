#!/usr/bin/env python3
"""
ingest_reservations_imap.py — Reservations mailbox IMAP watcher

Pattern: poll-based (NOT IDLE). Invoked by cron every 10 minutes.
Source:  reservations@cabin-rentals-of-georgia.com on mail.cabin-rentals-of-georgia.com (cPanel)
Sink:    Postgres table fortress_db.reservations_draft_queue

On startup:
  - First run of the day (or empty queue): scan last 24h for UNSEEN messages
  - Subsequent runs: scan only UNSEEN messages since last run's max UID
Idempotency: imap_uid UNIQUE constraint in Postgres — re-inserts are no-ops

Environment variables (required):
  RESERVATIONS_IMAP_HOST    e.g. "mail.cabin-rentals-of-georgia.com"
  RESERVATIONS_IMAP_PORT    e.g. "993"
  RESERVATIONS_IMAP_USER    e.g. "reservations@cabin-rentals-of-georgia.com"
  RESERVATIONS_IMAP_PASS    cPanel mailbox password
  DB_HOST, DB_NAME, DB_USER, DB_PASS (existing fortress_db credentials)

Environment variables (optional):
  RESERVATIONS_IMAP_FOLDER  default "INBOX"
  RESERVATIONS_LOOKBACK_HOURS  default 24 (first run per day)
  RESERVATIONS_MAX_PER_RUN  default 50 (cap per invocation)

Usage:
  python3 -m src.ingest_reservations_imap                    # production poll
  python3 -m src.ingest_reservations_imap --dry-run          # fetch + classify, don't write to DB
  python3 -m src.ingest_reservations_imap --no-ai            # ingest only, skip reply generation
  python3 -m src.ingest_reservations_imap --since-hours 48   # override lookback
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
# AI draft generation (wraps guest_reply_engine if available)
# -----------------------------------------------------------------------------

def generate_draft(fe: FetchedEmail, skip_ai: bool) -> tuple[Optional[str], Optional[float], Optional[dict]]:
    """
    Attempt to generate an AI draft using guest_reply_engine.
    Returns (draft_text, confidence, meta_dict) — any can be None on failure.
    Failures are logged but non-fatal: email still gets queued with no draft.
    """
    if skip_ai:
        return (None, None, {"ai_skipped": True})
    try:
        from src.guest_reply_engine import process_email  # type: ignore
    except Exception as e:
        log.warning(f"guest_reply_engine unavailable ({e}) — queuing without draft")
        return (None, None, {"ai_unavailable": str(e)})

    try:
        # guest_reply_engine.process_email signature varies by version;
        # we pass a dict payload and catch whatever shape comes back.
        payload = {
            "sender": fe.sender,
            "sender_name": fe.sender_name,
            "subject": fe.subject,
            "body": fe.body_text,
            "received_at": fe.received_at.isoformat(),
            "mailbox": "reservations",
        }
        result = process_email(payload)  # type: ignore
        # Normalize result shape
        if result is None:
            return (None, None, {"ai_returned_none": True})
        if isinstance(result, str):
            return (result, None, None)
        # Assume object/dict with attributes
        draft = getattr(result, "reply_text", None) or (result.get("reply_text") if isinstance(result, dict) else None)
        conf = getattr(result, "confidence", None) or (result.get("confidence") if isinstance(result, dict) else None)
        meta = {
            "tone": getattr(result, "tone", None) or (result.get("tone") if isinstance(result, dict) else None),
            "topic": getattr(result, "topic", None) or (result.get("topic") if isinstance(result, dict) else None),
            "needs_human": getattr(result, "needs_human", None) or (result.get("needs_human") if isinstance(result, dict) else None),
        }
        return (draft, float(conf) if conf is not None else None, meta)
    except Exception as e:
        log.exception(f"guest_reply_engine.process_email raised: {e}")
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

        # DB
        conn_db = None if dry_run else get_db_connection()
        if conn_db:
            ensure_table(conn_db)

        processed = 0
        for uid in uids:
            if conn_db and already_queued(conn_db, uid):
                log.info(f"UID {uid} already queued, skipping")
                continue
            fe = fetch_by_uid(conn_imap, uid)
            if not fe:
                continue
            log.info(f"UID {uid} from={fe.sender} subject={fe.subject[:80]!r}")
            draft, conf, meta = generate_draft(fe, skip_ai=skip_ai)
            if dry_run:
                log.info(f"  DRY-RUN: would insert (draft_len={len(draft) if draft else 0}, conf={conf})")
            else:
                insert_draft(conn_db, fe, draft, conf, meta)
                log.info(f"  inserted UID {uid} status={'pending' if draft else 'pending_no_draft'}")
            processed += 1

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
