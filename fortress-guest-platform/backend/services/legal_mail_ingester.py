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

import imaplib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog


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
        """Inner fetch — banded SEARCH + BODY.PEEK[] loop. Stub in 2A; full impl in 2B."""
        # Sub-phase 2A: stub returns [] without issuing SEARCH/FETCH.
        # Sub-phase 2B will implement:
        #   1. banded UID SEARCH: UNSEEN SINCE <today - search_band_days>
        #   2. cap UIDs at mailbox.max_messages_per_patrol
        #   3. per-UID BODY.PEEK[] (no flag mutation)
        #   4. parse to dict with raw_bytes + uid + folder + host + alias
        return []
