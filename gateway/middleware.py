"""
Gateway Middleware — Rate Limiting + Request Logging
======================================================
"""

import time
import json
import logging
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("gateway.access")

# ---------------------------------------------------------------------------
# Structured access logger (JSON to stdout — Docker / Loki friendly)
# ---------------------------------------------------------------------------

_access_logger = logging.getLogger("gateway.access_log")
_access_handler = logging.StreamHandler()
_access_handler.setFormatter(logging.Formatter("%(message)s"))
_access_logger.addHandler(_access_handler)
_access_logger.setLevel(logging.INFO)
_access_logger.propagate = False


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response as structured JSON."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - t0) * 1000

        # Extract user info if available (set by auth middleware)
        user = getattr(request.state, "user", None)
        username = user.get("username", "-") if user else "-"

        log_entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
            "user": username,
            "ip": request.client.host if request.client else "-",
        }
        _access_logger.info(json.dumps(log_entry))
        return response


# ---------------------------------------------------------------------------
# In-memory rate limiter (token bucket per IP)
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter.
    - Authenticated users: 200 req/min
    - Unauthenticated: 30 req/min
    """

    def __init__(self, app, auth_limit: int = 200, anon_limit: int = 30):
        super().__init__(app)
        self.auth_limit = auth_limit
        self.anon_limit = anon_limit
        self._buckets: dict[str, list] = defaultdict(list)

    def _check_rate(self, key: str, limit: int) -> bool:
        """Return True if request is allowed."""
        now = time.time()
        window_start = now - 60.0

        # Prune old entries
        bucket = self._buckets[key]
        self._buckets[key] = [t for t in bucket if t > window_start]

        if len(self._buckets[key]) >= limit:
            return False

        self._buckets[key].append(now)
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("Authorization", "")
        is_auth = bool(auth_header)

        limit = self.auth_limit if is_auth else self.anon_limit
        key = f"{ip}:{'auth' if is_auth else 'anon'}"

        if not self._check_rate(key, limit):
            return Response(
                content=json.dumps({
                    "detail": "Rate limit exceeded. Try again in 60 seconds."
                }),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
