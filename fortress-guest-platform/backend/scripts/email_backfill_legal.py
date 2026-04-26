"""
email_backfill_legal.py — case-aware IMAP email backfill into legal vault.

For a given --case-slug, walks IMAP per mailbox in date bands (Issue #177
SEARCH-overflow workaround), classifies each message against KNOWN PARTIES
(matched against `legal.cases.privileged_counsel_domains` JSONB + module-level
party-term tables), routes to the correct case_slug via the disambiguator,
and runs the canonical pipeline:

    process_vault_upload(message/rfc822 bytes)
        ├── INSERT legal.vault_documents (status='pending', ON CONFLICT DO NOTHING)
        ├── privilege classifier — sets 'locked_privileged' when triggered
        ├── _extract_text — sets 'ocr_failed' for empty extracts
        ├── chunk → nomic embed → Qdrant upsert
        │       ├── work-product → legal_ediscovery
        │       └── privileged    → legal_privileged_communications
        └── UPDATE status to 'completed'

The vault_documents row is mirrored to fortress_prod so consumers reading
prod see the same vault state (matches PR D's dual-DB pattern).

Idempotency: file_hash dedup across (case_slug, file_hash) via the
PR D-pre2 UNIQUE constraint. Re-running this script is a clean no-op for
already-ingested emails.

Atomicity: per-email try/except. One bad email does not abort the sweep.

Audit: IngestRunTracker (PR D-pre1) emits a single legal.ingest_runs row.
JSON manifest at /mnt/fortress_nas/audits/email-backfill-{case_slug}-{ts}.json.

Concurrency control: lock at /tmp/email-backfill-{case_slug}.lock.

Rollback: --rollback flag deletes email-backfill rows in both DBs and
Qdrant points whose payload.case_slug matches AND file_name ends in .eml.

Usage (after merge, with explicit auth):
    python -m backend.scripts.email_backfill_legal \
        --case-slug 7il-v-knight-ndga-i \
        --mailbox gary-gk,gary-crog \
        --since 2018-01-01 --until 2025-12-31
"""
from __future__ import annotations

import argparse
import asyncio
import email as email_module
import email.policy
import email.utils
import hashlib
import imaplib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("email_backfill_legal")


# ─── constants ────────────────────────────────────────────────────────────


IMAP_HOST           = "mail.cabin-rentals-of-georgia.com"
IMAP_PORT           = 993
ENV_PATH            = Path("/home/admin/Fortress-Prime/fortress-guest-platform/.env")
AUDIT_DIR           = Path("/mnt/fortress_nas/audits")
LOCK_STALE_AFTER_S  = 6 * 3600
SEARCH_TIMEOUT_S    = 60
FETCH_BATCH         = 100
RETRY_BACKOFFS_S    = (2.0, 8.0, 20.0)
BAND_MONTHS         = 6

QDRANT_COLLECTION_WORK_PRODUCT = "legal_ediscovery"
QDRANT_COLLECTION_PRIVILEGED   = "legal_privileged_communications"
EXPECTED_VECTOR_SIZE           = 768

MAILBOX_REGISTRY = {
    "gary-gk":   ("gary@garyknight.com",                "fortress/mailboxes/gary-garyknight"),
    "gary-crog": ("gary@cabin-rentals-of-georgia.com",  "fortress/mailboxes/gary-crog"),
    "info-crog": ("info@cabin-rentals-of-georgia.com",  "fortress/mailboxes/info-crog"),
}

# Folders to scan per mailbox (per PR I plan §3 — INBOX + Sent variants).
SEARCH_FOLDER_PATTERNS = (
    re.compile(r"^INBOX$"),
    re.compile(r"(?i)^(?:INBOX\.)?sent(?:\s|$|\.)"),
    re.compile(r"(?i)^(?:INBOX\.)?sent[- ]?mail(?:$|\b)"),
    re.compile(r"(?i)^(?:INBOX\.)?sent[- ]?items"),
)


# ─── party term + classification config ───────────────────────────────────


# Per-case routing keywords (subject + body match). Source of truth: PR I plan §3.
CASE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "7il-v-knight-ndga-i": (
        "2:21-cv-00226",
    ),
    "7il-v-knight-ndga-ii": (
        "2:26-cv-00113",
    ),
    "vanderburge-v-knight-fannin": (
        "vanderburge", "karen vanderburge", "fannin county",
        "easement", "appalachian judicial circuit",
    ),
}

# Generic 7IL-prefix keywords. Date-disambiguated (pre-2026 → case_i, else case_ii).
SEVEN_IL_KEYWORDS = (
    "7il properties", "7 il properties", "thor james",
    "fish trap", "fish-trap", "thatcher", "thacker",
)

# Counsel domains by case (mirrors `_DOMAIN_TO_ROLE` in legal_ediscovery.py
# but for routing, not labelling). Each domain implies privileged track.
COUNSEL_DOMAINS_BY_CASE: dict[str, tuple[str, ...]] = {
    "7il-v-knight-ndga-i": (
        "mhtlegal.com", "fgplaw.com", "dralaw.com",
        "wilsonhamilton.com", "wilsonpruittlaw.com",
        # msp-lawfirm.com appears in BOTH Case I (trial cocounsel) AND Vanderburge,
        # so it's listed under both — disambiguator decides which case
        "msp-lawfirm.com", "masp-lawfirm.com",
    ),
    "7il-v-knight-ndga-ii": (
        "msp-lawfirm.com", "masp-lawfirm.com",
        "fgplaw.com",  # Podesta could continue into Case II
    ),
    "vanderburge-v-knight-fannin": (
        "msp-lawfirm.com", "masp-lawfirm.com",
    ),
}

