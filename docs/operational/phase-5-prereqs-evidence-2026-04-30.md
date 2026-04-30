# Phase 5 — Prerequisites for Phase 6 launch (evidence)

**Date:** 2026-04-30 12:00–12:08 EDT
**Driver:** ADR-006 TP=2 cutover Phase 5 prereqs Q1-Q4. Surfaced four
blockers; operator answered, prereqs executed; ready for Phase 6 launch
greenlight.

**Status:** All prereqs complete. **Uncommitted** — Phase 8 grouping.

---

## Q1 — spark-3 → spark-4 ssh trust deployed

### What was missing

`ssh admin@spark-4` from spark-3 returned `Permission denied (publickey,password)` on both fabric A (10.10.10.4) and mgmt (192.168.0.106). `launch-cluster.sh` (head=spark-3) ssh's the worker at multiple points (lines 504, 554, 584, 611, 651, 677, 731, 793) and would fail.

### Action taken

```bash
# 1. Generate ed25519 key on spark-3 (admin user)
ssh admin@192.168.0.105 'test -f ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519'
# Output: key generated; fingerprint admin@spark-3
# Pubkey: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGWIUJgvJE4W6wEr1EJawvCnkQP6IhiWooWSeulLNizJ admin@spark-3

# 2. Append to spark-4 authorized_keys via LAN
PUB=$(ssh admin@192.168.0.105 'cat ~/.ssh/id_ed25519.pub')
ssh admin@192.168.0.106 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUB' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
# Output: append OK; admin@spark-3 key count = 1

# 3. Verify via fabric A
ssh admin@192.168.0.105 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new admin@10.10.10.4 hostname'
# Output: Spark-4
```

**Result:** ✅ trust established. Subsequent `ssh admin@10.10.10.4 hostname` from spark-3 returns `Spark-4` non-interactively.

## Q2 — spark-3 NIMs stopped before Phase 6 launch

### Pre-stop state

| Service | Type | Container image | Port | GPU mem |
|---|---|---|---|---|
| `fortress-nim-vision-concierge.service` | systemd → docker | `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:sha-33032f00aed9` | `:8101` | **47,066 MiB** (VLLM EngineCore PID 708672) |
| `fortress-nim-embed.service` | systemd → docker | `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest` | `:8102` | **11,555 MiB** (tritonserver PID 1396423) |

Total GPU mem in use by NIMs: **~58 GiB** of GB10 unified memory.

### Action taken

```bash
ssh admin@192.168.0.105 'sudo systemctl stop fortress-nim-vision-concierge.service'  # 47 GB GPU released
ssh admin@192.168.0.105 'sudo systemctl stop fortress-nim-embed.service'             # 11.5 GB GPU released
```

### Post-stop verification

| Check | Result |
|---|---|
| `systemctl is-active fortress-nim-vision-concierge` | `inactive` ✅ |
| `systemctl is-active fortress-nim-embed` | `inactive` ✅ |
| `nvidia-smi --query-compute-apps` | empty ✅ (no GPU processes) |
| Listening on `:8101` `:8102` | clean ✅ (no listeners) |
| `docker ps | grep fortress-nim` | empty ✅ (no containers) |

### Restart commands (post-Phase 7 / post-Phase 8, operator decides)

```bash
# Restart in original order (vision uses more RAM, give it priority):
ssh admin@192.168.0.105 'sudo systemctl start fortress-nim-vision-concierge.service'
ssh admin@192.168.0.105 'sudo systemctl start fortress-nim-embed.service'

# Verify health post-restart:
curl -sS http://192.168.0.105:8101/v1/health/ready  # vision
curl -sS http://192.168.0.105:8102/v1/health/ready  # embed
```

**Note:** Both services have `ExecStartPre=-/usr/bin/docker stop <name>` and `ExecStartPre=-/usr/bin/docker rm <name>` so systemd handles cleanup of any stale container state on restart.

**Decision deferred** to operator post-Phase 7: are the NIMs needed alongside TP=2 BRAIN, or does Nemotron-Super absorb the use cases (vision + embed)? If NIMs return, GPU contention re-emerges on spark-3.

## Q3 — Recipe + .env files written

### Files on spark-3

| Path | Size | Mode | Purpose |
|---|---|---|---|
| `/home/admin/spark-vllm-docker/recipes/nemotron-3-super-nvfp4-local.yaml` | 1289 bytes | `644 admin:admin` | Custom recipe; `model: cleared` to bypass HF Hub check; `command:` points at local mount path |
| `/home/admin/spark-vllm-docker/.env` | 542 bytes | `644 admin:admin` | Cluster topology + fabric NCCL env vars + container CONTAINER_* passthrough |

### Recipe content summary (key deltas vs upstream)

- `model:` field omitted (skips `run-recipe.py` `check_model_exists()` → no HF Hub redownload attempt)
- `command:` first line: `vllm serve /root/.cache/huggingface/nemotron-3-super-120b-nvfp4` (local path)
- Added `--served-model-name nemotron-3-super` for clean OpenAI API endpoint name
- All recipe defaults preserved per operator lock: `gpu_memory_utilization: 0.7`, `max_num_seqs: 10`, `reasoning-parser nemotron_v3`

### .env content summary

- `CLUSTER_NODES="10.10.10.3,10.10.10.4"` (fabric A IPs, head first)
- `ETH_IF="enp1s0f0np0"`, `IB_IF="rocep1s0f0,roceP2p1s0f1"` (per R2)
- 7 `CONTAINER_*` vars: NCCL_DEBUG/NCCL_IB_HCA/NCCL_SOCKET_IFNAME/GLOO_SOCKET_IFNAME/NCCL_IB_DISABLE/VLLM_NVFP4_GEMM_BACKEND/VLLM_USE_FLASHINFER_MOE_FP4
- `HF_TOKEN` intentionally omitted (model public)

## Q4 — Tmux session name confirmed

Phase 6 will use `tmux new-session -d -s nemotron-super-tp2` per brief.

---

## Final pre-Phase-6 verification (cross-cluster)

| Check | spark-3 (192.168.0.105) | spark-4 (192.168.0.106) |
|---|---|---|
| `ssh admin@10.10.10.4 hostname` from spark-3 | `Spark-4` ✅ | n/a |
| `nvidia-smi --query-compute-apps` | empty ✅ | (background, untouched) |
| Ports `:8101` `:8102` listening | clean ✅ | n/a |
| `fortress-nim-*` systemd | `inactive` ✅ | n/a |
| `/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/` file count | **37** ✅ | **37** ✅ |
| `docker images vllm-node` ID | `330ba87d78eb` ✅ | `330ba87d78eb` ✅ |
| Recipe + .env present | ✅ | n/a (head-only) |

All prereqs green.

---

## Out of scope (deferred)

- Whether to restart NIMs on spark-3 post-Phase 7 → operator decision after smoke quality verdict
- spark-2 → spark-3/4 ssh trust (unrelated; spark-2 already has working trust to all sparks)
- Documenting the NIM stop in master plan tier table → folds into ADR-007 PR

---

End of Phase 5 prereqs evidence.
