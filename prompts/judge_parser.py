"""
Fortress Prime — Thunderdome Judge Output Parser
==================================================
Parses the structured verdict output from the Thunderdome Judge into
machine-readable data. Extracts scorecard, winner, findings, ruling,
action plan, and risk assessments.

Use this to:
  - Auto-tag contracts as "High Risk" (Pitbull wins) or "Safe" (Shield wins)
  - Feed structured verdicts into dashboards
  - Build datasets for legal analysis training
  - Validate Judge output in integration tests

Usage:
    from prompts.judge_parser import parse_verdict

    verdict = parse_verdict(judge_raw_output)
    print(verdict.winner)                  # "PROSECUTION" or "DEFENSE"
    print(verdict.scores["prosecution"])   # {"statutory_authority": 8, ...}
    print(verdict.prosecution_total)       # 38
    print(verdict.risk_level)              # "HIGH" or "LOW"
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class VerdictResult:
    """Parsed Thunderdome Judge verdict with full structured data."""
    winner: Optional[str] = None           # "PROSECUTION" or "DEFENSE"
    winner_reason: Optional[str] = None    # One-sentence reason
    prosecution_total: int = 0
    defense_total: int = 0
    scores: Dict[str, Dict[str, int]] = field(default_factory=dict)
    findings: Optional[str] = None
    ruling: Optional[str] = None
    action_plan: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    risk_level: str = "UNKNOWN"            # HIGH, MODERATE, LOW
    parse_success: bool = False
    parse_errors: List[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def margin(self) -> int:
        """Score difference between winner and loser."""
        return abs(self.prosecution_total - self.defense_total)

    @property
    def is_decisive(self) -> bool:
        """True if the margin is 5+ points (clear winner)."""
        return self.margin >= 5

    @property
    def is_close(self) -> bool:
        """True if the margin is 2 or fewer points."""
        return self.margin <= 2

    def to_dict(self) -> Dict[str, Any]:
        """Export as a flat dictionary for JSON logging or database storage."""
        return {
            "winner": self.winner,
            "winner_reason": self.winner_reason,
            "prosecution_total": self.prosecution_total,
            "defense_total": self.defense_total,
            "scores": self.scores,
            "findings": self.findings,
            "ruling": self.ruling,
            "action_plan": self.action_plan,
            "risks": self.risks,
            "risk_level": self.risk_level,
            "margin": self.margin,
            "is_decisive": self.is_decisive,
            "is_close": self.is_close,
            "parse_success": self.parse_success,
            "parse_errors": self.parse_errors,
        }


# =============================================================================
# SCORE CRITERIA (must match thunderdome_judge.yaml rubric)
# =============================================================================

CRITERIA_NAMES = [
    "statutory_authority",
    "logical_coherence",
    "practical_viability",
    "risk_assessment",
    "strategic_value",
]

CRITERIA_PATTERNS = [
    (r'statutory\s*authority', "statutory_authority"),
    (r'logical\s*coherence', "logical_coherence"),
    (r'practical\s*viability', "practical_viability"),
    (r'risk\s*assessment', "risk_assessment"),
    (r'strategic\s*value', "strategic_value"),
]


# =============================================================================
# PARSER
# =============================================================================

def parse_verdict(raw_text: str) -> VerdictResult:
    """
    Parse the raw Judge output into a structured VerdictResult.

    Handles variations in formatting — the LLM won't always produce
    pixel-perfect markdown, so we use fuzzy regex matching.

    Args:
        raw_text: The raw text output from the Thunderdome Judge.

    Returns:
        VerdictResult with all parsed fields and parse_success flag.
    """
    result = VerdictResult(raw_text=raw_text)

    if not raw_text or len(raw_text.strip()) < 50:
        result.parse_errors.append("Output too short or empty")
        return result

    text = raw_text.strip()

    # --- 1. Extract WINNER ---
    _parse_winner(text, result)

    # --- 2. Extract SCORECARD ---
    _parse_scorecard(text, result)

    # --- 3. Extract FINDINGS ---
    _parse_section(text, result, "findings",
                   [r'##\s*FINDINGS', r'FINDINGS\s*:?\s*\n'])

    # --- 4. Extract RULING ---
    _parse_section(text, result, "ruling",
                   [r'##\s*RULING', r'RULING\s*:?\s*\n'])

    # --- 5. Extract ACTION PLAN ---
    _parse_action_plan(text, result)

    # --- 6. Extract RISKS ---
    _parse_risks(text, result)

    # --- 7. Determine risk level ---
    if result.winner == "PROSECUTION":
        if result.prosecution_total >= 40:
            result.risk_level = "HIGH"
        elif result.prosecution_total >= 30:
            result.risk_level = "MODERATE"
        else:
            result.risk_level = "LOW"
    elif result.winner == "DEFENSE":
        if result.defense_total >= 40:
            result.risk_level = "LOW"
        elif result.defense_total >= 30:
            result.risk_level = "MODERATE"
        else:
            result.risk_level = "HIGH"

    # --- Overall parse success ---
    result.parse_success = (
        result.winner is not None
        and result.prosecution_total > 0
        and result.defense_total > 0
    )

    return result


def _parse_winner(text: str, result: VerdictResult):
    """Extract the WINNER declaration."""
    patterns = [
        r'##\s*WINNER\s*:\s*(PROSECUTION|DEFENSE)',
        r'WINNER\s*:\s*(PROSECUTION|DEFENSE)',
        r'\*\*WINNER\*\*\s*:\s*(PROSECUTION|DEFENSE)',
        r'The\s+winner\s+is\s+(PROSECUTION|DEFENSE)',
        r'(?:wins?|prevails?|victory\s+for)\s+(?:the\s+)?(PROSECUTION|DEFENSE)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result.winner = match.group(1).upper()
            # Try to get the reason (sentence after the winner line)
            after_match = text[match.end():]
            reason_match = re.match(r'\s*\n\s*(.+?)(?:\n|$)', after_match)
            if reason_match:
                reason = reason_match.group(1).strip()
                if len(reason) > 10 and not reason.startswith("#"):
                    result.winner_reason = reason
            return

    result.parse_errors.append("Could not extract WINNER")


def _parse_scorecard(text: str, result: VerdictResult):
    """Extract scores from the SCORECARD table."""
    result.scores = {"prosecution": {}, "defense": {}}

    # Strategy 1: Parse markdown table rows
    # Look for rows like: | Statutory Authority | 8/10 | 7/10 |
    for criteria_pattern, criteria_name in CRITERIA_PATTERNS:
        row_pattern = (
            r'\|\s*' + criteria_pattern + r'\s*\|'
            r'\s*(\d{1,2})\s*/\s*10\s*\|'
            r'\s*(\d{1,2})\s*/\s*10\s*\|'
        )
        match = re.search(row_pattern, text, re.IGNORECASE)
        if match:
            result.scores["prosecution"][criteria_name] = int(match.group(1))
            result.scores["defense"][criteria_name] = int(match.group(2))
            continue

        # Strategy 2: Look for inline formats like "Statutory Authority: Prosecution 8, Defense 7"
        inline_pattern = (
            criteria_pattern + r'[:\s]+(?:prosecution|pitbull)\s*[:\-=]?\s*(\d{1,2})'
            r'.*?(?:defense|shield)\s*[:\-=]?\s*(\d{1,2})'
        )
        match = re.search(inline_pattern, text, re.IGNORECASE)
        if match:
            result.scores["prosecution"][criteria_name] = int(match.group(1))
            result.scores["defense"][criteria_name] = int(match.group(2))

    # Calculate totals
    result.prosecution_total = sum(result.scores.get("prosecution", {}).values())
    result.defense_total = sum(result.scores.get("defense", {}).values())

    # Strategy 3: If individual scores failed, try to find the TOTAL row
    if result.prosecution_total == 0:
        total_pattern = (
            r'\|\s*\*?\*?TOTAL\*?\*?\s*\|\s*\*?\*?(\d{1,2})\s*/\s*50\*?\*?\s*\|'
            r'\s*\*?\*?(\d{1,2})\s*/\s*50\*?\*?\s*\|'
        )
        match = re.search(total_pattern, text, re.IGNORECASE)
        if match:
            result.prosecution_total = int(match.group(1))
            result.defense_total = int(match.group(2))
        else:
            result.parse_errors.append("Could not extract scores from SCORECARD")


def _parse_section(text: str, result: VerdictResult, field_name: str,
                   header_patterns: list):
    """Extract a named section's content."""
    for pattern in header_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Get text until next ## header or end
            after = text[match.end():]
            next_header = re.search(r'\n##\s', after)
            section_text = after[:next_header.start()] if next_header else after
            section_text = section_text.strip()
            if section_text:
                setattr(result, field_name, section_text)
                return

    result.parse_errors.append(f"Could not extract {field_name.upper()}")


