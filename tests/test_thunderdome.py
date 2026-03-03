"""
Fortress Prime — Thunderdome Integration Test
===============================================
Feeds intentionally "bad" contracts through the full adversarial pipeline
to verify that:
  1. The Pitbull catches violations.
  2. The Shield mounts a defense.
  3. The Judge produces a valid scorecard with a clear winner.
  4. The output parser correctly extracts structured data.

Two test modes:
  --offline   Uses synthetic Judge output (no LLM required). Tests the parser.
  --live      Sends a real case through the Ollama pipeline (requires running cluster).

Usage:
    python tests/test_thunderdome.py              # Offline parser tests only
    python tests/test_thunderdome.py --live        # Full LLM integration test
    python tests/test_thunderdome.py --all         # Both offline and live
"""

import os
import sys
import time
import json
import re

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompts.loader import load_prompt, log_prompt_execution
from prompts.judge_parser import parse_verdict, VerdictResult, CRITERIA_NAMES
from prompts.tone_detector import detect_tone


# =============================================================================
# TEST CASES — Intentionally Bad Contracts
# =============================================================================

BAD_CONTRACTS = [
    {
        "name": "Illegal Eviction Without Notice",
        "scenario": (
            "Property manager changed the locks on a rental cabin while guests "
            "were out hiking, moved their belongings to the porch, and texted "
            "them 'You're out. Don't come back.' No formal notice was given. "
            "No refund was issued. Guests had 3 nights remaining on a paid "
            "7-night reservation."
        ),
        "expected_winner": "PROSECUTION",
        "expected_risk_level": "HIGH",
        "reason": "Illegal lockout violates O.C.G.A. § 44-7-14.1. Self-help eviction is prohibited."
    },
    {
        "name": "Contractor Fraud — Unlicensed Work",
        "scenario": (
            "A contractor was hired to renovate the deck at Buckhorn Lodge for "
            "$28,000. The contractor demanded full payment upfront, performed "
            "only 20% of the work using substandard materials (pressure-treated "
            "pine instead of specified composite), then stopped responding to "
            "calls. The contractor has no valid Georgia contractor's license. "
            "No written contract with scope of work exists — only a text message "
            "agreement."
        ),
        "expected_winner": "PROSECUTION",
        "expected_risk_level": "HIGH",
        "reason": "Unlicensed contracting violates O.C.G.A. § 43-41-17. Fraud elements present."
    },
    {
        "name": "Guest Slip-and-Fall — Properly Maintained",
        "scenario": (
            "A guest slipped on wet stairs at Rivers Edge cabin during a rainstorm "
            "and broke their ankle. The property has non-slip treads on all stairs, "
            "motion-activated lighting, and a 'Caution: Wet When Raining' sign posted "
            "at eye level. The guest was wearing leather-soled dress shoes. The property "
            "has passed all county safety inspections. The guest is threatening to sue "
            "for $200,000 in damages."
        ),
        "expected_winner": "DEFENSE",
        "expected_risk_level": "LOW",
        "reason": "Property met duty of care. Comparative negligence likely applies (O.C.G.A. § 51-11-7)."
    },
]


# =============================================================================
# SYNTHETIC JUDGE OUTPUTS (For Offline Testing)
# =============================================================================

