# EMBED Restart Verification — Wave 1 Close-Out

**Date:** 2026-04-30 (verification run 2026-05-01T01:02:46Z UTC = 2026-04-30 21:02 EDT)
**Branch:** `chore/embed-restart-verification-2026-04-30` (from `origin/main` at `e0e5b9632` — Wave 4 §5 merge)
**Closes:** Wave 1 of `nemotron-super-stack-architecture-2026-04-30.md`. Single-node TP=1 fit retired by operator amendment (`/home/admin/wave-1-single-node-closed-amendment-2026-04-30.md`); EMBED activation was the last remaining Wave 1 gate.
**Pairs with:** PR #300 (`llama-nemotron-embed-1b-v2 deployment + gateway cutover (2026-04-29)`) — already merged on main; this PR is the post-restart verification record proving yesterday's deployment is reproducible.

---

## 1. Why this PR exists

Yesterday (2026-04-29) the EMBED NIM was deployed and verified end-to-end on spark-3:8102 — that work merged to main as PR #300 at 06:12 EDT today. The service ran cleanly for 15h 7min, then was stopped by the operator at 12:08 EDT today for unrelated reasons (clean `systemctl stop`, exit 0, 22.8M unit memory peak, no errors).

This PR documents the restart + verification at 21:02 EDT confirming yesterday's deployment is reproducible after operator-initiated stop/start. No code changes; doc-only ratification record so the Wave 1 close has a durable artifact.

---

## 2. Pre-restart state (per kickoff §2.1 / §2.2)

| Check | Expected | Actual |
|---|---|---|
| `fortress-nim-embed.service` enabled | yes | yes |
| `fortress-nim-embed.service` active | inactive (since 12:08 EDT) | inactive |
| Port 8102 free | yes | yes |
| Image `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0` (digest `c559ea63`) | present | present (`c559ea6367af`, 4.49 GB) |
| Weights staged on NAS | yes (162 files) | 162 files |
| Frontier (`http://10.10.10.3:8000/health`) 200 throughout | required | 200 ✓ |

All pre-restart gates green. No GPU pressure read available (`nvidia-smi` returns `[N/A]` on Spark GB10 silicon — known driver limitation; vllm_node TP=2 partner running successfully on the same GPU is the indirect signal).

---

## 3. Restart execution

```sh
ssh admin@192.168.0.105 'sudo systemctl start fortress-nim-embed.service'
```

- Issued at 2026-05-01T01:02:46Z (21:02:46 EDT)
- `Active: active (running)` confirmed at +30s
- `/v1/health/ready` returns 200 at +42s (well within the 60s STOP-gate threshold)
- Container running as `fortress-nim-embed` from `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest`, port mapping `8102:8000`
- Weights loaded from cached snapshot `fp16-7af2b653` (no NGC re-pull — sovereign-pull-and-stage pattern working as designed)

ExecStartPre `docker stop` / `docker rm` exited with status=1 as expected (no prior container to stop/remove since `--rm` cleaned up at the 12:08 EDT shutdown). systemd allows these to fail per the unit's `ExecStartPre` semantics.

---

## 4. Verification matrix (§2.5 / §7 of the brief)

| Probe | Yesterday (9c5f45380) | Today (post-restart) | Status |
|---|---|---|---|
| Service active | yes | yes (running) | ✓ |
| Port 8102 listening | yes | yes (HTTP 200 health) | ✓ |
| Direct `/v1/models` | `nvidia/llama-nemotron-embed-1b-v2` | `nvidia/llama-nemotron-embed-1b-v2` | ✓ |
| Direct `/v1/embeddings` vec_dim | 2048 | **2048** | ✓ |
| `legal-embed` alias resolves on `:8002` | yes | yes (alongside `legal-reasoning`, `legal-drafting`, `legal-summarization`, `legal-brain`, `legal-classification`) | ✓ |
| Gateway-routed `/embeddings` vec_dim | 2048 | **2048** | ✓ |
| Zero cloud outbound during probes | 0 | **0** (NIM journal + local journal both clean for `openai.com`/`anthropic.com`/`googleapis.com`) | ✓ |
| Cosine quality margin > 0.05 | 0.754 (different sentences) | **0.5242** | ✓ PASS |
| Frontier `/health` 200 throughout | n/a (was already up) | 200 ✓ | ✓ |

