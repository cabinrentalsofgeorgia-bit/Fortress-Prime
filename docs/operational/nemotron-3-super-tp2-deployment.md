# Nemotron-3-Super-120B-A12B-NVFP4 TP=2 deployment — spark-3 + spark-4

**Date:** 2026-04-30
**ADR:** [ADR-007 (PROPOSED)](../architecture/cross-division/_architectural-decisions.md)
**Branch:** `feat/nemotron-3-super-tp2-spark34-2026-04-30`
**Operator authorization:** Phase-by-phase greenlights documented per
phase. Phase 7 smoke verdict: PASS. Phase 8 PR opened DRAFT — merge
gated on operator review + 14-day stability soak.

This doc is the consolidated evidence pack for the TP=2 deployment.
Per-phase evidence files (`phase-2-…`, `phase-4-…`, `phase-5-…`)
live alongside in `docs/operational/` for forensic detail.

---

## 1. Decision

Deploy **Nemotron-3-Super-120B-A12B-NVFP4** on **spark-3 + spark-4**
in **tensor-parallel-size=2** configuration (one rank per node, GB10
unified memory) using the community **`eugr/spark-vllm-docker`**
container image and recipe pattern.

This **supersedes Nano-9B** as Fortress Legal synthesizer because the
NemotronH `nemotron_v3` reasoning parser separates `<think>` content
from `content` by architecture, eliminating Nano-9B's first-person-
planning-prose-leaking-into-output failure mode that Phase B v0.3.5
could not solve at the synthesizer level.

## 2. Endpoint

| Field | Value |
|---|---|
| Base URL | `http://10.10.10.3:8000/v1` (fabric A) |
| OpenAI-compatible | `/v1/chat/completions`, `/v1/completions`, `/v1/models` |
| Served model name | `nemotron-3-super` |
| `max_model_len` | 262,144 (256k context; 1M context deferred) |
| `tensor_parallel_size` | 2 (one rank per node) |
| `pipeline_parallel_size` | 1 |
| `kv_cache_dtype` | fp8 |
| `gpu_memory_utilization` | 0.7 (recipe default; ~85 GiB/node committed) |
| `max_num_seqs` | 10 |
| MoE backend | cutlass |
| Attention backend | TRITON_ATTN |
| Reasoning parser | nemotron_v3 (separates `<think>` → `message.reasoning`) |
| Tool-call parser | qwen3_coder |
| Distributed executor | ray |
| Load format | fastsafetensors |
| Mamba SSM cache dtype | float32 |
| Prefix caching | enabled |
| MTP / speculative decoding | **NOT enabled** (deferred per brief) |

## 3. Container + recipe

| Item | Value |
|---|---|
| Container image | `vllm-node:latest` |
| Image SHA | `sha256:330ba87d78eb939efc0212485f346ff4b06db3562140137ad60b06bcc1ca066f` |
| Image size | 18.5 GB (built once on spark-3, NAS-relayed to spark-4) |
| vLLM version (in image) | `0.20.1rc1.dev96+gefdc95674.d20260430` |
| Source repo | https://github.com/eugr/spark-vllm-docker |
| Source HEAD | `9fbed882bcbf051fbe6c9f651cdf8633a1f4b0c9` ("Added EXPERIMENTAL mod for b12x") |
| Recipe (Fortress-custom) | `recipes/nemotron-3-super-nvfp4-local.yaml` |
| Recipe key change vs upstream | `model:` cleared (skips HF Hub existence check); `command:` points at local path `/root/.cache/huggingface/nemotron-3-super-120b-nvfp4` (mount via `HF_HOME=/home/admin/hf-cache`) + `--served-model-name nemotron-3-super` |
| `.env` file | `/home/admin/spark-vllm-docker/.env` on spark-3 (head); contains CLUSTER_NODES, ETH_IF, IB_IF, MASTER_PORT + 7× CONTAINER_* env passthrough vars |
| PR #141 patch | NOT applied. PR #141 (cu130→cu132) is closed-unmerged; upstream pinned `torch==2.11.0+cu130` instead. Build-as-is validated: no `_ZN3c1013MessageLogger` ABI errors observed. |

