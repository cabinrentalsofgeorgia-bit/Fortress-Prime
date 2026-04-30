"""Unit tests for ``backend.services.case_briefing_synthesizers``.

Phase B v0.2 — synthesizer ``<think>``-block stripping (Pass 1 only).

Per-fixture origin: most ``<think>``-block fixtures are real excerpts from
the PR #302 outcome-b dry-run output at
``/mnt/fortress_nas/legal-briefs/7il-v-knight-ndga-i-v3-outcome-b-2026-04-29.md``
(specifically lines 36, 133, 231, 249, 285).
"""
from __future__ import annotations

import textwrap

from backend.services.case_briefing_synthesizers import strip_reasoning_trace


class TestStripReasoningTrace:
    """Pass-1 stripper: ``<think>...</think>`` tag removal + whitespace cleanup."""

    def test_strips_simple_think_block(self) -> None:
        text = "Body before. <think>quick reasoning</think> Body after."
        out = strip_reasoning_trace(text)
        assert "<think>" not in out
        assert "</think>" not in out
        assert "Body before." in out
        assert "Body after." in out
        assert "quick reasoning" not in out

    def test_strips_multiline_think_block(self) -> None:
        # Real fixture excerpt (PR #302 outcome-b §2 Critical Timeline).
        text = textwrap.dedent(
            """\
            ## 2. Critical Timeline

            <think>
            Okay, let's tackle this. The user wants a chronological timeline of dated
            events for the case, using only the provided evidence. I need to go through
            each of the CASE EVIDENCE blocks and extract any dates mentioned, then
            organize them in order.

            First, I'll start by scanning each document for dates. Let's go one by one.
            </think>

            | Date | Event | Source |
            |---|---|---|
            | 2021-04-05 | Plaintiff accepted offer | [#13 Joint Preliminary Statement.pdf] |
            """
        )
        out = strip_reasoning_trace(text)
        assert "<think>" not in out
        assert "</think>" not in out
        assert "the user wants" not in out.lower()
        assert "scanning each document" not in out
        # substantive content preserved
        assert "## 2. Critical Timeline" in out
        assert "[#13 Joint Preliminary Statement.pdf]" in out
        assert "2021-04-05" in out

    def test_strips_multiple_think_blocks(self) -> None:
        text = textwrap.dedent(
            """\
            ## 4. Claims Analysis

            <think>First reasoning block — model planning the section.</think>

            ### 1. Specific Performance

            <think>
            Second reasoning block, multi-line, reasoning about the next count.
            </think>

            ### 2. Breach of Contract

            <think>Third block.</think>

            Body conclusion sentence.
            """
        )
        out = strip_reasoning_trace(text)
        assert out.count("<think>") == 0
        assert out.count("</think>") == 0
        assert "## 4. Claims Analysis" in out
        assert "### 1. Specific Performance" in out
        assert "### 2. Breach of Contract" in out
        assert "Body conclusion sentence." in out

    def test_handles_unclosed_think_tag(self) -> None:
        # PR #302 outcome-b had 5 <think> opens vs 4 </think> closes; one was
        # unclosed (model truncated mid-trace). Strip the unclosed reasoning
        # from <think> to the next blank line.
        text = textwrap.dedent(
            """\
            Body paragraph.

            <think>
            Reasoning that got cut off because of streaming abort or
            max_tokens — there is no closing tag.

            More cut-off thinking on the same trace.

            Body paragraph after the blank line acts as the strip terminator.
            """
        )
        out = strip_reasoning_trace(text)
        assert "<think>" not in out
        assert "Reasoning that got cut off" not in out
        # Content after the blank-line terminator is preserved.
        assert "Body paragraph after the blank line" in out
        assert "Body paragraph." in out

    def test_preserves_substantive_body_prose(self) -> None:
        # No-op on clean substantive input. Citations, headers, body prose
        # all preserved exactly.
        text = textwrap.dedent(
            """\
            ### **1. Specific Performance**
            **Elements (from evidence):**
            - Plaintiff alleges Defendant failed to perform under the agreements
              ([#13 Joint Preliminary Statement.pdf], p. 5).
            - Plaintiff seeks a judgment ordering specific performance.

            **Defendant's Likely Defense Theory:**
            - The agreements lapsed due to unmet conditions
              ([5464474_Exhibit_3_GaryKnight.pdf], paragraph 75).
            """
        )
        out = strip_reasoning_trace(text)
        assert out.strip() == text.strip()

    def test_collapses_excess_newlines(self) -> None:
        text = "Para one.\n\n\n\n\nPara two.\n\n\n\nPara three."
        out = strip_reasoning_trace(text)
        # 3+ newlines collapse to 2; nothing else changes.
        assert out == "Para one.\n\nPara two.\n\nPara three."

    def test_idempotent(self) -> None:
        # Running twice equals running once.
        text = textwrap.dedent(
            """\
            ## Section header

            <think>
            Reasoning that should be stripped on the first pass.
            </think>

            Body content with [citation.pdf] preserved.
            """
        )
        once = strip_reasoning_trace(text)
        twice = strip_reasoning_trace(once)
        assert once == twice
        assert "<think>" not in once
        assert "[citation.pdf]" in once

    def test_preserves_first_person_outside_think(self) -> None:
        # Pass 2 is intentionally NOT implemented in v0.2. First-person
        # planning prose that appears OUTSIDE <think> tags is preserved
        # verbatim — its handling is deferred (likely upstream system-prompt
        # adjustment). This test pins that contract.
        text = textwrap.dedent(
            """\
            ## Section body

            Let me address the elements one by one.

            I should note the following points about the encroachment.

            Now, structuring the analysis: the issue arose at closing.

            Looking at the evidence, three threads emerge.
            """
        )
        out = strip_reasoning_trace(text)
        # Tag-stripper has nothing to do — input has no <think> blocks.
        # All planning prose is preserved (Pass 2 deferred).
        assert "Let me address" in out
        assert "I should note" in out
        assert "Now, structuring" in out
        assert "Looking at the evidence" in out
