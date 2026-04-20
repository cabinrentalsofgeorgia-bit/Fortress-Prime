"""Tests for Phase 4d Part 2 — training pair generation."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock


def _scripted():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.legal import training_pairs_scripted as s
    return s


def _godhead():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.legal import training_pairs_godhead as g
    return g


def _consolidate():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.legal import training_pairs_consolidate as c
    return c


# ---------------------------------------------------------------------------
# Pattern A — Case analysis
# ---------------------------------------------------------------------------

SYNTHETIC_OPINION = {
    "cluster_id": "TEST001",
    "opinion_id": "OP001",
    "case_name": "State Farm v. Johnson",
    "court": "Court of Appeals of Georgia",
    "date_filed": "2022-06-15",
    "citation": [],
    "plain_text": """
Court of Appeals of Georgia

In the matter of State Farm Mutual Insurance Company v. Robert Johnson.

Facts: Johnson filed a homeowner's insurance claim after a fire destroyed his property.
State Farm denied coverage citing the arson exclusion. Johnson produced witnesses testifying
he was not present at the time of the fire. The trial court granted summary judgment for Johnson.

I. Analysis

The central issue is whether State Farm met its burden of proving the arson exclusion applies.
Under O.C.G.A. § 33-4-6, an insurer who denies a claim in bad faith may be liable for
attorney fees and penalties. See also Allstate Ins. Co. v. Reynolds, 269 Ga. App. 624 (2004).

II. Coverage Exclusion

We hold that State Farm failed to present clear and convincing evidence of arson.
The judgment is affirmed. State Farm's denial constituted bad faith under Georgia law.

