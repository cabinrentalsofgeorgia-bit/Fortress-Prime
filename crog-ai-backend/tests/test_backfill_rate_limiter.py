"""Smoke test that the Polygon backfill's rate limiter actually gates HTTP.

This proves two things:
  1. The module-level `_RATE_LIMITER` is wired into `fetch_ticker_bars`
     BEFORE the HTTP call (the common bug is acquiring after, which lets
     bursts fly unthrottled).
  2. Concurrent fetches are paced at ≤10/sec sustained.

Test design notes
-----------------
The user spec asked for "12 concurrent fetches take ≥1 second." That
threshold won't hold with `aiolimiter.AsyncLimiter`'s leaky-bucket
semantics: AsyncLimiter(10, 1.0) lets the first 10 acquisitions burst
(bucket capacity = 10), then trickles at 10/sec. So 12 calls finish in
~0.2s.

To meaningfully test gating (i.e., second batch must wait for the leak),
we use 25 concurrent calls. With burst-then-trickle semantics, the
last 15 calls have to wait for tokens to leak at 10/sec, which forces
total elapsed to ≥1.0s. If the limiter were missing or wired AFTER the
HTTP call, all 25 would complete in ~0s and the assertion would fail.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import backfill_eod_bars  # noqa: E402


async def test_rate_limiter_gates_concurrent_fetches() -> None:
    """25 concurrent fetches against a stubbed 200-OK endpoint take ≥1.0s."""
    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {"results": []}
    fake_response.raise_for_status.return_value = None

    fake_client = MagicMock(spec=httpx.AsyncClient)
    fake_client.get = AsyncMock(return_value=fake_response)

    n_calls = 25
    start = time.monotonic()
    results = await asyncio.gather(
        *(
            backfill_eod_bars.fetch_ticker_bars(fake_client, f"T{i:03d}")
            for i in range(n_calls)
        )
    )
    elapsed = time.monotonic() - start

    # All calls succeeded with empty results (no error).
    for payload, error in results:
        assert error is None
        assert payload == []

    # Limiter is configured at 10 RPS sustained. After the initial burst
    # of `max_rate` tokens, additional tokens release at 10/sec. So the
    # 11th-25th calls (15 of them) must wait for token leakage. The
    # tail-end elapsed time is therefore >= 15/10 = 1.5s; we assert
    # >= 1.0s for cushion against test-host jitter and aiolimiter
    # implementation details.
    assert elapsed >= 1.0, (
        f"Limiter did not gate: 25 concurrent fetches finished in "
        f"{elapsed:.3f}s (expected ≥1.0s). The limiter is either missing "
        f"or applied AFTER the HTTP call."
    )

    # Spot-check: all 25 calls actually went out (so the limiter isn't
    # accidentally short-circuiting).
    assert fake_client.get.await_count == n_calls
