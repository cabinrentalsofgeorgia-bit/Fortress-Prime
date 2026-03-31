"""
Managed automation event consumer entrypoint.

This wraps the canonical queue processor so systemd can run it as a first-class
service instead of relying on an orphaned ad hoc process.
"""

from __future__ import annotations

import asyncio

from backend.vrs.application.event_consumer import process_automation_queue


def main() -> int:
    asyncio.run(process_automation_queue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