SYNTHETIC_VERDICTS = {
    "prosecution_wins_clean": """
## SCORECARD

| Criteria             | Prosecution | Defense |
|----------------------|-------------|---------|
| Statutory Authority  |    9/10     |  4/10   |
| Logical Coherence    |    8/10     |  6/10   |
| Practical Viability  |    8/10     |  5/10   |
| Risk Assessment      |    7/10     |  6/10   |
| Strategic Value      |    9/10     |  5/10   |
| **TOTAL**            |  **41/50**  | **26/50** |

## WINNER: PROSECUTION

The prosecution dominated with overwhelming statutory authority and a highly actionable strategy.

## FINDINGS

The Pitbull correctly identified the core violation: O.C.G.A. § 44-7-14.1 explicitly prohibits self-help eviction. The lockout was conducted without any formal legal process — no dispossessory affidavit, no court order, no 30-day notice. This is textbook illegal eviction.

The Shield attempted to argue implied consent through the text message, but this defense is legally frivolous. Georgia law requires written notice under § 44-7-50, and a text message saying "You're out" does not constitute lawful notice.

## RULING

The client (guest) should file a complaint for illegal eviction under O.C.G.A. § 44-7-14.1. They are entitled to actual damages (remaining nights x nightly rate), plus potential punitive damages for the willful nature of the lockout.

## ACTION PLAN

1. [Immediate] Document all evidence: screenshots of texts, photos of belongings on porch, receipts for alternative lodging.
2. [Within 1 week] File formal complaint with the Fannin County Magistrate Court.
3. [Within 30 days] Retain counsel to pursue civil damages including treble damages under Georgia's FBPA.
4. [Contingency] If property manager retaliates or destroys belongings, file for emergency protective order.

## RISKS & WARNINGS

- Risk 1: Property manager may claim the guests violated the rental agreement first. Mitigation: Obtain copy of the agreement and review for any breach clauses.
- Risk 2: Small claims limit in Georgia is $15,000. If damages exceed this, case must move to State Court. Mitigation: Calculate total damages before filing to choose the correct court.
""",

    "defense_wins_clean": """
## SCORECARD

| Criteria             | Prosecution | Defense |
|----------------------|-------------|---------|
| Statutory Authority  |    5/10     |  8/10   |
| Logical Coherence    |    4/10     |  9/10   |
| Practical Viability  |    3/10     |  8/10   |
| Risk Assessment      |    6/10     |  7/10   |
| Strategic Value      |    4/10     |  8/10   |
| **TOTAL**            |  **22/50**  | **40/50** |

## WINNER: DEFENSE

The defense prevailed decisively. The property met all legal duties of care, and comparative negligence heavily favors the property owner.

## FINDINGS

The Shield demonstrated that the property owner fulfilled every reasonable duty of care: non-slip treads, motion lighting, visible warning signage, and current county inspection certifications. Under O.C.G.A. § 51-3-1, a premises owner's duty extends only to maintaining the property in a reasonably safe condition — which was clearly done.

The Pitbull's argument that the property should have "closed the stairs during rain" is legally unsupported and practically unreasonable. Georgia applies a comparative negligence standard (O.C.G.A. § 51-11-7), and the guest's choice of inappropriate footwear on a rainy day significantly contributed to the injury.

## RULING

The property owner should deny liability and prepare a defense based on comparative negligence. The $200,000 demand is disproportionate and unlikely to survive judicial scrutiny.

## ACTION PLAN

1. [Immediate] Preserve all maintenance records, inspection reports, and photos of safety features.
2. [Within 1 week] Respond to the demand letter denying liability and citing the safety measures in place.
3. [Within 30 days] If a lawsuit is filed, retain counsel and file an answer asserting comparative negligence.
4. [Contingency] Consider a nuisance settlement of $5,000-$10,000 only if the cost of litigation would exceed this amount.

## RISKS & WARNINGS

- Risk 1: Guest may find an aggressive plaintiff's attorney willing to take the case on contingency. Mitigation: Strong evidence of safety compliance makes this case unattractive for contingency firms.
- Risk 2: Jury sympathy for an injured person could override the legal merits. Mitigation: Request bench trial or file for summary judgment based on undisputed safety measures.
""",

    "malformed_output": """
The prosecution made some good points but the defense also had merit.

I think the prosecution wins but I'm not sure. The scores would be roughly:
Prosecution: 35
Defense: 30

They should probably talk to a lawyer.
""",

    "partial_scorecard": """
## SCORECARD

| Criteria             | Prosecution | Defense |
|----------------------|-------------|---------|
| Statutory Authority  |    7/10     |  6/10   |
| Logical Coherence    |    7/10     |  7/10   |

## WINNER: PROSECUTION

Prosecution edged ahead on statutory authority.

## FINDINGS

Both sides made reasonable arguments. The prosecution's citations were more specific.

## RULING

Proceed with caution. Consult local counsel.
""",
}


# =============================================================================
# OFFLINE TESTS (Parser Verification)
# =============================================================================

def test_parser_prosecution_wins():
    """Test: Parser correctly handles a clean prosecution victory."""
    v = parse_verdict(SYNTHETIC_VERDICTS["prosecution_wins_clean"])

    errors = []
    if v.winner != "PROSECUTION":
        errors.append(f"Winner: expected PROSECUTION, got {v.winner}")
    if v.prosecution_total != 41:
        errors.append(f"Prosecution total: expected 41, got {v.prosecution_total}")
    if v.defense_total != 26:
        errors.append(f"Defense total: expected 26, got {v.defense_total}")
    if not v.is_decisive:
        errors.append(f"Expected decisive victory (margin={v.margin})")
    if v.risk_level != "HIGH":
        errors.append(f"Risk level: expected HIGH, got {v.risk_level}")
    if not v.parse_success:
        errors.append(f"Parse failed: {v.parse_errors}")
    if len(v.action_plan) < 3:
        errors.append(f"Action plan: expected 3+ items, got {len(v.action_plan)}")
    if len(v.risks) < 2:
        errors.append(f"Risks: expected 2+ items, got {len(v.risks)}")

    # Check individual scores
    expected_scores = {
        "statutory_authority": 9,
        "logical_coherence": 8,
        "practical_viability": 8,
        "risk_assessment": 7,
        "strategic_value": 9,
    }
    for crit, expected in expected_scores.items():
        actual = v.scores.get("prosecution", {}).get(crit)
        if actual != expected:
            errors.append(f"Score {crit}: expected {expected}, got {actual}")

    return "prosecution_wins_clean", errors


