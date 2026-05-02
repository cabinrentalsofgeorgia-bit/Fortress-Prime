# Track A v3 Regression Run — Case I against legal_ediscovery_v2

**Date:** 2026-05-02
**Operator:** Gary Mitchell Knight
**Branch:** `feat/track-a-v3-case-i-vs-v2-regression-2026-05-02`
**Run stamp (this run):** `20260502T125938Z`
**Baseline:** `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md` (run stamp `20260430T224403Z`)
**Case:** `7il-v-knight-ndga-i` (closed; no live-matter risk for regression rerun)
**Verdict:** **PASS — strategic regression per Constitution §12.4. v2 alias swap canonical.**

---

## 1. Pre-flight (all gating probes green)

| # | Probe | Result |
|---|---|---|
| 1 | Frontier `/health` `10.10.10.3:8000` | HTTP 200 |
| 2 | Frontier `/v1/models` | `nemotron-3-super` |
| 3 | Embed NIM `/v1/health/ready` `192.168.0.105:8102` | "Service is ready" |
| 4 | Rerank NIM `/health` `192.168.0.109:8103` | `{"status":"ok"}` |
| 5 | Alias `legal_ediscovery_active` | → `legal_ediscovery_v2` |

Phase-9 soak log for 2026-05-02 was absent (last log 2026-04-30); flagged as informational, not a gating signal.

## 2. Atomic alias swap

```
POST http://localhost:6333/collections/aliases
  delete_alias  legal_ediscovery_active
  create_alias  legal_ediscovery_v2 -> legal_ediscovery_active
```

Operation took 9.2 ms, single Qdrant call, no read-window where the alias was undefined.

Confirmed post-swap: `legal_ediscovery_active` → `legal_ediscovery_v2` (738,917 points, 2048-dim, asymmetric `passage`-indexed).

## 3. Pre-swap validation summary

The original §B.2 inline-curl smoke test surfaced two runbook bugs and one corpus-style observation:

- Runbook bug: model name needs `nvidia/` prefix (NIM rejects bare model id with HTTP 404).
- Runbook bug: `input_type` is required for asymmetric encoder; `query` for retrieval-side, `passage` for ingest-side.
- Observation: `legal_ediscovery_v2` is Georgia state-court litigation pleadings (e.g. `O.C.G.A. § 9-11-12(b)(6)`); does **not** contain federal Twombly/Iqbal precedent. Phase B prompts that emit federal-style citations will systematically miss this corpus. Track A regression rerun is the canonical validation surface, not the dense-only score gate.

Code audit confirmed:

- Ingest (`src/reindex_legal_qdrant_to_legal_embed.py:121`) uses `input_type="passage"` ✓
- Retrieve (`fortress-guest-platform/backend/core/vector_db.py:137`) uses `input_type="query"` ✓
- Production retrieval is dense-only against `legal_ediscovery_active`; no BM25/sparse/RRF leg in the v2 retrieval path. The 0.4 score threshold IS the right gate, but it is a smoke test, not the contract.

## 4. Run execution

```
cd ~/Fortress-Prime/fortress-guest-platform
PYTHONPATH=.:backend .uv-venv/bin/python -m backend.scripts.track_a_case_i_runner
```

Wall: **445.08 s** (7m 25s) — **24.5% faster than baseline (589.68 s)**.
Frontier: 200 throughout, no soak halts, no rerank/embed 5xx.

### Runner-environment delta vs baseline

PR #349 (`60f6d2ea5` — §9 intel-resolver augmentation) introduced `from fortress.legal.intel_resolver import …` in `backend/services/case_briefing_augmentation.py` without arranging for `backend/` to be on `sys.path` for module-style invocation. Production services are unaffected (uvicorn launches with `backend/` as cwd), but `python -m backend.scripts.track_a_case_i_runner` raises `ModuleNotFoundError: No module named 'fortress'`.

**Workaround used here:** `PYTHONPATH=.:backend` at invocation.
**Recommended fix:** add `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))` in the runner — matches `build_golden_memory.py:25` and `run_dgx_swarm_worker.py:29`. Filed as TODO; not in scope of this regression branch.

## 5. Per-section comparison

| § | Section | Mode | Base chars | New chars | Δ | md5 vs base | Format ✓ | Finish |
|---|---|---|---:|---:|---:|---|---|---|
| 1 | Case Summary | mech | 511 | 511 | 0% | identical | true | n/a |
| 2 | Critical Timeline | synth | 4,659 | 4,659 | 0% | **byte-identical** | true | stop |
| 3 | Parties & Counsel | mech | 509 | 509 | 0% | identical | true | n/a |
| 4 | Claims Analysis | synth | 10,074 | 10,074 | 0% | **byte-identical** | true | stop |
| 5 | **Key Defenses Identified** | synth | 6,271 | 9,813 | **+56.5%** | DIFFERS | true | stop |
| 6 | Evidence Inventory | mech | 1,376 | 1,376 | 0% | identical | true | n/a |
| 7 | Email Intelligence | synth | 3,395 | 3,395 | 0% | byte-identical | true | stop |
| 8 | Financial Exposure | synth | 4,082 | 4,082 | 0% | byte-identical | true | stop |
| 9 | Recommended Strategy (raw) | synth | 383 | 39,100 | +10,108% | DIFFERS | true | stop |
| 9 | Recommended Strategy (augmented) | aug | 6,563 | 5,918 | -9.8% | DIFFERS | true | stop |
| 10 | Filing Checklist | mech | 611 | 611 | 0% | identical | true | n/a |

