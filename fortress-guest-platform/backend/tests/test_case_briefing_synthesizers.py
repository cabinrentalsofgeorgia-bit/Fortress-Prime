"""Tests for case_briefing_synthesizers — focused on Phase B v0.2 Pass 1
reasoning-trace stripping. The synthesis-call path itself (BRAIN streaming,
citation detection, defense-counsel exclusion) is exercised end-to-end by
the dry-run smoke documented in `docs/operational/phase-b-v0.1-dry-run-2026-04-29.md`
and the Phase A PR #2 cutover smoke; this file isolates the deterministic
text-cleanup primitive.
"""
from __future__ import annotations

import pytest

from backend.services.case_briefing_synthesizers import strip_reasoning_trace


class TestStripReasoningTrace:
    """Pass 1 — strip <think>...</think> blocks. First-person prose handling
    outside the tags is intentionally out of scope; Pass 2 (if needed) is a
    separate brief."""

    def test_strips_simple_think_block(self):
        # Smallest synthetic case.
        body = "<think>I should write this section.</think>\n\nThe result body."
        out = strip_reasoning_trace(body)
        assert "<think>" not in out
        assert "</think>" not in out
        assert "I should write this section." not in out
        assert out == "The result body."

    def test_strips_multiline_think_block(self):
        # Real fixture from PR #311 Phase A cutover smoke (Section 2 Critical
        # Timeline). The trace spans many lines and contains the model's
        # working memory before it produced the actual table.
        body = (
            "<think>\n"
            "Okay, let's tackle this. The user wants a chronological timeline of dated events from the case evidence provided. I need to go through each evidence block and extract any dates mentioned, then organize them in order.\n"
            "\n"
            "Starting with the first evidence block, [2022.01.04 Pl's Initial Disclosures.pdf], there's a mention of March 14, 2021, when 7 IL Properties and Gary Knight entered into a contract for 253 River Heights Road. Then April 5, 2021, for the 92 Fish Trap Road agreement.\n"
            "</think>\n"
            "\n"
            "| Date | Event | Source |\n"
            "|------|-------|--------|\n"
            "| 2021-03-14 | Contract executed for 253 River Heights Road | [2022.01.04 Pl's Initial Disclosures.pdf] |\n"
        )
        out = strip_reasoning_trace(body)
        assert "<think>" not in out
        assert "</think>" not in out
        assert "Okay, let's tackle this" not in out
        assert "I need to go through" not in out
        # Substantive content preserved.
        assert "| Date | Event | Source |" in out
        assert "2021-03-14" in out
        assert "[2022.01.04 Pl's Initial Disclosures.pdf]" in out

    def test_strips_multiple_think_blocks(self):
        # BRAIN occasionally emits multiple traces per response (mid-section
        # self-correction). Each must be stripped independently — greedy on
        # the *nearest* close tag, not on document end.
        body = (
            "<think>First trace — planning the table.</think>\n"
            "\n"
            "Section header.\n"
            "\n"
            "<think>Second trace — checking the citation format.</think>\n"
            "\n"
            "Final body line.\n"
        )
        out = strip_reasoning_trace(body)
        assert out.count("<think>") == 0
        assert out.count("</think>") == 0
        assert "First trace" not in out
        assert "Second trace" not in out
        assert "Section header." in out
        assert "Final body line." in out

    def test_handles_unclosed_think_tag(self):
        # Truncated stream — BRAIN ran out of tokens mid-trace OR the stream
        # cut before </think>. Strip from <think> to the next blank line
        # (double-newline) or end of text. The substantive body that follows
        # the blank line must be preserved.
        body = (
            "Existing prose above the trace.\n"
            "\n"
            "<think>\n"
            "Now I need to think about how to phrase this carefully — the user wants a clean response so I should\n"
            "\n"
            "Actual final body that survived after the truncated trace.\n"
        )
        out = strip_reasoning_trace(body)
        assert "<think>" not in out
        assert "Now I need to think" not in out
        assert "Existing prose above the trace." in out
        assert "Actual final body that survived" in out

    def test_preserves_substantive_body_prose(self):
        # No-op on clean input — must not corrupt or rewrite anything.
        clean = (
            "## 4. Claims Analysis\n"
            "\n"
            "### Specific Performance\n"
            "Plaintiff alleges breach of the 253 River Heights Road purchase agreement. "
            "[#13 Joint Preliminary Statement.pdf, p. 5]\n"
            "\n"
            "### Breach of Contract\n"
            "The closing was set for 2021-06-01 but the contract expired without closing. "
            "[2022.01.04 Pl's Initial Disclosures.pdf]\n"
        )
        out = strip_reasoning_trace(clean)
        assert out == clean.strip()

    def test_collapses_excess_newlines(self):
        # Stripping a <think> block can leave a long run of blank lines in
        # the surrounding text. Collapse 3+ to exactly 2 so the markdown
        # rendering stays tidy.
        body = "Header\n\n\n\n\n<think>trace</think>\n\n\n\n\nBody"
        out = strip_reasoning_trace(body)
        # Must not contain a run of 3+ newlines.
        assert "\n\n\n" not in out
        assert "Header" in out
        assert "Body" in out
        # Exactly one paragraph break between Header and Body.
        assert out == "Header\n\nBody"

    def test_idempotent(self):
        # Running strip twice equals running once — useful when callers
        # double-wrap the helper or the synthesizer is retried.
        body = (
            "<think>plan</think>\n\n# Title\n\n<think>recheck</think>\n\nBody."
        )
        once = strip_reasoning_trace(body)
        twice = strip_reasoning_trace(once)
        assert once == twice

    def test_preserves_first_person_outside_think(self):
        # Pass 1 ONLY strips tags. First-person planning prose that survives
        # *outside* <think> tags is intentionally preserved here — Pass 2
        # (system-prompt fix or post-strip prose filter) is a separate brief.
        # This test pins that contract so a future change can't silently
        # promote Pass 2 into Pass 1.
        body = (
            "<think>Okay, let me plan this.</think>\n"
            "\n"
            "Let me address the four counts in plaintiff's complaint.\n"
            "\n"
            "Now, looking at the evidence record, I should focus on...\n"
        )
        out = strip_reasoning_trace(body)
        assert "<think>" not in out
        # First-person prose OUTSIDE the tags survives:
        assert "Let me address the four counts" in out
        assert "Now, looking at the evidence record" in out
        assert "I should focus on" in out


@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("", ""),
        (None, None),
        ("no tags here", "no tags here"),
        ("<think></think>", ""),  # empty trace
    ],
)
def test_strip_edge_cases(input_text, expected):
    """Edge cases that aren't worth a named test method."""
    assert strip_reasoning_trace(input_text) == expected
