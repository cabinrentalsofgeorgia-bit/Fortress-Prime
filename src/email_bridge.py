#!/usr/bin/env python3
"""
FORTRESS PRIME — Email Bridge Service  (Enterprise v2)
========================================================
Fortune-500-grade email ingestion pipeline with self-healing, recursive
reprocessing, dead-letter recovery, and circuit-breaker resilience.

Architecture:
    Gmail IMAP / IPS Penguin POP3
         │
         ▼
    ┌─────────────────────────────────────────────────┐
    │  Layer 0  ·  HealthMonitor + CircuitBreaker      │
    │  Layer 1  ·  GateKeeper (pre-filter)             │
    │  Layer 2  ·  SmartClassifier (weighted DB rules)  │
    │  Layer 3  ·  EscalationEngine (attention queue)   │
    │  Layer 4  ·  SelfHealingEngine (DLQ + retry)      │
    │  Layer 5  ·  RecursiveReprocessor (confidence lift)│
    └─────────────────────────────────────────────────┘
         │
         ├── email_archive
         ├── email_dead_letter_queue  (failed → retry → recover)
         ├── legal.correspondence + legal.case_evidence
         └── email_escalation_queue

Usage:
    python -m src.email_bridge                          # single pass
    python -m src.email_bridge --watch --interval 120   # continuous
    python -m src.email_bridge --backfill 7             # backfill N days
    python -m src.email_bridge --dry-run                # no DB writes
    python -m src.email_bridge --heal                   # run self-healing only
    python -m src.email_bridge --reprocess              # recursive reprocessing only
"""

import sys
import os
import json
import time
import imaplib
import poplib
import email as email_lib
from email.policy import default as email_default_policy
from email.utils import parsedate_to_datetime
import logging
import argparse
import hashlib
import re
import ssl
import signal
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import psycopg2
import psycopg2.extras
from src.utils.text_sanitizer import sanitize_email_text

try:
    # Unified classifier entrypoint exposed by the batch classifier service module.
    from tools.batch_classifier import classify_document as unified_classify_document
except Exception as import_err:
    unified_classify_document = None
    logger = logging.getLogger("fortress.email_bridge")
    logger.warning("Unified classifier import unavailable at startup: %s", import_err)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fortress.email_bridge")

# Graceful shutdown
_RUNNING = True

def _signal_handler(sig, frame):
    global _RUNNING
    logger.info("Shutdown signal received. Finishing current cycle...")
    _RUNNING = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ── Enterprise Division Taxonomy ──────────────────────────────────────────
VALID_DIVISIONS = {
    "CABIN_VRS", "SALES_OPP", "REAL_ESTATE", "HEDGE_FUND",
    "LEGAL_ADMIN", "FINANCE", "PERSONAL", "JUNK", "UNKNOWN",
    "INSURANCE", "COMPLIANCE", "VENDOR_OPS", "MAINTENANCE",
    "TAX", "HR_ADMIN",
}

# ── SLA Thresholds (hours) per priority ──
SLA_HOURS = {"P0": 1, "P1": 4, "P2": 24, "P3": 72}


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class MailboxConfig:
    """Configuration for a single mailbox (IMAP or POP3)."""
    name: str
    host: str
    port: int
    user: str
    password: str
    protocol: str = "imap"          # "imap" or "pop3"
    use_ssl: bool = True
    verify_cert: bool = True
    folders: List[str] = field(default_factory=lambda: ["INBOX"])
    tag: str = "gmail"


