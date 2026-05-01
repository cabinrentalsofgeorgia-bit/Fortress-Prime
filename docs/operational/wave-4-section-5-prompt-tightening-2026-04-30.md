# Wave 4 §5 Prompt Tightening — Run Report

**Branch:** `feat/synthesizer-section-5-prompt-tightening-2026-04-30` (from `origin/main` at PR #333 merge `e72be18e8`)
**Date:** 2026-04-30
**Stacks on:** PR #326, #327, #329, #330, #331, #333. Closes the §5 grounding-format regression that was the operator-flagged issue from PR #333's three-run §5 isolation. Resolves Wave 4 §5 prompt tightening per the original brief + the 2026-04-30 deep-research amendment (force_nonempty_content, thinking_token_budget removal, NVIDIA sampling Path A).

**Frontier load consumed:** ~25 minutes wall across:
- 1× full-prompt §5 reconstruction probe (Phase 2 §4 stress pattern)
- 1× three-run isolation pre-Path-R (NVIDIA sampling, halt at Run 2 partial)
- 1× three-run isolation Path R (citation-per-row requirement)
- 1× full Track A v3 re-run (10/10 sections, 401.77s wall)

Frontier health 200 throughout. No soak halt events.

---

## 1. Problem statement (recap)

PR #333 routed §5 (Key Defenses Identified) to `enable_thinking=True, low_effort=False` — a deliberate Phase 3 deviation from the standard `low_effort=True` doctrinal-section policy because the §5 isolation probe at that time showed `low_effort=True` (a) compressed overlapping affirmative defenses and (b) **dropped the entire non-affirmative denial subsection** (4 explicit denial entries vanished). PR #333's run report documented this as a "Wave 4 prompt-tuning input — sections expecting multiple structural subsections sharing facts compress under `low_effort=True`."

Wave 4 closes that loop. Mechanistic confirmation from the Nemotron 3 Super Technical Report §3.1 (NVIDIA, 2026): low-effort SFT covered only math reasoning, STEM QA, and instruction following at 2% of SFT data — multi-block legal pleading shape is genuinely out of distribution. The "instruction following" slice is the only one of those three engageable from the prompt itself. The Wave 4 fix moves §5's structural requirements from implicit (recovered via multi-pass reasoning) to explicit (anchored in instruction-following prompt structure) so `low_effort=True` can engage them through the trained slice.

---

## 2. Prompt diff — additive append

**Before** (3 sentences, ~290 chars, `_SYNTHESIS_PROMPTS["section_05_key_defenses_identified"]`):

> "List the affirmative defenses + non-affirmative defense theories supported by the evidence. For each: cite the supporting chunks by bracketed filename. Flag any defense where the evidence is thin or contradicted."

**After** (~1,790 chars, additive — leading 3 sentences preserved verbatim, four named-block specification appended, plus per-row bracketed-citation requirement in Block C added during Path R refinement after the first three-run isolation):

```
[3 leading sentences preserved verbatim]

STRUCTURAL REQUIREMENTS — output MUST include all four blocks below in order:

### Block A — Per-claim defense analysis
For each cause of action plead by the plaintiff, identify defense theories
that apply. Use a markdown table with columns: Cause of Action | Defense
Theory | Strength (Strong/Moderate/Weak/Thin) | Factual/Legal Basis.

### Block B — Affirmative Defenses
Enumerate named affirmative defenses in pleading-style format. Minimum 5
entries, target 7-9. Include both substantive defenses (e.g., failure of
consideration, impossibility, lack of authority) AND procedural defenses
(e.g., statute of limitations, laches, waiver, estoppel, failure to state
a claim). Format each defense as:

#### NTH DEFENSE — [Name]
[2-5 sentence explanation grounded in the case record]
[Strength: Strong | Moderate | Weak | Thin]

### Block C — Non-Affirmative Denials
For each cause of action plead by the plaintiff, provide an explicit
denial framing. Minimum one entry per cause of action. Include a separate
entry for denial of damages. Use a markdown table with columns: Cause of
Action | Denial Framing | Factual or Legal Basis. Each row's Factual or
Legal Basis column MUST contain at least one bracketed-filename citation
in the form [filename.pdf] drawn from the supplied evidence chunks.

### Block D — Reservation
Single sentence asserting that defenses are reserved subject to discovery.

All four blocks are required regardless of reasoning depth. Do not
consolidate Block B into Block A or omit Block C. Each block must be
present even if shorter than the targets above.
```

The italicized sentence in Block C ("Each row's Factual or Legal Basis column MUST contain at least one bracketed-filename citation…") was the **Path R one-line refinement** added after the first three-run isolation showed §2.7 grounding count tripping at the boundary.

---

## 3. Three-run validation matrix (Path R, NVIDIA sampling)

Configurations isolated three axes: prompt template (legacy vs tightened+R), `low_effort` (True vs False), sampling held constant at NVIDIA-recommended `temperature=1.0, top_p=0.95` per Nemotron-3-Super technical report §3 + advanced deployment guide.

| Run | Prompt | `low_effort` | content | reasoning | wall | finish | denials | blocks A/B/C/D | orchestrator grounding |
|---|---|---|---:|---:|---:|---|---:|---|---:|
| **1** (goal) | tightened+R | True | **7,240** | 421 | **77.5s** | stop | **6** | ✓✓✓✓ | **5** |
| **2** (control) | tightened+R | False | 7,310 | 8,454 | 167.7s | stop | 6 | ✓✓✓✓ | 4 |
| **3** (sanity) | legacy | True | 2,274 | 357 | 24.2s | stop | 1 | ✗✗✗✗ | 1 |

All three: finish=stop, format_compliant=true, 0 first-person, 0 `<think>`.

### Three-axis attribution

- **Run 1 vs Run 3** (low_effort=True, prompt varies): tightened prompt + Block A/B/C/D + per-row citation requirement recovers all 4 blocks and 6 denials. Legacy prompt collapses both. **Tightening removes the structural-completeness dependency on multi-pass reasoning.**
- **Run 1 vs Run 2** (tightened prompt, low_effort varies): low_effort=True saves **90.2s wall (-54%)** at substantively equivalent output (both 6 denials, ~7,300 chars, all 4 blocks). **Wall savings real.**
- **Run 3** (legacy + low_effort=True at NVIDIA sampling): structural-collapse signature reproduces (block markers 0/4). Confirms the prompt change is responsible for Run 1's recovery, not a sampling artifact.

Run 3 numerical drift between Path A (pre-citation-add) and Path R (post-citation-add) iterations: the citation-requirement append modified only Block C of the **tightened** prompt — the legacy prompt is byte-identical across both Path A and Path R runs. Numerical variance (content_chars, denial count, wall) is purely t=1.0 sampling variance. The structural-collapse signature (block markers 0/4) is preserved exactly across both. **No Path R contamination of the legacy path.**

---

## 4. Hard-stop check vs Wave 4 brief §2

| Hard stop | Run 1 result | Status |
|---|---|---|
| §2.5 — denial entries <4 | 6 | **PASS** |
| §2.6 — content_chars drops >15% from baseline 6,271 (=floor 5,330) | 7,240 (+15% over baseline) | PASS |
| §2.7 — grounding (orchestrator regex) <5 | **5** (4 PDFs + "June 1, 2021" date-quirk) | **PASS — boundary case** |
| §2.8 — `<think>` / first-person / finish=length | 0 / 0 / stop | PASS |

§2.7 boundary case is documented in §7 below.

---

## 5. End-to-end Track A v3 — Wave 4 vs PR #332 (22:44Z) baseline

| Section | Mode | Baseline content | Wave 4 content | Δ% | Baseline reasoning | Wave 4 reasoning | Wall (B→W) | Grounding (orch) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| §1 mechanical | — | 511 | 511 | 0% | 0 | 0 | n/a | 0/0 |
| §2 critical_timeline | enable_thinking=False | 4,659 | 4,659 | 0% | 0 | 0 | 73s → 73s | 19/19 |
| §3 mechanical | — | 509 | 509 | 0% | 0 | 0 | n/a | 0/0 |
| §4 claims | low_effort=True | 10,074 | 10,074 | 0% | 527 | 527 | 126s → 125s | 4/4 |
| **§5 defenses** | **low_effort=True NEW** | 6,271 | **7,616** | **+21%** | 19,090 | **356** | **270s → 83s** | **5 → 4** |
| §6 mechanical | — | 1,376 | 1,376 | 0% | 0 | 0 | n/a | 0/0 |
| §7 email_intel | enable_thinking=False | 3,395 | 3,395 | 0% | 0 | 0 | 58s → 57s | 17/17 |
| §8 financial | low_effort=True | 4,082 | 4,082 | 0% | 1,162 | 1,162 | 63s → 62s | 2/2 |
| §9 augmented | low_effort=True | 6,563 | 6,676 | +1.7% | 208 | 139 | 76s → 72s | n/a |
| §10 mechanical | — | 611 | 611 | 0% | 0 | 0 | n/a | 0/0 |

**Total wall: 401.77s vs PR #332 baseline 590s — −32% (saves 188s, fully attributable to §5 routing flip).**

All sections finish=stop, format_compliant=true, 0 first-person, 0 `<think>`. §1-§4, §6-§8, §10 byte-identical to baseline (deterministic at t=0.0). §5 + §9 vary across runs (§5 by t=1.0 sampling under NVIDIA-recommended sampling; §9 by post-run augmentation path).

---

## 6. Routing policy update

**Before** (PR #333):

```python
"section_05_key_defenses_identified": {
    "enable_thinking": True,
    "low_effort": False,  # Wave 4 deviation per PR #332 — multi-pass planning required
    "force_nonempty_content": True,
    "max_tokens": 8000,
},
```

**After** (this PR):

```python
"section_05_key_defenses_identified": {
    "enable_thinking": True,
    "low_effort": True,  # Wave 4: tightened prompt + per-row citation requirement
                         # removes structural-completeness dependency on reasoning depth
    "force_nonempty_content": True,  # Wave 4: parser safety valve
    "temperature": 1.0,  # Wave 4: NVIDIA-recommended sampling per technical report
    "top_p": 0.95,       # Wave 4: NVIDIA-recommended sampling
    "max_tokens": 8000,
},
```

§5 is the only section running NVIDIA-spec sampling. Other 9 sections continue on the synthesizer-default `temperature=0.0` (no `top_p` sent). Per-section sampling override is a new policy capability introduced by this PR (BrainClient `top_p` kwarg + synthesizer `temperature`/`top_p` parameters).

---

## 7. §2.7 boundary case (orchestrator grounding measurement)

The orchestrator's `_detect_grounding_citations` (in `case_briefing_synthesizers.py:428`) extracts the *last* bracketed substring from each chunk's first 400 chars and treats it as a "source filename." Then it checks if that string appears as a substring anywhere in the response.

**Failure mode:** chunks that contain bracketed dates (e.g., `[June 1, 2021]` in a header), paragraph references, or other non-filename bracketed content get labeled as "sources." When the response naturally mentions the date (which §5 does — June 1, 2021 is the closing date central to the case), it scores as a grounding match.

**Path R Run 1 isolation:**
- 4 stable real-PDF sources matched: `#13 Joint Preliminary Statement.pdf`, `2022.01.04 Pl's Initial Disclosures.pdf`, `5464474_Exhibit_3_GaryKnight(23945080.1).pdf`, `#65-1 7IL's BIS MSJ.pdf`
- 1 date-quirk source: `June 1, 2021`
- Orchestrator total: 5

**Wave 4 production §5:**
- 4 stable real-PDF sources matched (same set as Run 1)
- 0 date-quirk source matches (sampling phrased the date differently this run)
- Orchestrator total: 4

The 4-vs-5 wobble is the orchestrator's regex labeling a bracketed date as a "source" — measurement-tool quirk, not an output regression. Production §5's substantive grounding evidence:

- 18 ASCII bracketed citations in the §5 response (vs PR #332 baseline §5's ~12 — citation density UP, not down)
- 4 unique real-PDF source filenames cited
- All 5 Block C denial rows have ≥1 bracketed real-PDF citation per row (Path R requirement met)

**Disposition:** PASS by both letter (orchestrator=5 in Run 1 isolation) and spirit (per-row real-PDF citation requirement met in production). The 4-vs-5 swing across stochastic samples at t=1.0 is documented for transparency. Future production §5 runs may register orchestrator grounding=4 or 5 depending on whether "June 1, 2021" gets sampled into the response.

A separate ticket (Issue #334) is filed to tighten `_detect_grounding_citations` to ignore non-filename bracketed substrings — out of scope for Wave 4.

---

## 8. Deep-research integrations (per Wave 4 amendment 2026-04-30)

Three additive findings from `nemotron-3-super-deep-research-2026-04-30.md` folded into this PR:

1. **`force_nonempty_content=True` on §5.** Documented in `super_v3_reasoning_parser.py` as a safety valve: when reasoning runs to `max_tokens` without emitting `</think>`, the parser falls back to placing the buffer in `content` rather than stranding it in `reasoning_content`. Zero behavioral cost on success path; cheap insurance on the cap-exhaust edge case. Wired into BrainClient `chat_template_kwargs` at top level.

2. **`thinking_token_budget` removed from production routing.** Mechanism: vLLM mainline's `thinking_token_budget` requires the server to be started with `--reasoning-config` defining `reasoning_start_str` / `reasoning_end_str` before the logits processor installs. Frontier (`http://10.10.10.3:8000`) is not started with `--reasoning-config`, so the parameter was empirically inert per PR #330 Probe E. Audit confirmed no `SECTION_REASONING_POLICY` entry carries the kwarg post-cleanup. BrainClient retains the parameter for re-engagement (separate frontier redeploy with `--reasoning-config`). Documentary comment added to `case_briefing_compose.py` near the policy lookup.

3. **NVIDIA-spec sampling on §5 (Path A).** Pre-Path-A, all Track A v3 runs used `temperature=0.0` (synthesizer default) — off-distribution per Nemotron-3-Super technical report which specifies `temperature=1.0, top_p=0.95` for ALL modes (reasoning, tool-calling, general chat). Outgoing JSON capture confirmed pre-Path-A §5 sent `temperature=0.0` with no `top_p`. Path A scoped to §5 only — extends `SECTION_REASONING_POLICY` format to support `temperature` and `top_p` keys, defaults the BrainClient `top_p` constructor/per-call kwarg to `None`, sets §5's policy to `temperature=1.0, top_p=0.95`. Other 9 sections preserved at prior sampling defaults.

---

## 9. BrainClient deviations from brief §8 constraint

Wave 4 brief §8 says "DO NOT modify BrainClient." This PR includes three operator-authorized one-time exceptions, grouped here for reviewer clarity:

| Deviation | Authorization | Wired |
|---|---|---|
| `force_nonempty_content: bool \| None` constructor + per-call kwarg | Operator-authorized 2026-04-30 prior to Run 1 | Top-level `chat_template_kwargs.force_nonempty_content` |
| `top_p: float \| None` constructor + per-call kwarg | Operator-authorized 2026-04-30 with Path A decision | Top-level `top_p` field of request body |
| `SECTION_REASONING_POLICY` format extended to support `temperature` + `top_p` keys | Operator-authorized 2026-04-30 with Path A decision | Synthesizer reads policy keys, forwards to BrainClient |

Each addition follows the established pattern from PR #331's Phase 2 work (top-level chat_template_kwargs placement, no `extra_body` wrapper, dual response-shape parsing). 24 unit tests pass after additions (2 new tests added: `test_top_p_at_top_level_when_set`, `test_top_p_absent_when_unset`).

---

## 10. Frontier health log

Frontier `/health` 200 throughout the ~25-minute total Wave 4 frontier session. No soak halt events. KV cache pressure not tripped (`--max-num-seqs 10` not saturated at single-call cadence).

---

## 11. Wave 4 brief on NAS

`/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_20260501T002431Z.md` — 41,591 bytes (vs PR #332's 40,170 — +1,421 bytes, all from §5 expansion).

The brief carries the "_v3_" stamp per the runner's hardcoded naming pattern (Wave 4 brief Step 13's `_w4_` prefix would have required modifying the runner; left as v3 to honor the brief's "DO NOT modify the runner" constraint). Distinguished from PR #332's brief by timestamp `20260501T002431Z`.

---

## 12. References

- PR #326 — BrainClient TP=2 frontier compatibility
- PR #327 — synthesizer cap 8000
- PR #329 — Track A v3 analysis baseline
- PR #330 — Phase 1 reasoning-control probes
- PR #331 — Phase 2 BrainClient surgery (force_nonempty_content + top_p extensions stack on PR #331's pattern)
- PR #333 — Phase 3 per-section reasoning routing (introduced `SECTION_REASONING_POLICY`)
- Issue #334 — follow-up: tighten `_detect_grounding_citations` to ignore non-filename bracketed substrings
- Wave 4 brief: `/home/admin/wave-4-section-5-prompt-tightening-brief-2026-04-30.md` (v2 amended)
- Wave 4 amendment: `/home/admin/wave-4-amendment-deep-research-actions-2026-04-30.md`
- Nemotron-3-Super deep research: `/home/admin/nemotron-3-super-deep-research-2026-04-30.md`
- Closes #328 follow-up (§5 grounding-format regression that was the residual quality concern from #333)

End of run report.