def test_parser_defense_wins():
    """Test: Parser correctly handles a clean defense victory."""
    v = parse_verdict(SYNTHETIC_VERDICTS["defense_wins_clean"])

    errors = []
    if v.winner != "DEFENSE":
        errors.append(f"Winner: expected DEFENSE, got {v.winner}")
    if v.defense_total != 40:
        errors.append(f"Defense total: expected 40, got {v.defense_total}")
    if v.prosecution_total != 22:
        errors.append(f"Prosecution total: expected 22, got {v.prosecution_total}")
    if v.risk_level != "LOW":
        errors.append(f"Risk level: expected LOW, got {v.risk_level}")
    if not v.is_decisive:
        errors.append(f"Expected decisive victory (margin={v.margin})")
    if not v.parse_success:
        errors.append(f"Parse failed: {v.parse_errors}")
    if not v.findings:
        errors.append("Missing FINDINGS section")
    if not v.ruling:
        errors.append("Missing RULING section")

    return "defense_wins_clean", errors


def test_parser_malformed():
    """Test: Parser gracefully handles malformed output."""
    v = parse_verdict(SYNTHETIC_VERDICTS["malformed_output"])

    errors = []
    # Should NOT parse successfully — no proper scorecard
    if v.parse_success:
        errors.append("Should NOT have parsed successfully (no scorecard)")
    if len(v.parse_errors) == 0:
        errors.append("Should have recorded parse errors")

    return "malformed_output", errors


def test_parser_partial():
    """Test: Parser handles a partial scorecard (only 2 criteria filled)."""
    v = parse_verdict(SYNTHETIC_VERDICTS["partial_scorecard"])

    errors = []
    if v.winner != "PROSECUTION":
        errors.append(f"Winner: expected PROSECUTION, got {v.winner}")
    # Should parse but with incomplete scores
    if v.prosecution_total == 0:
        errors.append("Should have extracted at least partial scores")

    return "partial_scorecard", errors


def test_parser_to_dict():
    """Test: VerdictResult.to_dict() produces valid serializable output."""
    v = parse_verdict(SYNTHETIC_VERDICTS["prosecution_wins_clean"])
    d = v.to_dict()

    errors = []
    try:
        json.dumps(d)
    except (TypeError, ValueError) as e:
        errors.append(f"to_dict() not JSON-serializable: {e}")

    required_keys = ["winner", "prosecution_total", "defense_total", "risk_level",
                     "margin", "is_decisive", "parse_success"]
    for key in required_keys:
        if key not in d:
            errors.append(f"Missing key in to_dict(): {key}")

    return "to_dict_serialization", errors


# =============================================================================
# TONE DETECTOR TESTS
# =============================================================================

def test_tone_detector():
    """Test: Tone detector correctly classifies email urgency."""
    test_cases = [
        ("Help! The pipes burst!", "emergency"),
        ("We're locked out and it's freezing", "emergency"),
        ("There's a gas smell", "emergency"),
        ("The cabin was dirty and disgusting", "complaint"),
        ("WiFi doesn't work. Very disappointed.", "complaint"),
        ("I want a refund", "complaint"),
        ("Celebrating our anniversary!", "vip"),
        ("Planning to propose to my girlfriend", "vip"),
        ("What time is check-in?", "standard"),
        ("Do you have a grill?", "standard"),
    ]

    errors = []
    for email, expected_tone in test_cases:
        result = detect_tone(email)
        if result.tone != expected_tone:
            errors.append(f"  Email: \"{email[:50]}...\"\n"
                          f"    Expected: {expected_tone}, Got: {result.tone} "
                          f"(triggers: {result.triggered_keywords[:3]})")

    return "tone_detector", errors


# =============================================================================
# TEMPLATE LOADING TESTS
# =============================================================================