def _get_fgp_conn():
    """Get a connection to fortress_guest DB (where email_sensors lives)."""
    fgp_db_url = os.getenv("FGP_DATABASE_URL", "")
    if fgp_db_url:
        return psycopg2.connect(fgp_db_url)
    return psycopg2.connect(
        dbname="fortress_guest",
        user=os.getenv("FGP_DB_USER", "fgp_app"),
        password=os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def _build_configs_from_db() -> List[MailboxConfig]:
    """Load mailbox configs from the email_sensors table (Sensor Grid).

    Passwords are Fernet-encrypted in the DB. Decrypted here using SECRET_KEY.
    Returns empty list if the table doesn't exist or has no active sensors.
    """
    import base64
    from cryptography.fernet import Fernet

    secret_key = os.getenv("SECRET_KEY", "")
    if not secret_key:
        logger.debug("SECRET_KEY not set — skipping Sensor Grid DB lookup")
        return []

    raw = secret_key.encode()[:32].ljust(32, b"\0")
    fernet = Fernet(base64.urlsafe_b64encode(raw))

    configs: List[MailboxConfig] = []
    conn = None
    try:
        conn = _get_fgp_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT email_address, display_name, protocol, server_address,
                   server_port, encrypted_password, use_ssl
            FROM public.email_sensors
            WHERE is_active = true
            ORDER BY created_at
        """)
        rows = cur.fetchall()
        cur.close()

        if not rows:
            logger.debug("Sensor Grid table empty or missing — falling back to .env")
            conn.close()
            return []

        for email, display, proto, server, port, enc_pw, use_ssl in rows:
            try:
                password = fernet.decrypt(enc_pw.encode()).decode()
            except Exception:
                logger.error("Failed to decrypt password for sensor %s — skipping", email)
                continue

            local = email.split("@")[0].replace(".", "_")
            domain = email.split("@")[1] if "@" in email else ""
            if domain and domain != "cabin-rentals-of-georgia.com":
                tag_suffix = f"{local}_{domain.replace('.', '_')}"
            else:
                tag_suffix = local

            if proto == "imap":
                tag = "gmail" if "gmail" in server else f"imap_{tag_suffix}"
                folders = ["INBOX"]
            else:
                tag = f"ips_pop3_{tag_suffix.lower()}"
                folders = ["INBOX"]

            configs.append(MailboxConfig(
                name=f"{display or email} ({proto.upper()})",
                host=server,
                port=port,
                user=email,
                password=password,
                protocol=proto,
                use_ssl=use_ssl,
                verify_cert=True,
                folders=folders,
                tag=tag,
            ))
            logger.info("Sensor Grid: %s (%s via %s:%d)", email, proto, server, port)

        logger.info("Sensor Grid loaded %d active sensors from DB", len(configs))
        conn.close()
    except Exception as e:
        logger.warning("Sensor Grid DB lookup failed (%s) — falling back to .env", e)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return configs


def _update_sensor_heartbeat(conn_unused, email_address: str, status: str,
                              ingested_count: int = 0, error_msg: str = ""):
    """Update the heartbeat for a sensor after a sweep attempt.

    Uses a dedicated fortress_guest connection since the sensor table
    lives in that database, not fortress_db.
    """
    fgp_conn = None
    try:
        fgp_conn = _get_fgp_conn()
        fgp_conn.autocommit = True
        cur = fgp_conn.cursor()
        if status == "green":
            cur.execute("""
                UPDATE public.email_sensors
                SET last_sweep_at = NOW(), last_sweep_status = 'green',
                    last_sweep_error = NULL,
                    emails_ingested_total = emails_ingested_total + %s,
                    updated_at = NOW()
                WHERE email_address = %s
            """, (ingested_count, email_address))
        else:
            cur.execute("""
                UPDATE public.email_sensors
                SET last_sweep_at = NOW(), last_sweep_status = 'red',
                    last_sweep_error = %s, updated_at = NOW()
                WHERE email_address = %s
            """, (error_msg[:500], email_address))
        cur.close()
    except Exception as e:
        logger.debug("Heartbeat update failed for %s: %s", email_address, e)
    finally:
        if fgp_conn:
            try:
                fgp_conn.close()
            except Exception:
                pass


def _load_env_configs() -> List[MailboxConfig]:
    """Load mailbox configurations from environment variables (legacy fallback)."""
    configs = []

    gmail_addr = os.getenv("GMAIL_ADDRESS", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if gmail_addr and gmail_pass:
        configs.append(MailboxConfig(
            name=f"Gmail ({gmail_addr})",
            host="imap.gmail.com",
            port=993,
            user=gmail_addr,
            password=gmail_pass,
            use_ssl=True,
            verify_cert=True,
            folders=["INBOX"],
            tag="gmail",
        ))
        logger.info(f"Gmail mailbox configured: {gmail_addr}")
    else:
        logger.warning("Gmail not configured — set GMAIL_ADDRESS and GMAIL_APP_PASSWORD")

    pop3_host = os.getenv("IPS_POP3_SERVER", "")
    pop3_port = int(os.getenv("IPS_POP3_PORT", "995"))
    if not pop3_host:
        logger.info("IPS POP3 not configured — set IPS_POP3_SERVER in .env")
        return configs

    accounts_str = os.getenv("IPS_POP3_ACCOUNTS", "").strip()
    if accounts_str:
        for acct_email in accounts_str.split(","):
            acct_email = acct_email.strip().lower()
            if not acct_email or "@" not in acct_email:
                continue
            local, domain = acct_email.split("@", 1)
            key_suffix = local.replace(".", "_")
            if domain != "cabin-rentals-of-georgia.com":
                key_suffix += "_" + domain.replace(".", "_")
            password = os.getenv(f"IPS_POP3_PASSWORD_{key_suffix.upper()}", "")
            if not password:
                logger.warning(
                    "IPS POP3 account %s has no password (set IPS_POP3_PASSWORD_%s)",
                    acct_email, key_suffix.upper(),
                )
                continue
            tag = f"ips_pop3_{key_suffix.lower()}"
            configs.append(MailboxConfig(
                name=f"IPS POP3 ({acct_email})",
                host=pop3_host,
                port=pop3_port,
                user=acct_email,
                password=password,
                protocol="pop3",
                use_ssl=True,
                verify_cert=True,
                tag=tag,
            ))
            logger.info("IPS POP3 configured: %s (%s)", acct_email, tag)

    return configs


def load_mailbox_configs() -> List[MailboxConfig]:
    """Load mailbox configs: DB Sensor Grid first, .env fallback."""
    configs = _build_configs_from_db()
    if configs:
        return configs
    logger.info("Sensor Grid empty — loading from .env (legacy mode)")
    return _load_env_configs()


# =============================================================================
# DATABASE
# =============================================================================

def get_db_conn():
    """Get a Postgres connection (admin via Unix socket by default)."""
    db_user = os.getenv("LEGAL_DB_USER", os.getenv("DB_USER_OVERRIDE", "admin"))
    db_name = os.getenv("DB_NAME", "fortress_db")
    db_pass = os.getenv("LEGAL_DB_PASS") or os.getenv("DB_PASS") or os.getenv("DB_PASSWORD") or os.getenv("ADMIN_DB_PASS") or ""

    params = {"dbname": db_name, "user": db_user}
    explicit_host = os.getenv("LEGAL_DB_HOST", "")
    if explicit_host:
        params["host"] = explicit_host
        params["port"] = os.getenv("LEGAL_DB_PORT", "5432")
    if db_pass:
        params["password"] = db_pass

    return psycopg2.connect(**params)


# =============================================================================
# WATCHDOG ENGINE
# =============================================================================

def load_watchdog_terms(conn) -> Dict[int, List[Dict]]:
    """Load active watchdog terms grouped by case_id.

    Returns: {case_id: [{"search_type": ..., "search_term": ..., "priority": ...}]}
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT w.case_id, w.search_type, w.search_term, w.priority,
               c.case_name, c.case_number, c.case_slug
        FROM legal.case_watchdog w
        JOIN legal.cases c ON c.id = w.case_id
        WHERE w.is_active = true
        ORDER BY w.case_id, w.priority
    """)
    rows = cur.fetchall()
    cur.close()

    terms: Dict[int, List[Dict]] = {}
    for row in rows:
        cid = row["case_id"]
        if cid not in terms:
            terms[cid] = []
            terms[cid].append({**dict(row), "slug": row.get("case_slug", "")})

    return terms


def check_watchdog(email_data: Dict, watchdog_terms: Dict[int, List[Dict]]) -> List[Dict]:
    """Check a single email against all watchdog terms.

    Returns list of matches: [{"case_id": ..., "case_name": ..., "term": ..., "match_type": ..., "priority": ...}]
    """
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

    # Deduplicate by case_id (keep highest priority match)
    seen_cases = {}
    for m in matches:
        cid = m["case_id"]
        if cid not in seen_cases or m["priority"] < seen_cases[cid]["priority"]:
            seen_cases[cid] = m
    return list(seen_cases.values())


def create_legal_records(conn, email_data: Dict, match: Dict, archive_id: int):
    """Create legal CRM records for a watchdog-matched email."""
    cur = conn.cursor()
    case_id = match["case_id"]

    # 1. Insert into legal.correspondence (inbound)
    cur.execute("""
        INSERT INTO legal.correspondence (
            case_id, direction, comm_type, recipient, recipient_email,
            subject, body, status, sent_at
        ) VALUES (%s, 'inbound', 'email', %s, %s, %s, %s, 'received', %s)
        ON CONFLICT DO NOTHING
        RETURNING id
    """, (
        case_id,
        email_data.get("sender_name", email_data.get("sender", "")),
        email_data.get("sender", ""),
        email_data.get("subject", ""),
        email_data.get("body", "")[:5000],
        email_data.get("sent_at"),
    ))
    corr_id = cur.fetchone()

    # 2. Insert into legal.case_evidence
    cur.execute("""
        INSERT INTO legal.case_evidence (
            case_id, evidence_type, email_id, description,
            relevance, discovered_at, is_critical
        ) VALUES (%s, 'email', %s, %s, %s, NOW(), %s)
        RETURNING id
    """, (
        case_id,
        archive_id,
        f"Auto-captured by Email Bridge: {email_data.get('subject', '')} — From: {email_data.get('sender', '')}",
        f"Watchdog match: '{match['term']}' ({match['match_type']}). Case: {match['case_name']}",
        match["priority"] == "P1",
    ))
    evidence_id = cur.fetchone()

    conn.commit()
    cur.close()

    logger.info(
        f"  LEGAL ALERT [{match['priority']}] Case #{case_id} ({match['case_name']}): "
        f"Matched '{match['term']}' in {match['match_type']}. "
        f"Correspondence={corr_id}, Evidence={evidence_id}"
    )

    # 3. Write alert file for CRM to pick up (non-fatal if NAS is down)
    alert_dir = Path("/mnt/fortress_nas/sectors/legal") / match.get("slug", "alerts") / "alerts"
    try:
        alert_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning(f"  NAS alert dir not writable: {alert_dir}")
        return
    alert_file = alert_dir / f"alert_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{archive_id}.json"
    try:
        alert_file.write_text(json.dumps({
            "type": "watchdog_match",
            "priority": match["priority"],
            "case_id": case_id,
            "case_name": match["case_name"],
            "case_number": match.get("case_number", ""),
            "match_term": match["term"],
            "match_type": match["match_type"],
            "email_from": email_data.get("sender", ""),
            "email_subject": email_data.get("subject", ""),
            "email_date": str(email_data.get("sent_at", "")),
            "archive_id": archive_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
        logger.info(f"  Alert file written: {alert_file}")
    except Exception as e:
        logger.warning(f"  Could not write alert file: {e}")


# =============================================================================
# IMAP EMAIL FETCHING
# =============================================================================

def connect_imap(config: MailboxConfig) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to an IMAP server."""
    if config.use_ssl:
        ctx = ssl.create_default_context()
        if not config.verify_cert:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        imap = imaplib.IMAP4_SSL(config.host, config.port, ssl_context=ctx)
    else:
        imap = imaplib.IMAP4(config.host, config.port)

    imap.login(config.user, config.password)
    logger.info(f"IMAP connected: {config.name}")
    return imap


def clean_html(raw_html: str) -> str:
    """Strip HTML tags to extract readable text."""
    return sanitize_email_text(raw_html, max_length=50000)


def parse_imap_email(msg_data: bytes) -> Dict[str, Any]:
    """Parse a raw IMAP email into a structured dict."""
    msg = email_lib.message_from_bytes(msg_data, policy=email_default_policy)

    sender = str(msg.get("From", "Unknown"))
    to_addr = str(msg.get("To", ""))
    cc_addr = str(msg.get("CC", ""))
    subject = str(msg.get("Subject", "No Subject"))
    message_id = str(msg.get("Message-ID", ""))
    in_reply_to = str(msg.get("In-Reply-To", ""))

    # Parse sender name
    sender_name = sender
    if "<" in sender:
        sender_name = sender.split("<")[0].strip().strip('"').strip("'")
    sender_email = sender
    match = re.search(r'<([^>]+)>', sender)
    if match:
        sender_email = match.group(1)

    # Parse date
    date_str = msg.get("Date", "")
    try:
        sent_at = parsedate_to_datetime(date_str)
    except Exception:
        sent_at = datetime.now(timezone.utc)

    # Extract body
    body = ""
    has_attachments = False
    attachment_names = []

    try:
        text_body = msg.get_body(preferencelist=('plain',))
        if text_body:
            body = text_body.get_content()
        else:
            html_body = msg.get_body(preferencelist=('html',))
            if html_body:
                body = clean_html(html_body.get_content())
    except Exception:
        pass

    if not body:
        # Fallback: walk parts
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    body += part.get_payload(decode=True).decode(errors='ignore')
                except Exception:
                    pass
            elif ct == "text/html" and "attachment" not in cd and not body:
                try:
                    body += clean_html(part.get_payload(decode=True).decode(errors='ignore'))
                except Exception:
                    pass
            if "attachment" in cd or ct.startswith("application/"):
                has_attachments = True
                fname = part.get_filename()
                if fname:
                    attachment_names.append(fname)

    # Generate a stable fingerprint for dedup
    fingerprint = hashlib.sha256(
        f"{sender_email}|{subject}|{str(sent_at)[:19]}".encode()
    ).hexdigest()[:32]

    return {
        "sender": sender_email,
        "sender_name": sender_name,
        "to": to_addr,
        "cc": cc_addr,
        "subject": subject,
        "body": body[:50000],  # Cap at 50KB
        "sent_at": sent_at,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "has_attachments": has_attachments,
        "attachment_names": attachment_names,
        "fingerprint": fingerprint,
    }


def fetch_new_emails(
    config: MailboxConfig,
    since_date: Optional[datetime] = None,
    max_fetch: int = 200,
) -> List[Dict]:
    """Fetch new emails from an IMAP mailbox.

    Args:
        config: Mailbox configuration
        since_date: Only fetch emails after this date
        max_fetch: Maximum number of emails to fetch per folder
    """
    emails = []

    try:
        imap = connect_imap(config)
    except Exception as e:
        logger.error(f"IMAP connection failed for {config.name}: {e}")
        return emails

    try:
        for folder in config.folders:
            try:
                status, _ = imap.select(folder, readonly=True)
                if status != "OK":
                    logger.warning(f"Cannot select folder {folder} on {config.name}")
                    continue
            except Exception as e:
                logger.warning(f"Error selecting {folder}: {e}")
                continue

            # Build search criteria
            if since_date:
                date_str = since_date.strftime("%d-%b-%Y")
                search_criteria = f'(SINCE "{date_str}")'
            else:
                # Default: last 3 days
                since = datetime.now(timezone.utc) - timedelta(days=3)
                date_str = since.strftime("%d-%b-%Y")
                search_criteria = f'(SINCE "{date_str}")'

            status, results = imap.search(None, search_criteria)
            if status != "OK":
                continue

            msg_ids = results[0].split()
            if not msg_ids:
                logger.info(f"  {config.name}/{folder}: No new emails since {date_str}")
                continue

            # Limit fetch (0 = no limit, fetch all matching SINCE)
            total_available = len(msg_ids)
            if max_fetch > 0 and total_available > max_fetch:
                msg_ids = msg_ids[-max_fetch:]
                logger.info(f"  {config.name}/{folder}: Limiting to last {max_fetch} of {total_available} emails")
            else:
                logger.info(f"  {config.name}/{folder}: Processing all {total_available} emails since {date_str}")

            for msg_id in msg_ids:
                try:
                    status, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    if not isinstance(raw, bytes):
                        continue
                    parsed = parse_imap_email(raw)
                    parsed["source_tag"] = config.tag
                    parsed["source_folder"] = folder
                    parsed["imap_uid"] = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    emails.append(parsed)
                except Exception as e:
                    logger.warning(f"  Error parsing email {msg_id}: {e}")
                    continue

    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return emails


# =============================================================================
# POP3 EMAIL FETCHING  (IPS Penguin — company accounts)
# =============================================================================

def connect_pop3(config: MailboxConfig) -> poplib.POP3_SSL:
    """Connect and authenticate to a POP3 server over SSL."""
    ctx = ssl.create_default_context()
    if not config.verify_cert:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    pop = poplib.POP3_SSL(config.host, config.port, context=ctx)
    pop.user(config.user)
    pop.pass_(config.password)
    logger.info("POP3 connected: %s (%d messages)", config.name, len(pop.list()[1]))
    return pop


def fetch_pop3_emails(
    config: MailboxConfig,
    max_fetch: int = 200,
) -> Tuple[Optional[poplib.POP3_SSL], List[Dict]]:
    """Fetch emails from a POP3 mailbox.

    Unlike IMAP, POP3 does not support date-based SEARCH. We retrieve all
    available messages (up to max_fetch) and rely on the dedup fingerprint
    in ``ingest_email`` to skip previously processed emails.

    Returns:
        (pop_connection, emails)  — caller MUST keep the connection open
        until delete confirmations are done, then call pop.quit().
        Returns (None, []) on connection failure.
    """
    emails: List[Dict] = []
    pop = None

    try:
        pop = connect_pop3(config)
    except Exception as e:
        logger.error("POP3 connection failed for %s: %s", config.name, e)
        return None, emails

    try:
        resp, listings, _ = pop.list()
        if not listings:
            logger.info("  %s: mailbox empty", config.name)
            return pop, emails

        total_available = len(listings)
        msg_numbers = []
        for entry in listings:
            parts = entry.split()
            msg_numbers.append(int(parts[0]))

        if max_fetch > 0 and total_available > max_fetch:
            msg_numbers = msg_numbers[-max_fetch:]
            logger.info("  %s: limiting to last %d of %d messages", config.name, max_fetch, total_available)
        else:
            logger.info("  %s: processing all %d messages", config.name, total_available)

        for msg_num in msg_numbers:
            try:
                resp, raw_lines, octets = pop.retr(msg_num)
                raw_bytes = b"\r\n".join(raw_lines)
                parsed = parse_imap_email(raw_bytes)
                parsed["source_tag"] = config.tag
                parsed["source_folder"] = "POP3"
                parsed["pop3_msg_num"] = msg_num
                emails.append(parsed)
            except Exception as e:
                logger.warning("  POP3 error retrieving msg #%d from %s: %s", msg_num, config.name, e)
                continue

    except Exception as e:
        logger.error("POP3 fetch error for %s: %s", config.name, e)

    return pop, emails


# =============================================================================
# LAYER 1: GATE KEEPER — Pre-Ingestion Filter
# =============================================================================

class GateKeeper:
    """Database-driven pre-ingestion filter.

    Checks every email against email_routing_rules BEFORE it enters email_archive.
    Actions: ALLOW, REJECT (quarantine), QUARANTINE (quarantine for review),
             ESCALATE (allow + flag for Gary), PRIORITY (allow + priority flag).
    """

    def __init__(self, conn):
        self.rules = self._load_rules(conn)
        self._stats = {"allowed": 0, "rejected": 0, "quarantined": 0, "escalated": 0}
        logger.info(f"GateKeeper loaded: {len(self.rules)} active routing rules")

    def _load_rules(self, conn) -> List[Dict]:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, rule_type, pattern, action, division, reason
            FROM email_routing_rules
            WHERE is_active = TRUE
            ORDER BY
                CASE action
                    WHEN 'ALLOW' THEN 1
                    WHEN 'ESCALATE' THEN 2
                    WHEN 'PRIORITY' THEN 3
                    WHEN 'QUARANTINE' THEN 4
                    WHEN 'REJECT' THEN 5
                END,
                rule_type
        """)
        rules = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rules

    def check(self, email_data: Dict) -> Dict:
        """Check an email against all routing rules.

        Returns: {"action": "ALLOW|REJECT|QUARANTINE|ESCALATE|PRIORITY",
                  "rule_id": int or None, "reason": str, "division_hint": str or None}
        """
        sender = (email_data.get("sender") or "").lower()
        subject = (email_data.get("subject") or "").lower()
        body = (email_data.get("body") or "")[:3000].lower()

        # Phase 1: Check ALLOW rules first (trusted domains/senders bypass blocks)
        for rule in self.rules:
            if rule["action"] not in ("ALLOW",):
                continue
            if self._match_rule(rule, sender, subject, body):
                return {"action": "ALLOW", "rule_id": rule["id"],
                        "reason": rule["reason"], "division_hint": rule.get("division")}

        # Phase 2: Check VIP/ESCALATE rules
        for rule in self.rules:
            if rule["action"] not in ("ESCALATE", "PRIORITY"):
                continue
            if self._match_rule(rule, sender, subject, body):
                self._stats["escalated"] += 1
                return {"action": rule["action"], "rule_id": rule["id"],
                        "reason": rule["reason"], "division_hint": rule.get("division")}

        # Phase 3: Check BLOCK/QUARANTINE rules
        for rule in self.rules:
            if rule["action"] not in ("REJECT", "QUARANTINE"):
                continue
            if self._match_rule(rule, sender, subject, body):
                action = rule["action"]
                if action == "REJECT":
                    self._stats["rejected"] += 1
                else:
                    self._stats["quarantined"] += 1
                return {"action": action, "rule_id": rule["id"],
                        "reason": rule["reason"], "division_hint": None}

        # Phase 4: No rule matched — allow by default
        self._stats["allowed"] += 1
        return {"action": "ALLOW", "rule_id": None, "reason": "No blocking rule matched",
                "division_hint": None}

    def _match_rule(self, rule: Dict, sender: str, subject: str, body: str) -> bool:
        """Test a single rule against email fields."""
        rt = rule["rule_type"]
        pattern = rule["pattern"].lower()

        if rt in ("sender_block", "sender_vip", "sender_allow", "domain_trust"):
            return self._like_match(pattern, sender)
        elif rt == "subject_block":
            return self._like_match(pattern, subject)
        elif rt == "content_block":
            if "+" in pattern:
                parts = [p.strip() for p in pattern.split("+")]
                return all(p in body for p in parts)
            return pattern in body
        return False

    @staticmethod
    def _like_match(pattern: str, text: str) -> bool:
        """SQL LIKE-style matching (% as wildcard)."""
        if not pattern or not text:
            return False
        pattern = pattern.strip("%")
        return pattern in text

    def quarantine(self, conn, email_data: Dict, gate_result: Dict):
        """Send a rejected email to quarantine instead of discarding it."""
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO email_quarantine
                (sender, subject, content_preview, sent_at, fingerprint,
                 source_tag, rule_id, rule_type, rule_reason, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'quarantined')
        """, (
            email_data.get("sender", ""),
            email_data.get("subject", ""),
            (email_data.get("body") or "")[:500],
            email_data.get("sent_at"),
            email_data.get("fingerprint", ""),
            email_data.get("source_tag", ""),
            gate_result.get("rule_id"),
            gate_result.get("action", "REJECT"),
            gate_result.get("reason", ""),
        ))
        conn.commit()
        cur.close()

    def bump_hit_count(self, conn, rule_id: int):
        """Increment hit counter on the matched rule."""
        if rule_id:
            cur = conn.cursor()
            cur.execute("UPDATE email_routing_rules SET hit_count = hit_count + 1 WHERE id = %s", (rule_id,))
            conn.commit()
            cur.close()

    @property
    def stats(self):
        return dict(self._stats)


