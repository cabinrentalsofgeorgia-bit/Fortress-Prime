"""
SyncWorker — Background ETL worker for the Streamline Data Synapse.

Runs a continuous polling loop that calls the production StreamlineVRS.sync_all()
engine every 5 minutes (300 seconds). All 10 sync phases execute on each cycle:
  Phase 1: Properties
  Phase 2: Reservations + Guests
  Phase 3: Blocked Days / Calendar (now persisted to blocked_days table)
  Phase 4: Work Orders
  Phase 5: Rental Agreements
  Phase 6: Financial Enrichment
  Phase 7: Owner Balances
  Phase 8: Housekeeping
  Phase 9: Guest Feedback
  Phase 10: Vectorization

Production polling runs as a supervised process (systemd ``fortress-sync-worker``)
via ``python -m backend.sync``. FastAPI no longer runs ``sync_all`` in lifespan.
"""
from __future__ import annotations

import asyncio
import time

import structlog

logger = structlog.get_logger(service="synapse_worker")

SYNC_INTERVAL = 300  # 5 minutes


class SyncWorker:
    """Fault-tolerant background sync loop with structured logging."""

    def __init__(self, interval: int = SYNC_INTERVAL):
        from backend.integrations.streamline_vrs import StreamlineVRS
        self._vrs = StreamlineVRS()
        self._interval = interval
        self._running = False

    @property
    def is_configured(self) -> bool:
        return self._vrs.is_configured

    async def run_once(self, db) -> dict:
        """Execute a single full sync cycle and return the summary."""
        t0 = time.time()
        logger.info("sync_cycle_start")
        try:
            summary = await self._vrs.sync_all(db)
            elapsed = round(time.time() - t0, 1)
            logger.info(
                "sync_cycle_complete",
                elapsed_seconds=elapsed,
                properties=summary.get("properties"),
                reservations=summary.get("reservations"),
                availability=summary.get("availability"),
                errors=len(summary.get("errors", [])),
            )
            return summary
        except Exception as e:
            elapsed = round(time.time() - t0, 1)
            logger.error("sync_cycle_failed", elapsed_seconds=elapsed, error=str(e))
            return {"status": "error", "error": str(e)}

    async def _sleep_or_shutdown(
        self,
        seconds: float,
        shutdown_event: asyncio.Event | None,
    ) -> None:
        if shutdown_event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def run_sync_loop(
        self,
        get_db_session,
        shutdown_event: asyncio.Event | None = None,
    ) -> None:
        """
        Infinite polling loop. Fetches a DB session each cycle.

        When ``shutdown_event`` is set (e.g. SIGTERM), the sleep between cycles
        ends early so the process can exit without waiting a full interval.
        """
        self._running = True
        logger.info(
            "synapse_worker_starting",
            interval=self._interval,
            configured=self.is_configured,
        )

        await self._sleep_or_shutdown(5.0, shutdown_event)

        while self._running:
            try:
                if self.is_configured:
                    async for db in get_db_session():
                        await self.run_once(db)
                else:
                    logger.warning("synapse_worker_skipped", reason="streamline_not_configured")
            except Exception as e:
                logger.error("synapse_worker_error", error=str(e))

            if not self._running or (shutdown_event is not None and shutdown_event.is_set()):
                break

            logger.info("synapse_worker_sleeping", seconds=self._interval)
            await self._sleep_or_shutdown(float(self._interval), shutdown_event)

        logger.info("synapse_worker_stopped")

    def stop(self) -> None:
        """Signal the worker to stop after the current cycle."""
        self._running = False
        logger.info("synapse_worker_stop_requested")

    async def close(self) -> None:
        await self._vrs.close()
