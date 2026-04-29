# llama-nemotron-embed-1b-v2 Deployment Record

**Date:** 2026-04-29
**Driver:** PR #291 NIM stack audit P0
**Status:** ⚠️ STOPPED at §5.3 — NGC weights inaccessible (operator decision required)
**Brief:** `/home/admin/llama-nemotron-embed-deployment-brief.md`
**Branch:** `feat/llama-nemotron-embed-1b-v2-deployment`

## Summary

Three obstacles surfaced during deployment, two fixed-in-place and one requiring operator decision:

1. **§5.2 port 8101 collision with Vision NIM** — RESOLVED by operator decision to re-port to **8102** on spark-3.
2. **§5.3 `NIM_MODEL_PROFILE=auto` rejected** — RESOLVED in-place by pinning to the only system-compatible profile SHA `e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528` (model_type:onnx|precision:fp16), discovered via `list-model-profiles` on the loaded image.
3. **§5.3 NGC weight download permission denied** — **OPEN, requires operator decision.** The brief assumed weights were NAS-cached. They are not. This NIM downloads weights from NGC at first boot, and the `NGC_API_KEY` in `/etc/fortress/nim.env` lacks permission for `nim/nvidia/llama-nemotron-embed-1b-v2`.

Service is **stopped and disabled** on spark-3 to halt the systemd restart loop. No service is running. Image remains loaded in spark-3's Docker daemon (additive). All §8 hard constraints honored.

## §3 Pre-deployment audit — PASSED with caveat

### §3.1 NAS-cached image

| Field | Value |
|---|---|
| Image tarball path | `/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar` |
| Tarball size | 2,600,837,120 bytes (~2.5 GiB) |
| Tarball mtime | 2026-04-21 23:17 |
| Tarball SHA256 | `f07afc8f7b59c5e9668681ad2fed54313af74ce0df6ffd261549efb091768fc6` |
| Repo tag (manifest.json) | `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest` |
| Image config blob | `c559ea63…json` |
| Loaded image ID on spark-3 | `sha256:c559ea63…` |

### §3.2 ARM64 verification — PASSED

Image config: `architecture: arm64`, `os: linux`. Layer-binary inspection deferred (image loaded successfully on ARM64 spark-3, partial arch confirmation).

Note: base image is from `nvcr.io/nvstaging/nim/nemo-retriever-base:26.2.0-rc.20260220012317` — pre-release.

### §3.3 Weights cache — RETROSPECTIVELY CAUGHT AS RED FLAG

```
$ find /mnt/fortress_nas -path "*llama-nemotron-embed-1b-v2*"
.../latest                       (image only)
.../latest/image.tar             (2.5 GiB runtime)
.../latest/image.sha256
.../nim-weights-cache            (empty — created by deployment for volume mount)

$ find /mnt/fortress_nas -path "*llama-nemotron-embed*" -type f
(only image.tar — no weights anywhere on NAS)
```

The brief read this as "weights are bundled in the image." That assumption did not hold — the 2.5 GiB image contains the NIM runtime + tokenizer + schema, NOT the model weights. NIMs of this class fetch weights from NGC at first boot.

**Lesson re-applied (Principle 1, audit before action):** §3.3 should have included a positive-confirmation step ("verify a `*.bin` / `*.safetensors` / `*.onnx` weight file is present, not just metadata"). Adding this gap to the lessons-learned for the next NIM deployment brief.

## §4 Deployment target — spark-3 selected; pre-flight PASSED

(Unchanged from initial draft — see git history.)

GPU 0% util, Vision NIM at 5.95% memory, well below 75% STOP. Spark-3 retained.

## §5 Deployment

### §5.1 Image load — PASSED

```
$ ssh admin@spark-3 'docker load -i .../image.tar'
Loaded image: nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest

$ ssh admin@spark-3 'docker image inspect ... --format "{{.Id}}"'
sha256:c559ea6367afdab29d6ce6d9d345668d9c641fdee4c268fdbf8f5cf2053ada7c
```