# =============================================================================
# LAYER 2: SMART CLASSIFIER — Database-Driven Division Routing
# =============================================================================

class SmartClassifier:
    """Database-driven email division classifier.

    Reads weighted rules from email_classification_rules and scores each email
    across all divisions. Much more accurate than the old hardcoded keyword lists.
    """

    def __init__(self, conn):
        self.rules = self._load_rules(conn)
        self._divisions = set(r["division"] for r in self.rules)
        logger.info(f"SmartClassifier loaded: {len(self.rules)} rules across {len(self._divisions)} divisions")

    def _load_rules(self, conn) -> List[Dict]:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, division, match_field, pattern, weight
            FROM email_classification_rules
            WHERE is_active = TRUE
            ORDER BY weight DESC
        """)
        rules = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rules

    def classify(self, email_data: Dict, division_hint: str = None) -> Tuple[str, int, str]:
        """Classify an email into a division using weighted DB rules.

        Args:
            email_data: Parsed email dict
            division_hint: Optional hint from GateKeeper (VIP sender → division)

        Returns: (division, confidence 0-100, summary)
        """
        sender = (email_data.get("sender") or "").lower()
        subject = (email_data.get("subject") or "").lower()
        body = (email_data.get("body") or "")[:3000].lower()

        scores = {}
        matched_rules = {}

        for rule in self.rules:
            div = rule["division"]
            pattern = rule["pattern"].lower()
            field = rule["match_field"]
            weight = rule["weight"]

            hit = False
            if field == "sender" and pattern in sender:
                hit = True
            elif field == "subject" and pattern in subject:
                hit = True
            elif field == "content" and pattern in body:
                hit = True
            elif field == "any" and (pattern in sender or pattern in subject or pattern in body):
                hit = True

            if hit:
                scores[div] = scores.get(div, 0) + weight
                if div not in matched_rules:
                    matched_rules[div] = []
                matched_rules[div].append(rule["pattern"])

        # If GateKeeper gave us a division hint and we have some score for it, boost it
        if division_hint and division_hint in scores:
            scores[division_hint] = scores[division_hint] + 50

        if not scores:
            return "PERSONAL", 10, "No classification rules matched"

        # If JUNK wins, label it but still store
        best_div = max(scores, key=scores.get)
        best_score = scores[best_div]
        total_score = sum(scores.values()) or 1

        # Confidence: ratio of best to total, scaled
        raw_confidence = (best_score / total_score) * 100
        # Also factor in absolute score (more rules hit = more confident)
        abs_factor = min(best_score / 100, 1.0)
        confidence = int(raw_confidence * 0.6 + abs_factor * 40)
        confidence = max(10, min(confidence, 98))

        top_patterns = matched_rules.get(best_div, [])[:3]
        summary = f"SmartClassifier: {best_div} (score={best_score}, rules={len(top_patterns)}): {', '.join(top_patterns)}"

        return best_div, confidence, summary

    def bump_hit_counts(self, conn, email_data: Dict, division: str):
        """Increment hit counters for the rules that matched."""
        sender = (email_data.get("sender") or "").lower()
        subject = (email_data.get("subject") or "").lower()
        body = (email_data.get("body") or "")[:3000].lower()

        matched_ids = []
        for rule in self.rules:
            if rule["division"] != division:
                continue
            pattern = rule["pattern"].lower()
            field = rule["match_field"]
            hit = False
            if field == "sender" and pattern in sender:
                hit = True
            elif field == "subject" and pattern in subject:
                hit = True
            elif field == "content" and pattern in body:
                hit = True
            elif field == "any" and (pattern in sender or pattern in subject or pattern in body):
                hit = True
            if hit:
                matched_ids.append(rule["id"])

        if matched_ids:
            cur = conn.cursor()
            cur.execute(
                "UPDATE email_classification_rules SET hit_count = hit_count + 1 WHERE id = ANY(%s)",
                (matched_ids,)
            )
            conn.commit()
            cur.close()


class UnifiedTriageClassifier:
    """Unified AI triage classifier with graceful fallback to legacy rules."""

    def __init__(self, conn):
        self._fallback = SmartClassifier(conn)
        self._ready = unified_classify_document is not None
        logger.info("UnifiedTriageClassifier initialized (ai_ready=%s)", self._ready)

    def classify(self, email_data: Dict, division_hint: str = None) -> Tuple[str, int, str]:
        sender = (email_data.get("sender") or "").strip()
        subject = sanitize_email_text(email_data.get("subject") or "", max_length=500)
        body = sanitize_email_text(email_data.get("body") or "", max_length=5000)

        if self._ready:
            try:
                doc = f"From: {sender}\nSubject: {subject}\n\nBody:\n{body}"
                result = unified_classify_document(
                    doc,
                    context="email_triage",
                    metadata={"sender": sender, "subject": subject},
                )
                division = (result.get("division") or "UNKNOWN").upper().strip()
                if division == "UNKNOWN" and division_hint:
                    division = division_hint
                confidence = int(round(float(result.get("confidence", 0.0)) * 100))
                confidence = max(0, min(confidence, 100))
                priority = (result.get("priority") or "P3").upper().strip()
                summary = result.get("summary") or "Unified AI triage classification"
                return division, confidence, f"UnifiedAI[{priority}] {summary}"
            except Exception as e:
                logger.exception("Unified classifier call failed, using legacy fallback: %s", e)

        # Fallback path keeps ingestion resilient.
        return self._fallback.classify(
            {"sender": sender, "subject": subject, "body": body},
            division_hint=division_hint,
        )

    def bump_hit_counts(self, conn, email_data: Dict, division: str):
        # Preserve legacy telemetry while unified classifier ramps up.
        self._fallback.bump_hit_counts(conn, email_data, division)


# =============================================================================
# LAYER 3: ESCALATION ENGINE — Gary's Attention Queue
# =============================================================================

class EscalationEngine:
    """Database-driven escalation engine.

    Checks ingested emails against escalation rules and pushes matches
    to email_escalation_queue for Gary's review.
    """

    def __init__(self, conn):
        self.rules = self._load_rules(conn)
        self._stats = {"escalated": 0}
        logger.info(f"EscalationEngine loaded: {len(self.rules)} active escalation rules")

    def _load_rules(self, conn) -> List[Dict]:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, rule_name, trigger_type, match_field, pattern, priority
            FROM email_escalation_rules
            WHERE is_active = TRUE
            ORDER BY priority, id
        """)
        rules = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rules

    TRUSTED_DOMAINS = {"cabin-rentals-of-georgia.com"}

    def check_and_escalate(self, conn, email_data: Dict, archive_id: int,
                           division: str, confidence: int):
        """Check an email against escalation rules and create queue entries."""
        sender = (email_data.get("sender") or "").lower()
        subject = (email_data.get("subject") or "").lower()
        body = (email_data.get("body") or "")[:3000].lower()

        # Skip content-based escalation for trusted internal senders.
        # Their emails may contain legal/financial keywords in forwarded
        # articles — those are not actionable threats.
        is_internal = any(d in sender for d in self.TRUSTED_DOMAINS)

        escalations = []

        for rule in self.rules:
            pattern = rule["pattern"].lower()
            field = rule["match_field"]
            trigger = rule["trigger_type"]

            # Internal staff: only escalate sender-based rules (VIP flagging),
            # never content/subject keyword matches
            if is_internal and trigger == "content_flag":
                continue

            hit = False
            if trigger == "failed_classification" and division == "UNKNOWN":
                hit = True
            elif field == "sender" and pattern.strip("%") in sender:
                hit = True
            elif field == "subject" and pattern.strip("%") in subject:
                hit = True
            elif field == "content" and pattern.strip("%") in body:
                hit = True
            elif field == "any":
                clean = pattern.strip("%")
                if clean in sender or clean in subject or clean in body:
                    hit = True

            if hit:
                escalations.append({
                    "trigger_type": trigger,
                    "trigger_detail": f"{rule['rule_name']}: matched '{rule['pattern']}' ({field})",
                    "priority": rule["priority"],
                })

        # Also escalate low-confidence classifications
        if confidence < 30 and division != "JUNK":
            escalations.append({
                "trigger_type": "failed_classification",
                "trigger_detail": f"Low confidence classification: {division} at {confidence}%",
                "priority": "P3",
            })

        if not escalations:
            return

        # Deduplicate by trigger_type, keep highest priority
        seen = {}
        for esc in escalations:
            tt = esc["trigger_type"]
            if tt not in seen or esc["priority"] < seen[tt]["priority"]:
                seen[tt] = esc

        cur = conn.cursor()
        for esc in seen.values():
            cur.execute("""
                INSERT INTO email_escalation_queue
                    (email_id, trigger_type, trigger_detail, priority)
                VALUES (%s, %s, %s, %s)
            """, (archive_id, esc["trigger_type"], esc["trigger_detail"], esc["priority"]))
            self._stats["escalated"] += 1
            logger.warning(
                f"  ESCALATION [{esc['priority']}] #{archive_id}: {esc['trigger_detail']}"
            )
        conn.commit()
        cur.close()

    @property
    def stats(self):
        return dict(self._stats)