def _parse_action_plan(text: str, result: VerdictResult):
    """Extract numbered action items from ACTION PLAN section."""
    # Find the ACTION PLAN section
    match = re.search(r'(?:##\s*)?ACTION\s*PLAN\s*:?\s*\n', text, re.IGNORECASE)
    if not match:
        result.parse_errors.append("Could not extract ACTION PLAN")
        return

    after = text[match.end():]
    next_header = re.search(r'\n##\s', after)
    section = after[:next_header.start()] if next_header else after

    # Extract numbered items
    items = re.findall(r'\d+\.\s*(.+?)(?=\n\d+\.|\n##|\n\n|$)', section, re.DOTALL)
    result.action_plan = [item.strip() for item in items if item.strip()]

    # Fallback: look for bullet points
    if not result.action_plan:
        items = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n##|\n\n|$)', section, re.DOTALL)
        result.action_plan = [item.strip() for item in items if item.strip()]


def _parse_risks(text: str, result: VerdictResult):
    """Extract risk items from RISKS & WARNINGS section."""
    match = re.search(r'(?:##\s*)?RISKS?\s*(?:&|AND)?\s*WARNINGS?\s*:?\s*\n',
                      text, re.IGNORECASE)
    if not match:
        # Also try just "RISKS"
        match = re.search(r'(?:##\s*)?RISKS?\s*:?\s*\n', text, re.IGNORECASE)
    if not match:
        return  # Risks section is optional

    after = text[match.end():]
    next_header = re.search(r'\n##\s', after)
    section = after[:next_header.start()] if next_header else after

    # Extract bullet items
    items = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n##|\n\n|$)', section, re.DOTALL)
    result.risks = [item.strip() for item in items if item.strip()]

    # Fallback: numbered items
    if not result.risks:
        items = re.findall(r'\d+\.\s*(.+?)(?=\n\d+\.|\n##|\n\n|$)', section, re.DOTALL)
        result.risks = [item.strip() for item in items if item.strip()]


