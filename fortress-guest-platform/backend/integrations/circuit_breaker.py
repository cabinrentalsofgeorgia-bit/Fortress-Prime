"""
Lightweight circuit breaker for external service calls.
States: CLOSED (normal) -> OPEN (failing) -> HALF_OPEN (testing recovery).
"""
import time
import asyncio
import structlog
from enum import Enum
from typing import Any, Callable, Optional
from functools import wraps

logger = structlog.get_logger()


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Per-service circuit breaker that tracks consecutive failures.

    Args:
        name: Identifier for logging/metrics (e.g. "streamline", "twilio")
        failure_threshold: Consecutive failures before opening circuit
        recovery_timeout: Seconds to wait before trying half-open
        fallback: Optional async callable to invoke when circuit is open
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        fallback: Optional[Callable] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fallback = fallback

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._success_count_half_open = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute func through the circuit breaker."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            logger.warning("circuit_open", breaker=self.name, recovery_in=f"{self.recovery_timeout - (time.time() - self._last_failure_time):.0f}s")
            if self.fallback:
                return await self.fallback(*args, **kwargs)
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is OPEN")

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(exc)
            raise

    async def _on_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count_half_open += 1
                if self._success_count_half_open >= 2:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count_half_open = 0
                    logger.info("circuit_closed", breaker=self.name)
                    try:
                        log_circuit_event(self.name, "closed", "Service recovered after half-open probe")
                    except Exception:
                        pass
            else:
                self._failure_count = 0

    async def _on_failure(self, exc: Exception):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            logger.warning(
                "circuit_failure",
                breaker=self.name,
                count=self._failure_count,
                threshold=self.failure_threshold,
                error=str(exc)[:200],
            )
            if self._failure_count >= self.failure_threshold:
                prev_state = self._state
                self._state = CircuitState.OPEN
                logger.error("circuit_opened", breaker=self.name, recovery_timeout=self.recovery_timeout)
                if prev_state != CircuitState.OPEN:
                    try:
                        log_circuit_event(
                            self.name, "opened",
                            f"After {self._failure_count} failures. Last: {str(exc)[:150]}"
                        )
                    except Exception:
                        pass

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class CircuitOpenError(Exception):
    pass


# ── Global circuit breaker instances ──────────────────────────────────────────

streamline_breaker = CircuitBreaker(
    name="streamline",
    failure_threshold=3,
    recovery_timeout=60,
)

twilio_breaker = CircuitBreaker(
    name="twilio",
    failure_threshold=5,
    recovery_timeout=30,
)

openai_breaker = CircuitBreaker(
    name="openai",
    failure_threshold=3,
    recovery_timeout=120,
)


def circuit_protected(breaker: CircuitBreaker):
    """Decorator that wraps an async function with circuit breaker protection."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        wrapper.breaker = breaker
        return wrapper
    return decorator


def get_all_breaker_states() -> list[dict]:
    return [b.to_dict() for b in (streamline_breaker, twilio_breaker, openai_breaker)]


# ── Deferred Write Queue (Pillar 2B) ─────────────────────────────────────────

import json
import os
import psycopg2
import psycopg2.extras


def _get_fortress_conn():
    """Get a connection to fortress_db for deferred write operations."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.0.100"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "fortress_db"),
        user=os.getenv("DB_USER", "miner_bot"),
        password=os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", "")),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def queue_deferred_write(service: str, method: str, payload: dict) -> int:
    """
    Queue a failed API write for later replay by the recovery worker.

    Called when the circuit breaker is OPEN and a write operation fails.
    The recovery worker (src/daemons/circuit_breaker.py) flushes these
    periodically via CRON.

    Returns the queued row ID, or -1 on failure.
    """
    try:
        conn = _get_fortress_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO deferred_api_writes (service, method, payload, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING id
            """, (service, method, json.dumps(payload)))
            row = cur.fetchone()
        conn.commit()
        row_id = row["id"] if row else -1
        conn.close()
        logger.info(
            "deferred_write_queued",
            service=service, method=method, row_id=row_id,
        )
        return row_id
    except Exception as e:
        logger.error("deferred_write_queue_failed", error=str(e)[:200])
        return -1


def log_circuit_event(breaker_name: str, event: str, details: str = "") -> None:
    """Log circuit breaker state changes to system_post_mortems."""
    severity = "critical" if event == "opened" else "info"
    try:
        conn = _get_fortress_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_post_mortems
                    (sector, severity, component, error_summary, status, resolved_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                "crog", severity,
                f"circuit_breaker_{breaker_name}",
                f"Circuit breaker '{breaker_name}' {event}. {details}".strip(),
                "open" if event == "opened" else "resolved",
                None if event == "opened" else "auto",
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("circuit_event_log_failed", error=str(e)[:100])