### Cosine quality detail

Three test sentences:
- **A:** "defendant filed a motion for summary judgment under Rule 56"
- **B:** "plaintiff opposes summary judgment under Federal Rules of Civil Procedure 56" (semantically related to A)
- **C:** "I baked a chocolate cake for my daughter's birthday party" (unrelated)

| Pair | Cosine |
|---|---:|
| cos(A, B) (legal pair) | 0.6073 |
| cos(A, C) (unrelated) | 0.0831 |
| **margin** | **0.5242** |

Yesterday's exact sentences differed; the threshold (>0.05) and direction (legal pair >> unrelated) are what reproduces. Margin 0.5242 is well above floor.

---

## 5. Sovereignty check

Zero outbound to `openai.com` / `anthropic.com` / `googleapis.com` / `api.together.xyz` during the verification probes. Both the NIM container's journal (spark-3) and the local journal show 0 hits across the 3-minute probe window. Contains-cloud constraint preserved.

---

## 6. Hard-constraint audit

| Constraint | Status |
|---|---|
| Don't touch Vision NIM / port 8101 | ✓ untouched (deferred per operator amendment) |
| Don't modify nomic-embed-text Ollama config | ✓ untouched |
| Don't reindex Qdrant collections | ✓ untouched |
| Don't modify `legal_council.py` / `freeze_context` / Phase B retrieval | ✓ untouched |
| Don't modify BrainClient / `case_briefing_synthesizers.py` (Wave 4 work) | ✓ untouched |
| Don't modify frontier endpoint / vllm_node config | ✓ untouched |
| No `--admin`, no `--force` (force-with-lease only), no self-merge | n/a (this PR is doc-only, no force-push needed) |

---

## 7. What this PR closes / advances

- **Closes Wave 1** of `nemotron-super-stack-architecture-2026-04-30.md`. Single-node TP=1 fit retired by operator amendment; EMBED was the only remaining gate.
- **Validates** the sovereign pull-and-stage pattern (NGC pull on spark-2 → NAS-canonical weights → tarball-load on inference cluster). Confirmed reusable for Wave 3 (Reranker + Extraction NIMs).
- **Opens Wave 2** — TITAN (second Nemotron-3-Super-120B-A12B NVFP4) deployment on spark-5 replacing retired BRAIN-49B. Wave 2 brief writes against this validated NIM deployment pattern.
- **Sets up Wave 3** — Retrieval stack (Reranker + Extraction + Qdrant reindex) and Phase B retrieval cutover.

---

## 8. Operator-resolved scope (per kickoff)

- **EMBED stop at 12:08 EDT was operator-initiated.** Triage confirmed clean exit, no defect, no co-residency issue with TP=2 frontier (15h coexistence before stop).
- **Vision NIM is DEFERRED.** §9 "Vision NIM (port 8101) must keep serving" constraint dropped from this work. Vision NIM has no journal entries this boot — separate concern, out of scope.
- **Single-node TP=1 fit RETIRED.** Production topology is TP=2 over spark-3+spark-4 per `/home/admin/wave-1-single-node-closed-amendment-2026-04-30.md`.

---

## 9. References

- PR #300 — original EMBED deployment + gateway cutover (merged 2026-04-30 06:12 EDT)
- Existing cutover record: `docs/operational/llama-nemotron-embed-deployment-2026-04-29.md` (already on main via PR #300, untouched here)
- Wave 1 single-node amendment: `/home/admin/wave-1-single-node-closed-amendment-2026-04-30.md`
- Wave 1 brief: `/home/admin/embed-deployment-final-stretch-brief.md` (verification template only — no new work)
- Kickoff (executed): `/home/admin/claude-code-kickoff-wave-1-restart-verify-ratify-2026-04-30.md`
- Superseded kickoff: `/home/admin/claude-code-kickoff-wave-1-close-embed-activation-2026-04-30.md` (discarded — premise was pre-deployment; reality was already-deployed-and-stopped)

---

## 10. Post-merge

Wave 1 closes. Wave 2 TITAN deployment brief gets drafted next.
