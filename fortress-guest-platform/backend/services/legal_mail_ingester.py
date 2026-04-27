"""
Legal Mail Ingester — observable, source-attributed legal email ingestion.

Phase 0a-2 implementation per:
  docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md

Replaces the dead legacy multi-mailbox producer (stopped 2026-03-25). Coexists
with Captain (captain_multi_mailbox.py) — both poll the same legal-tagged
mailboxes via two-pipeline parallel design (§3.4 of design v1.1):

    Captain                       legal_mail_ingester
    -------                       -------------------
    marks \\Seen                  BODY.PEEK[] (no flag mutation)
    feeds llm_training_captures   feeds email_archive + legal.event_log
    routing_tag-aware             ingester=legal_mail filter
    journalctl logs               structured logs + table-backed state

Output discipline (per FLOS principle 10 + ADR-001):
  - ingested_from='legal_mail_ingester:v1' on every email_archive row
  - file_path='imap://{host}/{folder}/{uid}' (deterministic, replayable)
  - category=f'imap_{transport}_{alias}' (legacy-compat for legal_case_manager.py)
  - Bilateral mirror to fortress_db + fortress_prod
  - Per-message try/except — one bad email never aborts a patrol

This file (Phase 0a-2) implements:
  - Sub-phase 2A: service skeleton + IMAP connection layer  ← THIS COMMIT
  - Sub-phase 2B: banded SEARCH + per-message processing    (next commit)
  - Sub-phase 2C: bilateral email_archive write              (next)
  - Sub-phase 2D: event emission to legal.event_log          (next)
  - Sub-phase 2E: patrol loop + state tracking               (next)
  - Sub-phase 2F: arq registration + worker integration      (final)
"""
from __future__ import annotations

import email as email_lib
import imaplib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Reuse Captain's well-tested parsing utilities (DRY — no parser drift).
# These are pure functions; importing does not couple our service to
# Captain's runtime state or coexistence policy.
from backend.services.captain_multi_mailbox import (
    _decode_header_value,
    _extract_address,
    _extract_attachments,
    _extract_plain_body,
    _extract_recipient_list,
)
from backend.core.config import settings
from backend.services.ediscovery_agent import LegacySession


# ─────────────────────────────────────────────────────────────────────────────
# Constants — the architectural defense ingester_from='<service>:v<int>'
# ─────────────────────────────────────────────────────────────────────────────


INGESTER_NAME = "legal_mail_ingester"
INGESTER_VERSION = "v1"
INGESTER_VERSIONED = f"{INGESTER_NAME}:{INGESTER_VERSION}"

# Default config values per design v1.1 §3.1
DEFAULT_MAX_MESSAGES_PER_PATROL = 50
DEFAULT_SEARCH_BAND_DAYS = 30
DEFAULT_FOLDER = "INBOX"
DEFAULT_POLL_INTERVAL_SEC = 120

# Routing-tag classification (closes Q-A from design v1.1 §3.5)
LEGAL_ROUTING_TAGS = frozenset({"legal", "litigation"})

# This service ONLY claims mailboxes where ingester == "legal_mail".
# Mailboxes without `ingester` field default to "captain" (preserves current
# Captain ownership). Mailboxes with `ingester=legal_mail` opt in to this
# pipeline and are also still polled by Captain (§3.4 coexistence).
INGESTER_CLAIM = "legal_mail"


