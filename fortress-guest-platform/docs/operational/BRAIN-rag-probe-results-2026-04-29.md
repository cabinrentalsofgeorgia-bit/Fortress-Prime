# Phase A5 — BRAIN + RAG Probe Results (2026-04-29)

**Branch:** `feat/brain-rag-probe-phase-a5`
**Operator:** Gary Knight
**Executor:** Claude Code on spark-2 (orchestrating; calling spark-5:8100 over Tailscale)
**Brief:** `/home/admin/phase-a5-brain-rag-probe-brief.md`
**Result:** **FAIL** — probe fails the §7 latency gate on both runs and is non-deterministic at temp=0. Retrieval, streaming finish-reason, grounding, and error-handling all PASS. Operator review required per §8 + §9.

---

## 1. Summary

| Criterion | Run 1 | Run 2 |
|---|---|---|
| Result | **FAIL** | **FAIL** |
| Retrieval (work-product / privileged) | 30 / 0 | 30 / 0 |
| Streaming `finish_reason` | `stop` | `stop` |
| TTFT | 4.94 s | 0.31 s |
| Total elapsed | **308.7 s** | **366.4 s** |
| Latency gate (60 s) | ✘ exceeded | ✘ exceeded |
| Grounding citations matched | 8 | 9 |
| Privilege chunks appended | NOT_NEEDED (0 hits) | NOT_NEEDED (0 hits) |
| Errors | none | none |
| Prompt tokens (approx) | 4,676 | 4,676 |
| Completion tokens (approx) | 1,151 | 1,416 |

**Determinism check (run1 vs run2 response_text byte-equality):** ✘ **NOT byte-equal** — the responses diverge at byte 1275 (line 8 inside the model's `<think>` block) and the final answers also differ in length and section ordering. Retrieved chunk IDs are identical between runs (RAG side is deterministic); the divergence is on the BRAIN inference side at temp=0.

---

## 2. Pass / fail breakdown vs §7 gates

```
PASS = retrieval >= 10 AND finish_reason=stop AND grounding >= 3 AND latency < 60s
```

| Gate | Run 1 | Run 2 |
|---|---|---|
| `retrieval_min_chunks` (>= 10) | ✓ 30 | ✓ 30 |
| `finish_reason_stop` | ✓ | ✓ |
| `grounding_min_citations` (>= 3) | ✓ 8 | ✓ 9 |
| `latency_under_gate` (< 60 s) | **✘ 308.7 s** | **✘ 366.4 s** |
| `no_error` | ✓ | ✓ |

Both runs fail the latency gate. All other gates pass cleanly.

---

## 3. Latency analysis

* **TTFT was healthy on both runs** (4.94 s on the cold first call, 0.31 s on the warm follow-up). The streaming path itself is responsive.
* The remainder is **token-generation wall time** for the 49B FP8 Nemotron model: 1,151 → 1,416 emitted tokens at roughly 3.7–3.9 tok/s.
* This is consistent with the published per-token throughput for `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` on a single DGX Spark node serving via NIM 2.0.1 / vLLM at this prompt length (≈4.7k input tokens).
* The §7 gate of `< 60 s total` is not satisfiable for a 2,000-`max_tokens` reasoning answer at the current per-token rate. Either:
  1. **Raise the latency gate** to a value consistent with the model's measured throughput (e.g. 8–10 minutes for max_tokens=2000), or
  2. **Lower max_tokens** for retrieval-grounded answers (e.g. cap at 600 tokens, which would land near the gate), or
  3. **Move BRAIN to a faster backend** (multi-node tensor-parallel, FP4/INT4 quant, or a non-reasoning model for short-answer paths).

This is an operator decision — see §6 below.

---

## 4. Determinism observation

The brief expected byte-equal output across run1 and run2 at `temperature=0`. That expectation **did not hold** on the current BRAIN deployment.

* RAG side is fully deterministic — top-15 retrieved chunk IDs are identical between runs (verified head-of-list; full `retrieved_chunk_ids` blocks committed alongside this doc).
* Inference side diverges. Both runs use `temperature=0.0` and identical messages; the model still produces different reasoning traces and slightly different formatting.

This pattern is consistent with vLLM's documented non-determinism under default settings (varying batch composition, FP8 dequant rounding, attention kernel selection). The Probe-1 BRAIN behavior cited in the brief was captured against an older NIM image and a different request-mix; current behavior is no longer byte-stable. Operator may want to:

* Capture this as a separate finding before relying on byte-equality for vault/audit replay, or
* Accept semantic equivalence as the acceptance contract for downstream Council swap.

---

## 5. Retrieval evidence (run 1)

* Primary case `7il-v-knight-ndga-i`: 15 chunks, top score 0.661.
* Related matter (resolved from `legal.cases.related_matters`): 1 sibling slug, 15 additional chunks, top score 0.652.
* Privileged collection (`legal_privileged_communications`) for `7il-v-knight-ndga-i`: 0 chunks. The probe still issued the privileged query — the FYEO appender simply had nothing to attach.

Grounded source citations matched in the run-1 response:

```
#65 7IL's MSJ.pdf
#58 Jt. Mtn. for Ext. of Deadline to File MSJ.pdf
#84 Jt. Mtn. to Ext. Time.pdf
#71-1 7 IL RIOT Knight SOUF.pdf
#71 7 IL RIOT Knight MSJ.pdf
2023.01.11 DN - GB.docx.pdf
#87 EOA - Sanker.pdf
2023.01.27 DN - AW.docx.pdf
```

---

## 6. Operator decision points

1. **Latency gate:** is `< 60 s total` the right contract for a 2,000-token reasoning answer, or should the gate move to TTFT (< 5 s) plus a per-token throughput floor?
2. **Determinism:** drop the byte-equality expectation, or pin BRAIN to a deterministic vLLM config before relying on this path for vault audits?
3. **Privileged retrieval:** zero hits for `7il-v-knight-ndga-i` is plausible (case may not have privileged comms ingested yet) but worth a separate sanity check. The probe code still exercised the path correctly and would surface chunks if present.

These are why the PR is opened with **merge blocked pending operator review** rather than self-merged.

---

## 7. Reproduction

```bash
cd ~/Fortress-Prime/fortress-guest-platform
source venv/bin/activate
source .env  # picks up BRAIN_BASE_URL=http://spark-5:8100 (Tailscale)

python -m backend.scripts.brain_rag_probe \
  --case-slug 7il-v-knight-ndga-i \
  --question "Summarize the procedural posture of Case I as of 2024-03-12, including counsel changes and dispositive motion practice." \
  --max-tokens 2000 \
  --top-k 15 \
  --include-privileged \
  --output /tmp/probe-a5-run1.json
```

Re-run with `--output /tmp/probe-a5-run2.json` for the determinism comparison.

---

## 8. Appendix — run records

The full JSON probe records are committed alongside this doc (sensitive privileged response text would be redacted before commit; this run had zero privileged chunks so nothing required redaction).

* `BRAIN-rag-probe-results-2026-04-29.run1.json`
* `BRAIN-rag-probe-results-2026-04-29.run2.json`

These mirror `/tmp/probe-a5-run1.json` and `/tmp/probe-a5-run2.json` from the executed runs.
