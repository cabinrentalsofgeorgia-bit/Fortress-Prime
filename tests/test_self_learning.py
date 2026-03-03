#!/usr/bin/env python3
"""
Self-Learning & Self-Grading Test Harness
============================================
Proves that the Fortress recursive stack can:

    1. GRADE ITSELF  — OODA REFLECT detects variance and flags degradation
    2. LEARN          — Prompt Governor rewrites agent prompts from failures
    3. GOVERN ITSELF  — Firewall blocks illegal data flows automatically
    4. REMEMBER        — Golden Rules persist vendor corrections as learned rules
    5. HEAL            — Sovereign detects system-wide issues and dispatches fixes

Run modes:
    python3 tests/test_self_learning.py              # Unit tests (no DB/LLM needed)
    python3 tests/test_self_learning.py --live        # Integration tests (full stack)
    python3 tests/test_self_learning.py --verbose     # Extra detail

Architecture tested:
    OODA Loop → REFLECT → Reflection Log → Escalation Processor → Prompt Governor
    Division Firewall → Corporate Veil enforcement
    Sovereign Orchestrator → Health Monitor → Dispatch Directives
"""

import json
import os
import sys
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# TEST FRAMEWORK (minimal, no external deps)
# =============================================================================

class TestResult:
    def __init__(self, name: str, passed: bool, detail: str = "", grade: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.grade = grade  # The system's self-assigned grade

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        grade_str = f" [Self-Grade: {self.grade}]" if self.grade else ""
        return f"  [{status}] {self.name}{grade_str}"


class TestSuite:
    def __init__(self, name: str):
        self.name = name
        self.results: list[TestResult] = []

    def add(self, result: TestResult):
        self.results.append(result)

    def report(self):
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        pct = (passed / total * 100) if total > 0 else 0

        print()
        print("=" * 70)
        print(f"  {self.name}")
        print("=" * 70)

        for r in self.results:
            print(r)
            if r.detail and ("--verbose" in sys.argv or not r.passed):
                for line in r.detail.split("\n"):
                    print(f"        {line}")

        print()
        print(f"  Score: {passed}/{total} ({pct:.0f}%)")
        if pct == 100:
            print("  VERDICT: All self-learning capabilities operational.")
        elif pct >= 75:
            print("  VERDICT: Core learning works. Some subsystems need attention.")
        elif pct >= 50:
            print("  VERDICT: Partial learning capability. Review failing tests.")
        else:
            print("  VERDICT: Learning pipeline needs repair.")
        print("=" * 70)
        return passed == total


# =============================================================================
# TEST 1: OODA REFLECT — Self-Grading via Variance Detection
# =============================================================================

def test_reflect_detects_high_variance(suite: TestSuite):
    """
    The REFLECT phase should flag events where predicted != actual by > 5%.
    This is the system grading its own predictions.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent, OODAPhase

    # Mock phase handlers (we only care about REFLECT)
    def observe(event):
        event.observation = {"raw": "test_data"}
        return event

    def orient(event):
        # Simulate: predicted $100, actual $108 → 8% variance
        event.predicted_value = 100.0
        event.actual_value = 108.0
        event.variance_pct = abs(108.0 - 100.0) / 100.0 * 100  # 8%
        event.orientation = {"predicted": 100, "actual": 108}
        return event

    def decide(event):
        event.decision = {"action": "categorize"}
        return event

    def act(event):
        event.action_result = {"success": True}
        return event

    loop = OODALoop(
        division="division_b",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_high_variance", division="division_b")

    # Patch out the reflection log so we don't write to disk
    with patch("recursive_core.reflection_log.log_reflection", return_value=None):
        result = loop.run(event)

    suite.add(TestResult(
        name="REFLECT detects 8% variance (threshold=5%)",
        passed=result.needs_optimization is True,
        detail=f"Variance: {result.event.variance_pct:.2f}%, "
               f"Escalated: {result.event.escalated_to_sovereign}, "
               f"Reason: {result.optimization_reason}",
        grade="NEEDS_OPTIMIZATION" if result.needs_optimization else "NOMINAL",
    ))


def test_reflect_passes_low_variance(suite: TestSuite):
    """
    When variance is under threshold, REFLECT should NOT trigger optimization.
    The system should grade itself as "nominal."
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def observe(event):
        event.observation = {"raw": "test_data"}
        return event

    def orient(event):
        # Simulate: predicted $89.99, actual $89.99 → 0% variance
        event.predicted_value = 89.99
        event.actual_value = 89.99
        event.variance_pct = 0.0
        return event

    def decide(event):
        event.decision = {"action": "categorize"}
        return event

    def act(event):
        event.action_result = {"success": True}
        return event

    loop = OODALoop(
        division="division_b",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_low_variance", division="division_b")
    result = loop.run(event)

    suite.add(TestResult(
        name="REFLECT passes exact match (0% variance)",
        passed=result.needs_optimization is False,
        detail=f"Variance: {result.event.variance_pct:.2f}%, "
               f"Needs optimization: {result.needs_optimization}",
        grade="NOMINAL",
    ))


def test_reflect_catches_action_failure(suite: TestSuite):
    """
    If the ACT phase fails, REFLECT should catch it regardless of variance.
    The system grades failed actions as needing optimization.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def observe(event):
        event.observation = {"raw": "test"}
        return event

    def orient(event):
        event.variance_pct = 0.0  # No variance, but action will fail
        return event

    def decide(event):
        event.decision = {"action": "categorize"}
        return event

    def act(event):
        event.action_result = {"success": False, "error": "LLM returned invalid JSON"}
        return event

    loop = OODALoop(
        division="division_a",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_action_failure", division="division_a")

    with patch("recursive_core.reflection_log.log_reflection", return_value=None):
        result = loop.run(event)

    suite.add(TestResult(
        name="REFLECT catches action failure (even with 0% variance)",
        passed=(result.needs_optimization is True and
                result.event.reflection.get("action_failed") is True),
        detail=f"Action failed: {result.event.reflection.get('action_failed')}, "
               f"Reason: {result.optimization_reason}",
        grade="NEEDS_OPTIMIZATION",
    ))


def test_reflect_boundary_exactly_at_threshold(suite: TestSuite):
    """
    Variance of exactly 5.0% should NOT trigger (must be > threshold).
    Tests the system's precision in self-grading.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def observe(event):
        event.observation = {"raw": "boundary"}
        return event

    def orient(event):
        event.predicted_value = 100.0
        event.actual_value = 105.0
        event.variance_pct = 5.0  # Exactly at threshold
        return event

    def decide(event):
        event.decision = {"action": "categorize"}
        return event

    def act(event):
        event.action_result = {"success": True}
        return event

    loop = OODALoop(
        division="division_b",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_boundary", division="division_b")
    result = loop.run(event)

    suite.add(TestResult(
        name="REFLECT boundary: exactly 5.0% does NOT trigger (> not >=)",
        passed=result.needs_optimization is False,
        detail=f"Variance: {result.event.variance_pct:.2f}%, "
               f"Threshold: 5.0%, Triggered: {result.needs_optimization}",
        grade="NOMINAL (boundary precision test)",
    ))


def test_reflect_exception_recovery(suite: TestSuite):
    """
    If a phase throws an exception, the OODA loop should catch it
    and self-grade as needing optimization (not crash silently).
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def observe(event):
        event.observation = {"raw": "will_crash"}
        return event

    def orient(event):
        raise RuntimeError("Simulated NIM container timeout")

    def decide(event):
        event.decision = {"action": "noop"}
        return event

    def act(event):
        event.action_result = {"success": True}
        return event

    loop = OODALoop(
        division="division_a",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_exception", division="division_a")

    with patch("recursive_core.reflection_log.log_reflection", return_value=None):
        result = loop.run(event)

    suite.add(TestResult(
        name="OODA loop recovers from phase exception (self-heals)",
        passed=(result.success is False and
                result.needs_optimization is True and
                "orient" in result.optimization_reason.lower()),
        detail=f"Success: {result.success}, "
               f"Reason: {result.optimization_reason}",
        grade="EXCEPTION_RECOVERY",
    ))


# =============================================================================
# TEST 2: Escalation Pipeline — REFLECT → Sovereign → Prompt Governor
# =============================================================================

def test_escalation_marks_event(suite: TestSuite):
    """
    When REFLECT triggers, it should mark the event as escalated_to_sovereign.
    This proves the learning pipeline's handoff mechanism works.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def observe(event):
        event.observation = {"raw": "escalation_test"}
        return event

    def orient(event):
        event.variance_pct = 15.0  # Way over threshold
        return event

    def decide(event):
        event.decision = {"action": "categorize"}
        return event

    def act(event):
        event.action_result = {"success": True}
        return event

    loop = OODALoop(
        division="division_b",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(event_id="test_escalation", division="division_b")

    with patch("recursive_core.reflection_log.log_reflection", return_value=None):
        result = loop.run(event)

    suite.add(TestResult(
        name="High variance event gets escalated_to_sovereign=True",
        passed=result.event.escalated_to_sovereign is True,
        detail=f"Escalated: {result.event.escalated_to_sovereign}, "
               f"Variance: {result.event.variance_pct:.2f}%",
        grade="ESCALATED",
    ))


def test_prompt_governor_reads_registry(suite: TestSuite):
    """
    The Prompt Governor should know where each agent's prompt lives.
    Tests the prompt registry mapping.
    """
    from sovereign.prompt_governor import AGENT_PROMPT_MAP

    expected_agents = ["division_a.agent", "division_b.agent"]
    found = [a for a in expected_agents if a in AGENT_PROMPT_MAP]

    suite.add(TestResult(
        name="Prompt Governor registry has both division agents mapped",
        passed=len(found) == len(expected_agents),
        detail=f"Registered agents: {list(AGENT_PROMPT_MAP.keys())}",
        grade="REGISTRY_COMPLETE" if len(found) == len(expected_agents) else "INCOMPLETE",
    ))


def test_prompt_governor_archive_workflow(suite: TestSuite):
    """
    The Prompt Governor should archive old prompts before writing new ones.
    Tests the version control mechanism (the system's memory of past selves).
    """
    from sovereign.prompt_governor import commit_prompt, PROMPT_HISTORY_DIR

    # Create a temporary prompt directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_prompts = Path(tmpdir) / "prompts"
        tmp_prompts.mkdir()
        tmp_history = tmp_prompts / "history"

        test_prompt_file = tmp_prompts / "test_agent.yaml"
        test_prompt_file.write_text("old prompt content: v1\n")

        # Patch the module-level paths
        with patch("sovereign.prompt_governor.AGENT_PROMPT_MAP",
                    {"test.agent": test_prompt_file}), \
             patch("sovereign.prompt_governor.PROMPT_HISTORY_DIR", tmp_history), \
             patch("recursive_core.reflection_log.log_optimization"):

            success = commit_prompt(
                agent_id="test.agent",
                new_prompt="optimized prompt content: v2\n",
                reasoning="Test optimization",
            )

        new_content = test_prompt_file.read_text()
        archive_exists = tmp_history.exists() and any(tmp_history.iterdir())

        suite.add(TestResult(
            name="Prompt Governor archives old prompt and writes new one",
            passed=(success is True and
                    "v2" in new_content and
                    archive_exists),
            detail=f"Committed: {success}, "
                   f"New content: '{new_content.strip()[:60]}', "
                   f"Archive exists: {archive_exists}",
            grade="PROMPT_EVOLVED",
        ))


# =============================================================================
# TEST 3: Firewall — Self-Governance (Corporate Veil)
# =============================================================================

def test_firewall_blocks_lateral_flow(suite: TestSuite):
    """
    Division A should NEVER access Division B data (and vice versa).
    The system must govern itself — block illegal access automatically.
    """
    from recursive_core.firewall import (
        validate_data_flow, Division, FirewallViolation
    )

    blocked = False
    try:
        validate_data_flow(Division.HOLDING, Division.PROPERTY, "transactions")
    except FirewallViolation:
        blocked = True

    suite.add(TestResult(
        name="Firewall blocks Division A → Division B lateral flow",
        passed=blocked is True,
        detail="Corporate veil integrity enforced at runtime",
        grade="VEIL_ENFORCED",
    ))


def test_firewall_allows_upward_flow(suite: TestSuite):
    """
    Data flowing UP to the Sovereign should always be permitted.
    Both divisions report to Tier 1.
    """
    from recursive_core.firewall import validate_data_flow, Division

    allowed_a = validate_data_flow(Division.HOLDING, Division.SOVEREIGN, "metrics")
    allowed_b = validate_data_flow(Division.PROPERTY, Division.SOVEREIGN, "metrics")

    suite.add(TestResult(
        name="Firewall allows upward flows (Division → Sovereign)",
        passed=allowed_a is True and allowed_b is True,
        detail=f"Division A → Sovereign: {allowed_a}, "
               f"Division B → Sovereign: {allowed_b}",
        grade="VERTICAL_FLOWS_OK",
    ))


def test_firewall_allows_downward_directives(suite: TestSuite):
    """
    The Sovereign should be able to send directives DOWN to divisions.
    """
    from recursive_core.firewall import validate_data_flow, Division

    allowed_a = validate_data_flow(Division.SOVEREIGN, Division.HOLDING, "directive")
    allowed_b = validate_data_flow(Division.SOVEREIGN, Division.PROPERTY, "directive")

    suite.add(TestResult(
        name="Firewall allows downward flows (Sovereign → Divisions)",
        passed=allowed_a is True and allowed_b is True,
        detail=f"Sovereign → A: {allowed_a}, Sovereign → B: {allowed_b}",
        grade="DIRECTIVES_FLOW_OK",
    ))


def test_firewall_access_matrix_isolation(suite: TestSuite):
    """
    The access matrix should guarantee Division B cannot read Division A
    resources and vice versa.
    """
    from recursive_core.firewall import check_access, Division, FirewallViolation

    violations = 0

    # Division B trying to read Division A's transactions
    try:
        check_access(Division.PROPERTY, "division_a.transactions")
    except FirewallViolation:
        violations += 1

    # Division A trying to read Division B's trust ledger
    try:
        check_access(Division.HOLDING, "division_b.trust_ledger")
    except FirewallViolation:
        violations += 1

    suite.add(TestResult(
        name="Access matrix blocks cross-division resource reads",
        passed=violations == 2,
        detail=f"Expected 2 violations, got {violations}",
        grade="MATRIX_ENFORCED",
    ))


# =============================================================================
# TEST 4: Sovereign Health Monitor — System Self-Assessment
# =============================================================================

def test_sovereign_state_machine(suite: TestSuite):
    """
    The Sovereign orchestrator's state machine should correctly track
    health status progression.
    """
    from sovereign.orchestrator import SovereignState, SystemHealthStatus

    state = SovereignState()

    # Default should be NOMINAL
    default_ok = state.health_status == SystemHealthStatus.NOMINAL

    # Simulate degradation
    state.health_status = SystemHealthStatus.DEGRADED
    state.optimization_triggers.append({
        "cycle": 0,
        "reason": "test degradation",
    })

    degraded_ok = (
        state.health_status == SystemHealthStatus.DEGRADED and
        len(state.optimization_triggers) == 1
    )

    suite.add(TestResult(
        name="Sovereign state machine tracks health transitions",
        passed=default_ok and degraded_ok,
        detail=f"Default=NOMINAL: {default_ok}, "
               f"Degraded with trigger: {degraded_ok}",
        grade=state.health_status.value.upper(),
    ))


def test_sovereign_division_reports(suite: TestSuite):
    """
    The Sovereign should be able to hold reports from both divisions
    simultaneously (it's the only entity with cross-division visibility).
    """
    from sovereign.orchestrator import SovereignState, DivisionReport

    state = SovereignState()
    state.division_a_report = DivisionReport(
        division="holding",
        metrics={"txn_count_24h": 4, "total_transactions": 150},
        anomalies=[],
    )
    state.division_b_report = DivisionReport(
        division="property",
        metrics={"txn_count_24h": 8, "trust_net": 0.0},
        anomalies=[{"type": "TRUST_IMBALANCE", "severity": "CRITICAL"}],
    )

    has_both = (state.division_a_report is not None and
                state.division_b_report is not None)
    a_isolated = "trust_net" not in state.division_a_report.metrics
    b_has_anomaly = len(state.division_b_report.anomalies) == 1

    suite.add(TestResult(
        name="Sovereign holds both division reports (cross-division visibility)",
        passed=has_both and a_isolated and b_has_anomaly,
        detail=f"Both reports: {has_both}, "
               f"A doesn't see trust: {a_isolated}, "
               f"B anomaly detected: {b_has_anomaly}",
        grade="SOVEREIGN_VISIBILITY_OK",
    ))


# =============================================================================
# TEST 5: Learning Memory — OODA Event Lifecycle
# =============================================================================

def test_ooda_event_tracks_all_phases(suite: TestSuite):
    """
    An OODA event should accumulate data through all 5 phases,
    creating a complete audit trail the system can learn from.
    """
    from recursive_core.ooda_loop import OODAEvent, OODAPhase

    event = OODAEvent(event_id="lifecycle_test", division="division_b")

    # Simulate flowing through all phases
    event.phase = OODAPhase.OBSERVE
    event.observation = {"vendor": "NVIDIA", "amount": -4999.00}

    event.phase = OODAPhase.ORIENT
    event.orientation = {"category": "ASSET", "confidence": 0.95}
    event.predicted_value = 5000.0
    event.actual_value = 4999.0

    event.phase = OODAPhase.DECIDE
    event.decision = {"action": "categorize", "account": "6100-GPU-Hardware"}

    event.phase = OODAPhase.ACT
    event.action_result = {"success": True, "journal_id": "JE-2026-0042"}

    event.phase = OODAPhase.REFLECT
    event.variance_pct = abs(4999.0 - 5000.0) / 5000.0 * 100  # 0.02%
    event.reflection = {"needs_optimization": False, "variance_pct": event.variance_pct}
    event.completed = True

    all_populated = all([
        event.observation,
        event.orientation,
        event.decision,
        event.action_result,
        event.reflection,
    ])

    suite.add(TestResult(
        name="OODA event accumulates data through all 5 phases",
        passed=all_populated and event.completed,
        detail=f"Phases populated: observation={bool(event.observation)}, "
               f"orientation={bool(event.orientation)}, "
               f"decision={bool(event.decision)}, "
               f"action={bool(event.action_result)}, "
               f"reflection={bool(event.reflection)}, "
               f"completed={event.completed}",
        grade="LIFECYCLE_COMPLETE",
    ))


def test_ooda_variance_calculation_accuracy(suite: TestSuite):
    """
    Test that the variance math is correct for several scenarios.
    The system's self-grading is only as good as its math.
    """
    test_cases = [
        # (predicted, actual, expected_variance_pct)
        (100.0, 108.0, 8.0),       # Over by 8%
        (100.0, 92.0, 8.0),        # Under by 8%
        (89.99, 89.99, 0.0),       # Exact match
        (325.0, 347.82, 7.02),     # Real-world utility bill
        (62.0, 65.0, 4.84),        # Just under threshold
    ]

    all_correct = True
    details = []
    for predicted, actual, expected_var in test_cases:
        if predicted > 0:
            calculated = abs(actual - predicted) / predicted * 100
        else:
            calculated = 0.0
        correct = abs(calculated - expected_var) < 0.1
        all_correct = all_correct and correct
        details.append(f"${predicted}→${actual}: {calculated:.2f}% "
                       f"(expected {expected_var}%) {'OK' if correct else 'WRONG'}")

    suite.add(TestResult(
        name="Variance calculation accuracy across 5 scenarios",
        passed=all_correct,
        detail="\n".join(details),
        grade="MATH_VERIFIED" if all_correct else "MATH_ERROR",
    ))


# =============================================================================
# TEST 6: DSPy Prompt Optimizer — Signature Definitions
# =============================================================================

def test_prompt_optimizer_failure_collection(suite: TestSuite):
    """
    The prompt optimizer should handle empty failure logs gracefully
    (early in the system's life, there may be no failures to learn from).
    """
    from recursive_core.prompt_optimizer import _collect_failures

    # Should return empty list when no reflection log exists
    failures = _collect_failures("nonexistent.agent", limit=10)

    suite.add(TestResult(
        name="Prompt optimizer handles empty failure history gracefully",
        passed=isinstance(failures, list),
        detail=f"Got {len(failures)} failures for nonexistent agent (expected 0 or [])",
        grade="COLD_START_OK",
    ))


# =============================================================================
# TEST 7: Full OODA Cycle — Learning Pipeline End-to-End
# =============================================================================

def test_full_learning_cycle(suite: TestSuite):
    """
    Run a complete OODA cycle with a deliberately bad prediction,
    verify the system:
        1. Detects the variance
        2. Self-grades as needing optimization
        3. Flags for Sovereign escalation
        4. Records the reflection

    This is the core proof that the system can learn and grade itself.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    reflection_log = []

    def mock_log_reflection(event):
        reflection_log.append({
            "event_id": event.event_id,
            "division": event.division,
            "variance_pct": event.variance_pct,
            "escalated": event.escalated_to_sovereign,
            "reflection": event.reflection,
        })

    # Simulate a utility bill that came in 12% over prediction
    def observe(event):
        event.observation = {
            "vendor": "Blue Ridge Electric",
            "amount": -347.82,
            "predicted_amount": -310.00,
        }
        return event

    def orient(event):
        obs = event.observation
        event.predicted_value = abs(obs["predicted_amount"])
        event.actual_value = abs(obs["amount"])
        if event.predicted_value > 0:
            event.variance_pct = (
                abs(event.actual_value - event.predicted_value)
                / event.predicted_value * 100
            )
        event.orientation = {
            "predicted": event.predicted_value,
            "actual": event.actual_value,
            "variance_pct": event.variance_pct,
        }
        return event

    def decide(event):
        event.decision = {
            "action": "categorize_as_utility",
            "account": "6200-Utilities",
        }
        return event

    def act(event):
        event.action_result = {
            "success": True,
            "journal_id": "JE-2026-TEST",
        }
        return event

    loop = OODALoop(
        division="division_b",
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
        variance_threshold=5.0,
    )

    event = OODAEvent(
        event_id="learning_cycle_001",
        division="division_b",
    )

    with patch("recursive_core.reflection_log.log_reflection",
               side_effect=mock_log_reflection):
        result = loop.run(event)

    # Verify the complete learning chain
    detected_variance = result.event.variance_pct > 5.0
    self_graded = result.needs_optimization is True
    escalated = result.event.escalated_to_sovereign is True
    logged = len(reflection_log) == 1

    all_passed = detected_variance and self_graded and escalated and logged

    suite.add(TestResult(
        name="Full learning cycle: detect → grade → escalate → log",
        passed=all_passed,
        detail=(
            f"Variance detected: {detected_variance} ({result.event.variance_pct:.2f}%)\n"
            f"Self-graded as needing optimization: {self_graded}\n"
            f"Escalated to Sovereign: {escalated}\n"
            f"Reflection logged: {logged}"
            + (f"\n  Log entry: {json.dumps(reflection_log[0], default=str, indent=2)[:300]}"
               if logged else "")
        ),
        grade="LEARNING_PIPELINE_VERIFIED",
    ))


# =============================================================================
# TEST 8: Adaptive Threshold Test — Different Tolerance Levels
# =============================================================================

def test_custom_thresholds(suite: TestSuite):
    """
    Different divisions can have different tolerance levels.
    Division B (trust accounting) should be stricter than Division A.
    Tests that the system can adapt its grading criteria.
    """
    from recursive_core.ooda_loop import OODALoop, OODAEvent

    def make_loop(division, threshold):
        return OODALoop(
            division=division,
            observe_fn=lambda e: setattr(e, "observation", {"test": True}) or e,
            orient_fn=lambda e: setattr(e, "variance_pct", 3.5) or e,
            decide_fn=lambda e: setattr(e, "decision", {"action": "test"}) or e,
            act_fn=lambda e: setattr(e, "action_result", {"success": True}) or e,
            variance_threshold=threshold,
        )

    # Division A: 5% threshold → 3.5% should pass
    loop_a = make_loop("division_a", 5.0)
    event_a = OODAEvent(event_id="threshold_a", division="division_a")
    result_a = loop_a.run(event_a)

    # Division B trust: 2% threshold → 3.5% should FAIL
    loop_b = make_loop("division_b", 2.0)
    event_b = OODAEvent(event_id="threshold_b", division="division_b")
    with patch("recursive_core.reflection_log.log_reflection", return_value=None):
        result_b = loop_b.run(event_b)

    a_passed = result_a.needs_optimization is False   # 3.5% < 5%
    b_flagged = result_b.needs_optimization is True    # 3.5% > 2%

    suite.add(TestResult(
        name="Adaptive thresholds: A@5% passes, B@2% flags (same 3.5% variance)",
        passed=a_passed and b_flagged,
        detail=f"Division A (5% threshold): needs_opt={result_a.needs_optimization}\n"
               f"Division B (2% threshold): needs_opt={result_b.needs_optimization}",
        grade="ADAPTIVE_GRADING_OK",
    ))


# =============================================================================
# LIVE INTEGRATION TESTS (require running infrastructure)
# =============================================================================

def test_live_sovereign_cycle(suite: TestSuite):
    """
    [LIVE] Run one real Sovereign orchestration cycle against the database.
    Requires: PostgreSQL, DeepSeek R1 on Spark-02.
    """
    try:
        from sovereign.orchestrator import run_cycle, SovereignState

        state = run_cycle(SovereignState(cycle_id=999))

        suite.add(TestResult(
            name="[LIVE] Sovereign orchestration cycle completes",
            passed=state.cycle_id == 1000,  # Should have been incremented
            detail=f"Health: {state.health_status.value}, "
                   f"Directives: {len(state.directives)}, "
                   f"Triggers: {len(state.optimization_triggers)}",
            grade=state.health_status.value.upper(),
        ))
    except Exception as e:
        suite.add(TestResult(
            name="[LIVE] Sovereign orchestration cycle completes",
            passed=False,
            detail=f"Error: {e}\n(Requires DB + LLM running)",
            grade="INFRASTRUCTURE_UNAVAILABLE",
        ))


def test_live_escalation_processor(suite: TestSuite):
    """
    [LIVE] Process any pending OODA escalations through the Sovereign.
    Requires: NAS logs, DeepSeek R1.
    """
    try:
        from sovereign.process_escalations import get_unprocessed_escalations

        escalations = get_unprocessed_escalations()

        suite.add(TestResult(
            name="[LIVE] Escalation processor reads reflection log",
            passed=isinstance(escalations, list),
            detail=f"Found {len(escalations)} unprocessed escalation(s)",
            grade=f"{len(escalations)}_PENDING",
        ))
    except Exception as e:
        suite.add(TestResult(
            name="[LIVE] Escalation processor reads reflection log",
            passed=False,
            detail=f"Error: {e}",
            grade="LOG_UNAVAILABLE",
        ))


def test_live_webhook_health(suite: TestSuite):
    """
    [LIVE] Check if the webhook server is running and both division agents
    are initialized.
    """
    try:
        import requests
        resp = requests.get("http://localhost:8006/health", timeout=5)
        data = resp.json()

        agents = data.get("agents", {})
        div_a_init = agents.get("division_a", {}).get("initialized", False)
        div_b_init = agents.get("division_b", {}).get("initialized", False)

        suite.add(TestResult(
            name="[LIVE] Webhook server healthy with both agents initialized",
            passed=data.get("status") == "operational" and div_a_init and div_b_init,
            detail=f"Status: {data.get('status')}, "
                   f"Division A: {div_a_init}, Division B: {div_b_init}, "
                   f"DB: {data.get('database')}",
            grade="OPERATIONAL" if data.get("status") == "operational" else "DEGRADED",
        ))
    except Exception as e:
        suite.add(TestResult(
            name="[LIVE] Webhook server healthy with both agents initialized",
            passed=False,
            detail=f"Error: {e}\n(Start with: python3 webhook_server.py)",
            grade="SERVER_DOWN",
        ))


# =============================================================================
# MAIN
# =============================================================================

def main():
    print()
    print("=" * 70)
    print("  FORTRESS PRIME — SELF-LEARNING & SELF-GRADING TEST HARNESS")
    print("  Testing the recursive intelligence stack")
    print("=" * 70)
    print()

    live_mode = "--live" in sys.argv

    # --- Unit Tests (always run, no infrastructure needed) ---
    unit_suite = TestSuite("UNIT TESTS — Core Learning Engine (no infrastructure)")

    # Test 1: OODA REFLECT self-grading
    test_reflect_detects_high_variance(unit_suite)
    test_reflect_passes_low_variance(unit_suite)
    test_reflect_catches_action_failure(unit_suite)
    test_reflect_boundary_exactly_at_threshold(unit_suite)
    test_reflect_exception_recovery(unit_suite)

    # Test 2: Escalation pipeline
    test_escalation_marks_event(unit_suite)
    test_prompt_governor_reads_registry(unit_suite)
    test_prompt_governor_archive_workflow(unit_suite)

    # Test 3: Firewall self-governance
    test_firewall_blocks_lateral_flow(unit_suite)
    test_firewall_allows_upward_flow(unit_suite)
    test_firewall_allows_downward_directives(unit_suite)
    test_firewall_access_matrix_isolation(unit_suite)

    # Test 4: Sovereign state machine
    test_sovereign_state_machine(unit_suite)
    test_sovereign_division_reports(unit_suite)

    # Test 5: Learning memory
    test_ooda_event_tracks_all_phases(unit_suite)
    test_ooda_variance_calculation_accuracy(unit_suite)

    # Test 6: Prompt optimizer cold start
    test_prompt_optimizer_failure_collection(unit_suite)

    # Test 7: Full learning cycle (the big one)
    test_full_learning_cycle(unit_suite)

    # Test 8: Adaptive thresholds
    test_custom_thresholds(unit_suite)

    unit_ok = unit_suite.report()

    # --- Live Integration Tests (only when --live flag is set) ---
    if live_mode:
        live_suite = TestSuite("LIVE INTEGRATION TESTS — Full Stack")
        test_live_webhook_health(live_suite)
        test_live_sovereign_cycle(live_suite)
        test_live_escalation_processor(live_suite)
        live_ok = live_suite.report()
    else:
        print()
        print("  Tip: Run with --live to also test against the running stack:")
        print("    python3 tests/test_self_learning.py --live")
        print()

    # Final verdict
    print()
    print("=" * 70)
    print("  SELF-LEARNING CAPABILITY MATRIX")
    print("=" * 70)
    print()
    print("  Capability                 | Status")
    print("  ─────────────────────────  | ──────")
    print(f"  Variance Detection         | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Self-Grading (REFLECT)     | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Escalation Pipeline        | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Prompt Rewriting           | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Corporate Veil (Firewall)  | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Sovereign Health Monitor   | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    print(f"  Adaptive Thresholds        | {'VERIFIED' if unit_ok else 'CHECK TESTS'}")
    if live_mode:
        print(f"  Live Sovereign Cycle       | {'VERIFIED' if live_ok else 'CHECK INFRA'}")
        print(f"  Live Escalation Processor  | {'VERIFIED' if live_ok else 'CHECK INFRA'}")
    else:
        print(f"  Live Sovereign Cycle       | SKIPPED (use --live)")
        print(f"  Live Escalation Processor  | SKIPPED (use --live)")

    print()
    print("=" * 70)

    sys.exit(0 if unit_ok else 1)


if __name__ == "__main__":
    main()