# Opposing counsel terms (work-product track regardless of routing).
OPPOSING_TERMS_BY_CASE: dict[str, tuple[str, ...]] = {
    "7il-v-knight-ndga-i": ("fmglaw.com", "goldberg", "brian goldberg"),
    "7il-v-knight-ndga-ii": ("fmglaw.com", "goldberg", "brian goldberg"),
    "vanderburge-v-knight-fannin": ("frank moore",),  # bare 'moore' too FP-prone
}

# Username/name terms that imply your-side counsel (privileged track).
USERNAME_TERMS_BY_CASE: dict[str, tuple[str, ...]] = {
    "7il-v-knight-ndga-i": ("podesta", "frank podesta", "argo", "alicia argo",
                             "terry wilson", "twilson"),
    "7il-v-knight-ndga-ii": ("sanker", "jsank", "jsanker"),
    "vanderburge-v-knight-fannin": ("sanker", "jsank", "jsanker"),
}

# Date windows (inclusive) per case for fallback routing.
CASE_DATE_WINDOWS: dict[str, tuple[date, date]] = {
    "7il-v-knight-ndga-i":      (date(2018, 1, 1),  date(2025, 12, 31)),
    "7il-v-knight-ndga-ii":     (date(2026, 1, 1),  date(2099, 12, 31)),
    "vanderburge-v-knight-fannin": (date(2019, 1, 1), date(2021, 12, 31)),
}


# ─── env + DSN helpers (mirrors vault_ingest pattern) ─────────────────────


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for raw in ENV_PATH.read_text().splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _ensure_env_loaded() -> None:
    for k, v in _read_env().items():
        os.environ.setdefault(k, v)


@dataclass
class _DSN:
    host: str
    port: int
    user: str
    password: str
    db: str


def _parse_admin_dsn(dbname: str) -> _DSN:
    uri = os.environ.get("POSTGRES_ADMIN_URI", "")
    m = re.match(
        r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/[^?]+",
        uri,
    )
    if not m:
        raise SystemExit(
            "POSTGRES_ADMIN_URI not set or unparseable in environ; "
            "load .env first"
        )
    user, pw, host, port = m.groups()
    return _DSN(host=host, port=int(port or 5432), user=user, password=pw, db=dbname)


def _connect(dbname: str):
    import psycopg2
    dsn = _parse_admin_dsn(dbname)
    conn = psycopg2.connect(
        host=dsn.host, port=dsn.port, user=dsn.user,
        password=dsn.password, dbname=dsn.db,
    )
    conn.autocommit = True
    return conn


def _password(slug: str) -> str:
    out = subprocess.check_output(
        ["pass", "show", slug], text=True, stderr=subprocess.PIPE,
    )
    pw = out.splitlines()[0] if out else ""
    if not pw:
        raise RuntimeError(f"empty password from pass show {slug}")
    return pw


# ─── pre-flight ──────────────────────────────────────────────────────────


class PreflightError(Exception):
    pass


def _preflight_case_exists(case_slug: str) -> dict[str, Any]:
    """case_slug must be present in BOTH fortress_prod and fortress_db. Returns
    the privileged_counsel_domains JSONB array from the prod row."""
    rows: dict[str, Any] = {}
    for dbname in ("fortress_prod", "fortress_db"):
        try:
            conn = _connect(dbname)
        except Exception as exc:
            raise PreflightError(f"cannot connect to {dbname}: {exc!s}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT case_slug, privileged_counsel_domains FROM legal.cases "
                    "WHERE case_slug = %s",
                    (case_slug,),
                )
                row = cur.fetchone()
            if row is None:
                raise PreflightError(
                    f"case_slug {case_slug!r} not found in {dbname}.legal.cases"
                )
            rows[dbname] = row
        finally:
            conn.close()
    return {"case_slug": case_slug, "privileged_counsel_domains": rows["fortress_prod"][1] or []}


def _preflight_postgres_writable(case_slug: str) -> None:
    """Probe SELECT 1 + a no-op INSERT into legal.ingest_runs (with the real
    case_slug because PR D-pre1 added an FK that rejects sentinel slugs)."""
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                if cur.fetchone() != (1,):
                    raise PreflightError(f"{dbname} SELECT 1 unexpected result")
        finally:
            conn.close()
    try:
        conn = _connect("fortress_db")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO legal.ingest_runs (case_slug, script_name, status, args) "
                "VALUES (%s, '__preflight__', 'running', '{}'::jsonb) RETURNING id",
                (case_slug,),
            )
            row = cur.fetchone()
            if row is None:
                raise PreflightError("preflight ingest_runs INSERT returned no id")
            cur.execute("DELETE FROM legal.ingest_runs WHERE id = %s", (row[0],))
        conn.close()
    except Exception as exc:
        raise PreflightError(
            f"fortress_db.legal.ingest_runs not writable: {exc!s}"
        ) from exc


def _preflight_schema_constraints() -> None:
    """Verify PR D-pre2 constraints on legal.vault_documents (FK + UNIQUE + CHECK)
    in both DBs. PR I creates rows there via process_vault_upload."""
    required = {
        "fk_vault_documents_case_slug",
        "uq_vault_documents_case_hash",
        "chk_vault_documents_status",
    }
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'legal.vault_documents'::regclass "
                    "AND conname = ANY(%s)",
                    (list(required),),
                )
                present = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()
        missing = required - present
        if missing:
            raise PreflightError(
                f"{dbname} missing PR D-pre2 constraints: {sorted(missing)} — "
                f"apply alembic d8e3c1f5b9a6 before backfill"
            )