### §5.2 Systemd unit — port 8101 collision RESOLVED to 8102

Operator chose port 8102 (next-sequential, free on spark-3). Unit at `deploy/systemd/fortress-nim-embed.service` updated; copied to `/etc/systemd/system/fortress-nim-embed.service` (root:root 0644).

### §5.3 First start — `NIM_MODEL_PROFILE=auto` rejected, then NGC download failed

#### Iteration 1: profile `auto` rejected

Service started, container ran briefly, exited:
```
Error: Environment variable NIM_MODEL_PROFILE is set to auto, but no matching
profile_id or profile description is found in manifest.
```

This NIM does not accept `auto` as a profile keyword (despite the brief specifying it). Discovered the only system-compatible profile via:

```
$ ssh admin@spark-3 'docker run --rm --gpus all <image> list-model-profiles'
SYSTEM INFO
- Free GPUs:
  - [2e12:10de] (0) NVIDIA GB10
MODEL PROFILES
- Compatible with system:
    - e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528
      - model_type:onnx | precision:fp16
- Incompatible with system:
    - 9 tensorrt profiles for compute_capability 8.0/8.6/8.9/9.0/10.0/12.0
      (FP16 + FP8 variants; TensorRT engines are pre-built for specific
      compute capabilities and not portable to GB10's compute capability)
```

Pinned `NIM_MODEL_PROFILE=e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528` in unit. **Resolved.**

#### Iteration 2: NGC permission denied — STOP

Service started again with profile pinned. Container now matches the profile, then attempts to fetch weights from NGC:
```
INFO 2026-04-29 22:04:02 nim_sdk.py:376] Downloading manifest profile: e28f17c9...
INFO 2026-04-29 22:04:02 tokio.rs:916] "nim/nvidia/llama-nemotron-embed-1b-v2:fp16-7af2b653":
   fetching filemap from: https://api.ngc.nvidia.com/v2/org/nim/team/nvidia/models/llama-nemotron-embed-1b-v2/fp16-7af2b653/files

ERROR 2026-04-29 22:04:03 nim_sdk.py:338] Download failed after 1 attempts. Last exception:
   Permission error: The requested operation requires permissions that the user does not have.
   This may be due to the user not being a member of the organization that owns the repo.

nimlib.exceptions.ManifestDownloadError: Error downloading manifest: Permission error: ...
```

The `NGC_API_KEY` in `/etc/fortress/nim.env` is valid (Vision NIM uses it successfully) but lacks permission for the `nim/nvidia/llama-nemotron-embed-1b-v2` repo. Either:

- The key needs a permission grant from NGC org admins for this specific NIM
- Or a different / scoped key is required for this model
- Or weights need to be pre-staged from a host that has access (e.g., NGC CLI download → NAS), eliminating the runtime NGC call entirely (the sovereign pattern)

**Service stopped + disabled to halt the systemd restart loop:**
```
$ ssh admin@spark-3 'sudo systemctl stop fortress-nim-embed.service; sudo systemctl disable fortress-nim-embed.service'
Removed "/etc/systemd/system/multi-user.target.wants/fortress-nim-embed.service".
$ ssh admin@spark-3 'sudo systemctl is-active fortress-nim-embed.service'
inactive
```

No state change beyond stopping + disabling our own service. No other service touched.

## §5.4–§5.6, §6 — NOT EXECUTED

Health check, direct probe, LiteLLM alias, gateway probe, quality validation all gated on §5.3 completing.

## §7 Cutover record — this file

## §8 Hard-constraint compliance — fully observed

