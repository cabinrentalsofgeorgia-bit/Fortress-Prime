#!/usr/bin/env python3
"""
FORTRESS PRIME — Iron Dome Workspace Archiver
==================================================
Domain-wide email compliance archiver using Google Workspace
Service Account with Domain-Wide Delegation.

Polls ALL corporate mailboxes on cabin-rentals-of-georgia.com via
the Gmail API, extracting full metadata (To, CC, BCC, Message-ID)
and committing to the fortress_db email_archive ledger.

Coexists with the legacy Email Bridge (src/email_bridge.py):
  - This script owns INGESTION (vacuum every mailbox)
  - The Email Bridge owns INTELLIGENCE (classify, escalate, heal)

Prerequisites:
  1. Google Cloud project with Gmail API enabled
  2. Service Account with Domain-Wide Delegation
  3. Workspace Admin: Client ID granted gmail.readonly scope
  4. JSON key vaulted at WORKSPACE_SA_KEY_PATH in .env

Usage:
  python3 -m src.workspace_archiver                 # single sweep
  python3 -m src.workspace_archiver --watch         # continuous (5m)
  python3 -m src.workspace_archiver --dry-run       # no DB writes
  python3 -m src.workspace_archiver --backfill 30   # last N days
"""

import os
import sys
import json
import time
import hashlib
import base64
import re
import signal
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from email.utils import parseaddr
from html.parser import HTMLParser

import psycopg2
from dotenv import load_dotenv

load_dotenv()

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("FATAL: google-api-python-client or google-auth not installed.")
    print("Run: pip3 install google-api-python-client google-auth")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SA_KEY_PATH = os.getenv(
    "WORKSPACE_SA_KEY_PATH",
    str(Path(__file__).resolve().parent.parent / ".secrets" / "workspace_service_account.json"),
)
MAILBOXES = [
    m.strip()
    for m in os.getenv(
        "WORKSPACE_MAILBOXES",
        "gary@cabin-rentals-of-georgia.com,"
        "info@cabin-rentals-of-georgia.com,"
        "taylor.knight@cabin-rentals-of-georgia.com,"
        "barbara@cabin-rentals-of-georgia.com,"
        "lissa@cabin-rentals-of-georgia.com",
    ).split(",")
    if m.strip()
]
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
STATE_FILE = Path.home() / ".fortress_archiver_state.json"
DEFAULT_INTERVAL = 300  # 5 minutes
MAX_RESULTS_PER_MAILBOX = 500
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN = 600  # 10 minutes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fortress.workspace_archiver — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fortress.workspace_archiver")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("Shutdown signal received, finishing current cycle...")


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------
class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str) -> str:
    s = _HTMLStripper()
    try:
        s.feed(html)
        return s.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: Dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db_conn():
    db_user = os.getenv("LEGAL_DB_USER", os.getenv("DB_USER_OVERRIDE", "admin"))
    db_name = os.getenv("DB_NAME", "fortress_db")
    db_pass = (
        os.getenv("LEGAL_DB_PASS")
        or os.getenv("DB_PASS")
        or os.getenv("DB_PASSWORD")
        or os.getenv("ADMIN_DB_PASS")
        or ""
    )
    params = {"dbname": db_name, "user": db_user}
    explicit_host = os.getenv("LEGAL_DB_HOST", "")
    if explicit_host:
        params["host"] = explicit_host
        params["port"] = os.getenv("LEGAL_DB_PORT", "5432")
    if db_pass:
        params["password"] = db_pass
    return psycopg2.connect(**params)