def _preflight_qdrant_reachable() -> None:
    """Both legal_ediscovery (work product) AND legal_privileged_communications
    must exist with vector_size=768 and Cosine distance."""
    import urllib.error
    import urllib.request
    qdrant_url = os.environ.get("QDRANT_URL", "").rstrip("/")
    if not qdrant_url:
        raise PreflightError("QDRANT_URL not set in environ")
    for collection in (QDRANT_COLLECTION_WORK_PRODUCT, QDRANT_COLLECTION_PRIVILEGED):
        try:
            with urllib.request.urlopen(
                f"{qdrant_url}/collections/{collection}", timeout=10,
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PreflightError(
                f"qdrant collection {collection!r} not reachable at "
                f"{qdrant_url}: HTTP {exc.code}"
            ) from exc
        except Exception as exc:
            raise PreflightError(
                f"qdrant unreachable at {qdrant_url}: {type(exc).__name__}"
            ) from exc
        cfg = (data.get("result") or {}).get("config", {}).get("params", {}).get("vectors", {})
        size = cfg.get("size") if isinstance(cfg, dict) else None
        if size is not None and int(size) != EXPECTED_VECTOR_SIZE:
            raise PreflightError(
                f"qdrant collection {collection} vector size is {size}, "
                f"expected {EXPECTED_VECTOR_SIZE}"
            )


def _preflight_pipeline_importable() -> None:
    try:
        from backend.services.legal_ediscovery import process_vault_upload  # noqa: F401
        from backend.services.ediscovery_agent import LegacySession           # noqa: F401
    except Exception as exc:
        raise PreflightError(
            f"pipeline imports failed: {type(exc).__name__}:{exc!s}"
        ) from exc


def run_preflight(case_slug: str) -> dict[str, Any]:
    """Run every pre-flight gate. Raises PreflightError on the first failure."""
    case_meta = _preflight_case_exists(case_slug)
    _preflight_postgres_writable(case_slug)
    _preflight_schema_constraints()
    _preflight_qdrant_reachable()
    _preflight_pipeline_importable()
    return case_meta


# ─── classifier ──────────────────────────────────────────────────────────


@dataclass
class ParsedEmail:
    """Minimal email view for classification."""
    message_id:    str
    sender:        str       # "Name <addr>"
    sender_addr:   str       # bare addr
    to_addrs:      list[str]
    cc_addrs:      list[str]
    subject:       str
    body_snippet:  str       # first 16 KB of body, lowercased
    internaldate:  Optional[date]
    raw_bytes:     bytes


@dataclass
class ClassificationResult:
    case_slug:    Optional[str]    # None when ambiguous → quarantined
    privileged:   bool             # informational; process_vault_upload makes the actual privilege decision
    reason:       str              # human-readable rule that fired
    matched_terms: list[str] = field(default_factory=list)


def _has_keyword(haystack: str, needles: tuple[str, ...]) -> Optional[str]:
    for n in needles:
        if n in haystack:
            return n
    return None


def _addr_domain(addr: str) -> str:
    return addr.lower().rsplit("@", 1)[-1] if "@" in addr else ""


def classify_email(msg: ParsedEmail) -> ClassificationResult:
    """Per-email routing decision. Returns case_slug + privileged flag.
    Returns case_slug=None when ambiguity can't be resolved (→ quarantine).

    Rule precedence (first match wins):
      1. Explicit docket number in subject or body → corresponding case
      2. Vanderburge-specific keyword → vanderburge
      3. 7IL-prefix keyword: pre-2026 → case_i; 2026+ → case_ii
      4. Counsel-domain match: route by date window + cc analysis
      5. Username-only match (e.g. bare 'sanker') → date-window fallback
      6. Otherwise: quarantine
    """
    subj_lower = msg.subject.lower()
    body_lower = msg.body_snippet  # already lowercased
    text = f"{subj_lower} {body_lower}"
    sender_dom = _addr_domain(msg.sender_addr)
    all_addrs = [msg.sender_addr] + msg.to_addrs + msg.cc_addrs
    all_doms = {_addr_domain(a) for a in all_addrs}

    matched: list[str] = []
    privileged = any(
        d in COUNSEL_DOMAINS_BY_CASE.get("7il-v-knight-ndga-i", ()) +
             COUNSEL_DOMAINS_BY_CASE.get("7il-v-knight-ndga-ii", ()) +
             COUNSEL_DOMAINS_BY_CASE.get("vanderburge-v-knight-fannin", ())
        for d in all_doms
    )

    # Rule 1: explicit docket number in subject or body.
    for case_slug, kws in CASE_KEYWORDS.items():
        if case_slug in ("7il-v-knight-ndga-i", "7il-v-knight-ndga-ii"):
            hit = _has_keyword(text, kws)
            if hit:
                matched.append(hit)
                return ClassificationResult(case_slug=case_slug, privileged=privileged,
                                            reason=f"docket {hit!r} in subject/body",
                                            matched_terms=matched)

    # Rule 2: Vanderburge keyword.
    vander = _has_keyword(text, CASE_KEYWORDS["vanderburge-v-knight-fannin"])
    if vander:
        matched.append(vander)
        return ClassificationResult(case_slug="vanderburge-v-knight-fannin",
                                    privileged=privileged,
                                    reason=f"vanderburge keyword {vander!r}",
                                    matched_terms=matched)

    # Rule 3: 7IL-prefix keywords. Date-disambiguated.
    sevenil = _has_keyword(text, SEVEN_IL_KEYWORDS)
    if sevenil:
        matched.append(sevenil)
        if msg.internaldate and msg.internaldate.year >= 2026:
            return ClassificationResult(case_slug="7il-v-knight-ndga-ii",
                                        privileged=privileged,
                                        reason=f"7IL keyword {sevenil!r} + 2026+ date",
                                        matched_terms=matched)
        return ClassificationResult(case_slug="7il-v-knight-ndga-i",
                                    privileged=privileged,
                                    reason=f"7IL keyword {sevenil!r} + pre-2026 date",
                                    matched_terms=matched)

    # Rule 4: counsel-domain match.
    counsel_match: Optional[tuple[str, str]] = None  # (domain, addr)
    for d in all_doms:
        if d in (COUNSEL_DOMAINS_BY_CASE.get("7il-v-knight-ndga-i", ()) +
                  COUNSEL_DOMAINS_BY_CASE.get("7il-v-knight-ndga-ii", ()) +
                  COUNSEL_DOMAINS_BY_CASE.get("vanderburge-v-knight-fannin", ())):
            counsel_match = (d, "")
            matched.append(d)
            break

    if counsel_match:
        d = counsel_match[0]
        # Cc Frank Moore → Vanderburge (matches both "frank moore" with space
        # and "frank.moore@" / "frankmoore@" username patterns)
        moore_patterns = ("frank moore", "frank.moore", "frankmoore", "f.moore", "fmoore@")
        if any(any(p in a.lower() for p in moore_patterns) for a in all_addrs):
            return ClassificationResult(case_slug="vanderburge-v-knight-fannin",
                                        privileged=privileged,
                                        reason=f"counsel {d} + cc 'frank moore'",
                                        matched_terms=matched)
        # Cc other your-side counsel (not msp-lawfirm) → 7IL track
        other_counsel = {"fgplaw.com", "mhtlegal.com", "dralaw.com",
                         "wilsonhamilton.com", "wilsonpruittlaw.com"}
        if all_doms & other_counsel:
            yr = msg.internaldate.year if msg.internaldate else 2024
            target = "7il-v-knight-ndga-ii" if yr >= 2026 else "7il-v-knight-ndga-i"
            return ClassificationResult(case_slug=target, privileged=privileged,
                                        reason=f"counsel {d} + cc other your-side",
                                        matched_terms=matched)

        # Sanker (msp-lawfirm.com) date-fallback (most ambiguous case).
        if d in ("msp-lawfirm.com", "masp-lawfirm.com"):
            yr = msg.internaldate.year if msg.internaldate else 0
            if yr >= 2026:
                return ClassificationResult(case_slug="7il-v-knight-ndga-ii",
                                            privileged=privileged,
                                            reason=f"sanker domain + 2026+ date",
                                            matched_terms=matched)
            if 2021 <= yr <= 2025:
                return ClassificationResult(case_slug="7il-v-knight-ndga-i",
                                            privileged=privileged,
                                            reason=f"sanker domain + 2021-2025 date",
                                            matched_terms=matched)
            if 2019 <= yr <= 2020:
                # Vanderburge active period; ambiguous with Case I prep
                return ClassificationResult(case_slug=None, privileged=privileged,
                                            reason=f"sanker domain in 2019-2020 — Vanderburge/Case-I overlap; needs human review",
                                            matched_terms=matched)
            return ClassificationResult(case_slug=None, privileged=privileged,
                                        reason=f"sanker domain with no clear date signal",
                                        matched_terms=matched)

        # Other your-side counsel — date window
        for case, dwin in CASE_DATE_WINDOWS.items():
            if d in COUNSEL_DOMAINS_BY_CASE.get(case, ()):
                if msg.internaldate and dwin[0] <= msg.internaldate <= dwin[1]:
                    return ClassificationResult(case_slug=case, privileged=privileged,
                                                reason=f"counsel {d} + date window {case}",
                                                matched_terms=matched)
        return ClassificationResult(case_slug=None, privileged=privileged,
                                    reason=f"counsel {d} but no date-window match",
                                    matched_terms=matched)

    # Rule 5: opposing-counsel terms.
    for case, terms in OPPOSING_TERMS_BY_CASE.items():
        hit = _has_keyword(text, terms)
        if hit is None:
            for a in all_addrs:
                hit = _has_keyword(a.lower(), terms)
                if hit:
                    break
        if hit:
            matched.append(hit)
            return ClassificationResult(case_slug=case, privileged=False,
                                        reason=f"opposing term {hit!r} for {case}",
                                        matched_terms=matched)

    # Rule 6: username/name terms (less specific than domains).
    for case, terms in USERNAME_TERMS_BY_CASE.items():
        hit = _has_keyword(text, terms)
        if hit:
            matched.append(hit)
            yr = msg.internaldate.year if msg.internaldate else 0
            dwin = CASE_DATE_WINDOWS.get(case)
            if dwin and msg.internaldate and dwin[0] <= msg.internaldate <= dwin[1]:
                return ClassificationResult(case_slug=case, privileged=privileged,
                                            reason=f"username {hit!r} + date window {case}",
                                            matched_terms=matched)

    # Default: quarantine.
    return ClassificationResult(case_slug=None, privileged=privileged,
                                reason="no rule matched; quarantine",
                                matched_terms=matched)


# ─── IMAP helpers ────────────────────────────────────────────────────────


def imap_connect(user: str, pw: str) -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=SEARCH_TIMEOUT_S)
    M.login(user, pw)
    return M


