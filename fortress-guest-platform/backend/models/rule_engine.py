"""
Backward-compat shim — canonical location is backend.vrs.domain.automations.

All consumers should migrate to:
  from backend.vrs.domain.automations import VRSRuleEngine
"""
from backend.vrs.domain.automations import VRSRuleEngine  # noqa: F401
