"""Phase 2 / ADR-0003 step 2: post-backfill corpus coverage audit.

Per ADR-0002 D2 ("Tickers without sufficient history get filtered out
of the calibration corpus with explicit logging"): for every observation
in hedge_fund.market_club_observations, count the prior EOD bars
available within the trailing 90-day window before the alert's
trading_day. The Donchian D63 feature requires 63 prior trading days.

Exclusion rule (per ADR-0003 D5 sprint workflow item 2):
    A ticker is excluded if ANY of its alert dates has fewer than
    63 prior bars in the [trading_day - 90 days, trading_day) window.

Output: calibration/excluded_tickers.json
{
  "generated_at": "ISO timestamp",
  "total_tickers": int,
  "excluded_count": int,
  "kept_count": int,
  "total_observations_excluded": int,
  "excluded_tickers": [
    {
      "ticker": "XYZ",
      "failing_alerts": [
        {"alert_date": "YYYY-MM-DD", "prior_bar_count": int},
        ...
      ]
    },
    ...
  ]
}

Usage:
    cd ~/Fortress-Prime/crog-ai-backend
    uv run python scripts/audit_corpus_coverage.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from dotenv import load_dotenv
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

CALIBRATION_DIR = PROJECT_ROOT / "calibration"
OUTPUT_FILE = CALIBRATION_DIR / "excluded_tickers.json"

MIN_PRIOR_BARS = 63
LOOKBACK_DAYS = 90

# Per-(ticker, trading_day) prior-bar count over the trailing window.
# LOOKBACK_DAYS interpolated (code-owned int, not user input).
COVERAGE_SQL = f"""
SELECT
    o.ticker,
    o.trading_day                     AS alert_date,
    COUNT(b.bar_date)                 AS prior_bar_count
FROM hedge_fund.market_club_observations o
LEFT JOIN hedge_fund.eod_bars b
  ON  b.ticker  = o.ticker
  AND b.bar_date < o.trading_day
  AND b.bar_date >= o.trading_day - INTERVAL '{LOOKBACK_DAYS} days'
GROUP BY o.ticker, o.trading_day
ORDER BY o.ticker, o.trading_day
"""

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL not set in .env")
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    log.info(
        "audit_starting",
        min_prior_bars=MIN_PRIOR_BARS,
        lookback_days=LOOKBACK_DAYS,
    )

    failing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_tickers: set[str] = set()
    observations_in_failing_tickers: dict[str, int] = defaultdict(int)

    with psycopg.connect(database_url()) as conn, conn.cursor(row_factory=dict_row) as cur:
        # Total observation count per ticker (for the "observations dropped" tally)
        cur.execute(
            "SELECT ticker, COUNT(*) AS n "
            "FROM hedge_fund.market_club_observations GROUP BY ticker"
        )
        per_ticker_count = {row["ticker"]: row["n"] for row in cur.fetchall()}
        all_tickers = set(per_ticker_count.keys())

        cur.execute(COVERAGE_SQL)
        for row in cur.fetchall():
            if row["prior_bar_count"] < MIN_PRIOR_BARS:
                ticker = row["ticker"]
                failing[ticker].append(
                    {
                        "alert_date": row["alert_date"].isoformat(),
                        "prior_bar_count": int(row["prior_bar_count"]),
                    }
                )

    excluded_tickers = sorted(failing.keys())
    for ticker in excluded_tickers:
        observations_in_failing_tickers[ticker] = per_ticker_count.get(ticker, 0)

    total_observations_excluded = sum(observations_in_failing_tickers.values())

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "min_prior_bars": MIN_PRIOR_BARS,
        "lookback_days": LOOKBACK_DAYS,
        "total_tickers": len(all_tickers),
        "excluded_count": len(excluded_tickers),
        "kept_count": len(all_tickers) - len(excluded_tickers),
        "total_observations_excluded": total_observations_excluded,
        "excluded_tickers": [
            {
                "ticker": ticker,
                "total_observations": observations_in_failing_tickers[ticker],
                "failing_alerts": failing[ticker],
            }
            for ticker in excluded_tickers
        ],
    }

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2, sort_keys=True))

    log.info(
        "audit_complete",
        kept_count=output["kept_count"],
        excluded_count=output["excluded_count"],
        total_observations_excluded=total_observations_excluded,
        output=str(OUTPUT_FILE),
    )

    print()
    print("=" * 60)
    print("Corpus coverage audit")
    print("=" * 60)
    print(f"  total_tickers................ {output['total_tickers']:>10}")
    print(f"  kept_count................... {output['kept_count']:>10}")
    print(f"  excluded_count............... {output['excluded_count']:>10}")
    print(f"  total_observations_excluded.. {total_observations_excluded:>10}")
    print()
    print(f"  output: {OUTPUT_FILE}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