## 6. Determinism finding

Sections 2, 4, 7, 8 produced **bit-identical synthesis output** to the April 30 baseline (md5 match across runs, despite freshly recomputed via `compose()` at 09:07 today). Combined with §1, §3, §6, §10 mechanical-deterministic outputs, **8 of 11 outputs are byte-identical to baseline**.

Implications:

1. Nemotron-3-Super is being served with deterministic decoding (greedy/temperature=0, fixed batching).
2. Retrieval against the v2 collection is returning the same evidence as v1 for these queries — i.e. the v2 reindex did not perturb the retrieval ranking for §2, §4, §7, §8 inputs on this case.
3. The Constitution §12.3 regression contract is highly diagnostic on this stack: any meaningful change shows up as a content change, not noise. Greedy decoding makes per-section md5 a load-bearing comparator.

## 7. Pass-criteria scorecard

| Gate | Criterion | Result |
|---|---|---|
| Finish reasons | 10/10 sections finish=stop | ✓ all synthesis sections stop; n/a for mechanical |
| Format compliance | zero regressions | ✓ all `format_compliant: true`; no first-person leakage; no `<think>` blocks |
| Frontier health | healthy throughout | ✓ pre-flight 200, no errors during run, post-run 200 |
| Soak halts | none | ✓ no halt events |
| Wall time | <12 min budget | ✓ 7m 25s |
| Single CC session per host | yes | ✓ this is the only CC session on spark-2 (tailscale 100.80.122.100) |
| Content ±5% vs baseline | every section within ±5% | ✗ §5 (+56.5%), §9-raw (+10,108%), §9-aug (-9.8%) |

**Hard regression gates: 6/6 pass. ±5% content gate: 3 sections out — analyzed below.**

## 8. Section 9 — architectural change, not regression

§9-raw +10,108% (383 → 39,100 chars) and §9-aug -9.8% (6,563 → 5,918 chars) are both attributable to **PR #349 (`60f6d2ea5`)**, which post-dates the April 30 baseline.

Before PR #349, the orchestrator emitted a 383-char "operator_written placeholder" for §9, and the runner's post-compose augmentation pass produced the user-facing §9 content (6,563 chars in baseline).

After PR #349, the orchestrator emits intel-resolved augmented content inline during compose (39,100 chars), and the post-run augmentation now overlays a refinement on top of an already-augmented section (5,918 chars).

The architectural change is intentional and was reviewed/merged separately. The ±5% gate is not the right comparator for §9 across this PR boundary. Both new outputs were `finish=stop` and `format_compliant=true`.

## 9. Section 5 — operator review verdict

**§5 is the only content delta attributable to the v2 alias swap itself** (§9 deltas are PR #349; §1/3/6/10 are mechanical; §2/4/7/8 are byte-identical). The +56.5% increase in `content_chars` was reviewed at the content level by the operator.

**Operator verdict (verbatim):**

> §5 operator review complete. Verdict: v2 §5 is materially better than baseline.
>
> - Structure now matches Wave 4 four-block design (Block B affirmative defenses 1ST–7TH, Block C denials table, Block D reservation)
> - Three new substantive defenses surfaced: Waiver/Estoppel (five amendments signal), Statute of Limitations (procedural), Failure to State a Claim (negligent misrepresentation specificity)
> - All citations grounded in same evidence corpus baseline used (no hallucination)
> - Strength tags and numbered defense headers improve counsel-readiness
> - Doctrinal upgrade on §13-6-11 attorneys' fees denial framing (prevailing-party basis)

Per Constitution §12.4 (strategic-regression rule), this is a **product improvement under the strategic-regression rule, not a regression**. v2 alias swap is canonical.

## 10. Decision

- v2 alias swap stands. `legal_ediscovery_active` → `legal_ediscovery_v2`.
- No rollback to v1.
- v1 collection retained per locked NAS layout for forensic reproducibility; not deleted.
- Phase B v0.1 prompts may need follow-up tuning for federal-style citation queries that miss the state-court corpus, but that is a prompt-side concern, not a v2 swap-blocker.
- Block C (§9 resolver smoke) proceeds.
- Block E (Wave 7) requires separate operator greenlight after Block C.

## 11. Artifacts

NAS:

- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_20260502T125938Z.md` — 43,047 bytes, runner-default name
- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_vs_v2_20260502T125938Z.md` — 43,047 bytes, regression-suffixed copy per brief

Local:

- `/tmp/track-a-case-i-v3-20260502T125938Z/` — full run dir (sections, raw, metrics, compose-output, assembled brief)
- `/tmp/track-a-case-i-v3-20260430T224403Z/` — April 30 baseline run dir (retained for diff)

In-repo (this branch):

- `docs/operational/track-a-v3-case-i-vs-v2-regression-2026-05-02-artifacts/run-summary-new-20260502T125938Z.json`
- `docs/operational/track-a-v3-case-i-vs-v2-regression-2026-05-02-artifacts/run-summary-baseline-20260430T224403Z.json`

## 12. Cross-references

- Constitution §12.3 — regression discipline (Track A v3 rerun is the canonical contract; dense-only score gate is a smoke test)
- Constitution §12.4 — strategic-regression rule (content improvements under improved corpus are not regressions)
- PR #349 (`60f6d2ea5`) — §9 intel-resolver augmentation (architectural change explaining §9 deltas)
- PR #357 — Fortress Legal Constitution v1+v2 (parent doc)