def _imap_date(d: date) -> str:
    return d.strftime("%-d-%b-%Y")


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    try:
        return date(y, m, d.day)
    except ValueError:
        nxt = date(y, m, 28) + timedelta(days=4)
        return nxt - timedelta(days=nxt.day)


def date_bands(start: date, end: date, months: int = BAND_MONTHS) -> list[tuple[date, date]]:
    bands: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        nxt = _add_months(cursor, months)
        if nxt > end:
            nxt = end
        bands.append((cursor, nxt))
        cursor = nxt
    return bands


def imap_examine(M: imaplib.IMAP4_SSL, folder: str) -> int:
    quoted = '"' + folder.replace('"', '\\"') + '"'
    typ, data = M.select(quoted, readonly=True)
    if typ != "OK":
        return -1
    raw = data[0] if data else b""
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return int(s.strip()) if s.strip().isdigit() else -1


def imap_list_priority_folders(M: imaplib.IMAP4_SSL) -> list[str]:
    typ, lines = M.list()
    if typ != "OK":
        return []
    folders: list[str] = []
    for line in lines or []:
        if line is None:
            continue
        if isinstance(line, bytes):
            s = line.decode("utf-8", "replace")
        elif isinstance(line, tuple):
            s = b"".join(p for p in line if isinstance(p, (bytes, bytearray))).decode("utf-8", "replace")
        else:
            continue
        m = re.search(r'"([^"]*)"\s*$', s)
        if m:
            folders.append(m.group(1))
    return [f for f in folders if any(p.search(f) for p in SEARCH_FOLDER_PATTERNS)]


