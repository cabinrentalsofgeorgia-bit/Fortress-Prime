# Spark-4 Service Rationalization Plan — Pre-stage for ADR-006 TP=2 Cutover

**Date:** 2026-04-30
**Status:** DRAFTED — doc-only PR; awaiting operator review
**Driver:** ADR-006 LOCKED on main (commit 25dcd11d5) reassigns Phase 2
TP=2 BRAIN partnership from spark-5+spark-6 to **spark-5+spark-4**.
The TP=2 cutover brief
(`docs/operational/briefs/tp2-brain-phase-2-cutover-2026-04-30.md`)
§4.1 calls for stopping spark-4 Ollama + SenseVoice before TP=2 startup
and §3.3 estimates spark-4 working set at ~30 GB. Reality on 2026-04-30
is much lighter (5.6 GiB), but Ollama's 72 GB on-disk model footprint
and SenseVoice's GPU usage need a documented placement decision **before**
the cutover-execution PR runs.

This brief is the **plan**, not the **execution**. Every action listed
under §3 / §4 lands in the cutover-execution PR or in subsequent caller-
migration PRs. **Nothing in this PR changes a service.**

**Stacks on:** ADR-004 v2 amendment (retain-and-document), ADR-006
(Phase 2 partner reassignment), TP=2 cutover brief.
**Closes pre-stage requirement for:** TP=2 cutover §4.1 prerequisites.

---

## 1. Spark-4 current state (verified read-only 2026-04-30)

| Item | Value |
|---|---|
| Hostname | `Spark-4` |
| IP | 192.168.0.106 |
| Architecture | aarch64 (ARM64) |
| GPU | NVIDIA GB10 (Spark) |
| RAM | 121 GiB total, **5.6 GiB used, 116 GiB available** |
| Swap | 0 used / 15 GiB |
| Root disk | 3.7 TiB total, **222 GiB used (7%)**, 3.3 TiB free |
| Ollama on-disk model footprint | **72 GiB** at `/usr/share/ollama/.ollama/models` |
| Ray membership | ALIVE worker against spark-2 head (192.168.0.100:6390); Ray budget 87.6 GiB at join time |

### 1.1 Active services

| Service | Port | Image / unit | Notes |
|---|---|---|---|
| `ollama.service` (systemd) | 11434 | host install | 6 models cached; load-on-demand (idle in RAM at audit) |
| `fortress-qdrant-vrs.service` (Docker) | 6333 | `qdrant/qdrant:latest` | 1 collection: `fgp_vrs_knowledge` (the dual-write target) |
| `sensevoice` (Docker) | 8000, 6006 (TB), 8888 (Jupyter) | `fortress/sensevoice:v2-arm64` | NVIDIA PyTorch 24.02 base (CUDA 12.3, TRT 8.6.3, Python 3.10), `NVIDIA_VISIBLE_DEVICES=all` — **uses GPU** |
| `fortress-ray-worker.service` (systemd) | various | host install | Ray worker against spark-2 GCS |

### 1.2 Ollama model inventory (spark-4)

| Model | Size | Tier | Caller surface (per ADR-004 v2 amendment) |
|---|---|---|---|
| `deepseek-r1:70b` | 42.5 GB | TITAN candidate | `crog_concierge_engine.HYDRA_120B_URL` default; legal/finance deep reasoning |
| `qwen2.5:32b` | 19.9 GB | SWARM heavy | `fortress-guest-platform/.env` SWARM_URL (some paths), HYDRA_FALLBACK_URL |
| `qwen2.5:7b` | 4.7 GB | SWARM light | `fortress_atlas.yaml` (vrs_fast_primary); **duplicate of spark-3's qwen2.5:7b** |
| `mistral:latest` | 4.4 GB | utility | `ingest_taylor_sent_tarball.py`, `reclassify_other_topics.py`, `sent_mail_retriever.py` callers |
| `llava:latest` | 4.7 GB | vision (legacy) | unused per current code grep — confirm before retirement |
| `nomic-embed-text:latest` | 0.3 GB | embed | **duplicate of spark-3's nomic-embed-text** |