def test_template_loading():
    """Test: All templates load and render without errors."""
    from prompts.loader import list_prompts

    errors = []
    for name in list_prompts():
        try:
            tmpl = load_prompt(name)
            # Static templates should render with no args
            if not tmpl.variables:
                rendered = tmpl.render()
                if len(rendered.strip()) < 10:
                    errors.append(f"{name}: rendered output too short ({len(rendered)} chars)")
        except Exception as e:
            errors.append(f"{name}: {e}")

    return "template_loading", errors


def test_guest_email_with_tone():
    """Test: Guest email template renders correctly with all three tone levels."""
    tmpl = load_prompt("guest_email_reply")
    errors = []

    for tone in ["Polite and helpful", "Apologetic, empathetic, and urgent", "Warm, celebratory"]:
        try:
            rendered = tmpl.render(
                cabin_context="3BR cabin, hot tub, WiFi, pet-friendly",
                guest_email="Test email",
                tone_modifier=tone,
                dynamic_examples="(No proven examples for this topic yet.)",
            )
            if tone not in rendered:
                errors.append(f"Tone '{tone[:30]}...' not found in rendered output")
            if "PROVEN EXAMPLES" not in rendered:
                errors.append(f"Dynamic examples section missing from rendered output")
        except Exception as e:
            errors.append(f"Render failed with tone '{tone[:30]}...': {e}")

    return "guest_email_tone_render", errors


# =============================================================================
# LIVE INTEGRATION TEST (Requires Running Cluster)
# =============================================================================