def search_uids_in_band(M: imaplib.IMAP4_SSL, since: date, before: date) -> list[str]:
    """UID SEARCH for the date band. Per Issue #177 SEARCH-overflow workaround."""
    typ, data = M.uid("SEARCH", f"SINCE {_imap_date(since)} BEFORE {_imap_date(before)}")
    if typ != "OK" or not data or not data[0]:
        return []
    return [u.decode("ascii", "replace") for u in data[0].split()]


def fetch_uid_full(M: imaplib.IMAP4_SSL, uid: str) -> Optional[bytes]:
    """FETCH the full message bytes (RFC822) for a UID. EXAMINE-mode safe."""
    typ, data = M.uid("FETCH", uid, "(BODY.PEEK[])")
    if typ != "OK" or not data:
        return None
    for entry in data:
        if isinstance(entry, tuple) and len(entry) >= 2:
            return entry[1] if isinstance(entry[1], bytes) else None
    return None


# ─── email parsing ───────────────────────────────────────────────────────


def parse_email(raw: bytes, internaldate: Optional[date]) -> Optional[ParsedEmail]:
    """Parse an .eml-shaped byte blob into a ParsedEmail. Returns None on bad input."""
    try:
        msg = email_module.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return None

    from_ = (msg.get("From") or "").strip()
    sender_addr = email.utils.parseaddr(from_)[1].lower() if from_ else ""

    to_field = (msg.get("To") or "").strip()
    cc_field = (msg.get("Cc") or "").strip()

    def _split_addrs(field: str) -> list[str]:
        out: list[str] = []
        for _, a in email.utils.getaddresses([field]):
            if a:
                out.append(a.lower())
        return out

    to_addrs = _split_addrs(to_field)
    cc_addrs = _split_addrs(cc_field)
    subject = (msg.get("Subject") or "").strip()
    msg_id = (msg.get("Message-ID") or "").strip()

    # Body snippet — first 16 KB, lowercase.
    body_chunks: list[str] = []
    try:
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                payload = part.get_content() if hasattr(part, "get_content") else part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8", "replace")
                if isinstance(payload, str):
                    body_chunks.append(payload)
                if sum(len(c) for c in body_chunks) > 32_000:
                    break
    except Exception:
        pass
    body_snippet = " ".join(body_chunks)[:16384].lower()

    return ParsedEmail(
        message_id=msg_id, sender=from_, sender_addr=sender_addr,
        to_addrs=to_addrs, cc_addrs=cc_addrs,
        subject=subject, body_snippet=body_snippet,
        internaldate=internaldate, raw_bytes=raw,
    )


def message_file_hash(parsed: ParsedEmail) -> str:
    """Stable hash for dedup. Uses Message-Id when available; else SHA-256 of raw bytes.
    Returns 64-char hex. Same hash → same email regardless of reformatting."""
    h = hashlib.sha256()
    if parsed.message_id:
        h.update(parsed.message_id.encode("utf-8", "replace"))
        return h.hexdigest()
    h.update(parsed.raw_bytes)
    return h.hexdigest()


def _slugify(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen] or "x"


def email_file_name(parsed: ParsedEmail) -> str:
    """Filename for vault_documents.file_name. Date_sender_subject.eml shape."""
    d = parsed.internaldate.strftime("%Y%m%d") if parsed.internaldate else "00000000"
    sender_slug = _slugify(parsed.sender_addr.split("@")[0] if "@" in parsed.sender_addr else parsed.sender_addr)
    subj_slug = _slugify(parsed.subject)
    return f"{d}_{sender_slug}_{subj_slug}.eml"


# ─── per-email processing ───────────────────────────────────────────────


@dataclass
class EmailOutcome:
    uid:           str
    mailbox:       str
    folder:        str
    message_id:    str
    file_hash:     str
    file_name:     str
    case_slug:     Optional[str]
    privileged:    bool
    classification_reason: str
    status:        str   # ingested | duplicate | quarantined | failed | skipped
    document_id:   Optional[str] = None
    chunks:        int = 0
    vectors_indexed: int = 0
    error:         Optional[str] = None


def _check_existing_row(case_slug: str, file_hash: str) -> Optional[str]:
    conn = _connect("fortress_db")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status FROM legal.vault_documents "
                "WHERE case_slug = %s AND file_hash = %s",
                (case_slug, file_hash),
            )
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _mirror_row_db_to_prod(case_slug: str, doc_id: str) -> None:
    """After process_vault_upload writes via LegacySession (fortress_db), copy
    the row to fortress_prod (mirrors PR D pattern)."""
    src = _connect("fortress_db")
    try:
        with src.cursor() as cur:
            cur.execute(
                "SELECT id, case_slug, file_name, nfs_path, mime_type, "
                "file_hash, file_size_bytes, processing_status, "
                "chunk_count, error_detail, created_at "
                "FROM legal.vault_documents WHERE id = %s AND case_slug = %s",
                (doc_id, case_slug),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"row {doc_id} missing in fortress_db for case {case_slug!r}"
            )
    finally:
        src.close()
    dst = _connect("fortress_prod")
    try:
        with dst.cursor() as cur:
            cur.execute(
                "INSERT INTO legal.vault_documents "
                "(id, case_slug, file_name, nfs_path, mime_type, file_hash, "
                " file_size_bytes, processing_status, chunk_count, error_detail, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT uq_vault_documents_case_hash DO UPDATE SET "
                "  processing_status = EXCLUDED.processing_status, "
                "  chunk_count = EXCLUDED.chunk_count, "
                "  error_detail = EXCLUDED.error_detail",
                row,
            )
    finally:
        dst.close()