## 4. Model

| Item | Value |
|---|---|
| HF repo | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` |
| Public access | YES — verified `HTTP/2 200` on unauthenticated `config.json` HEAD; **no `HF_TOKEN` required** |
| NAS canonical path | `/mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/` |
| Local NVMe path (both nodes) | `/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/` |
| In-container path | `/root/.cache/huggingface/nemotron-3-super-120b-nvfp4/` (mounted from `HF_HOME`) |
| Total size | 75 GB |
| File count | 36 model files + MANIFEST.sha256 |
| SHA256 manifest | `MANIFEST.sha256` in dir; verified all 36 model files OK on both nodes (one stale `MANIFEST.sha256.tmp` line is a benign manifest-gen artifact) |

## 5. Network facts

| Item | Value |
|---|---|
| Fabric A subnet | `10.10.10.0/24` (mtu 9000) |
| Fabric B subnet | `10.10.11.0/24` (mtu 9000; standby) |
| spark-3 fabric A IP | `10.10.10.3` (`enp1s0f0np0`) |
| spark-3 fabric B IP | `10.10.11.3` (`enP2p1s0f1np1`) |
| spark-4 fabric A IP | `10.10.10.4` (`enp1s0f0np0`) |
| spark-4 fabric B IP | `10.10.11.4` (`enP2p1s0f1np1`) |
| RoCE InfiniBand HCAs | `rocep1s0f0` (fabric A), `roceP2p1s0f1` (fabric B) — pair used as `NCCL_IB_HCA=rocep1s0f0,roceP2p1s0f1` |
| MTU | **9000** on **all 4 twins per node**, both fabrics, persisted via `/etc/netplan/99-mellanox-roce.yaml` |
| Verified bandwidth | **97.98 Gbps** average, all 4 directions (`ib_write_bw` Phase 3 — see `phase-2-netplan-mtu9000-evidence-2026-04-30.md` and PR #320 evidence pack) |
| TCP/sysctl | bbr + 512 MiB rmem_max + 256 MiB tcp_rmem max — applied to spark-3 in PR #320; spark-4 already canonical |

## 6. Phase 4 build + stage (capsule)

Full evidence: `phase-4-model-container-stage-evidence-2026-04-30.md`.

| Step | Outcome |
|---|---|
| 4.5 build `vllm-node` on spark-3 (`./build-and-copy.sh`) | 15:32 wall, 18.5 GB image, sha256:`330ba87d78eb…`, no ABI errors |
| 4.6 HF download to NAS | 11:46 wall, 75 GB, 36 files, model public (no token) |
| 4.7 NAS → spark-3 local NVMe rsync | 36 files transferred; SHA256 OK (36/36 model files) |
| 4.8 NAS → spark-4 local NVMe rsync | (revised path: NAS direct, not spark-3→spark-4 fabric — ssh auth gap; resolved Phase 5 Q1) 36 files transferred; SHA256 OK |
| 4.9 docker save → NAS tarball → docker load on spark-4 | 18.58 GB tarball; image ID `330ba87d78eb` matches both nodes |

## 7. Phase 5 prereqs (capsule)

Full evidence: `phase-5-prereqs-evidence-2026-04-30.md`.

| Q | Action | Outcome |
|---|---|---|
| Q1 | Generate ed25519 key on spark-3, push to spark-4 `authorized_keys` | `ssh admin@10.10.10.4 hostname` from spark-3 returns `Spark-4` ✅ |
| Q2 | Stop `fortress-nim-vision-concierge.service` (47 GiB GPU released) + `fortress-nim-embed.service` (11.5 GiB released) on spark-3 | both `inactive`; `nvidia-smi --query-compute-apps` empty; ports 8101/8102 clean |
| Q3 | Write `recipes/nemotron-3-super-nvfp4-local.yaml` (1289 B) + `.env` (542 B) on spark-3 | files in place, mode 644 |
| Q4 | Confirm tmux session name `nemotron-super-tp2` | confirmed |

### Stopped services on spark-3 — restart commands (operator decides post-Phase-7)

```bash
# Restart vision NIM (was on :8101 — used by FLOS frontend prior to Nemotron-Super pivot):
ssh admin@192.168.0.105 'sudo systemctl start fortress-nim-vision-concierge.service'
curl -sS http://192.168.0.105:8101/v1/health/ready  # verify

