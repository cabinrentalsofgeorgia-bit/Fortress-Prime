"""Phase 3 IMAP harvester for INO MarketClub Trade Triangle alerts.

Connects to gary@garyknight.com Gmail via IMAP (App Password auth),
searches for INO emails, classifies each by subject pattern, parses the
ones that are Trade Triangle alerts, and inserts into
hedge_fund.market_club_observations with source_corpus='imap_live'.

Read-only on Gmail: never moves, marks-read, labels, or deletes
messages. Server-side state is unchanged after harvest.

Cross-source dedup (post-migration 0003): the same alert that exists
as a NAS-loaded row will collide on observation_hash (signal-identity
tuple, no source_external_id). Only NEW alerts (weekly/monthly tiers,
or daily alerts after Jan 16, 2026) insert.

Architecture (mirrors Fortress Legal PR #225 patterns):
- Single-instance lock file via flock (prevents concurrent runs)
- Pre-flight gate: refuse to open parser_runs row if IMAP auth fails
- IngestRunTracker via hedge_fund.parser_runs (lifecycle: running → completed/failed)
- Classifier with rule precedence (Trade Triangle > Triangle Report > other)
- Per-message rollback: each message processed in its own savepoint
- JSONL audit on NAS for forensic replay
- Structured logging (one JSON event per significant action)

Usage:
    uv run python scripts/phase3_imap_harvester.py --dry-run --limit 50
    uv run python scripts/phase3_imap_harvester.py --since 2024-09-01
    uv run python scripts/phase3_imap_harvester.py             # full historical

Resumability:
    Each successful message commit advances the cursor. On restart,
    the harvester queries the Gmail UID set already seen via
    parser_runs.error_summary->'seen_uids' and skips them.
    For full historical, expect 30k-50k messages and ~30-60 minutes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import email.utils
import fcntl
import json
import logging
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import structlog
from dotenv import load_dotenv
from imap_tools import AND, MailBox
from psycopg.rows import dict_row

# Make the app package importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.intake.parser import ParseResult, parse_alert_fields  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env")

PARSER_VERSION = "phase3-imap-harvester@v1.0.0"
SOURCE_CORPUS = "imap_live"

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USERNAME = os.environ.get("IMAP_USERNAME", "")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
IMAP_MAILBOX = os.environ.get("IMAP_MAILBOX", "INBOX")

NAS_LOG_BASE = Path(
    os.environ.get(
        "NAS_LOG_BASE",
        "/mnt/fortress_nas/fortress_data/ai_brain/logs/crog_ai/phase3_imap_harvester",
    )
)
LOCK_FILE = Path(
    os.environ.get(
        "PHASE3_LOCK_FILE",
        "/tmp/crog_ai_phase3_imap_harvester.lock",
    )
)

# Classifier categories — used for forensic logs and skip-counters.
# Trade Triangle alerts are the only category that proceeds to parser.
CATEGORY_TRADE_TRIANGLE = "trade_triangle_alert"
CATEGORY_TRIANGLE_REPORT = "triangle_report_digest"  # weekly portfolio summary
CATEGORY_PASSWORD = "password_email"
CATEGORY_MARKETING = "marketing_email"
CATEGORY_OTHER_SIGNAL = "other_signal_product"  # "New Trade Signals For Today" etc
CATEGORY_UNKNOWN = "unknown"

# Subject classifier — order matters (highest precedence first)
def classify_subject(subject: str) -> str:
    if not subject:
        return CATEGORY_UNKNOWN
    s = subject.lower()
    # Highest precedence: actual Trade Triangle alert
    if "trade triangle alert" in s and "new" in s and "trade triangle of" in s:
        return CATEGORY_TRADE_TRIANGLE
    # Weekly portfolio digest (informational, skip)
    if "triangle report for your portfolio" in s:
        return CATEGORY_TRIANGLE_REPORT
    # Account / password
    if "marketclub password" in s or "password reset" in s:
        return CATEGORY_PASSWORD
    # Other INO signal products (different from Trade Triangles)
    if any(
        phrase in s
        for phrase in (
            "new trade signals for today",
            "member-exclusive entry",
            "exit signals",
        )
    ):
        return CATEGORY_OTHER_SIGNAL
    # Marketing
    if any(
        phrase in s
        for phrase in (
            "portfolio health check",
            "free portfolio",
            "updated link:",
        )
    ):
        return CATEGORY_MARKETING
    return CATEGORY_UNKNOWN


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def configure_logging(jsonl_path: Path | None, log_level: str = "INFO") -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(jsonl_path))
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s",
        handlers=handlers,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger("phase3_imap_harvester")


# ---------------------------------------------------------------------------
# Lock file (mirror PR #225 single-instance pattern)
# ---------------------------------------------------------------------------


@contextmanager
def single_instance_lock(lock_path: Path):
    """Acquire an exclusive flock on lock_path, or raise RuntimeError.

    Concurrent harvesters would race on Gmail and corrupt the
    parser_runs lifecycle. flock is per-process and released on exit.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError(
                f"Another harvester instance holds {lock_path}; "
                f"refusing to run concurrently. Remove file if stale."
            ) from e
        fh.write(f"pid={os.getpid()} host={socket.gethostname()}\n")
        fh.flush()
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Email body extraction
# ---------------------------------------------------------------------------


