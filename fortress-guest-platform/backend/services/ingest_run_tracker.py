"""
Audit-trail tracker for case-scoped ingest operations.

Wraps every script invocation (OCR sweep, vault ingestion, ASR run,
re-ingest pass) in a `legal.ingest_runs` row that records start, end,
counters, manifest path, status, and error summary.

Usage:

    with IngestRunTracker(case_slug, "ocr_legal_case",
                          args=vars(parsed_args)) as run:
        run.set_total_files(len(files))
        for f in files:
            try:
                process(f)
                run.inc_processed()
            except Exception:
                run.inc_errored()
        run.set_manifest_path(manifest_path)

Status state machine (handled automatically by `__exit__`):

    running ──clean exit──▶ complete
    running ──KeyboardInterrupt──▶ interrupted (re-raised)
    running ──other Exception──▶ error (re-raised, error_summary set)

Resilience contract: tracker DB writes are wrapped in retry+backoff
(max 3 attempts, ~30 s total). On exhaustion, the tracker degrades —
sets `self.degraded = True`, logs to stderr, and continues. Tracker
failure NEVER aborts the parent ingest job.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger("ingest_run_tracker")


# ─── DB connection helpers ─────────────────────────────────────────────────

# Tracker writes target fortress_db (where legal.* lives operationally) — same
# database the FastAPI handler queries via LegacySession.
_DEFAULT_TRACKER_DB = "fortress_db"

_RETRY_BACKOFFS_S = (0.5, 2.0, 8.0)   # sums to 10.5 s + per-attempt latency
_RETRY_TOTAL_CAP_S = 30.0


def _admin_dsn() -> dict[str, str]:
    """
    Parse POSTGRES_ADMIN_URI from env (loaded by the caller's .env step) and
    return a psycopg2 connection-keywords dict targeting fortress_db.
    """
    uri = os.environ.get("POSTGRES_ADMIN_URI", "")
    m = re.match(
        r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/[^?]+",
        uri,
    )
    if not m:
        raise RuntimeError(
            "POSTGRES_ADMIN_URI not set or not parseable; "
            "tracker requires admin DSN"
        )
    user, pw, host, port = m.groups()
    return {
        "host":     host,
        "port":     int(port or 5432),
        "user":     user,
        "password": pw,
        "dbname":   os.environ.get("INGEST_RUN_DB", _DEFAULT_TRACKER_DB),
    }


def _connect():
    """Open a fresh autocommit psycopg2 connection. Caller closes."""
    import psycopg2
    conn = psycopg2.connect(**_admin_dsn())
    conn.autocommit = True
    return conn


# ─── tracker ───────────────────────────────────────────────────────────────

@dataclass
class _State:
    processed: int = 0
    errored:   int = 0
    skipped:   int = 0


class IngestRunTracker:
    """
    Context manager that emits exactly one legal.ingest_runs row covering
    the lifecycle of a script invocation.
    """

    def __init__(
        self,
        case_slug: str,
        script_name: str,
        args: dict[str, Any] | None = None,
        connection_factory=None,        # injectable for tests
    ) -> None:
        self.case_slug = str(case_slug)
        self.script_name = str(script_name)
        self.args = dict(args or {})
        self._connect = connection_factory or _connect
        self.run_id: UUID | None = None
        self.degraded: bool = False
        self._started_monotonic: float | None = None
        self._counters = _State()

    # ─── lifecycle ─────────────────────────────────────────────────────────

    def __enter__(self) -> "IngestRunTracker":
        self._started_monotonic = time.monotonic()
        host = socket.gethostname()
        pid = os.getpid()
        args_json = json.dumps(self.args, default=str)
        ok = self._exec_with_retry(
            """
            INSERT INTO legal.ingest_runs (
                case_slug, script_name, args, invocation_args, host, pid, status,
                started_at
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, 'running', NOW())
            RETURNING id
            """,
            (
                self.case_slug, self.script_name,
                args_json, args_json,
                host, pid,
            ),
            fetch_one=True,
        )
        if ok is not None:
            self.run_id = ok[0]
        else:
            # All retries failed. The parent script must continue regardless;
            # we log loudly so an operator can spot the orphaned NOT-WRITTEN
            # state in stderr capture.
            self._log_degraded("INSERT (start row) failed")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = self._elapsed()
        if exc_type is None:
            self._update_status("complete", runtime=elapsed)
            return False
        if issubclass(exc_type, KeyboardInterrupt):
            self._update_status("interrupted", runtime=elapsed,
                                error_summary="KeyboardInterrupt")
            return False                                # re-raise
        # Other exceptions: capture short traceback and re-raise.
        summary = self._format_error(exc_type, exc, tb)
        self._update_status("error", runtime=elapsed, error_summary=summary)
        return False                                    # re-raise

    # ─── state setters ─────────────────────────────────────────────────────

    def set_total_files(self, n: int) -> None:
        self._update_counters(total_files=int(n))

    def set_manifest_path(self, path) -> None:
        self._update_counters(manifest_path=str(path))

    def inc_processed(self, n: int = 1) -> None:
        self._counters.processed += n
        self._update_counters(
            processed=self._counters.processed,
            **self._locked_counter_fields(),
        )

    def inc_errored(self, n: int = 1) -> None:
        self._counters.errored += n
        self._update_counters(
            errored=self._counters.errored,
            **self._locked_counter_fields(),
        )

    def inc_skipped(self, n: int = 1) -> None:
        self._counters.skipped += n
        self._update_counters(
            skipped=self._counters.skipped,
            **self._locked_counter_fields(),
        )

    def update(self, **fields: Any) -> None:
        """Bulk update. Keys must be column names of legal.ingest_runs."""
        if "processed" in fields: self._counters.processed = int(fields["processed"])
        if "errored"   in fields: self._counters.errored   = int(fields["errored"])
        if "skipped"   in fields: self._counters.skipped   = int(fields["skipped"])
        if {"processed", "errored", "skipped"} & fields.keys():
            fields = {**fields, **self._locked_counter_fields()}
        self._update_counters(**fields)

    # ─── private: writes ───────────────────────────────────────────────────

    def _update_status(
        self, status: str, *, runtime: float | None = None,
        error_summary: str | None = None,
    ) -> None:
        if self.run_id is None:
            return                          # tracker degraded at __enter__
        sets = [
            "status = %s",
            "ended_at = NOW()",
            "completed_at = NOW()",
            "updated_at = NOW()",
        ]
        params: list[Any] = [status]
        if runtime is not None:
            sets.append("runtime_seconds = %s")
            params.append(round(runtime, 3))
        if error_summary is not None:
            sets.append("error_summary = %s")
            params.append(error_summary[:4000])
        params.append(self.run_id)
        self._exec_with_retry(
            f"UPDATE legal.ingest_runs SET {', '.join(sets)} WHERE id = %s",
            tuple(params),
        )

    def _locked_counter_fields(self) -> dict[str, int]:
        files_seen = (
            self._counters.processed
            + self._counters.skipped
            + self._counters.errored
        )
        return {
            "files_processed": files_seen,
            "files_succeeded": self._counters.processed,
            "files_failed": self._counters.errored,
        }

    def _update_counters(self, **fields: Any) -> None:
        if self.run_id is None or not fields:
            return
        sets = []
        params: list[Any] = []
        for k, v in fields.items():
            sets.append(f"{k} = %s")
            params.append(v)
        sets.append("updated_at = NOW()")
        params.append(self.run_id)
        self._exec_with_retry(
            f"UPDATE legal.ingest_runs SET {', '.join(sets)} WHERE id = %s",
            tuple(params),
        )

    def _exec_with_retry(self, sql: str, params: tuple,
                         fetch_one: bool = False):
        if self.degraded:
            return None
        deadline = time.monotonic() + _RETRY_TOTAL_CAP_S
        last_exc: Exception | None = None
        for attempt, sleep_for in enumerate(_RETRY_BACKOFFS_S, start=1):
            if time.monotonic() >= deadline:
                break
            try:
                conn = self._connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        if fetch_one:
                            row = cur.fetchone()
                            return row
                    return True
                finally:
                    try: conn.close()
                    except Exception: pass
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "ingest_run_tracker_retry attempt=%d sleep=%.1fs error=%s",
                    attempt, sleep_for, str(exc)[:120],
                )
                if attempt < len(_RETRY_BACKOFFS_S):
                    time.sleep(min(sleep_for, max(0.0, deadline - time.monotonic())))
        # All retries failed
        self._log_degraded(f"DB write exhausted retries: {last_exc!s}"[:500])
        return None

    # ─── private: helpers ─────────────────────────────────────────────────

    def _elapsed(self) -> float | None:
        if self._started_monotonic is None:
            return None
        return time.monotonic() - self._started_monotonic

    def _log_degraded(self, reason: str) -> None:
        self.degraded = True
        sys.stderr.write(
            f"[ingest_run_tracker] DEGRADED for {self.case_slug}/"
            f"{self.script_name} pid={os.getpid()}: {reason}\n"
        )
        sys.stderr.flush()
        # Emit a structured log line too — operators querying logs by
        # 'ingest_run_tracker_degraded' can find the stuck row.
        logger.error(
            "ingest_run_tracker_degraded case_slug=%s script=%s reason=%s",
            self.case_slug, self.script_name, reason,
        )

    @staticmethod
    def _format_error(exc_type, exc, tb) -> str:
        """Two-line summary suitable for error_summary column (≤4000 chars)."""
        try:
            tb_text = "".join(traceback.format_exception(exc_type, exc, tb))
        except Exception:
            tb_text = f"{exc_type.__name__}: {exc!s}"
        # First line + last 6 frames keeps the column readable.
        lines = tb_text.splitlines()
        head = lines[0] if lines else f"{exc_type.__name__}: {exc!s}"
        tail = lines[-12:] if len(lines) > 12 else lines
        return (head + "\n" + "\n".join(tail))[:4000]