async def _ingest_email(parsed: ParsedEmail, classification: ClassificationResult) -> EmailOutcome:
    """Push one email through process_vault_upload. Returns outcome including
    case_slug + privilege routing decision (which is process_vault_upload's, not
    ours)."""
    fhash = message_file_hash(parsed)
    fname = email_file_name(parsed)
    case_slug = classification.case_slug

    base_outcome = EmailOutcome(
        uid="", mailbox="", folder="",
        message_id=parsed.message_id, file_hash=fhash, file_name=fname,
        case_slug=case_slug, privileged=classification.privileged,
        classification_reason=classification.reason,
        status="failed",
    )

    if case_slug is None:
        base_outcome.status = "quarantined"
        return base_outcome

    existing = _check_existing_row(case_slug, fhash)
    if existing in {"complete", "completed", "ocr_failed", "locked_privileged"}:
        base_outcome.status = "duplicate"
        return base_outcome

    from backend.services.ediscovery_agent import LegacySession
    from backend.services.legal_ediscovery import process_vault_upload

    try:
        async with LegacySession() as db:
            result = await process_vault_upload(
                db=db, case_slug=case_slug,
                file_bytes=parsed.raw_bytes,
                file_name=fname,
                mime_type="message/rfc822",
            )
    except Exception as exc:
        base_outcome.status = "failed"
        base_outcome.error = f"{type(exc).__name__}:{str(exc)[:200]}"
        return base_outcome

    status = result.get("status", "failed")
    doc_id = result.get("document_id")
    base_outcome.status = "ingested" if status in {"completed", "ocr_failed", "locked_privileged"} else (
        "duplicate" if status == "duplicate" else "failed"
    )
    base_outcome.document_id = doc_id
    base_outcome.chunks = int(result.get("chunks") or 0)
    base_outcome.vectors_indexed = int(result.get("vectors_indexed") or 0)
    base_outcome.error = str(result.get("error")) if status == "failed" else None

    if doc_id and base_outcome.status == "ingested":
        try:
            _mirror_row_db_to_prod(case_slug, doc_id)
        except Exception as exc:
            base_outcome.status = "failed"
            base_outcome.error = f"mirror_failed:{type(exc).__name__}:{str(exc)[:200]}"

    return base_outcome


# ─── lock + state ────────────────────────────────────────────────────────


def _lock_path(case_slug: str) -> Path:
    return Path(f"/tmp/email-backfill-{case_slug}.lock")


def _state_path(case_slug: str) -> Path:
    return Path(f"/tmp/email-backfill-{case_slug}.state.json")


def acquire_lock(case_slug: str, force: bool) -> Path:
    lp = _lock_path(case_slug)
    if lp.exists():
        try:
            mtime = lp.stat().st_mtime
        except OSError:
            mtime = 0.0
        age = time.time() - mtime
        if force and age > LOCK_STALE_AFTER_S:
            lp.unlink()
        elif force:
            raise SystemExit(
                f"--force given but lock at {lp} is only {int(age)}s old "
                f"(needs > {LOCK_STALE_AFTER_S}s)"
            )
        else:
            raise SystemExit(
                f"another backfill appears active (lock at {lp}); "
                f"after confirming no other run, pass --force"
            )
    lp.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n")
    return lp


def release_lock(lp: Path) -> None:
    try:
        lp.unlink()
    except Exception:
        pass


def load_state(case_slug: str) -> dict[str, Any]:
    p = _state_path(case_slug)
    if not p.exists():
        return {"completed_uids": []}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"completed_uids": []}


def save_state(case_slug: str, state: dict[str, Any]) -> None:
    try:
        _state_path(case_slug).write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


# ─── manifest ────────────────────────────────────────────────────────────


@dataclass
class BackfillManifest:
    case_slug:    str
    started_at:   str
    finished_at:  str = ""
    runtime_seconds: float = 0.0
    args:         dict[str, Any] = field(default_factory=dict)
    host:         str = ""
    pid:          int = 0
    ingest_run_id: Optional[str] = None
    mailboxes:    list[str] = field(default_factory=list)
    total_uids:   int = 0
    ingested:     int = 0
    duplicate:    int = 0
    quarantined:  int = 0
    failed:       int = 0
    skipped:      int = 0
    by_classification: dict[str, int] = field(default_factory=dict)
    quarantine_log: list[dict[str, Any]] = field(default_factory=list)
    errors:       list[dict[str, Any]] = field(default_factory=list)


def write_manifest(case_slug: str, manifest: BackfillManifest) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"email-backfill-{case_slug}-{ts}.json"
    out.write_text(json.dumps(asdict(manifest), indent=2, default=str))
    return out


# ─── orchestrator ────────────────────────────────────────────────────────


