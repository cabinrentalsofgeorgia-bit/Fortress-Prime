"""
Structured JSON Logging with Structlog

Every log entry includes:
- trace_id: For correlating logs across systems
- timestamp: ISO8601 format
- service: Service name
- level: Log level
- event: The log message
"""

import logging
import sys
from typing import Any
import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def add_app_context(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """
    Add application-level context to every log entry.
    """
    event_dict["service"] = settings.app_name
    event_dict["environment"] = settings.environment
    return event_dict


def setup_logging() -> None:
    """
    Configure structured logging for production.
    
    Logs are output as JSON for easy ingestion by log aggregators
    (CloudWatch, Datadog, ELK, etc.)
    """
    # Determine if we should use JSON or console formatting
    use_json = settings.environment in ["staging", "production"]

    # Configure shared processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_app_context,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if use_json:
        # Production: JSON logs
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Pretty console logs
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    # Silence noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger():
    """
    Get a structured logger instance.
    
    Usage:
        log = get_logger()
        log.info("user_logged_in", user_id=123, trace_id="abc")
    """
    return structlog.get_logger()