logger = structlog.get_logger(service=INGESTER_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Config — LegalMailboxConfig + parser
#
# Mirrors captain_multi_mailbox.MailboxConfig but adds the v1.1 §3.1 fields:
#   max_messages_per_patrol, search_band_days, ingester
# Keeps Captain's MailboxConfig untouched (Captain doesn't need these fields;
# Captain's existing parser silently ignores unknown JSON keys).
# ─────────────────────────────────────────────────────────────────────────────


class LegalMailboxConfigError(ValueError):
    """Raised when MAILBOXES_CONFIG is malformed for legal-track use."""


@dataclass(frozen=True)
class LegalMailboxConfig:
    name: str
    transport: str
    address: str
    routing_tag: str
    host: str = ""
    port: int = 993
    credentials_ref: str = ""
    poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC
    folder: str = DEFAULT_FOLDER
    max_messages_per_patrol: int = DEFAULT_MAX_MESSAGES_PER_PATROL
    search_band_days: int = DEFAULT_SEARCH_BAND_DAYS

    def resolve_password(self) -> str:
        if self.transport != "imap":
            return ""
        if not self.credentials_ref:
            raise LegalMailboxConfigError(
                f"mailbox {self.name}: imap transport requires credentials_ref"
            )
        return os.environ.get(self.credentials_ref, "")


def load_legal_mailbox_configs(raw: str | None = None) -> list[LegalMailboxConfig]:
    """
    Parse MAILBOXES_CONFIG env var, filter to ingester=legal_mail entries.

    Same env var as Captain (single source of truth for mailbox routing).
    Captain ignores ingester field; we filter on it. Mailboxes lacking the
    ingester field are NOT claimed by this service (default ownership stays
    with Captain).
    """
    raw_value = raw if raw is not None else os.environ.get("MAILBOXES_CONFIG", "")
    if not raw_value.strip():
        return []

    try:
        entries = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise LegalMailboxConfigError(
            f"MAILBOXES_CONFIG is not valid JSON: {exc}"
        ) from exc

    if not isinstance(entries, list):
        raise LegalMailboxConfigError("MAILBOXES_CONFIG must be a JSON list")

    out: list[LegalMailboxConfig] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue  # malformed — Captain will raise on this; we silently skip

        # Filter: only claim mailboxes explicitly tagged for this ingester
        if str(entry.get("ingester") or "").strip() != INGESTER_CLAIM:
            continue

        name = str(entry.get("name") or "").strip()
        transport = str(entry.get("transport") or "").strip()
        address = str(entry.get("address") or "").strip()
        routing_tag = str(entry.get("routing_tag") or "").strip()

        if not name or not transport or not address or not routing_tag:
            raise LegalMailboxConfigError(
                f"entry #{idx} (ingester=legal_mail): "
                f"name/transport/address/routing_tag are required"
            )

        if routing_tag not in LEGAL_ROUTING_TAGS:
            # Reject — a legal_mail-claimed mailbox MUST be legal-routed.
            # If operator wants 'executive' routing, they should NOT add
            # ingester=legal_mail to that mailbox.
            raise LegalMailboxConfigError(
                f"mailbox {name}: ingester=legal_mail requires "
                f"routing_tag in {sorted(LEGAL_ROUTING_TAGS)}, "
                f"got {routing_tag!r}"
            )

        out.append(LegalMailboxConfig(
            name=name,
            transport=transport,
            address=address,
            routing_tag=routing_tag,
            host=str(entry.get("host") or ""),
            port=int(entry.get("port") or 993),
            credentials_ref=str(entry.get("credentials_ref") or ""),
            poll_interval_sec=int(entry.get("poll_interval_sec") or DEFAULT_POLL_INTERVAL_SEC),
            folder=str(entry.get("folder") or DEFAULT_FOLDER),
            max_messages_per_patrol=int(
                entry.get("max_messages_per_patrol") or DEFAULT_MAX_MESSAGES_PER_PATROL
            ),
            search_band_days=int(
                entry.get("search_band_days") or DEFAULT_SEARCH_BAND_DAYS
            ),
        ))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# IMAP date formatting — for SEARCH SINCE clause (per §3.2 banding)
# ─────────────────────────────────────────────────────────────────────────────


def _imap_date(d: date) -> str:
    """Format a date as the IMAP SEARCH SINCE-compatible string (e.g. '1-Apr-2026')."""
    return d.strftime("%-d-%b-%Y")


# ─────────────────────────────────────────────────────────────────────────────
# IMAP transport — connection setup + retry
#
# Mirrors captain_multi_mailbox._IMAPTransport pattern (per §2 architectural
# placement) but with critical differences:
#   - Uses BODY.PEEK[] in fetch (preserves UNSEEN flag for Captain coexistence)
#   - Uses UID-based SEARCH + FETCH (idempotent across patrols; UIDs stable)
#   - Banded SEARCH (UNSEEN SINCE <today - search_band_days>) per §3.2
#     to defend against Issue #177 (>1MB SEARCH overflow on gary-gk)
#
# Connection lifetime: short-lived per patrol — open, fetch, close. cPanel
# does not support concurrent IMAP logins reliably (per Captain's notes), so
# pooling is intentionally avoided.
# ─────────────────────────────────────────────────────────────────────────────


SEARCH_TIMEOUT_S = 60
RETRY_BACKOFFS_S = (2.0, 8.0)


class LegalMailIngesterTransport:
    """
    Per-mailbox IMAP connection wrapper.

    fetch_recent() returns up to max_messages_per_patrol messages from the
    UNSEEN+SINCE-banded set. Reading uses BODY.PEEK[] so the \\Seen flag is
    not mutated — Captain's parallel polling sees the same UNSEEN set.
    """

    def __init__(self, mailbox: LegalMailboxConfig) -> None:
        if mailbox.transport != "imap":
            raise ValueError(f"{mailbox.name}: not an IMAP mailbox (transport={mailbox.transport!r})")
        if not mailbox.host:
            raise LegalMailboxConfigError(f"{mailbox.name}: imap host is required")
        self.mailbox = mailbox
        self._reconnects = 0

    @property
    def reconnect_count(self) -> int:
        return self._reconnects

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(
            self.mailbox.host,
            self.mailbox.port,
            timeout=SEARCH_TIMEOUT_S,
        )
        password = self.mailbox.resolve_password()
        if not password:
            raise LegalMailboxConfigError(
                f"{self.mailbox.name}: credentials_ref "
                f"{self.mailbox.credentials_ref!r} is unset or empty"
            )
        conn.login(self.mailbox.address, password)
        # readonly=True so Captain's parallel \\Seen mutations are not
        # contended; our path is fully read-only on server-side state.
        conn.select(self.mailbox.folder, readonly=True)
        return conn

    def verify_credentials(self) -> None:
        """Connect + login + logout. Raises on any failure. Used by preflight."""
        conn = self._connect()
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    def fetch_recent(self) -> list[dict[str, Any]]:
        """
        Fetch UNSEEN messages within the date band, capped at max_messages_per_patrol.

        Sub-phase 2A returns an empty list — full implementation lands in 2B.
        Connection retry pattern is in place (mirrors Captain's 2-attempt
        reconnect-on-abort for cPanel keep-alive drops).
        """
        attempts = 0
        last_err: Exception | None = None
        while attempts < 2:
            attempts += 1
            conn: Optional[imaplib.IMAP4_SSL] = None
            try:
                conn = self._connect()
                return self._fetch_with(conn)
            except (imaplib.IMAP4.abort, EOFError, OSError, imaplib.IMAP4.error) as exc:
                last_err = exc
                if attempts == 1:
                    self._reconnects += 1
                    logger.warning(
                        "legal_mail_imap_reconnect",
                        mailbox=self.mailbox.name,
                        error=str(exc)[:200],
                    )
                    continue
                logger.error(
                    "legal_mail_imap_final_failure",
                    mailbox=self.mailbox.name,
                    error=str(exc)[:200],
                )
                return []
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    try:
                        conn.logout()
                    except Exception:
                        pass

        if last_err is not None:
            logger.error(
                "legal_mail_imap_unexpected_exit",
                mailbox=self.mailbox.name,
                error=str(last_err)[:200],
            )
        return []

    def _fetch_with(self, conn: imaplib.IMAP4_SSL) -> list[dict[str, Any]]:
        """
        Banded UID SEARCH + per-UID BODY.PEEK[].

        Per design v1.1 §3.2: never issue an unbounded SEARCH UNSEEN — that's
        how gary-gk hits Issue #177's >1MB overflow. We always pair UNSEEN with
        a SINCE date floor (default 30 days back, configurable per-mailbox).

        Per design v1.1 §3.4 (Captain coexistence): use BODY.PEEK[] not
        (RFC822) — preserves the \\Seen flag. Captain marks \\Seen on its own
        cycle; we never mutate server-side state.

        Returns list of dicts each containing:
          uid, raw_bytes, host, folder, mailbox_alias
        """
        since_date = (date.today() - timedelta(days=self.mailbox.search_band_days))
        search_predicate = f"UNSEEN SINCE {_imap_date(since_date)}"

        typ, data = conn.uid("SEARCH", search_predicate)
        if typ != "OK" or not data or not data[0]:
            return []

        uids = data[0].split()[: self.mailbox.max_messages_per_patrol]
        if not uids:
            return []

        out: list[dict[str, Any]] = []
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii", errors="replace")
            try:
                # BODY.PEEK[] — server returns full message, does NOT mark \\Seen.
                # Captain runs in parallel with regular FETCH that marks \\Seen;
                # the two paths see the same UNSEEN set without contention.
                typ, fetch_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if typ != "OK" or not fetch_data:
                    continue

                raw_bytes: Optional[bytes] = None
                for entry in fetch_data:
                    if isinstance(entry, tuple) and len(entry) >= 2:
                        candidate = entry[1]
                        if isinstance(candidate, (bytes, bytearray)):
                            raw_bytes = bytes(candidate)
                            break
                if raw_bytes is None:
                    continue

                out.append({
                    "uid": uid,
                    "raw_bytes": raw_bytes,
                    "host": self.mailbox.host,
                    "folder": self.mailbox.folder,
                    "mailbox_alias": self.mailbox.name,
                    "transport": self.mailbox.transport,
                })
            except Exception as exc:
                # Per design v1.1 §1: per-message try/except so one bad email
                # never aborts a patrol. Logged but patrol continues.
                logger.warning(
                    "legal_mail_message_fetch_failed",
                    mailbox=self.mailbox.name,
                    uid=uid,
                    error=str(exc)[:200],
                )
                continue

        return out


# ─────────────────────────────────────────────────────────────────────────────
# Email parsing — produces a structured ParsedMessage from raw IMAP bytes.
# Reuses Captain's _parse_rfc822 conventions but emits a richer record
# tailored for the email_archive output contract (§3.6) + event payload (§5).
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ParsedMessage:
    """
    Result of parsing one IMAP message + Stage 1 classification.

    Sub-phase 2C will use these fields directly when writing to email_archive:
      - sender, subject, body, sent_at, message_id, to/cc/bcc → email_archive cols
      - file_path constructed from {host, folder, uid}
      - category constructed from {transport, mailbox_alias}

    Sub-phase 2D will use these fields when emitting to legal.event_log:
      - case_slug + privilege_class + watchdog_matches → event payload
    """
    # Source identity (drives file_path + category)
    uid: str
    host: str
    folder: str
    mailbox_alias: str
    transport: str
    routing_tag: str

    # Parsed headers + body
    sender: str
    sender_domain: str
    subject: str
    body: str
    message_id: str
    to_addresses: list[str] = field(default_factory=list)
    cc_addresses: list[str] = field(default_factory=list)
    bcc_addresses: list[str] = field(default_factory=list)
    sent_at: Optional[datetime] = None
    attachment_filenames: list[str] = field(default_factory=list)

    # Stage 1 classification (per design v1.1 §5)
    case_slug: Optional[str] = None
    privilege_class: Optional[str] = None  # 'work_product' | 'privileged' | 'public'
    watchdog_matches: list[dict[str, Any]] = field(default_factory=list)
    priority: Optional[str] = None  # 'P1' | 'P2' | 'P3' from priority_sender_rules

    # Construction helpers — keep email_archive output contract centralized
    @property
    def file_path(self) -> str:
        """Canonical, replayable identifier per design v1.1 §3.6."""
        return f"imap://{self.host}/{self.folder}/{self.uid}"

    @property
    def category(self) -> str:
        """legacy_case_manager.py compat per §3.6 — file_path LIKE 'imap://%' check."""
        return f"imap_{self.transport}_{self.mailbox_alias}"


def parse_message(raw_bytes: bytes, source: dict[str, Any], routing_tag: str) -> Optional[ParsedMessage]:
    """
    Parse IMAP raw bytes into a ParsedMessage. Returns None on parse failure
    (caller should log + skip; one bad email never aborts a patrol per §1).

    `source` is the dict from LegalMailIngesterTransport._fetch_with:
      uid, host, folder, mailbox_alias, transport
    """
    try:
        msg: Message = email_lib.message_from_bytes(raw_bytes)
    except Exception:
        return None

    subject = _decode_header_value(msg.get("Subject", ""))
    from_header = _decode_header_value(msg.get("From", ""))
    sender = _extract_address(from_header).lower()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""

    to_addrs = _extract_recipient_list(msg.get_all("To") or [])
    cc_addrs = _extract_recipient_list(msg.get_all("Cc") or [])
    bcc_addrs = _extract_recipient_list(msg.get_all("Bcc") or [])

    message_id = (msg.get("Message-ID") or "").strip()
    body = _extract_plain_body(msg)
    attachments = _extract_attachments(msg)

    sent_at: Optional[datetime] = None
    date_header = msg.get("Date")
    if date_header:
        try:
            sent_at = parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            sent_at = None

    return ParsedMessage(
        uid=str(source["uid"]),
        host=str(source["host"]),
        folder=str(source["folder"]),
        mailbox_alias=str(source["mailbox_alias"]),
        transport=str(source["transport"]),
        routing_tag=routing_tag,
        sender=sender,
        sender_domain=sender_domain,
        subject=subject,
        body=body,
        message_id=message_id,
        to_addresses=to_addrs,
        cc_addresses=cc_addrs,
        bcc_addresses=bcc_addrs,
        sent_at=sent_at,
        attachment_filenames=attachments,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 classifier — lightweight, deterministic, ~1ms/message (per §5)
#
# Three-step classification:
#   1. ILIKE match against priority_sender_rules (sender_pattern → case_slug + priority)
#   2. Heuristic regex on subject for known case identifiers
#   3. Mailbox routing_tag inheritance for default privilege_class
#
# Stage 2 (heavyweight LLM-backed _classify_privilege) fires only when the
# message attaches to a case via correspondence/vault — not in this pipeline.
# ─────────────────────────────────────────────────────────────────────────────


# Compiled at module load — cheap regex lookups on every inbound message.
# Pattern format: (regex, case_slug). First match wins.
# Regexes use word boundaries / token boundaries to avoid spurious matches
# (e.g., "fish-trap" inside an unrelated string).
_SUBJECT_CASE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bSUV20260000?13\b", re.IGNORECASE), "fish-trap-suv2026000013"),
    (re.compile(r"\bfish[\s-]?trap\b", re.IGNORECASE),  "fish-trap-suv2026000013"),
    (re.compile(r"\bgenerali\b", re.IGNORECASE),        "fish-trap-suv2026000013"),
    (re.compile(r"\b23-11161\b"),                       "prime-trust-23-11161"),
    (re.compile(r"\bprime[\s-]?trust\b", re.IGNORECASE),"prime-trust-23-11161"),
    (re.compile(r"\bdetweiler\b", re.IGNORECASE),       "prime-trust-23-11161"),
    (re.compile(r"\b7[\s-]?IL\b", re.IGNORECASE),       "7il-v-knight-ndga-ii"),  # active case II default
    (re.compile(r"\bvanderb[ue]rg[h]?\b", re.IGNORECASE), "vanderburge-v-knight-fannin"),  # closed; tag for archive
]


def _ilike_match(pattern: str, value: str) -> bool:
    """Mimic Postgres ILIKE in-memory: % is wildcard, case-insensitive."""
    if not pattern or not value:
        return False
    # Convert SQL ILIKE pattern to Python regex.
    # % → .*, _ → . (per SQL spec); other chars literal.
    regex_pattern = re.escape(pattern).replace(r"\%", ".*").replace(r"\_", ".")
    return re.search(regex_pattern, value, re.IGNORECASE) is not None


def classify_inbound(
    message: ParsedMessage,
    priority_sender_rules: list[dict[str, Any]],
    watchdog_rules: list[dict[str, Any]],
) -> ParsedMessage:
    """
    Mutate ParsedMessage in-place with Stage 1 classification results.

    `priority_sender_rules` is a list of rule dicts pre-loaded once per patrol:
        {sender_pattern, priority, case_slug, rationale}

    `watchdog_rules` is a list of case_watchdog rules pre-loaded once per patrol:
        {id, case_slug, search_type ('sender'|'body'), search_term, priority}

    Returns the same ParsedMessage (now with case_slug, privilege_class,
    watchdog_matches, priority populated).
    """
    # ── Step 1: priority_sender_rules match ─────────────────────────────
    # First match wins. We check sender + sender_domain against each pattern.
    for rule in priority_sender_rules:
        pattern = str(rule.get("sender_pattern") or "")
        if _ilike_match(pattern, message.sender) or _ilike_match(pattern, message.sender_domain):
            message.priority = str(rule.get("priority") or "")
            rule_case = rule.get("case_slug")
            if rule_case and not message.case_slug:
                message.case_slug = str(rule_case)
            break

    # ── Step 2: subject regex for case identifiers ─────────────────────
    # Only if Step 1 didn't already assign a case_slug (priority_sender_rules
    # is more authoritative when it matches). Body is NOT scanned at Stage 1
    # (deferred to Stage 2 heavyweight classifier per §5 boundary).
    if not message.case_slug:
        for pattern, case_slug in _SUBJECT_CASE_PATTERNS:
            if pattern.search(message.subject or ""):
                message.case_slug = case_slug
                break

    # ── Step 3: routing_tag inheritance for default privilege_class ────
    # Per design v1.1 §5 + §3.5:
    #   - 'legal' / 'litigation' tagged mailbox → 'work_product' default
    #   - other (executive, etc.) → no default ('public' if mailbox is
    #     non-legal; this service only sees legal-tagged mailboxes anyway)
    # Stage 2 may upgrade to 'privileged' on attorney-client signals.
    if message.routing_tag in LEGAL_ROUTING_TAGS:
        message.privilege_class = "work_product"
    else:
        message.privilege_class = "public"

    # ── Watchdog match ─────────────────────────────────────────────────
    # Per design v1.1 §5 + §8 (event payload includes watchdog_matches[]).
    # Same in-memory scan; case_watchdog rules pre-loaded per patrol.
    matches: list[dict[str, Any]] = []
    haystack_subject = (message.subject or "").lower()
    haystack_body = (message.body or "").lower()
    for rule in watchdog_rules:
        if not rule.get("is_active", True):
            continue
        # Optionally narrow by case_slug if rule is case-specific
        rule_case = rule.get("case_slug")
        if rule_case and message.case_slug and rule_case != message.case_slug:
            continue
        search_type = str(rule.get("search_type") or "").lower()
        term = str(rule.get("search_term") or "").lower()
        if not term:
            continue
        match_hit = False
        if search_type == "sender":
            if term in message.sender or term in message.sender_domain:
                match_hit = True
        elif search_type == "body":
            if term in haystack_subject or term in haystack_body:
                match_hit = True
        if match_hit:
            matches.append({
                "rule_id": rule.get("id"),
                "case_slug": rule_case,
                "priority": rule.get("priority"),
                "search_term": rule.get("search_term"),
                "search_type": rule.get("search_type"),
            })
    message.watchdog_matches = matches

    return message


# ─────────────────────────────────────────────────────────────────────────────
# Bilateral mirror write to email_archive
#
# Per design v1.1 §10 (LOCKED Q5) + ADR-001:
#   - Write to fortress_db (LegacySession) — canonical store
#   - Mirror to fortress_prod (ProdSession) with forced matching id
#   - Idempotency via file_path UNIQUE constraint (already on email_archive)
#   - ingested_from='legal_mail_ingester:v1' (matches CHECK regex from 0a-1)
#
# Mirror failure mode: log + continue (don't block primary ingestion). The
# 2E orchestrator updates legal.mail_ingester_state to flag mirror drift for
# later reconciliation.
#
# Note on AsyncSessionLocal vs ProdSession: backend/core/database.py's
# AsyncSessionLocal targets settings.database_url (typically fortress_shadow
# at runtime). fortress_prod requires its own engine — built here by string-
# replacing the DB name in settings.database_url, mirroring the pattern in
# backend/services/ediscovery_agent.py for LegacySession (fortress_db).
# ─────────────────────────────────────────────────────────────────────────────


def _build_prod_db_url() -> str:
    """Construct the fortress_prod URL by replacing the DB name in settings.database_url.

    Mirrors the LegacySession construction pattern in ediscovery_agent.py.
    Tolerates whichever runtime DB the API is currently pointed at.
    """
    url = (
        settings.database_url
        .replace("/fortress_db", "/fortress_prod")
        .replace("/fortress_shadow_test", "/fortress_prod")
        .replace("/fortress_shadow", "/fortress_prod")
        .replace("/fortress_guest", "/fortress_prod")
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_prod_engine = create_async_engine(
    _build_prod_db_url(),
    echo=False,
    pool_size=5,
    max_overflow=3,
    pool_pre_ping=True,
)

ProdSession = async_sessionmaker(
    _prod_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Column list — single source of truth for the INSERT column order.
# Must align with email_archive schema on fortress_db AND fortress_prod
# (verified bilaterally by Phase 0a-1 migration).
_EMAIL_ARCHIVE_COLUMNS = (
    "category",
    "file_path",
    "sender",
    "subject",
    "content",
    "sent_at",
    "to_addresses",
    "cc_addresses",
    "bcc_addresses",
    "message_id",
    "ingested_from",
)


def _row_dict_for_insert(message: ParsedMessage) -> dict[str, Any]:
    """Build the SQLAlchemy parameter dict for an email_archive INSERT.

    Centralizes the §3.6 output contract. file_path + category use ParsedMessage
    properties so the URL/category schema stays single-source-of-truth.
    """
    # Comma-join recipient lists for storage (existing schema is text columns,
    # not text[]). Matches the pattern legal_case_manager queries against.
    return {
        "category": message.category,
        "file_path": message.file_path,
        "sender": message.sender,
        "subject": message.subject,
        "content": message.body,
        "sent_at": message.sent_at,
        "to_addresses": ", ".join(message.to_addresses) if message.to_addresses else None,
        "cc_addresses": ", ".join(message.cc_addresses) if message.cc_addresses else None,
        "bcc_addresses": ", ".join(message.bcc_addresses) if message.bcc_addresses else None,
        "message_id": message.message_id or None,
        "ingested_from": INGESTER_VERSIONED,
    }


async def write_email_archive_bilateral(message: ParsedMessage) -> Optional[int]:
    """
    Bilateral mirror write to email_archive (fortress_db + fortress_prod).

    Returns the email_archive id from fortress_db on success (canonical store
    governs id assignment). Returns None if fortress_db write fails. Mirror
    drift to fortress_prod is logged but not raised — caller (2E orchestrator)
    decides whether to retry or flag for reconciliation.

    Idempotency: ON CONFLICT (file_path) DO NOTHING. Re-poll of an already-
    ingested message returns the existing id (via the existence-check fallback)
    or None if the conflict path was taken silently.

    Per design v1.1 §10: forward-only mirror. No attempt to backfill the 224-
    row split-brain delta in historical rows; this path only covers new writes.
    """
    row = _row_dict_for_insert(message)

    # ── 1. Write to fortress_db (canonical) ─────────────────────────────
    new_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO email_archive
                        (category, file_path, sender, subject, content, sent_at,
                         to_addresses, cc_addresses, bcc_addresses, message_id,
                         ingested_from)
                    VALUES
                        (:category, :file_path, :sender, :subject, :content, :sent_at,
                         :to_addresses, :cc_addresses, :bcc_addresses, :message_id,
                         :ingested_from)
                    ON CONFLICT (file_path) DO NOTHING
                    RETURNING id
                """),
                row,
            )
            row_obj = result.fetchone()
            if row_obj is not None:
                new_id = int(row_obj.id)
            await db.commit()
    except Exception as exc:
        logger.error(
            "legal_mail_email_archive_db_failed",
            mailbox=message.mailbox_alias,
            uid=message.uid,
            file_path=message.file_path,
            error=str(exc)[:300],
        )
        return None

    if new_id is None:
        # Conflict path — file_path already present; recover the existing id.
        try:
            async with LegacySession() as db:
                result = await db.execute(
                    text("SELECT id FROM email_archive WHERE file_path = :fp"),
                    {"fp": message.file_path},
                )
                row_obj = result.fetchone()
                if row_obj is not None:
                    new_id = int(row_obj.id)
        except Exception as exc:
            logger.warning(
                "legal_mail_email_archive_existing_id_lookup_failed",
                file_path=message.file_path,
                error=str(exc)[:200],
            )

        if new_id is None:
            # Re-conflict (race) or schema misalignment — bail out without mirror.
            logger.warning(
                "legal_mail_email_archive_dedup_no_id",
                file_path=message.file_path,
            )
            return None

        # Already ingested previously — no need to mirror again. Idempotent return.
        return new_id

    # ── 2. Mirror to fortress_prod with forced matching id ─────────────
    # Per ADR-001 + design v1.1 §10. If this fails, fortress_db write is
    # already committed — log the drift, return new_id, let 2E flag it.
    mirror_row = {**row, "forced_id": new_id}
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO email_archive
                        (id, category, file_path, sender, subject, content, sent_at,
                         to_addresses, cc_addresses, bcc_addresses, message_id,
                         ingested_from)
                    VALUES
                        (:forced_id, :category, :file_path, :sender, :subject,
                         :content, :sent_at, :to_addresses, :cc_addresses,
                         :bcc_addresses, :message_id, :ingested_from)
                    ON CONFLICT (file_path) DO NOTHING
                """),
                mirror_row,
            )
            # Manually advance the prod sequence so future autogenerated ids
            # don't collide with our forced ones. setval(seq, max(N, current))
            # is idempotent + monotonic; running it twice with the same N is
            # a no-op the second time.
            await prod.execute(
                text("""
                    SELECT setval(
                        'email_archive_id_seq',
                        GREATEST(:forced_id, (SELECT last_value FROM email_archive_id_seq))
                    )
                """),
                {"forced_id": new_id},
            )
            await prod.commit()
    except Exception as exc:
        # Mirror drift — log structured event for the 2E orchestrator to
        # surface in legal.mail_ingester_state.last_error / mirror_drift counter.
        logger.warning(
            "legal_mail_email_archive_prod_mirror_failed",
            email_archive_id=new_id,
            file_path=message.file_path,
            error=str(exc)[:300],
        )
        # Return the fortress_db id anyway — primary write succeeded.

    return new_id


# ─────────────────────────────────────────────────────────────────────────────
# Event emission to legal.event_log
#
# Per design v1.1 §5 + §8:
#   - event_type = 'email.received'
#   - emitted_by = 'legal_mail_ingester:v1' (matches event_log CHECK regex)
#   - payload includes case_slug, sender, subject, received_at, message_id,
#     privilege_class, watchdog_matches[], email_archive_id, ingester_version
#   - Phase 1 dispatcher will consume rows where processed_at IS NULL
#
# Bilateral mirror per ADR-001: same write pattern as email_archive
# (fortress_db canonical + fortress_prod mirror).
# Failure mode: log + don't raise; one bad event shouldn't abort the patrol.
# ─────────────────────────────────────────────────────────────────────────────


EVENT_TYPE_EMAIL_RECEIVED = "email.received"


def _build_event_payload(message: ParsedMessage, email_archive_id: int) -> dict[str, Any]:
    """Construct the event payload dict per design v1.1 §5.

    Stored as JSONB in legal.event_log.event_payload. Phase 1 dispatcher
    routes on event_type + reads case_slug/priority/watchdog_matches to
    decide downstream action (case_posture update, operator alert, etc.).
    """
    return {
        "event_type": EVENT_TYPE_EMAIL_RECEIVED,
        "ingester_version": INGESTER_VERSIONED,
        "mailbox": message.mailbox_alias,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "sender": message.sender,
        "sender_domain": message.sender_domain,
        "subject": message.subject,
        "message_id": message.message_id,
        "case_slug": message.case_slug,
        "privilege_class": message.privilege_class,
        "priority": message.priority,
        "watchdog_matches": message.watchdog_matches,
        "email_archive_id": email_archive_id,
        "file_path": message.file_path,
        "category": message.category,
        # sent_at as ISO-8601 if parseable; null otherwise. Useful for
        # downstream deadline calculation (response-due windows).
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
    }


async def emit_email_received_event(
    message: ParsedMessage,
    email_archive_id: int,
) -> Optional[int]:
    """
    Emit an email.received event to legal.event_log on both fortress_db
    and fortress_prod (bilateral per ADR-001).

    Returns the event_log.id from fortress_db on success (canonical store),
    None on primary failure. Mirror failure to fortress_prod is logged but
    does not raise — same pattern as email_archive bilateral write (§10).

    Should be called by 2E orchestrator AFTER write_email_archive_bilateral
    returns a non-None id. If email_archive write failed, no event emitted.
    """
    payload = _build_event_payload(message, email_archive_id)

    # serialize once; pass to both inserts as the same JSON string
    payload_json = json.dumps(payload, default=str, ensure_ascii=False)

    # ── 1. Write to fortress_db (canonical) ─────────────────────────────
    new_event_id: Optional[int] = None
    try:
        async with LegacySession() as db:
            result = await db.execute(
                text("""
                    INSERT INTO legal.event_log
                        (event_type, case_slug, event_payload, emitted_by)
                    VALUES
                        (:event_type, :case_slug, CAST(:payload AS JSONB), :emitted_by)
                    RETURNING id
                """),
                {
                    "event_type": EVENT_TYPE_EMAIL_RECEIVED,
                    "case_slug": message.case_slug,
                    "payload": payload_json,
                    "emitted_by": INGESTER_VERSIONED,
                },
            )
            row_obj = result.fetchone()
            if row_obj is not None:
                new_event_id = int(row_obj.id)
            await db.commit()
    except Exception as exc:
        logger.error(
            "legal_mail_event_log_db_failed",
            email_archive_id=email_archive_id,
            case_slug=message.case_slug,
            error=str(exc)[:300],
        )
        return None

    if new_event_id is None:
        # Should not happen — event_log has no UNIQUE constraints that
        # would silently DROP an INSERT. Defensive only.
        logger.warning(
            "legal_mail_event_log_no_id_returned",
            email_archive_id=email_archive_id,
        )
        return None

    # ── 2. Mirror to fortress_prod with forced matching id ─────────────
    # Same forced-id + setval pattern as email_archive write (§10).
    try:
        async with ProdSession() as prod:
            await prod.execute(
                text("""
                    INSERT INTO legal.event_log
                        (id, event_type, case_slug, event_payload, emitted_by)
                    VALUES
                        (:forced_id, :event_type, :case_slug,
                         CAST(:payload AS JSONB), :emitted_by)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "forced_id": new_event_id,
                    "event_type": EVENT_TYPE_EMAIL_RECEIVED,
                    "case_slug": message.case_slug,
                    "payload": payload_json,
                    "emitted_by": INGESTER_VERSIONED,
                },
            )
            # Advance prod's event_log sequence so future autogenerated ids
            # don't collide with our forced one (same pattern as email_archive).
            await prod.execute(
                text("""
                    SELECT setval(
                        'legal.event_log_id_seq',
                        GREATEST(:forced_id, (SELECT last_value FROM legal.event_log_id_seq))
                    )
                """),
                {"forced_id": new_event_id},
            )
            await prod.commit()
    except Exception as exc:
        # Event mirror drift — log + continue. Phase 1 dispatcher reads from
        # fortress_db (canonical), so a missing prod row doesn't block routing.
        logger.warning(
            "legal_mail_event_log_prod_mirror_failed",
            event_log_id=new_event_id,
            email_archive_id=email_archive_id,
            error=str(exc)[:300],
        )

    return new_event_id