# =============================================================================
# CLI: python -m prompts.judge_parser
# =============================================================================

if __name__ == "__main__":
    # Test with a sample Judge output
    sample_output = """
## SCORECARD

| Criteria             | Prosecution | Defense |
|----------------------|-------------|---------|
| Statutory Authority  |    8/10     |  6/10   |
| Logical Coherence    |    7/10     |  7/10   |
| Practical Viability  |    9/10     |  5/10   |
| Risk Assessment      |    6/10     |  8/10   |
| Strategic Value      |    8/10     |  6/10   |
| **TOTAL**            |  **38/50**  | **32/50** |

## WINNER: PROSECUTION

The prosecution prevailed with stronger statutory citations and a more actionable strategy, particularly on practical viability.

## FINDINGS

The Pitbull presented a compelling case grounded in O.C.G.A. Title 44 regarding landlord-tenant obligations. The citation of § 44-7-14 (duty to maintain premises) was directly applicable. The Shield's defense, while technically sound on procedural grounds, failed to address the core statutory obligation.

## RULING

The client should proceed with formal notice under O.C.G.A. § 44-7-50 and prepare for dispossessory proceedings if the tenant does not vacate within 30 days.

## ACTION PLAN

1. [Immediate] Send certified letter with formal 30-day notice citing O.C.G.A. § 44-7-50.
2. [2 weeks] If no response, retain local counsel to file dispossessory affidavit.
3. [30 days] If tenant remains, proceed with court filing in Fannin County Magistrate Court.
4. [Contingency] If tenant claims hardship, negotiate a move-out agreement with a 15-day extension.

## RISKS & WARNINGS

- Risk 1: Tenant may claim retaliatory eviction under O.C.G.A. § 44-7-24. Mitigation: Document all maintenance requests and responses.
- Risk 2: Court backlog in Fannin County may delay proceedings 2-4 weeks. Mitigation: File early and request expedited hearing.
- Risk 3: Property damage during vacancy period. Mitigation: Schedule property inspection within 24 hours of vacancy.
"""

    print("=" * 60)
    print("  THUNDERDOME — JUDGE OUTPUT PARSER TEST")
    print("=" * 60)

    v = parse_verdict(sample_output)

    print(f"\n  Parse Success: {v.parse_success}")
    print(f"  Winner:        {v.winner} (margin: {v.margin} pts)")
    print(f"  Risk Level:    {v.risk_level}")
    print(f"  Decisive:      {v.is_decisive}")
    print(f"  Close:         {v.is_close}")

    print(f"\n  SCORES:")
    print(f"  {'Criteria':<25} {'Prosecution':>12} {'Defense':>12}")
    print(f"  {'-'*50}")
    for crit in CRITERIA_NAMES:
        p = v.scores.get("prosecution", {}).get(crit, "?")
        d = v.scores.get("defense", {}).get(crit, "?")
        print(f"  {crit.replace('_', ' ').title():<25} {str(p)+'/10':>12} {str(d)+'/10':>12}")
    print(f"  {'TOTAL':<25} {str(v.prosecution_total)+'/50':>12} {str(v.defense_total)+'/50':>12}")

    print(f"\n  ACTION PLAN ({len(v.action_plan)} items):")
    for i, item in enumerate(v.action_plan, 1):
        print(f"    {i}. {item[:80]}")

    print(f"\n  RISKS ({len(v.risks)} items):")
    for risk in v.risks:
        print(f"    - {risk[:80]}")

    if v.parse_errors:
        print(f"\n  PARSE ERRORS:")
        for err in v.parse_errors:
            print(f"    ! {err}")

    print(f"\n{'=' * 60}")