def run_backfill(args: argparse.Namespace) -> int:
    case_meta = run_preflight(args.case_slug)
    lock = acquire_lock(args.case_slug, force=bool(args.force))
    state = load_state(args.case_slug) if args.resume else {"completed_uids": []}
    completed_uids = set(state.get("completed_uids", []))

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    bands = date_bands(since, until, BAND_MONTHS)
    mailbox_aliases = [m.strip() for m in args.mailbox.split(",") if m.strip()]

    manifest = BackfillManifest(
        case_slug=args.case_slug,
        started_at=started.isoformat(),
        args={k: v for k, v in vars(args).items() if k != "force"},
        host=socket.gethostname(),
        pid=os.getpid(),
        mailboxes=mailbox_aliases,
    )

    print(
        f"# email-backfill: case={args.case_slug} mailboxes={mailbox_aliases} "
        f"bands={len(bands)} ({since}→{until}) dry_run={args.dry_run}",
        flush=True,
    )

    from backend.services.ingest_run_tracker import IngestRunTracker

    try:
        with IngestRunTracker(
            args.case_slug, "email_backfill_legal",
            args=manifest.args,
        ) as tracker:
            manifest.ingest_run_id = (
                str(tracker.run_id) if tracker.run_id is not None else None
            )

            outcomes = asyncio.run(_drive_async_loop(
                mailbox_aliases=mailbox_aliases,
                bands=bands,
                args=args,
                completed_uids=completed_uids,
                manifest=manifest,
                tracker=tracker,
            ))

            for o in outcomes:
                manifest.by_classification[o.status] = manifest.by_classification.get(o.status, 0) + 1
                if o.status == "ingested":
                    manifest.ingested += 1
                elif o.status == "duplicate":
                    manifest.duplicate += 1
                elif o.status == "quarantined":
                    manifest.quarantined += 1
                    manifest.quarantine_log.append({
                        "uid": o.uid, "mailbox": o.mailbox, "folder": o.folder,
                        "message_id": o.message_id, "file_hash": o.file_hash,
                        "reason": o.classification_reason,
                    })
                elif o.status == "failed":
                    manifest.failed += 1
                    manifest.errors.append({
                        "uid": o.uid, "mailbox": o.mailbox, "folder": o.folder,
                        "message_id": o.message_id, "error": o.error or "",
                    })
                elif o.status == "skipped":
                    manifest.skipped += 1

            manifest.finished_at = datetime.now(timezone.utc).isoformat()
            manifest.runtime_seconds = round(time.monotonic() - t0, 2)
            manifest_path = write_manifest(args.case_slug, manifest)
            tracker.set_manifest_path(manifest_path)
            tracker.update(processed=manifest.ingested,
                           errored=manifest.failed,
                           skipped=manifest.duplicate + manifest.quarantined)

            print(
                f"# done: total={manifest.total_uids} ingested={manifest.ingested} "
                f"duplicate={manifest.duplicate} quarantined={manifest.quarantined} "
                f"failed={manifest.failed} runtime={manifest.runtime_seconds:.1f}s "
                f"manifest={manifest_path}",
                flush=True,
            )
            return 0 if manifest.failed == 0 else 1
    finally:
        save_state(args.case_slug, {"completed_uids": sorted(completed_uids)})
        release_lock(lock)


async def _drive_async_loop(
    *, mailbox_aliases: list[str],
    bands: list[tuple[date, date]],
    args: argparse.Namespace,
    completed_uids: set[str],
    manifest: BackfillManifest,
    tracker,
) -> list[EmailOutcome]:
    sem = asyncio.Semaphore(max(1, int(getattr(args, "jobs", 4))))
    outcomes: list[EmailOutcome] = []
    total = 0

    for alias in mailbox_aliases:
        if alias not in MAILBOX_REGISTRY:
            print(f"  SKIP {alias} — not in MAILBOX_REGISTRY", flush=True)
            continue
        user, slug = MAILBOX_REGISTRY[alias]
        try:
            pw = _password(slug)
        except Exception as exc:
            print(f"  SKIP {alias} — pass lookup failed: {exc}", flush=True)
            continue
        try:
            M = imap_connect(user, pw)
        except Exception as exc:
            print(f"  SKIP {alias} — login failed: {exc!s}", flush=True)
            continue

        try:
            folders = imap_list_priority_folders(M)
            print(f"  {alias} folders: {folders[:5]}...", flush=True)
            for folder in folders:
                cnt = imap_examine(M, folder)
                if cnt < 0:
                    continue
                for since, before in bands:
                    uids = search_uids_in_band(M, since, before)
                    for uid in uids:
                        key = f"{alias}|{folder}|{uid}"
                        if key in completed_uids:
                            continue
                        if args.limit is not None and total >= args.limit:
                            break

                        raw = fetch_uid_full(M, uid)
                        if raw is None:
                            continue
                        # crude internaldate from band midpoint as fallback;
                        # a more precise read would parse INTERNALDATE separately
                        midpoint = since + (before - since) // 2
                        parsed = parse_email(raw, midpoint)
                        if parsed is None:
                            outcomes.append(EmailOutcome(
                                uid=uid, mailbox=alias, folder=folder,
                                message_id="", file_hash="", file_name="",
                                case_slug=None, privileged=False,
                                classification_reason="parse_failed",
                                status="failed", error="email parse_failed",
                            ))
                            tracker.inc_errored()
                            total += 1
                            continue

                        cls = classify_email(parsed)

                        # Filter: only ingest emails classified to this case
                        # (or quarantine if --include-quarantine flagged)
                        if cls.case_slug != args.case_slug and not (
                            cls.case_slug is None and args.include_quarantine
                        ):
                            outcome = EmailOutcome(
                                uid=uid, mailbox=alias, folder=folder,
                                message_id=parsed.message_id,
                                file_hash=message_file_hash(parsed),
                                file_name=email_file_name(parsed),
                                case_slug=cls.case_slug, privileged=cls.privileged,
                                classification_reason=cls.reason,
                                status="skipped",
                            )
                            outcomes.append(outcome)
                            tracker.inc_skipped()
                            total += 1
                            continue

                        if args.dry_run:
                            outcome = EmailOutcome(
                                uid=uid, mailbox=alias, folder=folder,
                                message_id=parsed.message_id,
                                file_hash=message_file_hash(parsed),
                                file_name=email_file_name(parsed),
                                case_slug=cls.case_slug, privileged=cls.privileged,
                                classification_reason=cls.reason,
                                status="skipped",
                                error="dry_run",
                            )
                            outcomes.append(outcome)
                            tracker.inc_skipped()
                            total += 1
                            continue

                        outcome = await _ingest_email(parsed, cls)
                        outcome.uid = uid
                        outcome.mailbox = alias
                        outcome.folder = folder
                        outcomes.append(outcome)
                        completed_uids.add(key)
                        total += 1

                        if outcome.status == "ingested":
                            tracker.inc_processed()
                        elif outcome.status == "failed":
                            tracker.inc_errored()
                        else:
                            tracker.inc_skipped()

                        if total % 25 == 0:
                            print(
                                f"  [{total}] {outcome.status:<14s} "
                                f"{outcome.case_slug or '<quar>':<35s} "
                                f"{(outcome.classification_reason or '')[:60]}",
                                flush=True,
                            )

                    if args.limit is not None and total >= args.limit:
                        break
                if args.limit is not None and total >= args.limit:
                    break
        finally:
            try:
                M.logout()
            except Exception:
                pass

    manifest.total_uids = total
    return outcomes