### 1.3 Spark-3 capacity check (consolidation target)

| Item | Value |
|---|---|
| Hostname | `spark-3` |
| RAM | 121 GiB total, **76 GiB used, 44 GiB available** |
| Ollama on-disk footprint | 82 GiB at `/home/admin/.ollama/models` |
| Existing models | `qwen2.5:7b` (4.7), `llama3.2-vision:90b` (54.6), `llama3.2-vision:latest` (7.8), `nomic-embed-text:latest` (0.3) |
| Active NIMs | `fortress-nim-vision-concierge:8101` (10 GB working), `fortress-nim-embed:8102` (8 GB working) |
| Disk free | ~3.0 TiB |

**Spark-3 RAM is tight (44 GiB available).** Adding qwen2.5:32b (19.9 GB
on disk; ~16 GB in RAM when loaded) would push spark-3 to ~28 GiB
available (77% utilization). Doable but tighter than spark-4 alternatives.

---

## 2. Decisions to make

### 2.1 Ollama on spark-4 — TP=2 cutover behavior

vLLM TP=2 wants spark-4's GPU exclusively. Ollama keeps its models in
host RAM (not VRAM) but loads layers into GPU on inference. **At least
during TP=2 inference windows, no Ollama model may serve from spark-4's
GPU.** Three options:

| Option | What | Tradeoff |
|---|---|---|
| **A. Stop ollama.service entirely during TP=2** | `systemctl stop ollama` before TP=2 startup; restart on rollback | Full GPU isolation. Callers using spark-4 ollama get connection-refused. Requires either (a) caller redirect to spark-3 first, or (b) accept caller failures during cutover window |
| **B. Keep ollama running, models unloaded** | ollama `keep_alive=0` / aggressive eviction | Ollama still binds GPU on next inference call → contention with vLLM. **Not safe for TP=2.** |
| **C. Move ollama traffic to spark-3 first, then stop on spark-4** | Caller-redirect PR first; then stop ollama on spark-4 cleanly | Cleanest for callers. Requires upstream work before TP=2 cutover. ADR-004 v2 amendment §"Open follow-ups" already lists ollama consolidation as P4 with this exact requirement. |

**Recommendation: Option C, scoped to redirectable models only.**

| Model | Move to spark-3? | Action | Why |
|---|---|---|---|
| `nomic-embed-text:latest` | already there | **Caller redirect, no copy needed** | Identical model, identical name; just point spark-4 callers at spark-3 (or use the embed NIM at spark-3:8102) |
| `qwen2.5:7b` | already there | **Caller redirect, no copy needed** | Identical; spark-3 already serves it |
| `mistral:latest` | yes (4.4 GB) | `ollama pull mistral` on spark-3, then redirect callers | Light model; spark-3 RAM headroom sufficient |
| `llava:latest` | **retire** | Confirm no live callers, then drop | Code grep shows no production references; legacy |
| `qwen2.5:32b` | **stay on spark-4 OR retire** | Decide based on caller usage | If callers use it (HYDRA_FALLBACK), stay on spark-4 with stop/start around TP=2 windows. If unused, retire. |
| `deepseek-r1:70b` | **stay on spark-4** | Stop only during TP=2 inference window | TITAN-tier; too big to move (42.5 GB → spark-3 would exhaust RAM); keep on spark-4 with explicit start/stop bracketing of TP=2 sessions |

**Caller-redirect PRs needed before any spark-4 ollama stop:**
1. `crog_concierge_engine.HYDRA_120B_URL` — currently spark-4; redirect logic for TP=2 windows
2. `fortress-guest-platform/.env` SWARM_URL + HYDRA_FALLBACK_URL — point at spark-2 ollama (control plane) or spark-3 for SWARM-tier; spark-4 only when TP=2 idle
3. `fortress_atlas.yaml` — `vrs_fast_primary: spark-4` and `deep_reasoning_redundancy: spark-4` paths
4. Caller code (`ingest_taylor_sent_tarball.py`, `reclassify_other_topics.py`, `sent_mail_retriever.py`, `persona_template.HYDRA_HEAD_4`) for the few hardcoded spark-4 ollama URLs