def test_live_thunderdome(scenario_index: int = 0):
    """
    LIVE TEST: Send a bad contract through the full Thunderdome pipeline.
    Requires Ollama running on localhost:11434 with deepseek-r1:8b loaded.

    This test verifies the complete flow:
      Bad Contract -> Pitbull -> Shield -> Judge -> Parser -> Verdict
    """
    import requests

    case = BAD_CONTRACTS[scenario_index]

    print(f"\n{'=' * 60}")
    print(f"  LIVE THUNDERDOME TEST: {case['name']}")
    print(f"  Expected Winner: {case['expected_winner']}")
    print(f"{'=' * 60}")

    # Check if Ollama is reachable
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code != 200:
            return case["name"], ["Ollama not responding (HTTP {r.status_code})"]
    except Exception:
        return case["name"], ["Ollama not reachable at localhost:11434. Use --offline instead."]

    R1_URL = "http://localhost:11434/api/generate"
    R1_MODEL = "deepseek-r1:8b"

    def call_llm(system_prompt, task):
        prompt = f"[SYSTEM]\n{system_prompt}\n\n[CASE / TASK]\n{task}"
        payload = {
            "model": R1_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1500}
        }
        res = requests.post(R1_URL, json=payload, timeout=300)
        response = res.json().get("response", "")
        if "<think>" in response:
            parts = response.split("</think>")
            response = parts[-1].strip() if len(parts) > 1 else response
        return response

    errors = []

    # --- Round 1: Pitbull ---
    print("\n  [1/4] Pitbull attacking...")
    pitbull_prompt = load_prompt("thunderdome_pitbull").render()
    t0 = time.time()
    pitbull_output = call_llm(
        pitbull_prompt,
        f"Present your prosecution case:\n\n{case['scenario']}"
    )
    pitbull_ms = (time.time() - t0) * 1000
    print(f"         Done ({pitbull_ms:.0f}ms, {len(pitbull_output)} chars)")

    if len(pitbull_output) < 100:
        errors.append(f"Pitbull output too short ({len(pitbull_output)} chars)")

    log_prompt_execution(
        template_name="thunderdome_pitbull",
        variables={"scenario": case["scenario"][:200]},
        rendered_prompt=pitbull_prompt,
        raw_output=pitbull_output,
        model_name=R1_MODEL,
        duration_ms=pitbull_ms,
        metadata={"test": case["name"]},
    )

    # --- Round 2: Shield ---
    print("  [2/4] Shield defending...")
    shield_prompt = load_prompt("thunderdome_shield").render()
    t0 = time.time()
    shield_output = call_llm(
        shield_prompt,
        f"The Prosecution argued:\n\n{pitbull_output}\n\nDestroy their argument."
    )
    shield_ms = (time.time() - t0) * 1000
    print(f"         Done ({shield_ms:.0f}ms, {len(shield_output)} chars)")

    if len(shield_output) < 100:
        errors.append(f"Shield output too short ({len(shield_output)} chars)")

    log_prompt_execution(
        template_name="thunderdome_shield",
        variables={"scenario": case["scenario"][:200]},
        rendered_prompt=shield_prompt,
        raw_output=shield_output,
        model_name=R1_MODEL,
        duration_ms=shield_ms,
        metadata={"test": case["name"]},
    )

    # --- Round 3: Judge ---
    print("  [3/4] Judge deliberating...")
    judge_prompt = load_prompt("thunderdome_judge").render()
    full_debate = (
        f"PROSECUTION:\n{pitbull_output}\n\n"
        f"DEFENSE:\n{shield_output}"
    )
    t0 = time.time()
    judge_output = call_llm(
        judge_prompt,
        f"Case: {case['scenario']}\n\nDebate transcript:\n\n{full_debate}\n\n"
        f"Score both sides and deliver your verdict."
    )
    judge_ms = (time.time() - t0) * 1000
    print(f"         Done ({judge_ms:.0f}ms, {len(judge_output)} chars)")

    log_prompt_execution(
        template_name="thunderdome_judge",
        variables={"scenario": case["scenario"][:200]},
        rendered_prompt=judge_prompt,
        raw_output=judge_output,
        model_name=R1_MODEL,
        duration_ms=judge_ms,
        metadata={"test": case["name"]},
    )

    # --- Round 4: Parse Verdict ---
    print("  [4/4] Parsing verdict...")
    verdict = parse_verdict(judge_output)

    print(f"\n  RESULTS:")
    print(f"  Parse Success:    {verdict.parse_success}")
    print(f"  Winner:           {verdict.winner or '(not extracted)'}")
    print(f"  Expected Winner:  {case['expected_winner']}")
    print(f"  Prosecution:      {verdict.prosecution_total}/50")
    print(f"  Defense:          {verdict.defense_total}/50")
    print(f"  Margin:           {verdict.margin} pts")
    print(f"  Risk Level:       {verdict.risk_level}")
    print(f"  Action Items:     {len(verdict.action_plan)}")
    print(f"  Risks Identified: {len(verdict.risks)}")

    if verdict.parse_errors:
        print(f"  Parse Warnings:   {verdict.parse_errors}")

    # Validate expected outcome
    if verdict.winner != case["expected_winner"]:
        errors.append(
            f"Winner mismatch: expected {case['expected_winner']}, "
            f"got {verdict.winner} "
            f"(P:{verdict.prosecution_total} vs D:{verdict.defense_total})"
        )

    if not verdict.parse_success:
        errors.append(f"Judge output failed to parse: {verdict.parse_errors}")

    total_ms = pitbull_ms + shield_ms + judge_ms
    print(f"\n  Total pipeline time: {total_ms:.0f}ms ({total_ms/1000:.1f}s)")

    return f"LIVE: {case['name']}", errors


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_tests(include_live: bool = False):
    """Run all tests and report results."""
    print("=" * 60)
    print("  FORTRESS PRIME — THUNDERDOME TEST SUITE")
    print("=" * 60)

    # Collect offline tests
    tests = [
        test_parser_prosecution_wins,
        test_parser_defense_wins,
        test_parser_malformed,
        test_parser_partial,
        test_parser_to_dict,
        test_tone_detector,
        test_template_loading,
        test_guest_email_with_tone,
    ]

    results = []
    passed = 0
    failed = 0

    # Run offline tests
    print(f"\n  OFFLINE TESTS ({len(tests)} tests)")
    print(f"  {'─' * 50}")

    for test_fn in tests:
        name, errors = test_fn()
        if errors:
            failed += 1
            print(f"  [FAIL] {name}")
            for err in errors:
                print(f"         {err}")
        else:
            passed += 1
            print(f"  [PASS] {name}")
        results.append((name, errors))

    # Run live tests if requested
    if include_live:
        print(f"\n  LIVE INTEGRATION TESTS ({len(BAD_CONTRACTS)} scenarios)")
        print(f"  {'─' * 50}")

        for i, case in enumerate(BAD_CONTRACTS):
            name, errors = test_live_thunderdome(scenario_index=i)
            if errors:
                failed += 1
                print(f"\n  [FAIL] {name}")
                for err in errors:
                    print(f"         {err}")
            else:
                passed += 1
                print(f"\n  [PASS] {name}")
            results.append((name, errors))

    # Summary
    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print(f"  STATUS: ALL TESTS PASSED")
    else:
        print(f"  STATUS: {failed} FAILURE(S)")
    print(f"{'=' * 60}")

    return failed == 0


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    if "--live" in sys.argv:
        run_tests(include_live=True)
    elif "--all" in sys.argv:
        run_tests(include_live=True)
    else:
        run_tests(include_live=False)