# ---------------------------------------------------------------------------
# Legal watchdog (mirrors src/email_bridge.py pattern)
# ---------------------------------------------------------------------------
def load_watchdog_terms(conn) -> Dict[int, List[Dict]]:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT w.case_id, w.search_type, w.search_term, w.priority,
                   c.case_name, c.case_number, c.case_slug
            FROM legal.case_watchdog w
            JOIN legal.cases c ON c.id = w.case_id
            WHERE w.is_active = true
            ORDER BY w.case_id, w.priority
        """)
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("Could not load watchdog terms: %s", e)
        conn.rollback()
        return {}
    finally:
        cur.close()

    terms: Dict[int, List[Dict]] = {}
    for case_id, stype, sterm, priority, cname, cnum, slug in rows:
        terms.setdefault(case_id, []).append({
            "search_type": stype,
            "search_term": sterm,
            "priority": priority or "P2",
            "case_name": cname,
            "case_number": cnum,
            "slug": slug,
        })
    return terms


def check_watchdog(email_data: Dict, watchdog_terms: Dict[int, List[Dict]]) -> List[Dict]:
    matches = []
    sender = (email_data.get("sender") or "").lower()
    subject = (email_data.get("subject") or "").lower()
    body = (email_data.get("body") or "").lower()

    for case_id, terms in watchdog_terms.items():
        for term in terms:
            search_term = term["search_term"].lower()
            search_type = term["search_type"]

            hit = False
            if search_type == "sender" and search_term in sender:
                hit = True
            elif search_type == "subject" and search_term in subject:
                hit = True
            elif search_type == "body" and search_term in body:
                hit = True
            elif search_type == "any":
                if search_term in sender or search_term in subject or search_term in body:
                    hit = True

            if hit:
                matches.append({
                    "case_id": case_id,
                    "case_name": term.get("case_name", ""),
                    "case_number": term.get("case_number", ""),
                    "slug": term.get("slug", ""),
                    "term": term["search_term"],
                    "match_type": search_type,
                    "priority": term.get("priority", "P2"),
                })

    seen_cases = {}
    for m in matches:
        cid = m["case_id"]
        if cid not in seen_cases or m["priority"] < seen_cases[cid]["priority"]:
            seen_cases[cid] = m
    return list(seen_cases.values())


def create_legal_records(conn, email_data: Dict, match: Dict, archive_id: int):
    cur = conn.cursor()
    case_id = match["case_id"]
    try:
        cur.execute("""
            INSERT INTO legal.correspondence (
                case_id, direction, comm_type, recipient, recipient_email,
                subject, body, status, sent_at
            ) VALUES (%s, 'inbound', 'email', %s, %s, %s, %s, 'received', %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (
            case_id,
            email_data.get("sender", ""),
            email_data.get("sender", ""),
            email_data.get("subject", ""),
            (email_data.get("body") or "")[:5000],
            email_data.get("sent_at"),
        ))
        corr_id = cur.fetchone()

        cur.execute("""
            INSERT INTO legal.case_evidence (
                case_id, evidence_type, email_id, description,
                relevance, discovered_at, is_critical
            ) VALUES (%s, 'email', %s, %s, %s, NOW(), %s)
            RETURNING id
        """, (
            case_id,
            archive_id,
            f"Iron Dome auto-captured: {email_data.get('subject', '')} — From: {email_data.get('sender', '')}",
            f"Watchdog match: '{match['term']}' ({match['match_type']}). Case: {match['case_name']}",
            match["priority"] == "P1",
        ))
        evidence_id = cur.fetchone()
        conn.commit()

        logger.warning(
            "LEGAL ALERT [%s] Case #%d (%s): Matched '%s' in %s. Corr=%s, Evidence=%s",
            match["priority"], case_id, match["case_name"],
            match["term"], match["match_type"], corr_id, evidence_id,
        )
    except Exception as e:
        logger.error("Error creating legal records for case %d: %s", case_id, e)
        conn.rollback()
    finally:
        cur.close()

    alert_dir = Path("/mnt/fortress_nas/sectors/legal") / match.get("slug", "alerts") / "alerts"
    try:
        alert_dir.mkdir(parents=True, exist_ok=True)
        alert_file = alert_dir / f"iron_dome_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{archive_id}.json"
        alert_file.write_text(json.dumps({
            "type": "iron_dome_watchdog_match",
            "priority": match["priority"],
            "case_id": case_id,
            "case_name": match["case_name"],
            "archive_id": archive_id,
            "sender": email_data.get("sender", ""),
            "subject": email_data.get("subject", ""),
            "matched_term": match["term"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Gmail API helpers
# ---------------------------------------------------------------------------
def build_gmail_service(sa_key_path: str, impersonate_email: str):
    creds = service_account.Credentials.from_service_account_file(
        sa_key_path, scopes=SCOPES
    )
    delegated = creds.with_subject(impersonate_email)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)


def _decode_part(part: Dict) -> Tuple[Optional[str], Optional[str]]:
    """Extract text from a message part. Returns (text, mime_type)."""
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")

    if data and mime in ("text/plain", "text/html"):
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return decoded, mime

    for sub in part.get("parts", []):
        result = _decode_part(sub)
        if result[0]:
            return result

    return None, None


def extract_email_data(msg: Dict) -> Dict:
    """Parse a Gmail API full-format message into a flat dict."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

    sender = headers.get("from", "")
    to_addr = headers.get("to", "")
    cc_addr = headers.get("cc", "")
    bcc_addr = headers.get("bcc", "")
    subject = headers.get("subject", "")
    message_id = headers.get("message-id", "")
    date_str = headers.get("date", "")

    sent_at = None
    if date_str:
        try:
            from email.utils import parsedate_to_datetime
            sent_at = parsedate_to_datetime(date_str)
            if sent_at.tzinfo:
                sent_at = sent_at.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass

    payload = msg.get("payload", {})
    plain_text = None
    html_text = None

    body_data = payload.get("body", {}).get("data")
    if body_data and payload.get("mimeType") == "text/plain":
        plain_text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
    elif body_data and payload.get("mimeType") == "text/html":
        html_text = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text, mime = _decode_part(part)
        if text:
            if mime == "text/plain" and not plain_text:
                plain_text = text
            elif mime == "text/html" and not html_text:
                html_text = text

    body = plain_text or (strip_html(html_text) if html_text else "")

    fingerprint = hashlib.sha256(
        f"{message_id}|{sender}|{subject}|{date_str}".encode()
    ).hexdigest()[:32]

    return {
        "sender": sender,
        "to_addresses": to_addr,
        "cc_addresses": cc_addr,
        "bcc_addresses": bcc_addr,
        "subject": subject[:500] if subject else "",
        "body": body[:100000] if body else "",
        "message_id": message_id,
        "sent_at": sent_at,
        "fingerprint": fingerprint,
        "gmail_id": msg.get("id", ""),
    }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def ingest_email(conn, email_data: Dict, mailbox: str, dry_run: bool = False) -> Optional[int]:
    """Insert one email into email_archive. Returns archive_id or None if dupe."""
    cur = conn.cursor()

    msg_id = email_data.get("message_id", "")
    if msg_id:
        cur.execute("SELECT id FROM email_archive WHERE message_id = %s LIMIT 1", (msg_id,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            return None

    fp = f"workspace://{mailbox}/{email_data['fingerprint']}"
    cur.execute("SELECT id FROM email_archive WHERE file_path = %s LIMIT 1", (fp,))
    existing = cur.fetchone()
    if existing:
        cur.close()
        return None

    if dry_run:
        logger.info("  [DRY RUN] Would ingest: %s — %s", email_data["sender"][:50], email_data["subject"][:60])
        cur.close()
        return None

    cur.execute("""
        INSERT INTO email_archive (
            sender, subject, content, sent_at, file_path,
            to_addresses, cc_addresses, bcc_addresses, message_id, ingested_from,
            is_mined, is_vectorized
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, false)
        RETURNING id
    """, (
        email_data["sender"],
        email_data["subject"],
        email_data["body"],
        email_data["sent_at"],
        fp,
        email_data["to_addresses"],
        email_data["cc_addresses"],
        email_data["bcc_addresses"],
        email_data["message_id"],
        mailbox,
    ))
    row = cur.fetchone()
    archive_id = row[0] if row else None
    conn.commit()
    cur.close()
    return archive_id


# ---------------------------------------------------------------------------
# Per-mailbox sweep
# ---------------------------------------------------------------------------
def sweep_mailbox(
    service,
    mailbox: str,
    conn,
    watchdog_terms: Dict,
    since_epoch: int,
    dry_run: bool = False,
) -> Dict[str, int]:
    stats = {"fetched": 0, "ingested": 0, "dupes": 0, "errors": 0, "watchdog_hits": 0}

    query = f"after:{since_epoch}"
    page_token = None

    while True:
        if _shutdown:
            break

        try:
            resp = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=MAX_RESULTS_PER_MAILBOX,
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status == 429:
                logger.warning("  Rate limited on %s, backing off 60s...", mailbox)
                time.sleep(60)
                continue
            raise

        messages = resp.get("messages", [])
        if not messages:
            break

        for msg_stub in messages:
            if _shutdown:
                break
            stats["fetched"] += 1

            try:
                full_msg = service.users().messages().get(
                    userId="me", id=msg_stub["id"], format="full"
                ).execute()
            except HttpError as e:
                if e.resp.status == 429:
                    logger.warning("  Rate limited fetching message, backing off 30s...")
                    time.sleep(30)
                    try:
                        full_msg = service.users().messages().get(
                            userId="me", id=msg_stub["id"], format="full"
                        ).execute()
                    except Exception:
                        stats["errors"] += 1
                        continue
                else:
                    stats["errors"] += 1
                    continue

            email_data = extract_email_data(full_msg)

            try:
                archive_id = ingest_email(conn, email_data, mailbox, dry_run=dry_run)
            except Exception as e:
                logger.error("  DB error ingesting from %s: %s", mailbox, e)
                try:
                    conn.rollback()
                except Exception:
                    pass
                stats["errors"] += 1
                continue

            if archive_id:
                stats["ingested"] += 1
                logger.info(
                    "  Ingested #%d [%s]: %s — %s",
                    archive_id, mailbox, email_data["sender"][:40], email_data["subject"][:60],
                )

                matches = check_watchdog(email_data, watchdog_terms)
                for match in matches:
                    stats["watchdog_hits"] += 1
                    logger.warning(
                        "  WATCHDOG HIT [%s] Case: %s | Term: '%s' | From: %s",
                        match["priority"], match["case_name"],
                        match["term"], email_data["sender"][:40],
                    )
                    if not dry_run:
                        try:
                            create_legal_records(conn, email_data, match, archive_id)
                        except Exception as e:
                            logger.error("  Legal records error: %s", e)
            else:
                stats["dupes"] += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return stats


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
class MailboxCircuitBreaker:
    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD, cooldown: int = CIRCUIT_BREAKER_COOLDOWN):
        self._failures: Dict[str, int] = {}
        self._tripped_at: Dict[str, float] = {}
        self._threshold = threshold
        self._cooldown = cooldown

    def is_open(self, mailbox: str) -> bool:
        if mailbox not in self._tripped_at:
            return False
        elapsed = time.time() - self._tripped_at[mailbox]
        if elapsed > self._cooldown:
            self._failures[mailbox] = 0
            del self._tripped_at[mailbox]
            logger.info("Circuit breaker reset for %s after %ds cooldown", mailbox, int(elapsed))
            return False
        return True

    def record_failure(self, mailbox: str):
        self._failures[mailbox] = self._failures.get(mailbox, 0) + 1
        if self._failures[mailbox] >= self._threshold:
            self._tripped_at[mailbox] = time.time()
            logger.error(
                "CIRCUIT BREAKER TRIPPED [P1]: %s — %d consecutive failures. "
                "Skipping for %ds.", mailbox, self._failures[mailbox], self._cooldown,
            )

    def record_success(self, mailbox: str):
        self._failures[mailbox] = 0
        if mailbox in self._tripped_at:
            del self._tripped_at[mailbox]


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------
def run_sweep(
    dry_run: bool = False,
    backfill_days: Optional[int] = None,
) -> Dict[str, int]:
    if not Path(SA_KEY_PATH).exists():
        logger.error(
            "Service account key not found at %s. "
            "Complete Phase 1 (GCP setup) and vault the JSON key.", SA_KEY_PATH,
        )
        return {"error": "SA key not found"}

    state = load_state()
    breaker = MailboxCircuitBreaker()

    if backfill_days:
        since_dt = datetime.now(timezone.utc) - timedelta(days=backfill_days)
    else:
        last_run = state.get("last_successful_sweep")
        if last_run:
            since_dt = datetime.fromisoformat(last_run) - timedelta(minutes=10)
        else:
            since_dt = datetime.now(timezone.utc) - timedelta(days=7)

    since_epoch = int(since_dt.timestamp())

    logger.info(
        "\n"
        "    ╔═══════════════════════════════════════════════════════╗\n"
        "    ║   IRON DOME — Workspace Archiver                     ║\n"
        "    ║   Mailboxes: %-3d  ·  Mode: %-10s                 ║\n"
        "    ║   Since: %-40s  ║\n"
        "    ║   SA Key: %-38s  ║\n"
        "    ╚═══════════════════════════════════════════════════════╝",
        len(MAILBOXES),
        "DRY RUN" if dry_run else "LIVE",
        since_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        Path(SA_KEY_PATH).name[:38],
    )

    totals = {"fetched": 0, "ingested": 0, "dupes": 0, "errors": 0, "watchdog_hits": 0, "skipped_breaker": 0}

    conn = get_db_conn()
    watchdog_terms = load_watchdog_terms(conn)
    logger.info("Loaded watchdog: %d terms across %d cases", sum(len(v) for v in watchdog_terms.values()), len(watchdog_terms))

    for mailbox in MAILBOXES:
        if _shutdown:
            break

        if breaker.is_open(mailbox):
            logger.warning("  SKIPPED %s — circuit breaker open", mailbox)
            totals["skipped_breaker"] += 1
            continue

        logger.info("  Sweeping %s ...", mailbox)
        try:
            svc = build_gmail_service(SA_KEY_PATH, mailbox)
            stats = sweep_mailbox(svc, mailbox, conn, watchdog_terms, since_epoch, dry_run=dry_run)
            breaker.record_success(mailbox)

            for k in ("fetched", "ingested", "dupes", "errors", "watchdog_hits"):
                totals[k] += stats[k]

            logger.info(
                "  %s complete: fetched=%d ingested=%d dupes=%d errors=%d watchdog=%d",
                mailbox, stats["fetched"], stats["ingested"], stats["dupes"],
                stats["errors"], stats["watchdog_hits"],
            )

            state[f"last_sweep_{mailbox}"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error("  FAILED %s: %s", mailbox, e)
            breaker.record_failure(mailbox)
            totals["errors"] += 1
            try:
                conn.rollback()
            except Exception:
                pass

    conn.close()

    if not dry_run and totals["errors"] == 0:
        state["last_successful_sweep"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    logger.info(
        "Sweep complete: fetched=%d ingested=%d dupes=%d errors=%d watchdog_hits=%d skipped_breaker=%d",
        totals["fetched"], totals["ingested"], totals["dupes"],
        totals["errors"], totals["watchdog_hits"], totals["skipped_breaker"],
    )

    return totals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Iron Dome — Workspace Email Archiver")
    parser.add_argument("--watch", action="store_true", help="Continuous mode (sweep every 5 min)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Sweep interval in seconds (default: 300)")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    parser.add_argument("--backfill", type=int, default=None, metavar="DAYS", help="Backfill last N days")
    args = parser.parse_args()

    if args.watch:
        logger.info("Iron Dome entering continuous watch mode (interval=%ds)", args.interval)
        while not _shutdown:
            try:
                run_sweep(dry_run=args.dry_run, backfill_days=args.backfill)
            except Exception as e:
                logger.error("Sweep cycle failed: %s", e)
            if args.backfill:
                args.backfill = None
            if not _shutdown:
                logger.info("Next sweep in %ds...", args.interval)
                for _ in range(args.interval):
                    if _shutdown:
                        break
                    time.sleep(1)
        logger.info("Iron Dome shutdown complete.")
    else:
        run_sweep(dry_run=args.dry_run, backfill_days=args.backfill)


if __name__ == "__main__":
    main()