# =============================================================================
# LAYER 4: SELF-HEALING ENGINE — Dead Letter Queue + Circuit Breaker
# =============================================================================

class CircuitBreaker:
    """Prevents cascading failures by tripping after repeated errors."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure: Optional[datetime] = None
        self._state = "CLOSED"  # CLOSED (healthy), OPEN (tripped), HALF_OPEN (probing)

    @property
    def state(self):
        if self._state == "OPEN" and self._last_failure:
            elapsed = (datetime.now(timezone.utc) - self._last_failure).total_seconds()
            if elapsed >= self._recovery_timeout:
                self._state = "HALF_OPEN"
                logger.info("CircuitBreaker → HALF_OPEN (probing recovery)")
        return self._state

    def record_success(self):
        if self._state == "HALF_OPEN":
            logger.info("CircuitBreaker → CLOSED (recovered)")
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure = datetime.now(timezone.utc)
        if self._failure_count >= self._failure_threshold:
            self._state = "OPEN"
            logger.error(
                "CircuitBreaker → OPEN after %d failures. "
                "Will retry in %ds", self._failure_count, self._recovery_timeout
            )

    @property
    def is_available(self) -> bool:
        s = self.state
        return s in ("CLOSED", "HALF_OPEN")


class SelfHealingEngine:
    """Manages the dead-letter queue and automatic retry with exponential backoff."""

    MAX_RETRIES = 5
    BACKOFF_BASE = 60  # seconds

    def __init__(self, conn):
        self.conn = conn
        self._ensure_dlq_table()
        self._stats = {"recovered": 0, "dead": 0, "retried": 0}

    def _ensure_dlq_table(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_dead_letter_queue (
                id              SERIAL PRIMARY KEY,
                fingerprint     TEXT NOT NULL,
                source_tag      TEXT,
                sender          TEXT,
                subject         TEXT,
                raw_payload     JSONB NOT NULL,
                error_message   TEXT,
                error_traceback TEXT,
                retry_count     INTEGER DEFAULT 0,
                max_retries     INTEGER DEFAULT 5,
                next_retry_at   TIMESTAMPTZ,
                status          TEXT DEFAULT 'pending'
                    CHECK (status IN ('pending','retrying','recovered','dead','manual_review')),
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dlq_status_retry
                ON email_dead_letter_queue (status, next_retry_at)
        """)
        self.conn.commit()
        cur.close()

    def enqueue_failure(self, email_data: Dict, error: Exception):
        """Push a failed email into the dead-letter queue."""
        cur = self.conn.cursor()
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=self.BACKOFF_BASE)
        cur.execute("""
            INSERT INTO email_dead_letter_queue
                (fingerprint, source_tag, sender, subject, raw_payload,
                 error_message, error_traceback, next_retry_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            email_data.get("fingerprint", ""),
            email_data.get("source_tag", ""),
            email_data.get("sender", ""),
            email_data.get("subject", ""),
            json.dumps(email_data, default=str),
            str(error),
            traceback.format_exc(),
            next_retry,
        ))
        self.conn.commit()
        cur.close()
        logger.warning("DLQ enqueued: %s — %s", email_data.get("sender", "?"), str(error)[:100])

    def process_retries(self, gatekeeper, classifier, escalator) -> Dict[str, int]:
        """Process all DLQ items that are due for retry."""
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, raw_payload, retry_count, max_retries
            FROM email_dead_letter_queue
            WHERE status IN ('pending', 'retrying')
              AND next_retry_at <= NOW()
            ORDER BY created_at ASC
            LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()

        stats = {"attempted": 0, "recovered": 0, "dead": 0}

        for row in rows:
            stats["attempted"] += 1
            dlq_id = row["id"]
            retry_count = row["retry_count"] + 1
            max_retries = row["max_retries"] or self.MAX_RETRIES

            try:
                email_data = json.loads(row["raw_payload"]) if isinstance(row["raw_payload"], str) else row["raw_payload"]
                archive_id = ingest_email(
                    self.conn, email_data,
                    gatekeeper=gatekeeper,
                    classifier=classifier,
                    escalator=escalator,
                )
                if archive_id:
                    self._mark_recovered(dlq_id)
                    stats["recovered"] += 1
                    self._stats["recovered"] += 1
                    logger.info("DLQ RECOVERED #%d → archive #%d", dlq_id, archive_id)
                else:
                    self._mark_recovered(dlq_id)
                    stats["recovered"] += 1
            except Exception as e:
                if retry_count >= max_retries:
                    self._mark_dead(dlq_id, str(e))
                    stats["dead"] += 1
                    self._stats["dead"] += 1
                    logger.error("DLQ DEAD #%d after %d retries: %s", dlq_id, retry_count, e)
                else:
                    backoff = self.BACKOFF_BASE * (2 ** retry_count)
                    self._schedule_retry(dlq_id, retry_count, str(e), backoff)
                    self._stats["retried"] += 1
                    logger.warning("DLQ retry #%d scheduled for #%d (backoff %ds)", retry_count, dlq_id, backoff)

        return stats

    def _mark_recovered(self, dlq_id: int):
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE email_dead_letter_queue
            SET status = 'recovered', updated_at = NOW() WHERE id = %s
        """, (dlq_id,))
        self.conn.commit()
        cur.close()

    def _mark_dead(self, dlq_id: int, error: str):
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE email_dead_letter_queue
            SET status = 'dead', error_message = %s, updated_at = NOW() WHERE id = %s
        """, (error, dlq_id,))
        self.conn.commit()
        cur.close()

    def _schedule_retry(self, dlq_id: int, retry_count: int, error: str, backoff: int):
        next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE email_dead_letter_queue
            SET status = 'retrying', retry_count = %s, error_message = %s,
                next_retry_at = %s, updated_at = NOW()
            WHERE id = %s
        """, (retry_count, error, next_at, dlq_id,))
        self.conn.commit()
        cur.close()

    @property
    def stats(self):
        return dict(self._stats)