AFFIRMED. Johnson is entitled to attorney fees under O.C.G.A. § 33-4-6.
""",
    "plain_text_chars": 900,
}


class TestPatternA:
    def test_generates_pair_from_valid_opinion(self) -> None:
        s = _scripted()
        pair = s.pattern_a(SYNTHETIC_OPINION)
        assert pair is not None
        assert pair["pattern"] == "A"
        assert "instruction" in pair
        assert "output" in pair
        assert "facts" in pair["instruction"].lower() or "johnson" in pair["instruction"].lower()

    def test_returns_none_for_empty_opinion(self) -> None:
        s = _scripted()
        empty = {"cluster_id": "X", "plain_text": "", "case_name": "X v Y"}
        assert s.pattern_a(empty) is None

    def test_holding_extracted(self) -> None:
        s = _scripted()
        pair = s.pattern_a(SYNTHETIC_OPINION)
        assert pair is not None
        # Should contain the holding
        assert "hold" in pair["output"].lower() or "affirm" in pair["output"].lower()


# ---------------------------------------------------------------------------
# Pattern B — Issue spotting
# ---------------------------------------------------------------------------

class TestPatternB:
    def test_extracts_section_headers(self) -> None:
        s = _scripted()
        pair = s.pattern_b(SYNTHETIC_OPINION)
        assert pair is not None
        # Should find "Analysis" and "Coverage Exclusion"
        assert "analysis" in pair["output"].lower() or "coverage" in pair["output"].lower()

    def test_returns_none_when_no_sections(self) -> None:
        s = _scripted()
        no_sections = {
            "cluster_id": "X", "plain_text": "A long opinion without headers. " * 100,
            "case_name": "X v Y"
        }
        result = s.pattern_b(no_sections)
        assert result is None


# ---------------------------------------------------------------------------
# Pattern C — Citation lookup
# ---------------------------------------------------------------------------

class TestPatternC:
    def test_extracts_ocga_citations(self) -> None:
        s = _scripted()
        pairs = s.pattern_c(SYNTHETIC_OPINION)
        assert len(pairs) > 0
        ocga_pairs = [p for p in pairs if "O.C.G.A" in p["output"]]
        assert len(ocga_pairs) > 0

    def test_extracts_case_citations(self) -> None:
        s = _scripted()
        pairs = s.pattern_c(SYNTHETIC_OPINION)
        case_pairs = [p for p in pairs if "Allstate" in p["output"] or "Ga. App" in p["output"]]
        assert len(case_pairs) > 0

    def test_instruction_references_principle(self) -> None:
        s = _scripted()
        pairs = s.pattern_c(SYNTHETIC_OPINION)
        for p in pairs:
            assert "georgia" in p["instruction"].lower() or "authority" in p["instruction"].lower()


# ---------------------------------------------------------------------------
# Pattern D — Precedent outcome
# ---------------------------------------------------------------------------

class TestPatternD:
    def test_generates_outcome_pair(self) -> None:
        s = _scripted()
        pair = s.pattern_d(SYNTHETIC_OPINION)
        assert pair is not None
        assert pair["pattern"] == "D"
        assert "georgia" in pair["instruction"].lower()
        assert "state farm" in pair["output"].lower() or "affirm" in pair["output"].lower()

    def test_skips_non_insurance_opinions(self) -> None:
        s = _scripted()
        non_insurance = {
            "cluster_id": "X",
            "plain_text": "This is a contract dispute about real estate. We hold for the plaintiff. " * 50,
            "case_name": "Smith v. Jones",
            "date_filed": "2020-01-01",
            "court": "ga",
        }
        result = s.pattern_d(non_insurance)
        assert result is None


# ---------------------------------------------------------------------------
# Godhead — filter logic
# ---------------------------------------------------------------------------

class TestGodheadFilter:
    def _make_opinion(self, text: str, chars: int = 10000) -> dict:
        return {
            "cluster_id": "X",
            "case_name": "Test v. Test",
            "plain_text": text * (chars // len(text) + 1),
        }

    def test_matches_bad_faith(self) -> None:
        g = _godhead()
        op = self._make_opinion("bad faith denial of insurance claim coverage ")
        assert g._matches_filter(op)

    def test_matches_duty_to_defend(self) -> None:
        g = _godhead()
        op = self._make_opinion("the insurer had a duty to defend under the policy ")
        assert g._matches_filter(op)

    def test_rejects_short_opinions(self) -> None:
        g = _godhead()
        op = {"cluster_id": "X", "plain_text": "bad faith denial." * 10}
        assert not g._matches_filter(op)  # too short

    def test_rejects_non_insurance(self) -> None:
        g = _godhead()
        op = self._make_opinion("contract dispute over real property delivery ")
        assert not g._matches_filter(op)

    def test_filter_selects_longest_first(self) -> None:
        g = _godhead()
        records = [
            {"cluster_id": "short", "plain_text": "bad faith " * 900},   # ~9000 chars
            {"cluster_id": "long",  "plain_text": "bad faith " * 2000},  # ~20000 chars
        ]
        selected = g.filter_cases(records, 1)
        assert selected[0]["cluster_id"] == "long"


# ---------------------------------------------------------------------------
# Godhead — budget guard
# ---------------------------------------------------------------------------

class TestBudgetGuard:
    def test_cost_estimate_is_reasonable(self) -> None:
        g = _godhead()
        cost = g.estimate_cost("claude-haiku-4-5", 150, 9000)
        assert 0.01 < cost < 50.0, f"Unexpected cost estimate: {cost}"

    def test_opus_costs_more_than_haiku(self) -> None:
        g = _godhead()
        haiku_cost = g.estimate_cost("claude-haiku-4-5", 150, 9000)
        opus_cost = g.estimate_cost("claude-opus-4-6", 150, 9000)
        assert opus_cost > haiku_cost * 5

    def test_dry_run_does_not_call_api(self, tmp_path: Path) -> None:
        g = _godhead()
        import argparse
        args = argparse.Namespace(limit=10, model="claude-haiku-4-5", dry_run=True)
        with patch.object(g, "FULLTEXT_PATH", tmp_path / "opinions.jsonl"), \
             patch.object(g, "OUT_PATH", tmp_path / "out.jsonl"):
            # Create minimal corpus
            (tmp_path / "opinions.jsonl").write_text(
                json.dumps({"cluster_id": "1", "plain_text": "bad faith insurance " * 600,
                            "case_name": "A v B", "date_filed": "2020-01-01"}) + "\n"
            )
            api_called = []
            with patch.object(g, "_call_godhead", side_effect=lambda *a, **k: api_called.append(1)):
                g.run(args)
        assert len(api_called) == 0, "API should not be called in dry-run mode"


# ---------------------------------------------------------------------------
# Consolidation — split ratio + deduplication
# ---------------------------------------------------------------------------

class TestConsolidation:
    def test_split_ratios(self, tmp_path: Path) -> None:
        c = _consolidate()
        pairs_dir = tmp_path / "training-pairs"
        pairs_dir.mkdir()
        # Write 100 pairs to scripted.jsonl
        scripted = pairs_dir / "scripted.jsonl"
        with scripted.open("w") as f:
            for i in range(100):
                f.write(json.dumps({
                    "pattern": "A",
                    "instruction": f"unique instruction {i}",
                    "output": f"unique output {i}",
                }) + "\n")

        with patch.object(c, "PAIRS_DIR", pairs_dir), \
             patch.object(c, "SCRIPTED", scripted), \
             patch.object(c, "GODHEAD", pairs_dir / "godhead.jsonl"), \
             patch.object(c, "COMBINED", pairs_dir / "combined.jsonl"), \
             patch.object(c, "TRAIN", pairs_dir / "train.jsonl"), \
             patch.object(c, "VAL", pairs_dir / "val.jsonl"), \
             patch.object(c, "HOLDOUT", pairs_dir / "holdout.jsonl"):
            rc = c.run()
        assert rc == 0

        train_n = sum(1 for _ in (pairs_dir / "train.jsonl").open())
        val_n   = sum(1 for _ in (pairs_dir / "val.jsonl").open())
        hold_n  = sum(1 for _ in (pairs_dir / "holdout.jsonl").open())
        assert train_n + val_n + hold_n == 100
        assert abs(train_n / 100 - 0.80) < 0.05

    def test_deduplication(self, tmp_path: Path) -> None:
        c = _consolidate()
        pairs_dir = tmp_path / "training-pairs"
        pairs_dir.mkdir()
        scripted = pairs_dir / "scripted.jsonl"
        # Write 10 unique + 5 exact duplicates
        with scripted.open("w") as f:
            for i in range(10):
                p = {"pattern": "A", "instruction": f"instr {i}", "output": f"out {i}"}
                f.write(json.dumps(p) + "\n")
            for i in range(5):
                p = {"pattern": "A", "instruction": f"instr {i}", "output": f"out {i}"}
                f.write(json.dumps(p) + "\n")

        with patch.object(c, "PAIRS_DIR", pairs_dir), \
             patch.object(c, "SCRIPTED", scripted), \
             patch.object(c, "GODHEAD", pairs_dir / "godhead.jsonl"), \
             patch.object(c, "COMBINED", pairs_dir / "combined.jsonl"), \
             patch.object(c, "TRAIN", pairs_dir / "train.jsonl"), \
             patch.object(c, "VAL", pairs_dir / "val.jsonl"), \
             patch.object(c, "HOLDOUT", pairs_dir / "holdout.jsonl"):
            c.run()

        combined_n = sum(1 for _ in (pairs_dir / "combined.jsonl").open())
        assert combined_n == 10  # 5 dupes removed