These are **separate PRs**, not in scope here. This brief documents the plan.

### 2.2 SenseVoice on spark-4 — TP=2 cutover behavior

SenseVoice ARM64 container uses the GPU (`NVIDIA_VISIBLE_DEVICES=all`).
Active 4+ days. Production usage = deposition ASR (audio → text).

| Option | What | Tradeoff |
|---|---|---|
| **A. Stop SenseVoice during TP=2 windows** | `docker stop sensevoice` before TP=2 startup; restart on rollback | Full GPU isolation; deposition ASR offline during TP=2 windows. Acceptable if deposition workload is bursty (manual operator action) and not SLO'd. |
| **B. Keep SenseVoice running, accept GPU contention** | No change | vLLM TP=2 + SenseVoice both on the GB10. CUDA streams will multiplex but TP=2 throughput may degrade and OOM risk on simultaneous large-context inference. **Not recommended.** |
| **C. Migrate SenseVoice to spark-3 or spark-1** | Move container; update operator-side ASR caller | Spark-3 has GPU but is already running 2 NIMs (vision + embed); spark-1 hosts the legal nim-sovereign. Migration is non-trivial — separate brief if pursued. |

**Recommendation: Option A.** SenseVoice is bursty, operator-driven
(no continuous traffic per audit). Stop before TP=2 cutover, restart
on rollback. Long-term, ADR-004 v2 already flags "NIM ASR ARM64
availability triggers SenseVoice replacement" as P3 monitoring — when
NVIDIA ships a NIM ASR ARM64 image, SenseVoice retires.

**Operator decisions surfaced:**
- (D1) Confirm SenseVoice can be offline during TP=2 windows — i.e., no
  active deposition transcription scheduled during the cutover.
- (D2) Decide whether SenseVoice runs on spark-4 long-term or migrates;
  recommendation defers migration until NIM ASR ARM64 lands.

### 2.3 Qdrant-VRS on spark-4 — keep as-is

Per ADR-004 v2 amendment, qdrant-vrs is "light load, no inference
contention." Single collection `fgp_vrs_knowledge` (VRS dual-write
target). **No action.** Port 6333 (TCP) does not contend with vLLM
TP=2's NCCL fabric paths or port 8000 OpenAI endpoint.

The "VRS dual-write retirement triggers fortress-qdrant-vrs migration
to spark-2" follow-up (ADR-004 v2 P5 monitoring) remains separate.

### 2.4 Ray worker on spark-4 — keep registered, dual-cluster aware

