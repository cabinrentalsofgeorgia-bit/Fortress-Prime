"""
Backward-compat shim — canonical location is backend.vrs.application.event_consumer.

All consumers should migrate to:
  from backend.vrs.application.event_consumer import process_automation_queue
"""
from backend.vrs.application.event_consumer import (  # noqa: F401
    process_automation_queue,
    run_consumer,
)
