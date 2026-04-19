"""
Tests for check_training_contamination in privilege_filter.py.

Covers:
  - Known-bad Feb 2026 ASSESSMENT block format (full separator pattern)
  - Individual internal metadata markers as fallback
  - Clean responses pass through without false positives
  - Training export filter: contaminated rows are skipped
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fortress-guest-platform"))
from backend.services.privilege_filter import check_training_contamination

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_CLEAN_GUEST_RESPONSE = """Dear [Guest's Name],

Thank you for your inquiry about Buckhorn Lodge!
The deck features pressure-treated pine boards with composite railings.

Best regards,
Taylor Knight
"""

_ASSESSMENT_BLOCK_RESPONSE = """\
**Response:**

Dear [Guest's Name],

Thank you for considering Fallen Timber Lodge for your special day!

---

**ASSESSMENT**

- **Risk Level:** Medium
- **Strategy Type:** Negotiation
- **Missing Information:** None
- **Citations Used:** FINANCIAL HARD CONSTRAINTS — Fallen Timber Lodge, Retrieved Context [5], [8]
"""

_MARKER_ONLY_RESPONSE = """\
Dear Guest,

Here is our recommendation.

**Risk Level:** Low
"""

_STRATEGY_TYPE_RESPONSE = """\
To address your booking:

**Strategy Type:** Direct

We can accommodate your request.
"""

_CITATIONS_USED_RESPONSE = """\
Based on our policy review:

**Citations Used:** Property Policy v3, Ops Override Memo

Your stay is confirmed.
"""

_BARE_ASSESSMENT_HEADER = """\
**ASSESSMENT**
- Risk: none
"""


# ---------------------------------------------------------------------------
# Tests: known-bad Feb 2026 ASSESSMENT format
# ---------------------------------------------------------------------------

class TestAssessmentBlockSeparator:
    def test_detects_full_separator_pattern(self):
        contaminated, reason = check_training_contamination("", _ASSESSMENT_BLOCK_RESPONSE)
        assert contaminated is True
        assert reason == "assessment_block_separator"

    def test_case_insensitive_separator(self):
        response = "\n---\n\n**assessment**\nsome content"
        contaminated, _ = check_training_contamination("", response)
        assert contaminated is True

    def test_separator_requires_double_newline(self):
        """'\n---\n**ASSESSMENT**' without the blank line should not match separator
        but may match the header marker fallback."""
        response = "\n---\n**ASSESSMENT**\nsome content"
        contaminated, _ = check_training_contamination("", response)
        # Falls through to marker check — should still be caught
        assert contaminated is True

    def test_prompt_content_does_not_affect_result(self):
        """Contamination is in the response, not the prompt."""
        contaminated, _ = check_training_contamination(
            "What does the deck look like?",
            _ASSESSMENT_BLOCK_RESPONSE,
        )
        assert contaminated is True


# ---------------------------------------------------------------------------
# Tests: individual metadata marker fallbacks
# ---------------------------------------------------------------------------

class TestInternalMetadataMarkers:
    def test_risk_level_marker(self):
        contaminated, reason = check_training_contamination("", _MARKER_ONLY_RESPONSE)
        assert contaminated is True
        assert "risk_level" in reason

    def test_strategy_type_marker(self):
        contaminated, reason = check_training_contamination("", _STRATEGY_TYPE_RESPONSE)
        assert contaminated is True
        assert "strategy_type" in reason

    def test_citations_used_marker(self):
        contaminated, reason = check_training_contamination("", _CITATIONS_USED_RESPONSE)
        assert contaminated is True
        assert "citations_used" in reason

    def test_bare_assessment_header(self):
        contaminated, reason = check_training_contamination("", _BARE_ASSESSMENT_HEADER)
        assert contaminated is True
        assert "assessment" in reason


# ---------------------------------------------------------------------------
# Tests: clean responses pass through
# ---------------------------------------------------------------------------

class TestCleanResponses:
    def test_normal_guest_response_is_clean(self):
        contaminated, reason = check_training_contamination("", _CLEAN_GUEST_RESPONSE)
        assert contaminated is False
        assert reason == ""

    def test_json_response_with_reasoning_field_is_clean(self):
        response = '{"cleaning_type": "turnover", "reasoning": "standard 3-night stay"}'
        contaminated, _ = check_training_contamination("", response)
        assert contaminated is False

    def test_response_with_markdown_hr_but_no_assessment_is_clean(self):
        response = "Summary:\n\n---\n\nConclusion: all good."
        contaminated, _ = check_training_contamination("", response)
        assert contaminated is False

    def test_empty_response_is_clean(self):
        contaminated, _ = check_training_contamination("", "")
        assert contaminated is False

    def test_prompt_containing_markers_does_not_flag_clean_response(self):
        """Markers in the prompt should not cause false positives on clean responses."""
        contaminated, _ = check_training_contamination(
            "Please assess the Risk Level of this situation.",
            _CLEAN_GUEST_RESPONSE,
        )
        assert contaminated is False

    def test_response_mentioning_assessment_in_plain_text_is_clean(self):
        """'assessment' as an ordinary word should not trigger contamination."""
        response = "Our risk assessment shows low probability of issues."
        contaminated, _ = check_training_contamination("", response)
        assert contaminated is False


# ---------------------------------------------------------------------------
# Tests: training export filter logic
# ---------------------------------------------------------------------------

class TestExportFilter:
    def _would_export(self, capture_metadata: dict | None) -> bool:
        """Mirrors the exporter WHERE clause logic in Python."""
        if capture_metadata is None:
            return True
        return capture_metadata.get("training_excluded") is not True

    def test_clean_capture_is_exported(self):
        assert self._would_export(None) is True
        assert self._would_export({}) is True
        assert self._would_export({"dedup_winner": True}) is True

    def test_excluded_capture_is_skipped(self):
        assert self._would_export({"training_excluded": True}) is False
        assert self._would_export({
            "training_excluded": True,
            "exclusion_reason": "pre-2026-03-01_assessment_block_leak",
        }) is False

    def test_dedup_winner_that_is_also_excluded_is_skipped(self):
        assert self._would_export({
            "dedup_winner": True,
            "training_excluded": True,
            "exclusion_reason": "pre-2026-03-01_assessment_block_leak",
        }) is False

    def test_string_true_does_not_skip(self):
        """DB returns the value as a boolean via jsonb; string 'true' is different."""
        assert self._would_export({"training_excluded": "true"}) is True
