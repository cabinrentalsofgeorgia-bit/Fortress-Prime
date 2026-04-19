#!/usr/bin/env python3
"""
training_prep.py — Phase 4d Part 2 (STUB — not yet implemented).

This module will convert the raw legal corpus (acquired in Part 1) into
instruction-tuning pairs suitable for fine-tuning qwen2.5:32b as the
Fortress Legal judge model.

=== What Part 2 will do ===

Input: /mnt/fortress_nas/legal-corpus/ (populated by corpus_ingest.py)

Output: /mnt/fortress_nas/finetune-artifacts/legal-corpus-v1/
  ├── train.jsonl       Instruction-tuning pairs (80%)
  ├── holdout.jsonl     Evaluation set (20%)
  └── manifest.json     Provenance, counts, split details

=== Pair generation strategy ===

1. Legal reasoning pairs (from CourtListener opinions):
   Prompt:  "Analyze whether coverage applies under Georgia law given: {facts}"
   Response: {court's actual reasoning from opinion, cleaned}

2. Bad faith pairs (from bad-faith cases):
   Prompt:  "Does this claims handling conduct constitute bad faith under O.C.G.A. § 33-4-6?"
   Response: {court's analysis}

3. Statutory interpretation pairs (from OCGA + opinions):
   Prompt:  "What does O.C.G.A. § {section} require regarding {topic}?"
   Response: {section text + relevant case citations}

4. Coverage denial analysis:
   Prompt:  "Evaluate this coverage denial under Georgia law: {policy language + facts}"
   Response: {structured analysis following GA appellate court patterns}

=== Quality filters ===

- Minimum opinion length: 500 words
- Require insurance-specific holding (not just procedural)
- Deduplicate by cluster_id
- Strip boilerplate headers/footers

=== Phase 4d Part 3 will ===

Fine-tune qwen2.5:32b-fortress-legal on these pairs using LoRA adapters
on spark-1. Target: legal_reasoning_judge and brief_drafting_judge models
in the Iron Dome judge tier.

=== Usage (when implemented) ===

  python -m src.legal.training_prep build-pairs \\
      --source /mnt/fortress_nas/legal-corpus \\
      --output /mnt/fortress_nas/finetune-artifacts/legal-corpus-v1 \\
      --split 0.8

  python -m src.legal.training_prep validate \\
      --pairs /mnt/fortress_nas/finetune-artifacts/legal-corpus-v1/train.jsonl
"""
from __future__ import annotations


def build_pairs() -> None:
    raise NotImplementedError("Phase 4d Part 2 — not yet implemented. See module docstring.")


def validate_pairs() -> None:
    raise NotImplementedError("Phase 4d Part 2 — not yet implemented. See module docstring.")