# Restart embed NIM (was on :8102 — used by Phase B retrieval pipeline):
ssh admin@192.168.0.105 'sudo systemctl start fortress-nim-embed.service'
curl -sS http://192.168.0.105:8102/v1/health/ready  # verify
```

**Note:** with TP=2 BRAIN now on spark-3, restarting these NIMs causes
~58 GiB GPU contention. Operator decision deferred to ADR-007 follow-up
(d): "Re-evaluate spark-3 NIM disposition (vision + embed)". Likely
moves vision NIM to spark-1 or spark-2, embed NIM to spark-2 or
retire if Nemotron-Super absorbs use cases.

## 8. Phase 6 launch (transcript milestones)

tmux session: `nemotron-super-tp2` on spark-3.
Launch command: `cd /home/admin/spark-vllm-docker && HF_HOME=/home/admin/hf-cache ./run-recipe.sh recipes/nemotron-3-super-nvfp4-local.yaml --nccl-debug INFO 2>&1 | tee /home/admin/nemotron-super-tp2-launch.log`

| Time (UTC) | Event |
|---|---|
| 16:15:21 | Launch dispatched (host EDT 12:15:21) |
| 16:15:21 | `Loaded .env variables: DOTENV_CLUSTER_NODES … DOTENV_MASTER_PORT` (13 vars) |
| 16:15:46 | `(APIServer pid=537) non-default args: {model: '/root/.cache/huggingface/nemotron-3-super-120b-nvfp4', tensor_parallel_size: 2, gpu_memory_utilization: 0.7, max_model_len: 262144, served_model_name: ['nemotron-3-super'], …}` |
| 16:15:53 | `KV cache fp8 data type` initialized |
| 16:15:57 | EngineCore (pid=656) initializes V1 LLM engine `v0.20.1rc1.dev96+gefdc95674.d20260430` |
| 16:15:57 | Ray env propagation: `Copying environment variables to workers: ['LD_LIBRARY_PATH', 'NCCL_DEBUG', 'NCCL_IB_DISABLE', 'NCCL_IB_HCA', 'NCCL_IGNORE_CPU_AFFINITY', 'NCCL_SOCKET_IFNAME', …, 'VLLM_NVFP4_GEMM_BACKEND', 'VLLM_USE_FLASHINFER_MOE_FP4', …]` |
| 16:16:05 | **NCCL channel-establishment line:** `Spark-4:269:269 [0] NCCL INFO comm 0x390c6980 rank 1 nRanks 2 nNodes 2 localRanks 1 localRank 0 MNNVL 0` from `10.10.10.4` |
| 16:16:11 | Both ranks: `Using AttentionBackendEnum.TRITON_ATTN backend.` |
| 16:16:11+ | 5 total NCCL comms established (different vLLM collective channels) |
| 16:17–18 | Weight loading (fastsafetensors, parallel shard read from local NVMe) |
| ~16:18 | `Started server process [537]` |
| ~16:18 | **`Application startup complete.`** |

**Wall time:** ~2.5 min from dispatch to ready.

### Memory snapshots

| Phase | spark-3 RAM used | spark-4 RAM used | spark-3 GPU compute-app | spark-4 GPU compute-app |
|---|---|---|---|---|
| Pre-launch | 7.4 GiB | 6.4 GiB | (none) | (none) |
| Steady-state (post-ready) | **95 GiB** (78%) | **93 GiB** (77%) | `ray::RayWorkerWrapper` 85,333 MiB | `ray::RayWorkerWrapper` 85,413 MiB |
| Post-Phase-7 smoke (KV cache filled) | 97 GiB | 94 GiB | 86,287 MiB | 86,369 MiB |

## 9. Phase 7 smoke — Case I Section 2 (the worst Nano-9B failure point)

**Prompt source:** v0.3.5 case_briefing pipeline, `case_slug=7il-v-knight-ndga-i`, `section_id=section_02_critical_timeline`. Captured exactly via `stage_0_curate` + `stage_1_grounding_packet` + `_build_synthesis_user_prompt` (script at `/tmp/capture_section2_prompt.py`). 30 work-product chunks, 0 privileged chunks, 24,793-char user prompt + 403-char system prompt.

**Run parameters:** `temperature=0.6` (NVIDIA Nemotron-3-Super recommendation), `max_tokens=8192`, `stream=False`.

**Endpoint:** `POST http://10.10.10.3:8000/v1/chat/completions`.

