"""Phase 2 / ADR-0003 step 2: EOD bar backfill via Polygon.io.

For every distinct ticker in hedge_fund.market_club_observations, fetch
daily aggregate bars from Polygon and insert into hedge_fund.eod_bars.

Per ADR-0003 D5 ("trust Polygon adjustments"): we request `adjusted=true`
and populate BOTH `close` and `adjusted_close` with Polygon's adjusted
close value. `split_factor` and `dividend_cash` are placeholders (1.0 / 0)
because v1 does not track corporate actions explicitly — that is a v2
concern via hedge_fund.corporate_actions.

Architecture:
- httpx.AsyncClient, no client-side rate limiter (Polygon paid tier)
- Bounded concurrency (HTTP_CONCURRENCY) so we don't open hundreds of
  sockets at once. Defensive HTTP 429 backoff up to 60s in case Polygon
  surprises us with a per-tier limit.
- Resumable: completed tickers persisted to scripts/state/backfill_state.json.
  Re-running skips them.
- Per-ticker isolation: any failure goes to scripts/state/backfill_errors.log
  and the script continues. Empty result sets go to
  scripts/state/no_data_tickers.json.
- Idempotent inserts: ON CONFLICT (ticker, bar_date) DO NOTHING.

Partition coverage gap (known issue):
hedge_fund.eod_bars is partitioned monthly from 2024-09-01 (per
ADR-0001 D6). Bars before that date have no destination partition and
would raise an integrity error if inserted. We filter them client-side
and report a per-ticker `dropped_pre_partition` count. The downstream
audit script (audit_corpus_coverage.py) will surface tickers whose
calibration alerts now lack 63 prior bars — caller must decide whether
to backfill earlier partitions before fitting begins.

Usage:
    cd ~/Fortress-Prime/crog-ai-backend
    uv run python scripts/backfill_eod_bars.py
    uv run python scripts/backfill_eod_bars.py --tickers AAPL,MSFT
    uv run python scripts/backfill_eod_bars.py --reset-state

State files (scripts/state/, gitignored):
    backfill_state.json    completed tickers + run metadata
    backfill_errors.log    per-ticker error trail
    no_data_tickers.json   tickers Polygon returned 0 bars for
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import psycopg
import structlog
from dotenv import load_dotenv
from psycopg.rows import dict_row
from tqdm.asyncio import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
POLYGON_BASE = "https://api.polygon.io"
SOURCE_VENDOR = "polygon"

# Earliest partition in hedge_fund.eod_bars per ADR-0001 D6 / migration 0002.
PARTITION_FLOOR = date(2024, 9, 1)

# Backfill range. Polygon paid tier returns up to 50,000 bars in one call,
# so 5 years fits comfortably in a single request per ticker.
BACKFILL_START = "2024-01-01"
BACKFILL_END = datetime.now(UTC).date().isoformat()

# Bounded HTTP concurrency. Paid tier has no documented rate cap but we
# don't need to sustain more than 50 parallel sockets to hit the ~5 min
# budget on ~700 tickers.
HTTP_CONCURRENCY = 50
HTTP_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 5
MAX_BACKOFF_SECONDS = 60.0

STATE_DIR = PROJECT_ROOT / "scripts" / "state"
STATE_FILE = STATE_DIR / "backfill_state.json"
ERROR_LOG = STATE_DIR / "backfill_errors.log"
NO_DATA_FILE = STATE_DIR / "no_data_tickers.json"

INSERT_SQL = """
INSERT INTO hedge_fund.eod_bars (
    ticker, bar_date, open, high, low, close, volume, vwap,
    adjusted_close, split_factor, dividend_cash, source_vendor
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticker, bar_date) DO NOTHING
"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"started_at": None, "completed": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


def append_error(ticker: str, message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).isoformat()
    with ERROR_LOG.open("a") as f:
        f.write(f"{ts}\t{ticker}\t{message}\n")


