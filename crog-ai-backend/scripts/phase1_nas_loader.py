"""Phase 1 NAS loader for INO MarketClub Trade Triangle alerts.

Reads JSON alert files from NAS (processed/ + failed_ingest/), parses the
subject line and body text into structured fields, and inserts into
hedge_fund.market_club_observations.

Idempotent by default: re-running over the same source directory results
in zero new inserts because every observation has a deterministic UNIQUE hash.

Audit trail:
  - hedge_fund.parser_runs: one row per invocation, lifecycle tracked.
  - JSONL audit file per run, written to NAS_LOG_BASE.

Source corpus tagging:
  - processed/    -> source_corpus = 'nas_processed'
  - failed_ingest/ -> source_corpus = 'nas_failed'

Usage:
    uv run python scripts/phase1_nas_loader.py
    uv run python scripts/phase1_nas_loader.py --source processed
    uv run python scripts/phase1_nas_loader.py --source failed_ingest
    uv run python scripts/phase1_nas_loader.py --dry-run
    uv run python scripts/phase1_nas_loader.py --limit 100

By default, both processed/ and failed_ingest/ load sequentially.

Cutover note:
  When this code moves to Spark 3, only NAS_BASE_PATH and DATABASE_URL change.
  The loader is path-agnostic and host-agnostic.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import structlog
from dotenv import load_dotenv
from psycopg.rows import dict_row

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

PARSER_VERSION = "phase1-nas-loader@v1.0.0"

NAS_BASE_PATH = Path(
    os.environ.get(
        "NAS_MARKETCLUB_PATH",
        "/mnt/vol1_source/Business/MarketClub",
    )
)
NAS_LOG_BASE = Path(
    os.environ.get(
        "NAS_LOG_BASE",
        "/mnt/fortress_nas/fortress_data/ai_brain/logs/crog_ai/phase1_nas_loader",
    )
)

# Subject: "Trade Triangle Alert - NYSE_AG NEW Green Daily Trade Triangle of 100"
SUBJECT_RE = re.compile(
    r"Trade Triangle Alert\s*-\s*"
    r"(?P<exchange>[A-Z]+)_(?P<ticker>[A-Z\.\-]+)\s+"
    r"NEW\s+"
    r"(?P<color>Green|Red)\s+"
    r"(?P<timeframe>Monthly|Weekly|Daily)\s+"
    r"Trade Triangle of\s+"
    r"(?P<score>-?\d+)",
    re.IGNORECASE,
)

# Body fields — independently optional
LAST_RE = re.compile(r"Last\s+(?P<last>[\d,]+\.?\d*)")
NET_CHANGE_RE = re.compile(
    r"Net Change\s+(?P<change>[+-]?[\d,]+\.?\d*)\s+"
    r"\(\s*(?P<pct>[+-]?[\d\.]+)\s*%\s*\)"
)
SCORE_BODY_RE = re.compile(r"Score\s+(?P<score>-?\d+)")
VOLUME_RE = re.compile(r"Volume\s+(?P<volume>\d+)")
OPEN_RE = re.compile(r"Open\s+(?P<open>[\d,]+\.?\d*)")
DAY_HIGH_RE = re.compile(r"Day High\s+(?P<high>[\d,]+\.?\d*)")
DAY_LOW_RE = re.compile(r"Day Low\s+(?P<low>[\d,]+\.?\d*)")
PREV_CLOSE_RE = re.compile(r"Prev Close\s+(?P<prev>[\d,]+\.?\d*)")


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


log = structlog.get_logger("phase1_nas_loader")


@dataclass
class ParsedObservation:
    source_corpus: str
    source_reference: str
    source_external_id: str | None
    raw_json_path: str
    ticker: str
    exchange: str
    triangle_color: str
    timeframe: str
    score: int
    last_price: float | None
    net_change: float | None
    net_change_pct: float | None
    volume: int | None
    open_price: float | None
    day_high: float | None
    day_low: float | None
    prev_close: float | None
    alert_timestamp_utc: dt.datetime
    trading_day: dt.date
    raw_subject: str
    raw_body_text: str
    parse_warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def observation_hash(self) -> str:
        """Cross-source dedup hash. Excludes source_external_id so that
        the same alert from NAS vs IMAP collapses to one row.

        MUST stay byte-identical to app/intake/parser.py and to the SQL
        formula in alembic/versions/0003_rehash_xsource_dedup.py.
        """
        ts_iso = self.alert_timestamp_utc.astimezone(dt.UTC).isoformat()
        parts = [
            self.ticker,
            ts_iso,
            self.triangle_color,
            self.timeframe,
            str(self.score),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass
class ParseResult:
    observation: ParsedObservation | None
    error: str | None
    file_path: str

    @property
    def succeeded(self) -> bool:
        return self.observation is not None and self.error is None


def _parse_decimal(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_int(s: str) -> int | None:
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _derive_trading_day(ts: dt.datetime) -> dt.date:
    """Map UTC timestamp to its US-equity trading day.

    Heuristic: trading day = date in US/Eastern. Approximate as UTC - 4h.
    Adequate for day-bucket assignment; tighten with zoneinfo if needed.
    """
    et = ts.astimezone(dt.UTC) - dt.timedelta(hours=4)
    return et.date()


def parse_alert_json(file_path: Path, source_corpus: str) -> ParseResult:
    try:
        raw = file_path.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return ParseResult(None, f"unreadable_or_invalid_json: {e}", str(file_path))

    meta = doc.get("meta") or {}
    data = doc.get("data") or {}

    if not data:
        return ParseResult(None, "missing data block", str(file_path))

    subject = data.get("subject") or ""
    body_text = data.get("body_text") or ""
    timestamp_utc_str = data.get("timestamp_utc")

    if not subject or not timestamp_utc_str:
        return ParseResult(
            None,
            f"missing subject ({bool(subject)}) or timestamp ({bool(timestamp_utc_str)})",
            str(file_path),
        )

    m = SUBJECT_RE.search(subject)
    if not m:
        return ParseResult(None, f"subject did not match pattern: {subject!r}", str(file_path))

    ticker = m.group("ticker").upper()
    exchange = m.group("exchange").upper()
    color = m.group("color").lower()
    timeframe = m.group("timeframe").lower()
    try:
        score = int(m.group("score"))
    except ValueError:
        return ParseResult(None, f"score not an integer: {m.group('score')!r}", str(file_path))

    if not (-100 <= score <= 100):
        return ParseResult(None, f"score out of range -100..100: {score}", str(file_path))

    try:
        ts = dt.datetime.fromisoformat(timestamp_utc_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.UTC)
    except ValueError as e:
        return ParseResult(None, f"unparseable timestamp {timestamp_utc_str!r}: {e}", str(file_path))

    warnings: list[dict[str, Any]] = []

    def _pull_decimal(rx: re.Pattern[str], group: str, fname: str) -> float | None:
        bm = rx.search(body_text)
        if not bm:
            warnings.append({"field": fname, "reason": "regex_miss"})
            return None
        v = _parse_decimal(bm.group(group))
        if v is None:
            warnings.append({"field": fname, "reason": "decimal_parse_fail", "raw": bm.group(group)})
        return v

    last_price = _pull_decimal(LAST_RE, "last", "last_price")

    nc_match = NET_CHANGE_RE.search(body_text)
    if nc_match:
        net_change = _parse_decimal(nc_match.group("change"))
        net_change_pct = _parse_decimal(nc_match.group("pct"))
    else:
        net_change = None
        net_change_pct = None
        warnings.append({"field": "net_change", "reason": "regex_miss"})

    vol_match = VOLUME_RE.search(body_text)
    volume = _parse_int(vol_match.group("volume")) if vol_match else None
    if volume is None:
        warnings.append({
            "field": "volume",
            "reason": "regex_miss" if not vol_match else "int_parse_fail",
        })

    open_price = _pull_decimal(OPEN_RE, "open", "open_price")
    day_high = _pull_decimal(DAY_HIGH_RE, "high", "day_high")
    day_low = _pull_decimal(DAY_LOW_RE, "low", "day_low")
    prev_close = _pull_decimal(PREV_CLOSE_RE, "prev", "prev_close")

    body_score_match = SCORE_BODY_RE.search(body_text)
    if body_score_match:
        body_score = int(body_score_match.group("score"))
        if body_score != score:
            warnings.append({
                "field": "score",
                "reason": "subject_body_mismatch",
                "subject_score": score,
                "body_score": body_score,
            })

    obs = ParsedObservation(
        source_corpus=source_corpus,
        source_reference=str(file_path),
        source_external_id=meta.get("id"),
        raw_json_path=str(file_path),
        ticker=ticker,
        exchange=exchange,
        triangle_color=color,
        timeframe=timeframe,
        score=score,
        last_price=last_price,
        net_change=net_change,
        net_change_pct=net_change_pct,
        volume=volume,
        open_price=open_price,
        day_high=day_high,
        day_low=day_low,
        prev_close=prev_close,
        alert_timestamp_utc=ts,
        trading_day=_derive_trading_day(ts),
        raw_subject=subject,
        raw_body_text=body_text,
        parse_warnings=warnings,
    )
    return ParseResult(obs, None, str(file_path))


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set; copy .env.example to .env and configure")
    pg_url = url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(pg_url, row_factory=dict_row, autocommit=False)


def open_parser_run(
    conn: psycopg.Connection, *,
    run_name: str, source_corpus: str,
    git_sha: str | None, jsonl_audit_path: str,
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
            (run_name, source_corpus, PARSER_VERSION, git_sha,
             socket.gethostname(), jsonl_audit_path),
        )
        row = cur.fetchone()
        assert row is not None
    conn.commit()
    return row["id"]


def close_parser_run(
    conn: psycopg.Connection, *,
    run_id: UUID, status: str,
    files_scanned: int, files_skipped_dedup: int,
    observations_inserted: int, parse_errors: int,
    duration_seconds: float, error_summary: dict[str, Any] | None = None,
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
            (status, files_scanned, files_skipped_dedup,
             observations_inserted, parse_errors, duration_seconds,
             json.dumps(error_summary) if error_summary else None,
             str(run_id)),
        )
    conn.commit()


def insert_observation(
    conn: psycopg.Connection, *, run_id: UUID, obs: ParsedObservation,
) -> bool:
    with conn.cursor() as cur:
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
                "ticker": obs.ticker, "exchange": obs.exchange,
                "triangle_color": obs.triangle_color,
                "timeframe": obs.timeframe, "score": obs.score,
                "last_price": obs.last_price, "net_change": obs.net_change,
                "net_change_pct": obs.net_change_pct, "volume": obs.volume,
                "open_price": obs.open_price, "day_high": obs.day_high,
                "day_low": obs.day_low, "prev_close": obs.prev_close,
                "alert_timestamp_utc": obs.alert_timestamp_utc,
                "trading_day": obs.trading_day,
                "raw_subject": obs.raw_subject,
                "raw_body_text": obs.raw_body_text,
                "raw_json_path": obs.raw_json_path,
                "parse_warnings":
                    json.dumps(obs.parse_warnings) if obs.parse_warnings else None,
            },
        )
        inserted_row = cur.fetchone()
    return inserted_row is not None


def iter_alert_files(directory: Path) -> Iterator[Path]:
    if not directory.exists():
        log.warning("source_directory_missing", path=str(directory))
        return
    for p in sorted(directory.glob("alert_*.json")):
        if p.is_file():
            yield p


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


def run_loader(
    *, source_dir: Path, source_corpus: str,
    dry_run: bool = False, limit: int | None = None,
    commit_every: int = 500,
) -> dict[str, int]:
    files_scanned = 0
    observations_inserted = 0
    files_skipped_dedup = 0
    parse_errors = 0
    error_categories: dict[str, int] = {}

    started = dt.datetime.now(dt.UTC)
    timestamp_slug = started.strftime("%Y%m%dT%H%M%SZ")
    jsonl_audit_path = NAS_LOG_BASE / f"{source_corpus}_{timestamp_slug}.jsonl"
    run_name = f"phase1_nas_loader/{source_corpus}/{timestamp_slug}"

    configure_logging(jsonl_audit_path)

    log.info(
        "loader_starting",
        source_dir=str(source_dir), source_corpus=source_corpus,
        dry_run=dry_run, limit=limit,
        jsonl_audit_path=str(jsonl_audit_path),
        parser_version=PARSER_VERSION, host=socket.gethostname(),
    )

    if dry_run:
        for fp in iter_alert_files(source_dir):
            if limit is not None and files_scanned >= limit:
                break
            files_scanned += 1
            result = parse_alert_json(fp, source_corpus)
            if result.succeeded:
                log.info(
                    "would_insert", file=fp.name,
                    ticker=result.observation.ticker,  # type: ignore[union-attr]
                    score=result.observation.score,  # type: ignore[union-attr]
                    hash=result.observation.observation_hash[:12],  # type: ignore[union-attr]
                )
            else:
                parse_errors += 1
                error_categories[result.error or "unknown"] = (
                    error_categories.get(result.error or "unknown", 0) + 1
                )
                log.warning("parse_failed", file=fp.name, error=result.error)
        log.info(
            "dry_run_complete",
            files_scanned=files_scanned, parse_errors=parse_errors,
            error_categories=error_categories,
        )
        return {
            "files_scanned": files_scanned,
            "observations_inserted": 0,
            "files_skipped_dedup": 0,
            "parse_errors": parse_errors,
        }

    conn = _connect()
    run_id: UUID | None = None
    try:
        run_id = open_parser_run(
            conn, run_name=run_name, source_corpus=source_corpus,
            git_sha=_git_sha(), jsonl_audit_path=str(jsonl_audit_path),
        )
        log.info("parser_run_opened", run_id=str(run_id), run_name=run_name)

        batch_since_commit = 0
        for fp in iter_alert_files(source_dir):
            if limit is not None and files_scanned >= limit:
                break
            files_scanned += 1
            result = parse_alert_json(fp, source_corpus)

            if not result.succeeded:
                parse_errors += 1
                error_categories[result.error or "unknown"] = (
                    error_categories.get(result.error or "unknown", 0) + 1
                )
                log.warning(
                    "parse_failed", file=fp.name, error=result.error,
                    file_count=files_scanned,
                )
                continue

            obs = result.observation
            assert obs is not None
            try:
                inserted = insert_observation(conn, run_id=run_id, obs=obs)
            except psycopg.Error as e:
                conn.rollback()
                parse_errors += 1
                error_categories["db_error"] = error_categories.get("db_error", 0) + 1
                log.error(
                    "insert_failed", file=fp.name, error=str(e),
                    file_count=files_scanned,
                )
                continue

            if inserted:
                observations_inserted += 1
                log.debug(
                    "inserted", ticker=obs.ticker, score=obs.score,
                    hash=obs.observation_hash[:12],
                )
            else:
                files_skipped_dedup += 1
                log.debug(
                    "skipped_dedup", ticker=obs.ticker,
                    hash=obs.observation_hash[:12],
                )

            batch_since_commit += 1
            if batch_since_commit >= commit_every:
                conn.commit()
                batch_since_commit = 0
                log.info(
                    "checkpoint",
                    files_scanned=files_scanned,
                    observations_inserted=observations_inserted,
                    files_skipped_dedup=files_skipped_dedup,
                    parse_errors=parse_errors,
                )

        conn.commit()
        duration = (dt.datetime.now(dt.UTC) - started).total_seconds()

        close_parser_run(
            conn, run_id=run_id, status="completed",
            files_scanned=files_scanned,
            files_skipped_dedup=files_skipped_dedup,
            observations_inserted=observations_inserted,
            parse_errors=parse_errors,
            duration_seconds=duration,
            error_summary={"error_categories": error_categories} if error_categories else None,
        )

        log.info(
            "loader_complete",
            run_id=str(run_id),
            files_scanned=files_scanned,
            observations_inserted=observations_inserted,
            files_skipped_dedup=files_skipped_dedup,
            parse_errors=parse_errors,
            duration_seconds=duration,
            error_categories=error_categories,
        )
        return {
            "files_scanned": files_scanned,
            "observations_inserted": observations_inserted,
            "files_skipped_dedup": files_skipped_dedup,
            "parse_errors": parse_errors,
        }

    except Exception as e:
        log.error("loader_aborted", error=str(e), error_type=type(e).__name__)
        if run_id is not None:
            try:
                conn.rollback()
                duration = (dt.datetime.now(dt.UTC) - started).total_seconds()
                close_parser_run(
                    conn, run_id=run_id, status="failed",
                    files_scanned=files_scanned,
                    files_skipped_dedup=files_skipped_dedup,
                    observations_inserted=observations_inserted,
                    parse_errors=parse_errors,
                    duration_seconds=duration,
                    error_summary={
                        "fatal_error": str(e),
                        "error_type": type(e).__name__,
                        "error_categories": error_categories,
                    },
                )
            except psycopg.Error:
                log.error("could_not_close_parser_run", run_id=str(run_id))
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1 NAS loader for INO MarketClub Trade Triangle alerts.",
    )
    parser.add_argument(
        "--source",
        choices=["processed", "failed_ingest", "both"],
        default="both",
        help="Which NAS subdirectory to load (default: both)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse but don't write to the database",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N files (for testing)",
    )
    parser.add_argument(
        "--commit-every", type=int, default=500,
        help="Commit DB transaction every N processed files (default: 500)",
    )
    args = parser.parse_args()

    sources_to_run: list[tuple[str, str]] = []
    if args.source in ("processed", "both"):
        sources_to_run.append(("processed", "nas_processed"))
    if args.source in ("failed_ingest", "both"):
        sources_to_run.append(("failed_ingest", "nas_failed"))

    overall: dict[str, dict[str, int]] = {}
    for dirname, corpus_tag in sources_to_run:
        source_dir = NAS_BASE_PATH / dirname
        log.info("starting_corpus", source_dir=str(source_dir), source_corpus=corpus_tag)
        counts = run_loader(
            source_dir=source_dir,
            source_corpus=corpus_tag,
            dry_run=args.dry_run,
            limit=args.limit,
            commit_every=args.commit_every,
        )
        overall[corpus_tag] = counts

    print("\n" + "=" * 60)
    print("Phase 1 NAS loader summary")
    print("=" * 60)
    for corpus, counts in overall.items():
        print(f"\n{corpus}:")
        for k, v in counts.items():
            print(f"  {k:.<30s} {v:>10d}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
