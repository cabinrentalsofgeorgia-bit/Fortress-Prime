"""
qdrant_dual_writer.py — Phase 5a Part 3: dual-write helper for VRS Qdrant migration.

Wraps every fgp_knowledge upsert with a best-effort secondary write to
fgp_vrs_knowledge on spark-4 (192.168.0.106). Reads are unchanged — all
retrieval still targets spark-2 until Phase 5a Part 4 (read cutover).

Failure mode (Option B):
  - Primary write (spark-2) is synchronous and raises on failure. The caller's
    existing error handling is fully preserved.
  - Secondary write (spark-4) is fire-and-forget with a 5-second timeout.
    Any failure is logged as WARNING + metrics incremented. The primary write
    result is never affected.

Feature flag:
  ENABLE_QDRANT_VRS_DUAL_WRITE=false disables all secondary writes instantly
  (no network call). Restart fortress-backend to take effect.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import httpx

from backend.core.config import settings
from backend.core.qdrant import COLLECTION_NAME

log = logging.getLogger("qdrant_dual_writer")

_VRS_COLLECTION = "fgp_vrs_knowledge"
_SECONDARY_TIMEOUT = 5.0  # max seconds for secondary write (never blocks primary)

# ---------------------------------------------------------------------------
# In-process metrics (thread-safe)
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()
_metrics: dict[str, int] = {
    "qdrant_vrs_dual_write_success_total": 0,
    "qdrant_vrs_dual_write_failure_total": 0,
    "qdrant_vrs_dual_write_skipped_total": 0,
}


def get_metrics() -> dict[str, int]:
    """Return a snapshot of the dual-write metrics counters."""
    with _metrics_lock:
        return dict(_metrics)


def _inc(key: str) -> None:
    with _metrics_lock:
        _metrics[key] += 1


def reset_metrics() -> None:
    """Reset all counters to zero (test helper)."""
    with _metrics_lock:
        for k in _metrics:
            _metrics[k] = 0


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def _write_primary(points: list[dict[str, Any]], collection: str) -> None:
    """
    Primary write to spark-2. Synchronous, raises on any failure.
    The caller's existing exception handling applies unchanged.
    """
    url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(
            f"{url}/collections/{collection}/points",
            json={"points": points},
            headers=headers,
        )
        resp.raise_for_status()


async def _write_secondary(points: list[dict[str, Any]], collection: str) -> None:
    """
    Best-effort write to spark-4. Never raises — all failures are logged + metered.
    5-second timeout ensures secondary latency never bleeds into primary path.
    """
    url = settings.qdrant_vrs_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=_SECONDARY_TIMEOUT) as client:
            resp = await client.put(
                f"{url}/collections/{collection}/points",
                json={"points": points},
                headers=headers,
            )
            resp.raise_for_status()
        _inc("qdrant_vrs_dual_write_success_total")
        log.debug("vrs_secondary_write_ok points=%d collection=%s", len(points), collection)
    except Exception as exc:
        ids = [str(p.get("id", "?"))[:8] for p in points[:5]]
        log.warning(
            "vrs_secondary_write_failed points=%d ids=%s collection=%s error=%s",
            len(points), ids, collection, str(exc)[:200],
        )
        _inc("qdrant_vrs_dual_write_failure_total")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Read endpoint resolver (Phase 5a Part 4)
# ---------------------------------------------------------------------------

def resolve_read_endpoint() -> tuple[str, str]:
    """Return (qdrant_url, collection_name) for fgp_knowledge reads.

    flag=False (default) → spark-2 fgp_knowledge  (no production change)
    flag=True            → spark-4 fgp_vrs_knowledge  (post-cutover)
    """
    if settings.read_from_vrs_store:
        return (settings.qdrant_vrs_url.rstrip("/"), _VRS_COLLECTION)
    return (settings.qdrant_url.rstrip("/"), COLLECTION_NAME)


def log_read_endpoint_at_startup() -> None:
    """Emit a single INFO log so the active read target is visible on every restart."""
    url, collection = resolve_read_endpoint()
    log.info(
        "qdrant_read_endpoint url=%s collection=%s flag=%s",
        url, collection, settings.read_from_vrs_store,
    )


# Keeps fire-and-forget tasks alive until the event loop can run them.
_pending: set[asyncio.Task] = set()


async def dual_upsert_points(
    points: list[dict[str, Any]],
    primary_collection: str = COLLECTION_NAME,
    secondary_collection: str = _VRS_COLLECTION,
) -> None:
    """
    Upsert points to primary Qdrant (spark-2) and — best-effort — to secondary
    Qdrant (spark-4).

    Primary: awaited synchronously, raises on failure (same semantics as before).
    Secondary: fire-and-forget asyncio.Task with 5s timeout; never raises.

    If ENABLE_QDRANT_VRS_DUAL_WRITE is false, secondary is skipped entirely
    with no network call and the skipped counter is incremented.
    """
    if not points:
        return

    # Primary — synchronous, caller's error handling applies
    await _write_primary(points, primary_collection)

    # Secondary — fire-and-forget
    if not settings.enable_qdrant_vrs_dual_write:
        _inc("qdrant_vrs_dual_write_skipped_total")
        return

    task = asyncio.create_task(_write_secondary(points, secondary_collection))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
