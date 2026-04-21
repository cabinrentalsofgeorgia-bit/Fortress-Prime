# Stale PR Triage — 2026-04-21

Triage of 5 open PRs that predate the main session and have UNKNOWN mergeability.
No rebases or merges performed — classification only per brief.

---

## PR #103 — `feat(eval): legal holdout adapter for run_eval.py compatibility`
**Branch:** `feat/legal-holdout-eval-adapter` | **38 commits behind main** | Last: 21h ago

**Classification: KEEP OPEN — active, not urgent**

`src/eval/prepare_legal_holdout.py` and `src/eval/run_eval.py` are NOT on main.
PR #109 (bf16 fix for DGX Spark) landed separately and addresses a related eval
issue but doesn't supersede this PR's holdout adapter work. This PR adds the
converter that bridges the training holdout format to run_eval.py's expected
schema. The branch is actively being worked (21h ago, 38 commits behind).
Needs a rebase before it can merge but the work is still valid.

---

## PR #99 — `fix(phase-4d): corpus quality — truncation, Pattern C, max_tokens`
**Branch:** `fix/phase-4d-corpus-quality` | **44 commits behind main** | Last: 33h ago

**Classification: KEEP OPEN — active legal training work, not urgent**

`src/legal/training_pairs_godhead.py` and `src/legal/training_pairs_scripted.py`
are on main but this PR has further corpus-quality fixes. Active work from
yesterday — the legal training pipeline (epoch currently running as `legal_train`)
depends on these scripts. Closing while training is active is wrong. Needs a
rebase review once the current training epoch completes.

---

## PR #8 — `fix: restore backend recovery paths on current main`
**Branch:** `fix/backend-recovery-clean` | **267 commits behind main** | Last: 3 weeks ago

**Classification: SUPERSEDE — all files now exist on main with newer implementations**

267 commits behind, 3 weeks stale. All touched files (reservation_engine.py,
seo_audit.py, seo_patches.py, quote_builder.py, main.py) exist on main with
substantially more recent changes. The "recovery paths" context predates the
full email pipeline, legal graph, atlas routing, and concierge work that has since
landed. Closing with explanation pointing to current main.

---

## PR #6 — `feat(ops): add sovereign hardware telemetry surfaces`
**Branch:** `feat/sovereign-hardware-telemetry-command-center` | **268 commits behind** | Last: 3 weeks ago

**Classification: KEEP OPEN — still relevant, low priority**

`deploy/compute/paperclip/` files exist on main. However the broader telemetry
surface work (command-center UI dashboards, node health displays) may extend
beyond what's on main. 268 commits behind but the telemetry/ops observability
context is still valid as the cluster grows (spark-4 now carries VRS inference,
legal training on spark-2). Tag as low priority — Gary decides whether to rebase
and revive or scope a fresh PR.

---

## PR #3 — `feat(legal): complete phase2 graph stack and guardrails`
**Branch:** `feature/legal-phase2-graph-guardrails` | **383 commits behind** | Last: 5 weeks ago

**Classification: SUPERSEDE — all core models already on main**

383 commits behind, 5 weeks stale. `backend/models/legal_phase2.py`,
`backend/services/legal_case_graph.py`, `legal_discovery_engine.py`,
`legal_evidence_ingestion.py` all exist on main. The legal Phase 2 stack landed
via other PRs in the intervening weeks. The frontend component
(`case-detail-shell.tsx`) would need conflict resolution against current
command-center code. Closing — any outstanding pieces should come as a fresh
targeted PR.

---

## Summary

| PR | Title | Decision | Reason |
|---|---|---|---|
| #103 | legal holdout adapter | **KEEP** | Active work, valid, needs rebase |
| #99 | corpus quality fixes | **KEEP** | Active legal training pipeline, epoch running |
| #8 | backend recovery paths | **SUPERSEDE** | 267 commits behind, all files superseded |
| #6 | hardware telemetry | **KEEP** | Potentially valid, low priority |
| #3 | legal phase2 graph | **SUPERSEDE** | 383 commits behind, models already on main |
