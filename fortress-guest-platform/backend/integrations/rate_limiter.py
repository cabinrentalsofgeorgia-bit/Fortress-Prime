"""
Async rate limiter utilities for third-party integrations.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    """
    Lightweight in-process sliding-window rate limiter.

    This is intentionally dependency-free so service boot does not rely on
    external Redis/limits packages in constrained environments.
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._calls = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.period_seconds
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()

    async def acquire_async(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return

                next_slot = self._calls[0] + self.period_seconds
                sleep_for = max(0.01, next_slot - now)

            if time.monotonic() + sleep_for > deadline:
                raise TimeoutError("Rate limiter timeout while waiting for token")
            await asyncio.sleep(sleep_for)


# Streamline API guardrail: up to 8 calls / second.
streamline_limiter = AsyncRateLimiter(max_calls=8, period_seconds=1.0)