### Acceptance criteria — all 4 PASS

| # | Criterion | Result |
|---|---|---|
| 1 | output_tokens ≥ 3000 | ✅ **5,560** |
| 2 | citation count ≥ 18 | ✅ **18** bracketed-filename citations in content (7 unique sources) |
| 3 | no first-person planning prose in `content` | ✅ 0 matches for "Let me / I'll / I'm going to / Wait / Let's / First, I" |
| 4 | no `<think>` blocks in `content` | ✅ 0 — `nemotron_v3` parser separates reasoning into `message.reasoning` (15,006 chars) |

### Metrics

| Metric | Value |
|---|---|
| Wall time | 278.37 s (4.6 min) |
| Output tok/s steady-state | **19.97 tok/s** (~83% of NVIDIA's claimed 24 tok/s) |
| `prompt_tokens` | 9,614 |
| `completion_tokens` | 5,560 |
| `total_tokens` | 15,174 |
| `finish_reason` | `stop` (clean termination) |
| Content chars (the table) | 2,246 |
| Reasoning chars (separate field) | 15,006 |

### Sources cited (7 unique, 18 references)

```
[#13 Joint Preliminary Statement.pdf]
[#5464474_Exhibit_3_GaryKnight(23945080.1).pdf]
[#65-1 7IL's BIS MSJ.pdf]
[#65-2 7IL's SOUF.pdf]
[#86 Jt. PTO.pdf]
[01-8.pdf]
[2022.01.04 Pl's Initial Disclosures.pdf]
```

### First 500 chars of content (operator sanity)

```
| Date | Event | Source |
|------|-------|--------|
| August 28, 2020 | Padrutt v. Knight initiated in Fannin County Superior Court. | [#86 Jt. PTO.pdf] |
| On or about March 14, 2021 | 7 IL Properties, LLC and Gary Knight entered into a binding purchase and sale contract for 253 River Heights Road. | [#13 Joint Preliminary Statement.pdf] (also [2022.01.04 Pl's Initial Disclosures.pdf]) |
| On or about April 5, 2021 | Plaintiff and Defendant executed an amendment to the 253 River Heights Road
```

### Last 500 chars of content (clean ending)

```
| October 14, 2021 | Original plaintiffs Jocinda Padrutt and Diana Campbell were dismissed; the caption was converted to 7IL Properties, LLC v. Knight. | [#86 Jt. PTO.pdf] |
| As of July 11, 2023 | Defendant earned income of $134,575.86 from the Fish Trap Property and $170,706.01 from the River Heights Property. | [#65-1 7IL's BIS MSJ.pdf] |
| May 14, 2025 | Home inspection of 92 Fish Trap Road conducted. | [01-8.pdf] |
```

### `usage` block (verbatim)

```json
{"prompt_tokens": 9614, "total_tokens": 15174, "completion_tokens": 5560, "prompt_tokens_details": null}
```

**Operator quality verdict:** **PASS**. Format compliance is the
decisive shift — `nemotron_v3` parser separates reasoning from content
by architecture, killing the entire Nano-9B failure mode.

## 10. Mitigation table (every error encountered + the fix)

| # | Error / Issue | Phase | Fix |
|---|---|---|---|
| M1 | spark-3 had `cubic` + 208 KiB rmem_max kernel default (PR #318 audit finding) | 1 | `sudo sysctl --system` re-applied existing canonical `/etc/sysctl.d/99-network-tuning.conf` (file content was already correct, runtime hadn't picked it up). PR #320 evidence. |
| M2 | spark-3 + spark-4 had `mtu 1500` on inactive twins (`enP2p1s0f0np0`); active twins were 9000 but inactive twins are autodiscovery-visible | 2 | Edited `/etc/netplan/99-mellanox-roce.yaml` in-place on both nodes — added `mtu 9000 + dhcp4:no + dhcp6:no + link-local:[]` to **all 4 twins**. `netplan try` (auto-revert wrapper) then `netplan apply`. ping `-M do -s 8972` 0% loss confirmed jumbo end-to-end. |
| M3 | PR #141 (cu130 → cu132 PyTorch fix) was state=CLOSED unmerged on `eugr/spark-vllm-docker` `main`. `git apply --check` failed (Dockerfile diverged). | 4 | **Build as-is.** Upstream pinned `torch==2.11.0+cu130` deliberately; ABI mismatch did NOT manifest at build or launch (no `_ZN3c1013MessageLogger`). PR #141 was closed because main moved to a different fix. |
| M4 | `/etc/fortress/secrets.env` did not exist on spark-3 or spark-4; spark-2's `secrets.env` had no `HF_TOKEN`-named key | 4 | Verified model is **public** (HTTP 200 on unauthenticated `config.json` HEAD). HF_TOKEN omitted everywhere. |
| M5 | `/raid` exists but is empty / not a separate FS on spark-3 + spark-4 | 4 | Adopted `/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/` (under `/`, 3+ TiB free, no sudo). Set `HF_HOME=/home/admin/hf-cache` so `launch-cluster.sh` line 6+8 mounts it as `/root/.cache/huggingface` in the container. |
| M6 | spark-3 → spark-4 ssh trust missing (both fabric and mgmt LAN); broke 4.8 (rsync over fabric) and 4.9 (`docker save \| ssh \| docker load`) AND would block `launch-cluster.sh`'s remote orchestration | 4, 5 | (a) Phase 4 routed around via NAS relay (each node pulled NAS independently; image distributed via NAS tarball). (b) Phase 5 Q1 deployed admin ed25519 pubkey from spark-3 to spark-4's `authorized_keys`. `ssh admin@10.10.10.4 hostname` from spark-3 returns `Spark-4`. |
| M7 | `run-recipe.py` lacks `--model` CLI override flag; recipe `model:` field referenced HF Hub repo ID, would trigger `check_model_exists()` → 75 GB redownload inside container | 5 | Created custom recipe `nemotron-3-super-nvfp4-local.yaml`: `model:` field cleared (line 1027 `if model:` guard skips check); `command:` first line points at local mount path. |
| M8 | spark-3 `fortress-nim-vision-concierge` (:8101, 47 GiB GPU) + `fortress-nim-embed` (:8102, 11.5 GiB GPU) would contend with TP=2 BRAIN | 5 | Stopped both via `systemctl stop`. Restart commands documented (§7). |
| M9 | vLLM warning at init: "Tensor parallel size (2) exceeds available GPUs (1)" | 6 | **Cosmetic only.** Per-node view; Ray's placement group spans both nodes, NCCL comms established successfully, TP=2 functional per Phase 7 200 OK. |
| M10 | curl response file had appended `--- Timing ---` footer breaking JSON parse | 7 | `awk` split on `^--- Timing ---` — body to `.body.json`, footer to `.timing.txt`. |

## 11. Rollback path

If Nemotron-Super endpoint becomes unhealthy mid-soak:

```bash
# 1. Stop tmux session + container on both nodes
ssh admin@192.168.0.105 'tmux kill-session -t nemotron-super-tp2'
ssh admin@192.168.0.105 'docker stop vllm_node 2>/dev/null'
ssh admin@192.168.0.106 'docker stop vllm_node 2>/dev/null'

# 2. Restart spark-3 NIMs (vision + embed) per §7 commands above

# 3. Revert any caller config that points at nemotron-3-super endpoint
#    (Phase 9 caller-retarget brief, separately authorized)

# 4. Rollback netplan (Phase 2):
ssh admin@192.168.0.105 'sudo cp /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'
ssh admin@192.168.0.106 'sudo cp /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'

# 5. Phase 1 sysctl is independent — leaves bbr/512 MiB in place; no rollback unless operator wants kernel default back
```

## 12. Open follow-ups (not blocking ADR-007 lock)

| ID | Description | Priority |
|---|---|---|
| F1 | Caller retarget brief — point Phase B + Council deliberation + legal-brief callers at `nemotron-3-super` instead of Nano-9B / cloud LiteLLM | P0 (separate brief, after ADR-007 lock) |
| F2 | Parallel section synthesis (5 sections concurrent via `--max-num-seqs 10` headroom) — wall-time reduction | P2 |
| F3 | MTP / `--speculative_config` evaluation — only after 14-day stability soak proves baseline | P3 |
| F4 | Re-evaluate spark-3 NIM disposition (vision NIM, embed NIM) — likely move vision to spark-1, embed to spark-2, or retire if Nemotron-Super absorbs use cases | P2 |
| F5 | Sustained-bandwidth iperf3 across fabric A + B (Step 3 of cluster-network-audit-2026-04-30) — separately authorized | P3 |

## 13. Phase 1 PR #320 (sysctl) grouping

Per operator decision: **PR #320 stays separate**. Sysctl on spark-3 is
operationally distinct from this deployment story. PR #320 evidence
remains independent and reviewable on its own.

## 14. Cross-references

- `docs/operational/spark-3-sysctl-apply-evidence-2026-04-30.md` (PR #320)
- `docs/operational/phase-2-netplan-mtu9000-evidence-2026-04-30.md`
- `docs/operational/phase-4-model-container-stage-evidence-2026-04-30.md`
- `docs/operational/phase-5-prereqs-evidence-2026-04-30.md`
- `docs/operational/cluster-network-audit-2026-04-30.md` (PR #309)
- `docs/operational/spark-5-6-fabric-cutover-runbook-2026-04-30.md` (PR #310)
- `docs/architecture/cross-division/ADR-006-phase-2-partner-reassignment.md` (PR #315)
- `docs/architecture/cross-division/_architectural-decisions.md` (ADR-007 entry below)

## 15. Operational handoff

- **tmux session:** `nemotron-super-tp2` on spark-3 (attach: `ssh admin@192.168.0.105 'tmux attach -t nemotron-super-tp2'`)
- **launch log:** `/home/admin/nemotron-super-tp2-launch.log` on spark-3 (~80 KB at boot, grows with serving)
- **NAS tarball backup of image:** `/mnt/fortress_nas/vllm-node-image-20260430.tar` (18.58 GB) — kept for rollback / new-node deploy until 14-day soak passes
- **Health check:** `curl -sS http://10.10.10.3:8000/v1/models` (expected: `nemotron-3-super` listed)

---

End of deployment evidence pack.
