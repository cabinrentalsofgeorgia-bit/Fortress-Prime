# Track A v3 Case I — Analysis Harvest Report

**Date:** 2026-04-30
**Branch:** `feat/track-a-v3-analysis-harvest-2026-04-30` (from `origin/main` 8d8c41b65)
**Source artifacts:** `/tmp/track-a-case-i-v3-20260430T194507Z/`
**Brief on NAS (untouched):** `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T194507Z.md` (28,011 bytes, 2026-04-30 16:26)
**Frontier load consumed by this run:** zero (analysis is read-only over disk artifacts)

This report harvests Wave 4 prompt-tuning input from the existing 19:45Z Track A run instead of consuming frontier capacity for a redundant re-run. Four v3 briefs landed today across the cap cascade; the 19:45Z run is the canonical at-cap baseline.

---

## 1. Run summary (from `metrics/run-summary.json`)

| Field | Value |
|---|---|
| Stamp | `20260430T194507Z` |
| Frontier endpoint | `http://10.10.10.3:8000` (`nemotron-3-super`) |
| Overall wall | 2377.2s (39.6 min) |
| Synthesizer cap (`max_tokens`) — actual | **20000** |
| Total content chars (11 emitted slots) | 26,356 |
| Total reasoning chars (LLM calls only) | 192,935 |
| Sections producing content | 9 of 11 slots |
| Sections empty (per #328 expectation + observed) | §2, §7 |

> **Cap delta vs. brief context:** The brief framed PR #327 as raising the synthesizer cap from 2000→8000. The actual `max_tokens` recorded on every brain-client call in this run is **20000**, set inside `track_a_case_i_runner.py`'s BrainClient injection — i.e. the runner overrides the synthesizer-default cap. So this baseline is at runner-chosen cap=20000, **not** PR #327's 8000. Wave 4 should treat this as the cap=20000 data point; a true cap=8000 sample requires either an earlier run today or a re-run with the override removed.

---

## 2. Per-section metrics

| section | mode | content | reasoning | wall_s | finish | cit_uniq | grounding_orch | rsn_ratio | tok/s |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| §1 case_summary | mechanical | 511 | 0 | — | n/a | 0 | 0 | 0 | — |
| §2 critical_timeline | synthesis | **0** | **71,294** | 840.3 | **length** | 0 | 0 | ∞ | 0.00 |
| §3 parties_counsel | mechanical | 509 | 0 | — | n/a | 0 | 0 | 0 | — |
| §4 claims_analysis | synthesis | 7,818 | 21,656 | 306.1 | stop | 0 | 4 | 2.77 | 6.38 |
| §5 key_defenses | synthesis | 6,271 | 19,090 | 268.9 | stop | 4 | 5 | 3.04 | 5.83 |
| §6 evidence_inventory | mechanical | 1,376 | 0 | — | n/a | 0 | 0 | 0 | — |
| §7 email_intel | synthesis | **0** | **73,407** | 835.5 | **length** | 0 | 0 | ∞ | 0.00 |
| §8 financial_exposure | synthesis | 3,565 | 7,488 | 125.8 | stop | 4 | 4 | 2.10 | 7.09 |
| §9 strategy (placeholder) | operator_written | 383 | 0 | 107.8 | stop | 0 | 0 | 0 | 0.88 |
| §9 strategy (augmented) | synthesis_augmented | 5,312 | 0 | — | n/a | 5 | 0 | 0 | — |
| §10 filing_checklist | mechanical | 611 | 0 | — | n/a | 0 | 0 | 0 | — |

`cit_uniq` = unique bracketed-filename citations in the emitted markdown (this analysis); `grounding_orch` = orchestrator-tracked grounding-citation count from the synthesizer pipeline. They measure different things, see §5.

Format compliance per orchestrator: **all 11 slots `format_compliant=true`, zero `<think>` leakage, zero first-person bleed in the LLM voice.** One advisory regex hit on §6 (`we` inside a quoted email subject "I_ Want to make_ Sure we have answered…") which is bracketed evidence content, not the model's voice.

---

## 3. §2 / §7 gap classification (per Issue #328)

The brief framed §2 (Critical Timeline) and §7 (Email Intelligence) as "expected empties per #328". The metrics tell a sharper story than "expected gap":

| section | finish_reason | reasoning_chars | content_chars | wall_s | failure mode |
|---|---|---:|---:|---:|---|
| §2 critical_timeline | length | 71,294 | 0 | 840.3 | **runaway reasoning — exhausted 20K-token cap with zero content emitted** |
| §7 email_intelligence | length | 73,407 | 0 | 835.5 | **runaway reasoning — same pattern** |

Both sections spent the entire 20,000-token completion budget in the reasoning channel before ever crossing into content. Each consumed ~14 minutes of frontier wall and ~71-73K reasoning chars — approximately 17-18K reasoning tokens at ~4 chars/token. Neither produced a single character the user can read.

This is not "the source data is missing" (the #328 framing); it's "the model can't *finish thinking* at this cap." For Wave 4: at cap=20000, two of five synthesis sections runaway. The fix space is prompt tuning to cut reasoning depth, not raising the cap further.

---

## 4. Reasoning-vs-content shape

Among synthesis sections that did emit content (`finish=stop`):

```
section            reasoning_chars  content_chars  ratio  wall_s
§4 claims              21,656           7,818     2.77    306.1
§5 key_defenses        19,090           6,271     3.04    268.9
§8 financial_exposure   7,488           3,565     2.10    125.8
```

Productive synthesis sections sit in a 2.10–3.04 reasoning-to-content ratio band. Token throughput on emitted content is 5.8–7.1 tok/s (estimate from `content_token_estimate / wall_seconds`).

The runaway pair (§2, §7) sit at ratio = ∞: 100% of the budget went to reasoning. They are categorically a different shape, not just "more of the same."

Reasoning-vs-content scatter data is in `docs/operational/track-a-v3-case-i-analysis-2026-04-30/reasoning_vs_content.tsv`.

---

## 5. Citation density curve (by mode)

| mode | sections | with_content | content_chars | cit_total | cit_unique | grounding_orch | density / 1k chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| mechanical | 4 | 4 | 3,007 | 0 | 0 | 0 | 0.00 |
| operator_written | 1 | 1 | 383 | 0 | 0 | 0 | 0.00 |
| synthesis | 5 | 3 | 17,654 | 20 | 8 | 13 | 1.13 |
| synthesis_augmented | 1 | 1 | 5,312 | 10 | 5 | 0 | 1.88 |

Filename-citation density inside emitted synthesis content runs ~1.1–1.9 brackets per 1,000 chars. The augmented §9 path (post-orchestrator legal-reasoning call) is the densest at 1.88/kchar, which suggests the augmentation prompt is asking for more explicit attribution than the in-orchestrator synthesis prompt.

### Cross-reference: orchestrator grounding count vs. emitted-md filename citations

| section | orch_grounding | md_cit_unique | delta | note |
|---|---:|---:|---:|---|
| §4 claims_analysis | 4 | 0 | +4 | **orch says 4 grounded, no bracketed filename citations in emitted md** |
| §5 key_defenses | 5 | 4 | +1 | mostly aligned |
| §8 financial_exposure | 4 | 4 | 0 | aligned |
| §9 augmented | 0 | 5 | -5 | **orch doesn't track this path; augmenter cites 5 unique filenames** |

Two findings worth flagging for Wave 4:

- **§4 anomaly**: orchestrator records 4 grounding citations but the emitted §4 content contains zero bracketed-filename citations. Either §4's prompt instructs a different citation format (footnote-style, inline reference) and the regex misses it, or §4 produced content without surfacing the filename citations the retrieval pipeline supplied. Worth eyeballing the §4 prompt template.
- **§9 augmented**: the post-run legal-reasoning augmentation produces well-cited content (5 unique filenames in 5,312 chars) but the orchestrator's grounding tracker is bypassed entirely. If §9 stays a post-run augmentation, grounding-tracker integration should be added so we don't lose visibility on the most important section.

---

## 6. Wave 4 prompt-tuning observations

1. **Runaway reasoning is the binary failure mode at cap=20000.** Two synthesis sections consume the entire token budget on reasoning and emit zero content. Symptom is `finish=length` + `reasoning_chars` near max (71-73K chars ≈ near the 20K-token cap). Fix space: add explicit "summarize and emit content within N reasoning tokens" instructions, or move §2/§7 to a structured-extraction prompt rather than free synthesis.

2. **Productive synthesis cluster is tight and predictable.** §4/§5/§8 reasoning-to-content ratios are 2.1–3.0; tok/s is 5.8–7.1. That's a stable enough band to set per-section expected-reasoning budgets in the prompt and short-circuit if exceeded.

3. **Mechanical sections are noise-free at zero cost.** §1/§3/§6/§10 all produce small (509-1376 char) compliant content with no LLM call. Don't move them under synthesis.

4. **§9 placeholder pathway is wasted.** The orchestrator emits a 383-char placeholder (`mode=operator_written`); the runner then makes a separate post-run legal-reasoning call producing 5,312 chars. That's two paths producing one output. Either drop the placeholder or merge §9 into the orchestrator's synthesis path with a dedicated prompt.

5. **Citation-format inconsistency in §4.** Orchestrator records 4 grounding citations, emitted md has zero bracketed-filename citations. Suggests §4's prompt template differs from §5/§8.

6. **Cap=20000, not cap=8000.** Track A runner overrides the synthesizer's PR #327 default. If Wave 4 prompt tuning is meant to land on top of the cap=8000 default, it has to be tested against that — not the cap=20000 baseline this run produced.

---

## 7. Frontier health, soak, hard stops

Pre-flight only. The 19:45Z run completed at 16:26 local; this analysis ran ~24 minutes after that and consumed zero frontier load. Frontier liveness probes used during pre-flight (course-corrected from `/v1/health/ready` → `/health` because the v1 path 404s on the current server build):

- `GET /health` → 200
- `GET /v1/models` → 200
- `GET /metrics` → 200
- `GET /ping` → 200
- `GET /v1/health/ready` → **404** (path missing on current server)

No soak halt events checked (analysis is read-only; soak collector is independent).

---

## 8. Artifacts

```
docs/operational/track-a-v3-case-i-analysis-2026-04-30/
├── metrics_table.tsv            # per-section: content/reasoning/wall/finish/cits/ratio/tps
├── citation_density.tsv         # by-mode aggregate
├── reasoning_vs_content.tsv     # scatter data for productive + runaway sections
├── format_compliance.tsv        # orch fmt_ok + advisory regex hits
├── cross_reference.tsv          # orch grounding vs md-extracted citations
├── observations.md              # narrative cut of the same data
└── rows.json                    # machine-readable per-section dump
```

Analysis script: `fortress-guest-platform/backend/scripts/track_a_v3_analysis.py` (pure stdlib, re-runnable against any future Track A run dir).

---

## 9. References

- Issue #328 — §2/§7 source-data gaps in Track A v0.1 orchestrator
- PR #326 — TP=2 frontier compatibility (BrainClient defects)
- PR #327 — synthesizer max_tokens cap raise 2000→8000
- PR #323 — Phase B v0.1 dry-run on Case I (initial Wave 4 build target identification)
- v3 brief on NAS: `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T194507Z.md` (untouched by this work)