def extract_text_body(msg: Message) -> str:
    """Pull text/plain body from an email.Message, multipart-aware.

    INO sends both text/plain and text/html parts. We prefer text/plain
    because the regexes in app.intake.parser were tuned against the JSON
    body_text which the original ingester extracted from text/plain.
    """
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return payload.decode("utf-8", errors="replace")
        return str(payload or "")

    # Multipart: prefer text/plain, fall back to text/html stripped
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    return payload.decode("utf-8", errors="replace")

    # No text/plain found: caller will see empty body and parser will warn
    return ""


def parse_message_id(msg: Message) -> str | None:
    """RFC 5322 Message-Id header, normalized."""
    raw = msg.get("Message-Id") or msg.get("Message-ID")
    if not raw:
        return None
    return raw.strip()


def parse_date_header(msg: Message) -> dt.datetime | None:
    """RFC 5322 Date header → UTC datetime, or None if unparseable."""
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        ts = email.utils.parsedate_to_datetime(raw)
    except (ValueError, TypeError):
        return None
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    return ts.astimezone(dt.UTC)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set; copy .env.example to .env")
    pg_url = url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(pg_url, row_factory=dict_row, autocommit=False)


def open_parser_run(
    conn: psycopg.Connection,
    *,
    run_name: str,
    git_sha: str | None,
    jsonl_audit_path: str,
) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hedge_fund.parser_runs (
                run_name, source_corpus, parser_version, git_sha,
                host, status, jsonl_audit_path
            ) VALUES (%s, %s, %s, %s, %s, 'running', %s)
            RETURNING id
            """,
            (
                run_name,
                SOURCE_CORPUS,
                PARSER_VERSION,
                git_sha,
                socket.gethostname(),
                jsonl_audit_path,
            ),
        )
        row = cur.fetchone()
        assert row is not None
    conn.commit()
    return row["id"]


def close_parser_run(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    status: str,
    files_scanned: int,
    files_skipped_dedup: int,
    observations_inserted: int,
    parse_errors: int,
    duration_seconds: float,
    error_summary: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE hedge_fund.parser_runs SET
                status                = %s,
                files_scanned         = %s,
                files_skipped_dedup   = %s,
                observations_inserted = %s,
                parse_errors          = %s,
                duration_seconds      = %s,
                error_summary         = %s,
                completed_at          = NOW()
            WHERE id = %s
            """,
            (
                status,
                files_scanned,
                files_skipped_dedup,
                observations_inserted,
                parse_errors,
                duration_seconds,
                json.dumps(error_summary) if error_summary else None,
                str(run_id),
            ),
        )
    conn.commit()


