"""
OODA Loop — Observe, Orient, Decide, Act (+ Reflect)
=======================================================
The core learning cycle of the Fortress recursive stack.

Each division agent runs its own OODA loop. When the REFLECT phase
detects high variance, it escalates to the Sovereign for prompt
rewriting.

This module provides the framework; each division customizes
the Observe and Act phases for its specific domain.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("recursive_core.ooda")


# =============================================================================
# OODA PHASE DEFINITIONS
# =============================================================================

class OODAPhase(str, Enum):
    OBSERVE = "observe"
    ORIENT = "orient"
    DECIDE = "decide"
    ACT = "act"
    REFLECT = "reflect"


@dataclass
class OODAEvent:
    """A single event flowing through the OODA loop."""
    event_id: str
    division: str                       # "division_a" or "division_b"
    phase: OODAPhase = OODAPhase.OBSERVE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Data at each phase
    observation: Dict[str, Any] = field(default_factory=dict)      # Raw input data
    orientation: Dict[str, Any] = field(default_factory=dict)      # Prediction vs actual
    decision: Dict[str, Any] = field(default_factory=dict)         # Planned action
    action_result: Dict[str, Any] = field(default_factory=dict)    # Action outcome
    reflection: Dict[str, Any] = field(default_factory=dict)       # Self-correction

    # Variance tracking
    predicted_value: Optional[float] = None
    actual_value: Optional[float] = None
    variance_pct: float = 0.0

    # Status
    completed: bool = False
    escalated_to_sovereign: bool = False


@dataclass
class OODACycleResult:
    """Result of a complete OODA cycle."""
    event: OODAEvent
    success: bool
    needs_optimization: bool = False
    optimization_reason: str = ""


# =============================================================================
# THE OODA LOOP ENGINE
# =============================================================================

class OODALoop:
    """
    The OODA loop engine. Each division instantiates one with its own
    phase handlers.

    Usage:
        loop = OODALoop(
            division="division_b",
            observe_fn=my_observe,
            orient_fn=my_orient,
            decide_fn=my_decide,
            act_fn=my_act,
            variance_threshold=5.0,
        )
        result = loop.run(event)
    """

    def __init__(
        self,
        division: str,
        observe_fn: Callable[[OODAEvent], OODAEvent],
        orient_fn: Callable[[OODAEvent], OODAEvent],
        decide_fn: Callable[[OODAEvent], OODAEvent],
        act_fn: Callable[[OODAEvent], OODAEvent],
        variance_threshold: float = 5.0,
    ):
        self.division = division
        self._observe = observe_fn
        self._orient = orient_fn
        self._decide = decide_fn
        self._act = act_fn
        self.variance_threshold = variance_threshold

        logger.info(f"OODA loop initialized for {division} (threshold={variance_threshold}%)")

    def run(self, event: OODAEvent) -> OODACycleResult:
        """
        Execute a complete OODA cycle for the given event.

        Returns an OODACycleResult indicating whether the cycle succeeded
        and whether optimization is needed.
        """
        logger.info(f"[OODA] Starting cycle for event {event.event_id} ({self.division})")

        try:
            # Phase 1: OBSERVE
            event.phase = OODAPhase.OBSERVE
            event = self._observe(event)
            logger.debug(f"  OBSERVE complete: {len(event.observation)} keys")

            # Phase 2: ORIENT
            event.phase = OODAPhase.ORIENT
            event = self._orient(event)
            logger.debug(f"  ORIENT complete: variance={event.variance_pct:.2f}%")

            # Phase 3: DECIDE
            event.phase = OODAPhase.DECIDE
            event = self._decide(event)
            logger.debug(f"  DECIDE complete: action={event.decision.get('action', 'none')}")

            # Phase 4: ACT
            event.phase = OODAPhase.ACT
            event = self._act(event)
            logger.debug(f"  ACT complete: success={event.action_result.get('success', False)}")

            # Phase 5: REFLECT
            event.phase = OODAPhase.REFLECT
            needs_optimization = self._reflect(event)

            event.completed = True

            return OODACycleResult(
                event=event,
                success=event.action_result.get("success", True),
                needs_optimization=needs_optimization,
                optimization_reason=event.reflection.get("reason", ""),
            )

        except Exception as e:
            logger.error(f"[OODA] Cycle failed at {event.phase.value}: {e}")
            event.reflection = {
                "reason": f"Cycle failed at {event.phase.value}: {str(e)}",
                "error": True,
            }
            return OODACycleResult(
                event=event,
                success=False,
                needs_optimization=True,
                optimization_reason=f"Exception in {event.phase.value}: {str(e)}",
            )

    def _reflect(self, event: OODAEvent) -> bool:
        """
        REFLECT phase — the recursive step.

        Checks if:
            1. The action failed
            2. The prediction had high variance (> threshold)

        If either is true, logs the reflection and flags for optimization.
        """
        action_failed = not event.action_result.get("success", True)
        high_variance = event.variance_pct > self.variance_threshold

        needs_optimization = action_failed or high_variance

        event.reflection = {
            "action_failed": action_failed,
            "high_variance": high_variance,
            "variance_pct": event.variance_pct,
            "threshold": self.variance_threshold,
            "needs_optimization": needs_optimization,
            "reason": "",
        }

        if action_failed:
            event.reflection["reason"] = (
                f"Action failed: {event.action_result.get('error', 'unknown')}"
            )
            logger.warning(f"  REFLECT: Action failed — triggering optimization")

        elif high_variance:
            event.reflection["reason"] = (
                f"High variance: {event.variance_pct:.2f}% "
                f"(threshold: {self.variance_threshold}%)"
            )
            logger.warning(
                f"  REFLECT: Variance {event.variance_pct:.2f}% > "
                f"{self.variance_threshold}% — triggering optimization"
            )

        if needs_optimization:
            event.escalated_to_sovereign = True
            # Log to reflection log
            from recursive_core.reflection_log import log_reflection
            log_reflection(event)

        return needs_optimization