# =============================================================================
# LAYER 5: RECURSIVE REPROCESSOR — Re-evaluate stale classifications
# =============================================================================

class RecursiveReprocessor:
    """Re-evaluates UNKNOWN and low-confidence emails when rules have changed."""

    def __init__(self, conn):
        self.conn = conn

    def reprocess(self, classifier: 'SmartClassifier', escalator: 'EscalationEngine',
                  confidence_threshold: int = 40, max_batch: int = 200) -> Dict[str, int]:
        """Re-classify emails that are UNKNOWN or below the confidence threshold."""
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, sender, subject, LEFT(content, 3000) as body,
                   division, division_confidence, sent_at
            FROM email_archive
            WHERE (division = 'UNKNOWN'
                   OR division_confidence < %s
                   OR (division = 'PERSONAL' AND division_confidence < 30))
              AND sent_at > NOW() - INTERVAL '30 days'
            ORDER BY sent_at DESC
            LIMIT %s
        """, (confidence_threshold, max_batch))
        rows = cur.fetchall()
        cur.close()

        stats = {"evaluated": 0, "upgraded": 0, "unchanged": 0, "newly_escalated": 0}

        for row in rows:
            stats["evaluated"] += 1
            email_data = {
                "sender": row["sender"],
                "subject": row["subject"],
                "body": row["body"],
            }
            new_div, new_conf, summary = classifier.classify(email_data)

            old_div = row["division"]
            old_conf = row["division_confidence"] or 0

            if new_conf > old_conf and (new_div != old_div or new_conf - old_conf >= 15):
                update_cur = self.conn.cursor()
                update_cur.execute("""
                    UPDATE email_archive
                    SET division = %s, division_confidence = %s,
                        division_summary = %s
                    WHERE id = %s
                """, (new_div, new_conf,
                      f"Recursive reprocess: {old_div}({old_conf}%) → {new_div}({new_conf}%)",
                      row["id"]))
                self.conn.commit()
                update_cur.close()
                stats["upgraded"] += 1
                logger.info(
                    "REPROCESS #%d: %s(%d%%) → %s(%d%%)",
                    row["id"], old_div, old_conf, new_div, new_conf
                )

                if new_conf < 50 and new_div != "JUNK":
                    escalator.check_and_escalate(
                        self.conn, email_data, row["id"], new_div, new_conf
                    )
                    stats["newly_escalated"] += 1
            else:
                stats["unchanged"] += 1

        return stats

    def detect_stale_escalations(self) -> List[Dict]:
        """Find escalation items that have breached SLA thresholds."""
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        results = []
        for priority, hours in SLA_HOURS.items():
            cur.execute("""
                SELECT eq.id, eq.email_id, eq.priority, eq.created_at,
                       ea.sender, ea.subject,
                       EXTRACT(EPOCH FROM (NOW() - eq.created_at))/3600 as hours_pending
                FROM email_escalation_queue eq
                JOIN email_archive ea ON ea.id = eq.email_id
                WHERE eq.status = 'pending'
                  AND eq.priority = %s
                  AND eq.created_at < NOW() - INTERVAL '%s hours'
                ORDER BY eq.created_at ASC
            """, (priority, hours))
            for row in cur.fetchall():
                results.append({**dict(row), "sla_hours": hours, "breached": True})
        cur.close()
        return results


# =============================================================================
# SCHEMA MIGRATION — Ensure new columns/tables exist
# =============================================================================

def ensure_enterprise_schema(conn):
    """Idempotent migration: add columns and tables needed by Enterprise v2."""
    cur = conn.cursor()
    migrations = [
        "ALTER TABLE email_escalation_queue ADD COLUMN IF NOT EXISTS snooze_until TIMESTAMPTZ",
        "ALTER TABLE email_intake_review_log ADD COLUMN IF NOT EXISTS review_grade INTEGER DEFAULT 0",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except Exception as e:
            logger.debug("Migration skipped (already exists): %s", e)
            conn.rollback()
    conn.commit()
    cur.close()
    logger.info("Enterprise schema verified")


# =============================================================================
# INGESTION ENGINE (with 5-layer pipeline)
# =============================================================================

def email_exists(conn, fingerprint: str) -> bool:
    """Check if email already exists in archive by fingerprint."""
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM email_archive WHERE file_path = %s LIMIT 1",
        (f"imap://{fingerprint}",)
    )
    exists = cur.fetchone() is not None
    cur.close()
    return exists


def ingest_email(conn, email_data: Dict, gatekeeper: 'GateKeeper',
                 classifier: 'SmartClassifier', escalator: 'EscalationEngine',
                 dry_run: bool = False) -> Optional[int]:
    """Ingest a single email through the 3-layer pipeline.

    Layer 1 (GateKeeper):  Block spam, allow trusted, flag VIPs
    Layer 2 (Classifier):  Assign division with weighted DB rules
    Layer 3 (Escalation):  Flag important items for Gary's queue

    Returns the archive ID if inserted, None if skipped/rejected.
    """
    email_data = dict(email_data)
    email_data["subject"] = sanitize_email_text(email_data.get("subject") or "", max_length=500)
    email_data["body"] = sanitize_email_text(email_data.get("body") or "", max_length=50000)

    fp = email_data["fingerprint"]
    file_path = f"imap://{email_data.get('source_tag', 'unknown')}/{fp}"

    # Dedup check
    cur = conn.cursor()
    cur.execute("SELECT id FROM email_archive WHERE file_path = %s LIMIT 1", (file_path,))
    existing = cur.fetchone()
    if existing:
        cur.close()
        return None

    # ── LAYER 1: Gate Keeper ──────────────────────────────────
    gate_result = gatekeeper.check(email_data)
    action = gate_result["action"]

    if action in ("REJECT", "QUARANTINE"):
        if not dry_run:
            gatekeeper.quarantine(conn, email_data, gate_result)
            gatekeeper.bump_hit_count(conn, gate_result.get("rule_id"))
        logger.info(f"  [{action}] {email_data['sender'][:40]} — {gate_result['reason']}")
        cur.close()
        return None

    if dry_run:
        logger.info(f"  [DRY RUN] Would ingest: {email_data['sender']} — {email_data['subject'][:60]}")
        cur.close()
        return None

    # Bump routing rule hit count for ALLOW/ESCALATE
    gatekeeper.bump_hit_count(conn, gate_result.get("rule_id"))

    # ── LAYER 2: Smart Classifier ─────────────────────────────
    division_hint = gate_result.get("division_hint")
    division, confidence, summary = classifier.classify(email_data, division_hint)

    cur.execute("""
        INSERT INTO email_archive (
            category, file_path, sender, subject, content,
            sent_at, division, division_confidence, division_summary,
            is_mined, is_vectorized
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, false, false
        )
        ON CONFLICT (file_path) DO NOTHING
        RETURNING id
    """, (
        f"imap_{email_data.get('source_tag', 'unknown')}",
        file_path,
        email_data["sender"],
        email_data["subject"],
        email_data["body"][:50000],
        email_data["sent_at"],
        division,
        confidence,
        summary,
    ))
    result = cur.fetchone()
    conn.commit()
    cur.close()

    if not result:
        return None

    archive_id = result[0]

    # Bump classification rule hit counts
    classifier.bump_hit_counts(conn, email_data, division)

    # ── LAYER 3: Escalation Engine ────────────────────────────
    escalator.check_and_escalate(conn, email_data, archive_id, division, confidence)

    # If GateKeeper flagged as ESCALATE, also add to escalation queue
    if action == "ESCALATE":
        esc_cur = conn.cursor()
        esc_cur.execute("""
            INSERT INTO email_escalation_queue
                (email_id, trigger_type, trigger_detail, priority)
            VALUES (%s, 'vip_sender', %s, 'P1')
        """, (archive_id, f"VIP sender rule: {gate_result['reason']}"))
        conn.commit()
        esc_cur.close()

    return archive_id


# =============================================================================
# MAIN BRIDGE LOOP
# =============================================================================

_imap_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)


def _ingest_one(
    conn, em: Dict, gatekeeper, classifier, escalator, healer,
    watchdog_terms: Dict, stats: Dict, dry_run: bool,
) -> Optional[int]:
    """Process a single email through the 5-layer pipeline.

    Returns the archive_id if successfully ingested, None otherwise.
    Updates ``stats`` dict in-place.
    """
    try:
        archive_id = ingest_email(
            conn, em,
            gatekeeper=gatekeeper,
            classifier=classifier,
            escalator=escalator,
            dry_run=dry_run,
        )
        if archive_id:
            stats["ingested"] += 1
            logger.info("  Ingested #%d: %s — %s", archive_id, em['sender'], em['subject'][:60])

            matches = check_watchdog(em, watchdog_terms)
            for match in matches:
                stats["watchdog_hits"] += 1
                logger.warning(
                    "  WATCHDOG HIT [%s] Case: %s | Term: '%s' | Email: %s — %s",
                    match['priority'], match['case_name'],
                    match['term'], em['sender'], em['subject'][:50]
                )
                if not dry_run:
                    try:
                        create_legal_records(conn, em, match, archive_id)
                    except Exception as e:
                        logger.error("  Error creating legal records: %s", e)
                        conn.rollback()
            return archive_id
        else:
            stats["skipped_dupes"] += 1
            return None

    except Exception as e:
        logger.error("  Error processing email from %s: %s", em.get('sender', '?'), e)
        stats["errors"] += 1
        if not dry_run:
            try:
                healer.enqueue_failure(em, e)
            except Exception:
                pass
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def run_bridge_cycle(
    configs: List[MailboxConfig],
    since_date: Optional[datetime] = None,
    dry_run: bool = False,
    max_fetch: int = 200,
) -> Dict[str, int]:
    """Run one full ingestion cycle with 5-layer enterprise pipeline.

    Pipeline per email:
        L0  CircuitBreaker — halt if IMAP is repeatedly failing
        L1  GateKeeper — block spam, quarantine suspicious, allow trusted
        L2  SmartClassifier — DB-driven division assignment (weighted rules)
        L3  EscalationEngine — flag important items for Gary's queue
        L4  SelfHealingEngine — DLQ recovery for failed emails
        L5  RecursiveReprocessor — re-evaluate stale UNKNOWN/low-conf emails

    Returns stats dict.
    """
    stats = {
        "fetched": 0, "ingested": 0, "watchdog_hits": 0,
        "errors": 0, "skipped_dupes": 0,
        "rejected": 0, "quarantined": 0, "escalated": 0,
        "dlq_recovered": 0, "dlq_dead": 0, "dlq_retried": 0,
        "reprocess_upgraded": 0, "sla_breaches": 0,
    }

    conn = None
    try:
        conn = get_db_conn()

        # Schema migration (idempotent)
        ensure_enterprise_schema(conn)

        # Initialize the 5-layer pipeline
        gatekeeper = GateKeeper(conn)
        classifier = UnifiedTriageClassifier(conn)
        escalator = EscalationEngine(conn)
        healer = SelfHealingEngine(conn)
        reprocessor = RecursiveReprocessor(conn)

        watchdog_terms = load_watchdog_terms(conn)
        logger.info(
            "Loaded watchdog: %d terms across %d cases",
            sum(len(v) for v in watchdog_terms.values()), len(watchdog_terms)
        )

        # ── L4: Process DLQ retries before new ingestion ──
        if not dry_run:
            try:
                dlq_stats = healer.process_retries(gatekeeper, classifier, escalator)
                stats["dlq_recovered"] = dlq_stats.get("recovered", 0)
                stats["dlq_dead"] = dlq_stats.get("dead", 0)
                if dlq_stats["attempted"]:
                    logger.info(
                        "DLQ sweep: attempted=%d recovered=%d dead=%d",
                        dlq_stats["attempted"], dlq_stats["recovered"], dlq_stats["dead"]
                    )
            except Exception as e:
                logger.error("DLQ sweep failed (non-fatal): %s", e)

        # ── L0: Circuit Breaker gate ──
        if not _imap_breaker.is_available:
            logger.warning(
                "CircuitBreaker OPEN — skipping email fetch (will retry in %ds)",
                _imap_breaker._recovery_timeout
            )
        else:
            imap_configs = [c for c in configs if c.protocol == "imap"]
            pop3_configs = [c for c in configs if c.protocol == "pop3"]

            # ── IMAP accounts (Gmail) ──
            for config in imap_configs:
                logger.info("Polling IMAP: %s...", config.name)
                ingested_before = stats["ingested"]
                try:
                    emails = fetch_new_emails(config, since_date=since_date, max_fetch=max_fetch)
                    stats["fetched"] += len(emails)
                    _imap_breaker.record_success()
                except Exception as e:
                    logger.error("Failed to fetch from %s: %s", config.name, e)
                    _imap_breaker.record_failure()
                    stats["errors"] += 1
                    _update_sensor_heartbeat(conn, config.user, "red", error_msg=str(e)[:500])
                    continue

                for em in emails:
                    _ingest_one(conn, em, gatekeeper, classifier, escalator, healer,
                                watchdog_terms, stats, dry_run)

                _update_sensor_heartbeat(
                    conn, config.user, "green",
                    ingested_count=stats["ingested"] - ingested_before,
                )

            # ── POP3 accounts (IPS Penguin) ──
            for config in pop3_configs:
                logger.info("Polling POP3: %s...", config.name)
                pop_conn = None
                ingested_before = stats["ingested"]
                try:
                    pop_conn, emails = fetch_pop3_emails(config, max_fetch=max_fetch)
                    stats["fetched"] += len(emails)
                    if pop_conn:
                        _imap_breaker.record_success()
                except Exception as e:
                    logger.error("Failed to fetch POP3 from %s: %s", config.name, e)
                    _imap_breaker.record_failure()
                    stats["errors"] += 1
                    _update_sensor_heartbeat(conn, config.user, "red", error_msg=str(e)[:500])
                    continue

                try:
                    for em in emails:
                        archive_id = _ingest_one(
                            conn, em, gatekeeper, classifier, escalator, healer,
                            watchdog_terms, stats, dry_run,
                        )
                        if archive_id and pop_conn and not dry_run:
                            msg_num = em.get("pop3_msg_num")
                            if msg_num:
                                try:
                                    pop_conn.dele(msg_num)
                                    logger.debug("  POP3 DELE #%d (ingested as archive #%d)", msg_num, archive_id)
                                except Exception as de:
                                    logger.error("  POP3 DELE failed for #%d: %s", msg_num, de)
                finally:
                    if pop_conn:
                        try:
                            pop_conn.quit()
                        except Exception:
                            pass

                _update_sensor_heartbeat(
                    conn, config.user, "green",
                    ingested_count=stats["ingested"] - ingested_before,
                )

        # ── L5: Recursive reprocessing (every cycle) ──
        if not dry_run:
            try:
                rp_stats = reprocessor.reprocess(classifier, escalator)
                stats["reprocess_upgraded"] = rp_stats.get("upgraded", 0)
                if rp_stats["evaluated"]:
                    logger.info(
                        "Reprocessor: evaluated=%d upgraded=%d unchanged=%d",
                        rp_stats["evaluated"], rp_stats["upgraded"], rp_stats["unchanged"]
                    )
            except Exception as e:
                logger.error("Recursive reprocessing failed (non-fatal): %s", e)

        # ── SLA breach detection ──
        if not dry_run:
            try:
                breaches = reprocessor.detect_stale_escalations()
                stats["sla_breaches"] = len(breaches)
                for b in breaches[:5]:
                    logger.warning(
                        "SLA BREACH [%s] #%d: %.1fh pending (limit %dh) — %s",
                        b["priority"], b["id"], b["hours_pending"],
                        b["sla_hours"], b.get("subject", "")[:50]
                    )
            except Exception as e:
                logger.error("SLA detection failed (non-fatal): %s", e)

        # Merge layer stats
        gate_stats = gatekeeper.stats
        stats["rejected"] = gate_stats.get("rejected", 0)
        stats["quarantined"] = gate_stats.get("quarantined", 0)
        stats["escalated"] = escalator.stats.get("escalated", 0)

    except Exception as e:
        logger.error("Bridge cycle error: %s", e)
        stats["errors"] += 1
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return stats


def get_last_ingestion_date(conn) -> Optional[datetime]:
    """Get the date of the most recently ingested IMAP email."""
    cur = conn.cursor()
    cur.execute("""
        SELECT MAX(sent_at) FROM email_archive
        WHERE file_path LIKE 'imap://%'
    """)
    row = cur.fetchone()
    cur.close()
    if row and row[0]:
        return row[0]
    return None


# =============================================================================
# CLI
# =============================================================================

def _run_heal_only():
    """Run only the self-healing DLQ recovery pass."""
    conn = get_db_conn()
    try:
        gatekeeper = GateKeeper(conn)
        classifier = UnifiedTriageClassifier(conn)
        escalator = EscalationEngine(conn)
        healer = SelfHealingEngine(conn)
        stats = healer.process_retries(gatekeeper, classifier, escalator)
        logger.info("Self-healing pass: %s", stats)
    finally:
        conn.close()


def _run_reprocess_only():
    """Run only the recursive reprocessing pass."""
    conn = get_db_conn()
    try:
        classifier = UnifiedTriageClassifier(conn)
        escalator = EscalationEngine(conn)
        reprocessor = RecursiveReprocessor(conn)
        stats = reprocessor.reprocess(classifier, escalator)
        logger.info("Reprocessing pass: %s", stats)
        breaches = reprocessor.detect_stale_escalations()
        logger.info("SLA breaches: %d", len(breaches))
        for b in breaches:
            logger.warning(
                "  [%s] #%d: %.1fh pending (limit %dh) — %s",
                b["priority"], b["id"], b["hours_pending"],
                b["sla_hours"], b.get("subject", "")[:50]
            )
    finally:
        conn.close()


def _format_stats_line(stats: Dict) -> str:
    parts = []
    for key in ("fetched", "ingested", "rejected", "quarantined", "escalated",
                "skipped_dupes", "watchdog_hits", "dlq_recovered", "dlq_dead",
                "reprocess_upgraded", "sla_breaches", "errors"):
        val = stats.get(key, 0)
        if val:
            parts.append(f"{key}={val}")
    return ", ".join(parts) if parts else "no activity"


def main():
    parser = argparse.ArgumentParser(description="Fortress Prime — Email Bridge (Enterprise v2)")
    parser.add_argument("--watch", action="store_true", help="Run continuously (polling mode)")
    parser.add_argument("--interval", type=int, default=120, help="Poll interval in seconds (default: 120)")
    parser.add_argument("--backfill", type=int, default=0, help="Backfill last N days of email")
    parser.add_argument("--dry-run", action="store_true", help="No database writes")
    parser.add_argument("--max-fetch", type=int, default=200, help="Max emails per mailbox per cycle (0 = no limit)")
    parser.add_argument("--mailplus-only", action="store_true", help="(LEGACY) Alias for --pop3-only")
    parser.add_argument("--pop3-only", action="store_true", help="Only fetch from IPS POP3 company accounts")
    parser.add_argument("--gmail-only", action="store_true", help="Only fetch from Gmail IMAP")
    parser.add_argument("--since", type=str, default="", help="Fetch since date (YYYY-MM-DD)")
    parser.add_argument("--heal", action="store_true", help="Run self-healing DLQ recovery only")
    parser.add_argument("--reprocess", action="store_true", help="Run recursive reprocessing only")
    args = parser.parse_args()

    if args.heal:
        logger.info("Running self-healing pass...")
        _run_heal_only()
        return

    if args.reprocess:
        logger.info("Running recursive reprocessing pass...")
        _run_reprocess_only()
        return

    configs = load_mailbox_configs()
    if not configs:
        logger.error("No mailboxes configured. Set GMAIL_ADDRESS/GMAIL_APP_PASSWORD or NAS_IMAP_* / MAILPLUS_IMAP_* in .env")
        sys.exit(1)
    if args.pop3_only or args.mailplus_only:
        configs = [c for c in configs if c.protocol == "pop3"]
        if not configs:
            logger.error("--pop3-only set but no IPS POP3 accounts configured (IPS_POP3_SERVER + IPS_POP3_ACCOUNTS)")
            sys.exit(1)
        logger.info("POP3-only mode: fetching from %d company account(s): %s", len(configs), [c.user for c in configs])
    elif args.gmail_only:
        configs = [c for c in configs if c.protocol == "imap"]
        if not configs:
            logger.error("--gmail-only set but no Gmail IMAP configured (GMAIL_ADDRESS + GMAIL_APP_PASSWORD)")
            sys.exit(1)
        logger.info("Gmail-only mode: fetching from %d IMAP account(s): %s", len(configs), [c.user for c in configs])

    since_date = None
    if args.since:
        since_date = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    elif args.backfill > 0:
        since_date = datetime.now(timezone.utc) - timedelta(days=args.backfill)
    else:
        try:
            conn = get_db_conn()
            last = get_last_ingestion_date(conn)
            conn.close()
            if last:
                since_date = last - timedelta(hours=1)
                logger.info("Resuming from last ingestion: %s", since_date)
            else:
                since_date = datetime.now(timezone.utc) - timedelta(days=3)
                logger.info("No prior IMAP ingestion found. Starting with last 3 days.")
        except Exception as e:
            logger.warning("Could not check last ingestion date: %s", e)
            since_date = datetime.now(timezone.utc) - timedelta(days=3)

    mode = "WATCH" if args.watch else "SINGLE PASS"
    n_imap = sum(1 for c in configs if c.protocol == "imap")
    n_pop3 = sum(1 for c in configs if c.protocol == "pop3")
    banner = (
        "\n"
        "    ╔═══════════════════════════════════════════════════════╗\n"
        "    ║   FORTRESS PRIME — EMAIL BRIDGE  (Enterprise v3)      ║\n"
        f"    ║   Mailboxes: {len(configs):<3} (IMAP:{n_imap} POP3:{n_pop3})  ·  Mode: {mode:<8}  ║\n"
        f"    ║   Interval: {args.interval}s  ·  Dry Run: {str(args.dry_run):<5}               ║\n"
        f"    ║   Since: {str(since_date)[:19] if since_date else 'auto':<22}                 ║\n"
        "    ║   Layers: Gate→Classify→Escalate→Heal→Reprocess      ║\n"
        "    ╚═══════════════════════════════════════════════════════╝\n"
    )
    logger.info(banner)

    if args.watch:
        cycle = 0
        while _RUNNING:
            cycle += 1
            logger.info("=== Cycle %d ===", cycle)
            stats = run_bridge_cycle(configs, since_date=since_date, dry_run=args.dry_run, max_fetch=args.max_fetch)
            logger.info("Cycle %d complete: %s", cycle, _format_stats_line(stats))

            since_date = datetime.now(timezone.utc) - timedelta(hours=6)

            if not _RUNNING:
                break
            logger.info("Sleeping %ds...", args.interval)
            for _ in range(args.interval):
                if not _RUNNING:
                    break
                time.sleep(1)
    else:
        stats = run_bridge_cycle(configs, since_date=since_date, dry_run=args.dry_run, max_fetch=args.max_fetch)
        logger.info("Bridge complete: %s", _format_stats_line(stats))

    logger.info("Email Bridge shutdown complete.")


if __name__ == "__main__":
    main()