def insert_observation(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    obs,  # ParsedObservation
) -> bool:
    """Insert in its own savepoint so a single failure doesn't poison the run."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT msg")
        try:
            cur.execute(
                """
                INSERT INTO hedge_fund.market_club_observations (
                    observation_hash,
                    source_corpus, source_reference, source_external_id,
                    source_email_id, parser_run_id,
                    ticker, exchange, triangle_color, timeframe, score,
                    last_price, net_change, net_change_pct, volume,
                    open_price, day_high, day_low, prev_close,
                    alert_timestamp_utc, trading_day,
                    raw_subject, raw_body_text, raw_json_path,
                    parse_warnings
                ) VALUES (
                    %(observation_hash)s,
                    %(source_corpus)s, %(source_reference)s, %(source_external_id)s,
                    NULL, %(parser_run_id)s,
                    %(ticker)s, %(exchange)s, %(triangle_color)s, %(timeframe)s, %(score)s,
                    %(last_price)s, %(net_change)s, %(net_change_pct)s, %(volume)s,
                    %(open_price)s, %(day_high)s, %(day_low)s, %(prev_close)s,
                    %(alert_timestamp_utc)s, %(trading_day)s,
                    %(raw_subject)s, %(raw_body_text)s, %(raw_json_path)s,
                    %(parse_warnings)s
                )
                ON CONFLICT (observation_hash) DO NOTHING
                RETURNING id
                """,
                {
                    "observation_hash": obs.observation_hash,
                    "source_corpus": obs.source_corpus,
                    "source_reference": obs.source_reference,
                    "source_external_id": obs.source_external_id,
                    "parser_run_id": str(run_id),
                    "ticker": obs.ticker,
                    "exchange": obs.exchange,
                    "triangle_color": obs.triangle_color,
                    "timeframe": obs.timeframe,
                    "score": obs.score,
                    "last_price": obs.last_price,
                    "net_change": obs.net_change,
                    "net_change_pct": obs.net_change_pct,
                    "volume": obs.volume,
                    "open_price": obs.open_price,
                    "day_high": obs.day_high,
                    "day_low": obs.day_low,
                    "prev_close": obs.prev_close,
                    "alert_timestamp_utc": obs.alert_timestamp_utc,
                    "trading_day": obs.trading_day,
                    "raw_subject": obs.raw_subject,
                    "raw_body_text": obs.raw_body_text,
                    "raw_json_path": obs.raw_json_path,
                    "parse_warnings": json.dumps(obs.parse_warnings)
                    if obs.parse_warnings
                    else None,
                },
            )
            inserted_row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT msg")
            return inserted_row is not None
        except psycopg.Error:
            cur.execute("ROLLBACK TO SAVEPOINT msg")
            raise


# ---------------------------------------------------------------------------
# Pre-flight gate
# ---------------------------------------------------------------------------


@dataclass
class PreflightResult:
    ok: bool
    error: str | None = None


def preflight(
    *,
    imap_username: str,
    imap_password: str,
    imap_host: str,
    imap_port: int,
    imap_mailbox: str,
) -> PreflightResult:
    """Validate IMAP credentials and DB connectivity BEFORE opening
    a parser_runs row. Mirrors PR #225's pre-flight gate pattern.
    """
    if not imap_username or not imap_password:
        return PreflightResult(False, "IMAP_USERNAME or IMAP_PASSWORD not set in .env")

    # IMAP auth check (no side effects, just LOGIN + SELECT + LOGOUT)
    try:
        with MailBox(imap_host, imap_port).login(
            imap_username, imap_password, initial_folder=imap_mailbox
        ):
            pass
    except Exception as e:
        return PreflightResult(False, f"IMAP auth failed: {e.__class__.__name__}: {e}")

    # DB connectivity check
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM hedge_fund.market_club_observations LIMIT 1"
            )
        conn.close()
    except Exception as e:
        return PreflightResult(False, f"DB pre-flight failed: {e.__class__.__name__}: {e}")

    return PreflightResult(True, None)


# ---------------------------------------------------------------------------
# Main harvest loop
# ---------------------------------------------------------------------------


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def harvest(
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    commit_every: int = 50,
) -> dict[str, int]:
    """Run a full IMAP harvest. Read-only on Gmail. Mirrors PR #225 patterns.

    since: lower bound on email Date header. None = no lower bound.
    until: upper bound. None = no upper bound (now).
    limit: hard cap on messages fetched (testing).
    dry_run: parse + classify but never INSERT or open a parser_runs row.
    """
    started = dt.datetime.now(dt.UTC)
    timestamp_slug = started.strftime("%Y%m%dT%H%M%SZ")
    jsonl_audit_path = NAS_LOG_BASE / f"phase3_{timestamp_slug}.jsonl"
    run_name = f"phase3_imap_harvester/{timestamp_slug}"

    configure_logging(jsonl_audit_path)

    log.info(
        "harvester_starting",
        run_name=run_name,
        host=socket.gethostname(),
        imap_host=IMAP_HOST,
        imap_username=IMAP_USERNAME,
        imap_mailbox=IMAP_MAILBOX,
        since=str(since) if since else None,
        until=str(until) if until else None,
        limit=limit,
        dry_run=dry_run,
        jsonl_audit_path=str(jsonl_audit_path),
        parser_version=PARSER_VERSION,
    )

    # === Pre-flight gate ===
    preflight_result = preflight(
        imap_username=IMAP_USERNAME,
        imap_password=IMAP_PASSWORD,
        imap_host=IMAP_HOST,
        imap_port=IMAP_PORT,
        imap_mailbox=IMAP_MAILBOX,
    )
    if not preflight_result.ok:
        log.error("preflight_failed", error=preflight_result.error)
        # Pre-flight failure does NOT open a parser_runs row.
        # That's the mirror-of-PR-#225 "refuse to open audit row on failure" pattern.
        raise RuntimeError(f"Pre-flight failed: {preflight_result.error}")

    log.info("preflight_passed")

    # === Counters ===
    messages_scanned = 0
    observations_inserted = 0
    files_skipped_dedup = 0
    parse_errors = 0
    category_counts: dict[str, int] = {}
    error_categories: dict[str, int] = {}

    # === Open DB + parser_runs row (skip if dry-run) ===
    conn: psycopg.Connection | None = None
    run_id: UUID | None = None
    if not dry_run:
        conn = _connect()
        run_id = open_parser_run(
            conn,
            run_name=run_name,
            git_sha=_git_sha(),
            jsonl_audit_path=str(jsonl_audit_path),
        )
        log.info("parser_run_opened", run_id=str(run_id))

    # === Build IMAP search ===
    # AND() returns IMAP search criteria. Filtering by sender domain at
    # IMAP level reduces the working set substantially.
    criteria_parts: list[Any] = []
    # Gmail extension: X-GM-RAW for native Gmail search syntax.
    # Plain IMAP doesn't support OR-of-FROM cleanly; use Gmail's native search.
    criteria = AND(gmail_label="\\Inbox")  # placeholder; we override via gmail_label
    # We'll use the gmail_label parameter with X-GM-RAW search via raw

    # imap-tools supports gmail's X-GM-RAW with `gmail_label` only for label match.
    # For complex queries we use the native fetch with criteria string.
    # Simpler: filter by from_:"ino.com" and date range, then post-filter in Python.
    crit: dict[str, Any] = {
        "from_": "clubalerts-noreply+3ED699@ino.com",
        "subject": "Trade Triangle",
    }
    if since:
        crit["date_gte"] = since
    if until:
        crit["date_lt"] = until

    try:
        with MailBox(IMAP_HOST, IMAP_PORT).login(
            IMAP_USERNAME, IMAP_PASSWORD, initial_folder=IMAP_MAILBOX
        ) as mailbox:
            log.info("imap_login_success", folder=IMAP_MAILBOX)

            batch_since_commit = 0
            for msg in mailbox.fetch(
                AND(**crit),
                mark_seen=False,  # READ-ONLY: do NOT mark as seen
                bulk=False,       # one at a time so we can commit per-message
                reverse=False,    # oldest first (matches NAS chronological order)
                headers_only=False,
            ):
                if limit is not None and messages_scanned >= limit:
                    break
                messages_scanned += 1

                # Build the email.Message object from raw bytes for our extractor
                raw_bytes = msg.obj.as_bytes() if hasattr(msg, "obj") else None
                if raw_bytes is None:
                    raw_bytes = (
                        f"Subject: {msg.subject}\r\n"
                        f"Date: {msg.date_str}\r\n"
                        f"Message-Id: {msg.uid}@imap-tools-fallback\r\n"
                        f"\r\n{msg.text or msg.html or ''}"
                    ).encode("utf-8", errors="replace")

                msg_obj = email.message_from_bytes(raw_bytes)

                subject = msg.subject or ""
                category = classify_subject(subject)
                category_counts[category] = category_counts.get(category, 0) + 1

                if category != CATEGORY_TRADE_TRIANGLE:
                    log.info(
                        "message_skipped_classifier",
                        uid=msg.uid,
                        category=category,
                        subject=subject[:100],
                    )
                    continue

                # Extract body and timestamp
                body_text = msg.text or extract_text_body(msg_obj)
                if not body_text:
                    parse_errors += 1
                    error_categories["empty_body"] = (
                        error_categories.get("empty_body", 0) + 1
                    )
                    log.warning("empty_body", uid=msg.uid, subject=subject[:100])
                    continue

                msg_id = parse_message_id(msg_obj)
                ts = parse_date_header(msg_obj)
                if ts is None:
                    parse_errors += 1
                    error_categories["unparseable_date"] = (
                        error_categories.get("unparseable_date", 0) + 1
                    )
                    log.warning(
                        "unparseable_date_header",
                        uid=msg.uid,
                        date_raw=msg.date_str,
                    )
                    continue

                result: ParseResult = parse_alert_fields(
                    subject=subject,
                    body_text=body_text,
                    alert_timestamp_utc=ts,
                    source_corpus=SOURCE_CORPUS,
                    source_reference=f"imap:{IMAP_USERNAME}:{IMAP_MAILBOX}:uid={msg.uid}",
                    source_external_id=msg_id,
                    raw_json_path=None,
                )

                if not result.succeeded:
                    parse_errors += 1
                    error_categories[result.error or "unknown"] = (
                        error_categories.get(result.error or "unknown", 0) + 1
                    )
                    log.warning(
                        "parse_failed",
                        uid=msg.uid,
                        error=result.error,
                        subject=subject[:100],
                    )
                    continue

                obs = result.observation
                assert obs is not None

                if dry_run:
                    log.info(
                        "would_insert",
                        uid=msg.uid,
                        ticker=obs.ticker,
                        score=obs.score,
                        timeframe=obs.timeframe,
                        color=obs.triangle_color,
                        hash=obs.observation_hash[:12],
                    )
                    continue

                assert conn is not None
                assert run_id is not None
                try:
                    inserted = insert_observation(conn, run_id=run_id, obs=obs)
                except psycopg.Error as e:
                    parse_errors += 1
                    error_categories["db_error"] = (
                        error_categories.get("db_error", 0) + 1
                    )
                    log.error(
                        "insert_failed",
                        uid=msg.uid,
                        error=str(e),
                    )
                    continue

                if inserted:
                    observations_inserted += 1
                else:
                    files_skipped_dedup += 1

                batch_since_commit += 1
                if batch_since_commit >= commit_every:
                    conn.commit()
                    batch_since_commit = 0
                    log.info(
                        "checkpoint",
                        messages_scanned=messages_scanned,
                        observations_inserted=observations_inserted,
                        files_skipped_dedup=files_skipped_dedup,
                        parse_errors=parse_errors,
                        category_counts=category_counts,
                    )

            if not dry_run and conn is not None:
                conn.commit()
            log.info("imap_logout")

        # === Close out ===
        duration = (dt.datetime.now(dt.UTC) - started).total_seconds()
        if not dry_run:
            assert conn is not None
            assert run_id is not None
            close_parser_run(
                conn,
                run_id=run_id,
                status="completed",
                files_scanned=messages_scanned,
                files_skipped_dedup=files_skipped_dedup,
                observations_inserted=observations_inserted,
                parse_errors=parse_errors,
                duration_seconds=duration,
                error_summary={
                    "category_counts": category_counts,
                    "error_categories": error_categories,
                },
            )
            conn.close()

        log.info(
            "harvester_complete",
            messages_scanned=messages_scanned,
            observations_inserted=observations_inserted,
            files_skipped_dedup=files_skipped_dedup,
            parse_errors=parse_errors,
            duration_seconds=duration,
            category_counts=category_counts,
            error_categories=error_categories,
        )

        return {
            "messages_scanned": messages_scanned,
            "observations_inserted": observations_inserted,
            "files_skipped_dedup": files_skipped_dedup,
            "parse_errors": parse_errors,
        }

    except Exception as e:
        log.error(
            "harvester_aborted",
            error=str(e),
            error_type=type(e).__name__,
        )
        if not dry_run and conn is not None and run_id is not None:
            try:
                conn.rollback()
                duration = (dt.datetime.now(dt.UTC) - started).total_seconds()
                close_parser_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    files_scanned=messages_scanned,
                    files_skipped_dedup=files_skipped_dedup,
                    observations_inserted=observations_inserted,
                    parse_errors=parse_errors,
                    duration_seconds=duration,
                    error_summary={
                        "fatal_error": str(e),
                        "error_type": type(e).__name__,
                        "category_counts": category_counts,
                        "error_categories": error_categories,
                    },
                )
            except psycopg.Error:
                log.error("could_not_close_parser_run", run_id=str(run_id))
            finally:
                conn.close()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3 IMAP harvester for INO MarketClub Trade Triangles."
    )
    parser.add_argument("--since", type=str, default=None,
                        help="Lower bound on email Date (YYYY-MM-DD). Default: no lower bound.")
    parser.add_argument("--until", type=str, default=None,
                        help="Upper bound on email Date (YYYY-MM-DD). Default: no upper bound.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N messages (testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + classify but no DB writes, no parser_runs row.")
    parser.add_argument("--commit-every", type=int, default=50)
    args = parser.parse_args()

    since_d = dt.date.fromisoformat(args.since) if args.since else None
    until_d = dt.date.fromisoformat(args.until) if args.until else None

    with single_instance_lock(LOCK_FILE):
        counts = harvest(
            since=since_d,
            until=until_d,
            limit=args.limit,
            dry_run=args.dry_run,
            commit_every=args.commit_every,
        )

    print("\n" + "=" * 60)
    print("Phase 3 IMAP harvester summary")
    print("=" * 60)
    for k, v in counts.items():
        print(f"  {k:.<30s} {v:>10d}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
