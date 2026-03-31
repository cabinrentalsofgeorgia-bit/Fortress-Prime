"""
Services Layer - Business Logic for Fortress Guest Platform.

Keep package imports lazy so `import backend.services.fireclaw_runner` does not
eagerly import unrelated service modules with heavier model dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "MessageService": ("backend.services.message_service", "MessageService"),
    "AIEngine": ("backend.services.ai_engine", "AIEngine"),
    "LifecycleEngine": ("backend.services.lifecycle_engine", "LifecycleEngine"),
    "SchedulerService": ("backend.services.scheduler_service", "SchedulerService"),
    "OperationsService": ("backend.services.operations_service", "OperationsService"),
    "ReservationEngine": ("backend.services.reservation_engine", "ReservationEngine"),
    "ChannelManager": ("backend.services.channel_manager", "ChannelManager"),
    "DirectBookingEngine": ("backend.services.direct_booking", "DirectBookingEngine"),
    "AgenticOrchestrator": ("backend.services.agentic_orchestrator", "AgenticOrchestrator"),
    "AgentDecision": ("backend.services.agentic_orchestrator", "AgentDecision"),
    "MessageIntent": ("backend.services.agentic_orchestrator", "MessageIntent"),
    "SentimentScore": ("backend.services.agentic_orchestrator", "SentimentScore"),
    "HousekeepingService": ("backend.services.housekeeping_service", "HousekeepingService"),
    "PricingEngine": ("backend.services.pricing_engine", "PricingEngine"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