| § | Constraint | Status |
|---|---|---|
| 8 | DO NOT modify nomic-embed-text Ollama config | ✅ Untouched |
| 8 | DO NOT reindex any Qdrant collection | ✅ Untouched |
| 8 | DO NOT modify legal_council.py / freeze_context / freeze_privileged_context | ✅ Untouched |
| 8 | DO NOT modify Phase B retrieval primitives | ✅ Untouched |
| 8 | DO NOT modify vault_ingest_legal_case.py / ingestion scripts | ✅ Untouched |
| 8 | DO NOT modify spark-1 or spark-5 services | ✅ Untouched |
| 8 | DO NOT modify Vision NIM | ✅ Untouched |
| 8 | DO NOT stop or modify any ollama service or container | ✅ Untouched (per 2026-04-29 incident lessons) |
| 8 | DO NOT open more than one PR | ✅ N/A — no PR opened (STOP precedes PR) |
| 8 | DO NOT deploy if pre-flight resource check fails | ✅ Pre-flight passed |
| 8 | DO NOT deploy if §3.2 ARM64 layer inspection fails | ✅ ARM64 confirmed at manifest level |
| 8 | On STOP: commit work-in-progress, surface, do not push partially-deployed service | ✅ Service stopped + disabled; unit committed; surfaced |

## Operator decision required

| Option | Action | Cost | Sovereignty implication |
|---|---|---|---|
| **A** | Get NGC permission grant for `nim/nvidia/llama-nemotron-embed-1b-v2` on the existing key, or rotate to a key that has it. Then start service — NIM will download weights once on first boot, cache to `/mnt/fortress_nas/.../nim-weights-cache/` on NAS, and run sovereign thereafter. | Lowest. One credential update + one boot cycle. | One-time NGC outbound during weight pull (single ~2GB download). Subsequent boots are local. |
| B | Pre-stage weights manually: download via `ngc registry model download-version nim/nvidia/llama-nemotron-embed-1b-v2:fp16-7af2b653` on a host with credentials, copy to `nim-weights-cache/` on NAS, then start service offline. | Slightly higher (manual step, but a one-time job). | Zero NGC outbound from spark-3 once staged. Cleaner sovereign pattern. |
| C | Pivot to a different embedding model that already has weights on NAS (e.g., `nv-embedqa-e5-v5` per spark-cluster-inventory). Brief becomes obsolete. | Requires brief revision. Different model means different vector dimension and different downstream migration plan. | N/A |
| D | Defer the deployment until the NGC org access is sorted. Roll back image load (`docker rmi`). | None — clean revert. | N/A |

## Rollback

Service stopped + disabled. Nothing running. To unwind even the additive image load:
```
ssh admin@spark-3 'docker rmi nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest'
ssh admin@spark-3 'sudo rm /etc/systemd/system/fortress-nim-embed.service && sudo systemctl daemon-reload'
ssh admin@spark-2 'rmdir /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/nim-weights-cache'  # only if empty
```

Tarball remains on NAS for redeploy.

## Lessons applied + extended

From 2026-04-29 ollama-removal incident:
- **Principle 1 (audit before action):** §3.3 audit caught the empty cache-dir but read it as "weights bundled in image." The audit needs a *positive* check, not just absence-of-files. Add `du -sh nim-weights-cache/` AND `find … -name "*.onnx" -o -name "*.safetensors" -o -name "*.bin"` to next NIM brief's §3.3.
- **Principle 2 (config story trumps doc story):** brief said port 8101 free → `ss -tlnp` said no. Brief said `NIM_MODEL_PROFILE=auto` works → `list-model-profiles` said no. Brief said weights cached → NGC API said no. Three for three: live state always disagreed with the doc. Lesson holds.
- **Principle 5 (rollback first / blame later):** stopped + disabled the service immediately when the second iteration kept failing — no running state, no churn, clean handoff to operator.

New principle proposed (lesson-extended):
- **Principle 6 (deployment briefs cannot reliably specify cached state):** any "weights are NAS-cached" / "image is pre-pulled" / "API key is pre-configured" claim in a brief is provisional until verified by the deployer. The brief author is writing from memory of a different point in time; the cluster state moves under them. Pre-deployment audit must verify each cached-state claim independently before starting any service.
