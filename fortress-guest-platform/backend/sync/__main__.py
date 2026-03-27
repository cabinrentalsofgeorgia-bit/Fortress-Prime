"""
Standalone Streamline full-sync poller for systemd (fortress-sync-worker).

Runs ``SyncWorker.run_sync_loop`` against Postgres; does not start FastAPI or ARQ.
"""
from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from backend.core.config import settings
from backend.core.database import close_db, get_db, init_db
from backend.sync.worker import SyncWorker

logger = structlog.get_logger(service="synapse_worker_main")


async def _async_main() -> None:
    await init_db()
    interval = max(300, int(settings.streamline_sync_interval))
    worker = SyncWorker(interval=interval)
    shutdown = asyncio.Event()

    def _on_signal() -> None:
        logger.info("sync_worker_signal_received")
        worker.stop()
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows / restricted event loops
            pass

    try:
        await worker.run_sync_loop(get_db, shutdown_event=shutdown)
    finally:
        await worker.close()
        await close_db()


def main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