def append_no_data(ticker: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if NO_DATA_FILE.exists():
        existing = json.loads(NO_DATA_FILE.read_text()).get("no_data", [])
    if ticker not in existing:
        existing.append(ticker)
    NO_DATA_FILE.write_text(json.dumps({"no_data": sorted(existing)}, indent=2))


# ---------------------------------------------------------------------------
# Polygon fetch
# ---------------------------------------------------------------------------


async def fetch_ticker_bars(
    client: httpx.AsyncClient,
    ticker: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch daily aggregate bars for one ticker.

    Returns (results, error). On error, results is None. On no-data,
    results is [].
    """
    url = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{BACKFILL_START}/{BACKFILL_END}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }
    backoff = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            r = await client.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            if r.status_code == 429:
                wait = min(backoff, MAX_BACKOFF_SECONDS)
                log.warning("rate_limited", ticker=ticker, attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
                backoff *= 2
                continue
            r.raise_for_status()
            payload = r.json()
            return payload.get("results") or [], None
        except httpx.HTTPStatusError as e:
            return None, f"http_{e.response.status_code}: {e.response.text[:200]}"
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            if attempt == MAX_RETRIES - 1:
                return None, f"{type(e).__name__}: {e}"
            await asyncio.sleep(min(backoff, MAX_BACKOFF_SECONDS))
            backoff *= 2
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
    return None, "max_retries_exceeded"


# ---------------------------------------------------------------------------
# Row construction + insert
# ---------------------------------------------------------------------------


def polygon_bar_to_row(ticker: str, bar: dict[str, Any]) -> tuple[Any, ...] | None:
    """Map a Polygon aggregate bar to an eod_bars insert tuple.

    Returns None if the bar's date is before PARTITION_FLOOR (caller drops it).
    Polygon `t` is epoch ms.
    """
    bar_date = datetime.fromtimestamp(bar["t"] / 1000.0, tz=UTC).date()
    if bar_date < PARTITION_FLOOR:
        return None

    adjusted_close = Decimal(str(bar["c"]))
    vwap = Decimal(str(bar["vw"])) if bar.get("vw") is not None else None

    return (
        ticker,
        bar_date,
        Decimal(str(bar["o"])),
        Decimal(str(bar["h"])),
        Decimal(str(bar["l"])),
        adjusted_close,
        int(bar["v"]),
        vwap,
        adjusted_close,
        Decimal("1.0"),
        Decimal("0"),
        SOURCE_VENDOR,
    )


def insert_rows(conn: psycopg.Connection[Any], rows: list[tuple[Any, ...]]) -> int:
    """Insert rows for one ticker. Returns number of rows attempted."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Main backfill loop
# ---------------------------------------------------------------------------


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL not set in .env")
    # Strip SQLAlchemy driver tag for raw psycopg.
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def fetch_corpus_tickers(conn: psycopg.Connection[Any]) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM hedge_fund.market_club_observations "
            "ORDER BY ticker"
        )
        return [row["ticker"] for row in cur.fetchall()]


async def process_ticker(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    db_lock: asyncio.Lock,
    conn: psycopg.Connection[Any],
    ticker: str,
) -> dict[str, Any]:
    """Returns a result dict with status/inserted/dropped/error for the ticker."""
    async with sem:
        results, error = await fetch_ticker_bars(client, ticker)

    if error is not None:
        append_error(ticker, error)
        log.error("ticker_failed", ticker=ticker, error=error)
        return {"ticker": ticker, "status": "error", "error": error, "inserted": 0}

    assert results is not None
    if not results:
        append_no_data(ticker)
        log.info("ticker_no_data", ticker=ticker)
        return {"ticker": ticker, "status": "no_data", "inserted": 0}

    rows: list[tuple[Any, ...]] = []
    dropped = 0
    for bar in results:
        row = polygon_bar_to_row(ticker, bar)
        if row is None:
            dropped += 1
        else:
            rows.append(row)

    async with db_lock:
        attempted = await asyncio.to_thread(insert_rows, conn, rows)

    log.info(
        "ticker_completed",
        ticker=ticker,
        bars_returned=len(results),
        rows_attempted=attempted,
        dropped_pre_partition=dropped,
    )
    return {
        "ticker": ticker,
        "status": "ok",
        "inserted": attempted,
        "dropped_pre_partition": dropped,
        "bars_returned": len(results),
    }


async def main_async(args: argparse.Namespace) -> int:
    if not POLYGON_API_KEY:
        print("ERROR: POLYGON_API_KEY not set in .env", file=sys.stderr)
        return 2

    state = load_state()
    if args.reset_state:
        state = {"started_at": None, "completed": []}

    completed_set = set(state.get("completed", []))

    with psycopg.connect(database_url()) as conn:
        if args.tickers:
            corpus = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            corpus = fetch_corpus_tickers(conn)

        todo = [t for t in corpus if t not in completed_set]
        log.info(
            "backfill_starting",
            corpus_size=len(corpus),
            already_done=len(corpus) - len(todo),
            todo=len(todo),
            backfill_start=BACKFILL_START,
            backfill_end=BACKFILL_END,
            partition_floor=PARTITION_FLOOR.isoformat(),
        )

        if state.get("started_at") is None:
            state["started_at"] = datetime.now(UTC).isoformat()
            save_state(state)

        sem = asyncio.Semaphore(HTTP_CONCURRENCY)
        db_lock = asyncio.Lock()

        attempted = 0
        succeeded = 0
        no_data = 0
        failed = 0
        bars_inserted = 0
        bars_dropped_pre_partition = 0

        async with httpx.AsyncClient() as client:
            tasks = [
                process_ticker(sem, client, db_lock, conn, ticker)
                for ticker in todo
            ]
            for fut in tqdm.as_completed(tasks, total=len(tasks), desc="tickers"):
                result = await fut
                attempted += 1
                ticker = result["ticker"]

                if result["status"] == "ok":
                    succeeded += 1
                    bars_inserted += result["inserted"]
                    bars_dropped_pre_partition += result.get(
                        "dropped_pre_partition", 0
                    )
                    completed_set.add(ticker)
                elif result["status"] == "no_data":
                    no_data += 1
                    completed_set.add(ticker)
                else:
                    failed += 1

                # Persist state every 10 tickers so a kill mid-run loses little.
                if attempted % 10 == 0:
                    state["completed"] = sorted(completed_set)
                    save_state(state)

        state["completed"] = sorted(completed_set)
        state["finished_at"] = datetime.now(UTC).isoformat()
        save_state(state)

    summary = {
        "tickers_attempted": attempted,
        "tickers_succeeded": succeeded,
        "tickers_no_data": no_data,
        "tickers_failed": failed,
        "bars_inserted": bars_inserted,
        "bars_dropped_pre_partition": bars_dropped_pre_partition,
    }
    log.info("backfill_complete", **summary)

    print()
    print("=" * 60)
    print("EOD backfill summary")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:.<40} {v:>10}")
    print()
    print(f"  state_file......... {STATE_FILE}")
    print(f"  errors_log......... {ERROR_LOG}")
    print(f"  no_data_file....... {NO_DATA_FILE}")
    print()

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="EOD bar backfill via Polygon.")
    parser.add_argument(
        "--tickers",
        help="Comma-separated ticker subset (default: full corpus from observations)",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Ignore prior state file and re-fetch every ticker",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