ADR-006 cutover brief §3.2 recommends Option B (dedicated TP=2 Ray
sub-cluster on spark-5 head, spark-4 as worker on a different port
than spark-2's existing Ray head). Spark-4's existing
`fortress-ray-worker.service` registers against spark-2's Ray head on
:6390; the TP=2 sub-cluster uses :6380 (per cutover brief §4.3). The
two Ray clients can coexist on spark-4 as long as the vLLM container
has its own Ray daemon lifecycle (the standard NVIDIA stacked-Sparks
pattern).

**No action in this brief.** Cutover PR handles sub-cluster startup.

---

## 3. Cutover prerequisites this brief produces

After operator review of §2, the cutover brief §4.1 prerequisites get
concrete pre-cutover steps:

| Prereq | Concrete action |
|---|---|
| "Drain spark-4 Ollama traffic — point any callers at spark-3 ollama" | (a) Open caller-redirect PRs per §2.1's list of 4 caller surfaces; (b) merge them; (c) verify spark-4 ollama traffic ≤5%/min via systemd journal grep before TP=2 cutover |
| "Stop spark-4 Ollama: `sudo systemctl stop ollama`" | Authorized after (c) above |
| "Stop spark-4 SenseVoice if not actively used" | Operator confirms D1 (no active depositions); `docker stop sensevoice` |
| "Verify spark-4 RAM working set drops to under 30GB after stops" | `ssh admin@192.168.0.106 'free -h'`; expect drop from current 5.6 GiB (already under) to a similar level (Ollama is idle in RAM regardless) |

---

## 4. Caller-rewrite work (separate PRs, not in this brief)

Tracked under ADR-004 v2 amendment "Open follow-ups" P4 (ollama
consolidation migration). The 4 caller surfaces:

1. **`crog_concierge_engine.py`** — `HYDRA_120B_URL` default. Redirect logic: prefer spark-2 ollama (control plane) for SWARM-tier; fall back to spark-4 only when TP=2 idle.
2. **`fortress-guest-platform/.env`** — `SWARM_URL`, `HYDRA_FALLBACK_URL` defaults. Same logic as above.
3. **`fortress_atlas.yaml`** — `vrs_fast_primary` lane currently lists spark-4; `deep_reasoning_redundancy` lane same. Update to drop spark-4 from primary lane (keep as standby) or move primary to spark-3.
4. **Caller code** — `ingest_taylor_sent_tarball.py`, `reclassify_other_topics.py`, `sent_mail_retriever.py`, `persona_template.HYDRA_HEAD_4` — hardcoded `spark-4:11434` references. Convert to env-based URL with defaults that prefer spark-2/spark-3.

Suggested grouping: one PR per file/area; each independently mergeable;
all merged before the spark-4 ollama stop authorization.

---

## 5. Risk matrix

| Risk | Likelihood | Mitigation |
|---|---|---|
| Caller hits spark-4:11434 mid-TP=2 (connection-refused) | Medium if cutover before all 4 caller-rewrite PRs land | Block cutover authorization on all 4 caller PRs merged + 24h soak |
| Deposition ASR needed during TP=2 window | Low (operator-paced) | D1 confirms cutover window; communicate to legal team; rollback path restores SenseVoice |
| qwen2.5:32b unused-but-thought-used → caller failure on retire | Low | Pre-retirement audit: 7-day grep of journalctl for actual model name in ollama logs; retire only if zero usage |
| spark-3 RAM exhaustion if all 4 spark-4 models migrate | Low (only mistral suggested for migration) | Recommendation §2.1 keeps qwen2.5:32b + deepseek-r1:70b on spark-4; only mistral moves |
| Long-term: SenseVoice on spark-4 conflicts with future TP=2 sessions | Medium (recurring) | Stop/start choreography in cutover runbook; long-term ADR-004 v2 P3 NIM ASR ARM64 replacement closes this |

---

## 6. Definition of done (this brief)

- [x] Spark-4 current state captured (services, models, RAM, disk)
- [x] Spark-3 consolidation-target capacity verified
- [x] Ollama model inventory mapped to caller surface
- [x] SenseVoice GPU-usage decision options surfaced
- [x] Qdrant-VRS keep-as-is rationale recorded
- [x] Ray dual-cluster behavior pre-staged for TP=2 cutover §3.2 Option B
- [x] Cutover §4.1 prereqs translated to concrete pre-cutover actions
- [x] Caller-rewrite PR list enumerated (4 surfaces)
- [x] Risk matrix populated
- [ ] Operator decisions D1 (SenseVoice cutover-window allowance) and
      D2 (long-term SenseVoice placement) — **awaiting**
- [ ] Operator confirms recommendation for §2.1 (Option C scoped to
      redirectable models, deepseek-r1 stays on spark-4 with stop/start
      bracketing)

---

## 7. Out of scope

- TP=2 cutover execution itself (separate authorized PR per ADR-006)
- Caller-rewrite PRs themselves (4 separate PRs, this brief lists them)
- Retirement of qdrant-vrs (gated on dual-write retirement, P5 monitoring per ADR-004 v2)
- Replacement of SenseVoice with NIM ASR ARM64 (gated on NVIDIA availability, P3 monitoring per ADR-004 v2)
- Master plan §5.1 / §5.2 doc updates (land in cutover PR)
- Any spark-3 changes (this brief reads spark-3 only as capacity reference; spark-3 is unchanged)

---

End of brief.