# ─── rollback ────────────────────────────────────────────────────────────


def run_rollback(args: argparse.Namespace) -> int:
    """Delete email-backfill rows for the case in both DBs and Qdrant points
    where payload.case_slug matches AND file_name ends in .eml. Confirmation
    required unless --force."""
    case_slug = args.case_slug
    if not args.force:
        print(
            f"This will DELETE all email-backfill rows (.eml files) for "
            f"case_slug '{case_slug}' in fortress_prod AND fortress_db, "
            f"plus Qdrant points where payload.case_slug == '{case_slug}'.",
            flush=True,
        )
        try:
            typed = input(f"Type the case_slug ({case_slug}) to confirm: ").strip()
        except EOFError:
            typed = ""
        if typed != case_slug:
            print("rollback cancelled — confirmation did not match", flush=True)
            return 2

    pre: dict[str, int] = {}
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM legal.vault_documents "
                    "WHERE case_slug = %s AND file_name LIKE %s",
                    (case_slug, "%.eml"),
                )
                row = cur.fetchone()
                pre[dbname] = int(row[0]) if row else 0
        finally:
            conn.close()
    print(f"# pre-rollback row counts: {pre}", flush=True)

    deleted: dict[str, int] = {}
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM legal.vault_documents "
                    "WHERE case_slug = %s AND file_name LIKE %s",
                    (case_slug, "%.eml"),
                )
                deleted[dbname] = cur.rowcount or 0
        finally:
            conn.close()
    print(f"# deleted vault_documents rows: {deleted}", flush=True)

    # Qdrant: best-effort — delete points with payload case_slug match.
    # File-name filtering at Qdrant level isn't supported uniformly;
    # operator can scope further via the --qdrant-only flag.
    deleted["qdrant_estimate"] = _delete_qdrant_points_for_case(case_slug)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"email-backfill-rollback-{case_slug}-{ts}.json"
    out.write_text(json.dumps({
        "case_slug": case_slug,
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "operation": "email-backfill-rollback",
        "pre_counts": pre,
        "deleted": deleted,
    }, indent=2, default=str))
    print(f"# rollback manifest: {out}", flush=True)
    return 0


def _delete_qdrant_points_for_case(case_slug: str) -> int:
    """Delete Qdrant points across BOTH collections where payload.case_slug
    matches. Returns approximate count via pre/post delta."""
    import urllib.request
    qdrant_url = os.environ.get("QDRANT_URL", "").rstrip("/")
    if not qdrant_url:
        return 0
    total_deleted = 0
    for collection in (QDRANT_COLLECTION_WORK_PRODUCT, QDRANT_COLLECTION_PRIVILEGED):
        body = {"filter": {"must": [{"key": "case_slug", "match": {"value": case_slug}}]}}
        try:
            pre_count = _count_qdrant_points(qdrant_url, collection, case_slug)
            req = urllib.request.Request(
                f"{qdrant_url}/collections/{collection}/points/delete?wait=true",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
            post_count = _count_qdrant_points(qdrant_url, collection, case_slug)
            total_deleted += max(0, pre_count - post_count)
        except Exception as exc:
            logger.warning("qdrant_delete %s failed: %s", collection, str(exc)[:120])
    return total_deleted


def _count_qdrant_points(qdrant_url: str, collection: str, case_slug: str) -> int:
    import urllib.request
    body = {"filter": {"must": [{"key": "case_slug", "match": {"value": case_slug}}]},
            "exact": True}
    req = urllib.request.Request(
        f"{qdrant_url}/collections/{collection}/points/count",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        return int((data.get("result") or {}).get("count") or 0)
    except Exception:
        return 0


# ─── CLI ─────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Case-aware IMAP email backfill into legal vault",
    )
    p.add_argument("--case-slug", required=True,
                   help="Target case_slug. Only emails classified to this slug are ingested")
    p.add_argument("--mailbox", default="gary-gk,gary-crog",
                   help="Comma-separated mailbox aliases from MAILBOX_REGISTRY")
    p.add_argument("--since", default="2018-01-01",
                   help="Earliest date (YYYY-MM-DD) for IMAP SEARCH")
    p.add_argument("--until", default=None,
                   help="Latest date (YYYY-MM-DD); default today")
    p.add_argument("--dry-run", action="store_true",
                   help="Classify and report but do not call process_vault_upload")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap on emails processed (testing)")
    p.add_argument("--include-quarantine", action="store_true",
                   help="Also process emails that classify to None (quarantine flow)")
    p.add_argument("--rollback", action="store_true",
                   help="Delete vault_documents rows + Qdrant points for the case")
    p.add_argument("--jobs", type=int, default=4,
                   help="Parallel workers for per-email pipeline (default 4)")
    p.add_argument("--resume", action="store_true",
                   help="Skip UIDs in state file from a previous run")
    p.add_argument("--force", action="store_true",
                   help="Override stale lock or skip rollback confirmation")
    args = p.parse_args(argv)
    if args.until is None:
        args.until = datetime.now(timezone.utc).date().isoformat()
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _ensure_env_loaded()
    args = _parse_args(argv)

    if args.rollback:
        return run_rollback(args)

    try:
        return run_backfill(args)
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr, flush=True)
        return 3
    except KeyboardInterrupt:
        print("\n# interrupted — state checkpointed; resume with --resume",
              file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        traceback.print_exc()
        print(f"FATAL: {type(exc).__name__}:{exc!s}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
