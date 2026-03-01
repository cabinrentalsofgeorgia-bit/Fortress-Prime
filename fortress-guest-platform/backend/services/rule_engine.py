"""
Backward-compat shim — canonical location is backend.vrs.application.rule_engine.

All consumers should migrate to:
  from backend.vrs.domain.automations import StreamlineEventPayload
  from backend.vrs.application.rule_engine import RuleEngine
"""
from backend.vrs.domain.automations import (  # noqa: F401
    StreamlineEventPayload,
    ALLOWED_ENTITIES,
    ALLOWED_TRIGGERS,
    ALLOWED_ACTIONS,
    CMP_OPS,
)
from backend.vrs.application.rule_engine import RuleEngine  # noqa: F401
