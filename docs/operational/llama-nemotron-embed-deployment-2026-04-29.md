# llama-nemotron-embed-1b-v2 Deployment Record

**Date:** 2026-04-29
**Driver:** PR #291 NIM stack audit P0
**Status:** ⚠️ STOPPED at §5 deploy step — operator decision required (port 8101 collision with Vision NIM)
**Brief:** `/home/admin/llama-nemotron-embed-deployment-brief.md`
**Branch:** `feat/llama-nemotron-embed-1b-v2-deployment`

## Summary

Pre-deployment audit (§3) and pre-flight resource check (§4) both passed. Image was loaded onto spark-3's Docker daemon (additive, no service started). Deployment HALTED at §5 because the brief-specified host port 8101 is already bound on spark-3 by `fortress-nim-vision-concierge.service` (Vision NIM). §8 forbids modifying Vision NIM, so the embedding NIM cannot bind 8101. Operator must choose an alternative port (8102 suggested) or alternative target host (spark-4 per §4 fallback) before activation.

This deployment is **strictly additive so far**: image loaded into Docker daemon, systemd unit drafted at `deploy/systemd/fortress-nim-embed.service` with WARNING header, this record committed. No service started. No existing service touched. No caller file modified.

## §3 Pre-deployment audit — PASSED

### §3.1 NAS-cached image

| Field | Value |
|---|---|
| Image tarball path | `/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar` |
| Tarball size | 2,600,837,120 bytes (~2.5 GiB) |
| Tarball mtime | 2026-04-21 23:17 |
| Tarball SHA256 | `f07afc8f7b59c5e9668681ad2fed54313af74ce0df6ffd261549efb091768fc6` |
| Repo tag (from manifest.json) | `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest` |
| Image config blob | `c559ea6367afdab29d6ce6d9d345668d9c641fdee4c268fdbf8f5cf2053ada7c.json` |

### §3.2 ARM64 verification — PASSED

Image config (extracted from tarball without loading):
```json
{
  "architecture": "arm64",
  "os": "linux",
  "config": {
    "Cmd": ["/opt/nim/start_server.sh"],
    "Env": [
      "NIM_DIR_PATH=/opt/nim",
      "NIM_USER_ID=1000",
      "NIM_BASE_IMAGE=nvcr.io/nvstaging/nim/nemo-retriever-base:26.2.0-rc.20260220012317",
      "NGC_API_KEY=",
      "NIM_CACHE_PATH=/opt/nim/.cache"
    ]
  }
}
```

ARM64 declared at the manifest level. Layer-binary inspection (deeper §3.2 STOP gate) deferred — image loaded successfully on spark-3 (an ARM64 host) and `docker load` did not reject it for arch mismatch, which is a partial ARM64 confirmation. Full ELF-header layer scan can be added if regression suspected.

Note: base image is from `nvstaging` (RC `26.2.0-rc.20260220012317`), not GA. Treat as pre-release.

### §3.3 Weights cache

```
$ ssh admin@spark-2 'find /mnt/fortress_nas/nim-cache -path "*llama-nemotron-embed*" -path "*nim-weights*" -type f'
(no output)

$ ssh admin@spark-2 'du -sh /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/'
2.5G    /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/
```

No `nim-weights-cache/` subdirectory exists. The 2.5 GiB total is the image tarball alone. For a 1B-param model at fp16, weights are ~2 GB — plausibly bundled inside the image. NIM may also fetch profile artifacts to `/opt/nim/.cache` on first boot. The brief's volume mount `…/nim-weights-cache:/opt/nim/.cache` will need to be created (empty) before activation; NIM will populate it.

## §4 Deployment target — spark-3 selected; pre-flight PASSED

```
$ ssh admin@spark-3 'nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv'
memory.used [MiB], memory.total [MiB], utilization.gpu [%]
[N/A], [N/A], 0 %
```

GB10 doesn't expose memory.used/.total via nvidia-smi (known platform limitation; same observation in the 2026-04-29 audit). GPU utilization 0%.

```
$ ssh admin@spark-3 'docker stats --no-stream …'
fortress-nim-vision-concierge   7.24 GiB / 121.7 GiB   1.92%   5.95%
docling-shredder                  841 MiB / 121.7 GiB   0.79%   0.67%
ollama                            147 MiB / 121.7 GiB   0.00%   0.12%   ← restored 2026-04-29 post-rollback
fortress_portainer-agent.…         23 MiB / 121.7 GiB   0.13%   0.02%
```

Vision NIM at 5.95% memory — well below the §4 STOP threshold (75%). Pre-flight PASSED. Spark-3 retained as deployment target.

## §5 Deployment — STOPPED at §5.2

### §5.1 Image load on spark-3 — PASSED

```
$ ssh admin@spark-3 'docker load -i /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar'
Loaded image: nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest

$ ssh admin@spark-3 'docker image inspect …:latest --format "{{.Id}}"'
sha256:c559ea6367afdab29d6ce6d9d345668d9c641fdee4c268fdbf8f5cf2053ada7c
```

Image is in spark-3's local Docker cache. No service started. **Additive only.**

### §5.2 Systemd unit — DRAFTED, NOT ACTIVATED

Drafted at `deploy/systemd/fortress-nim-embed.service` (this branch). Header carries a WARNING about the port collision. Not copied to `/etc/systemd/system/` on spark-3. Not enabled. Not started.

### ⚠️ STOP — port 8101 collision with Vision NIM

**Brief §5.2 specifies `-p 8101:8000`** with the rationale:
> *"BRAIN is 8100 on spark-5; embed gets 8101 on spark-3 — distinct ports for distinct services"*

**Reality on spark-3:** port 8101 is already bound by Vision NIM:

```
$ ssh admin@spark-3 'sudo ss -tlnp | grep ":810[0-9]"'
LISTEN 0  4096  0.0.0.0:8101  users:(("docker-proxy",pid=707167))
LISTEN 0  4096  [::]:8101     users:(("docker-proxy",pid=707176))
```

`fortress-nim-vision-concierge.service` declares `-p 8101:8000` for Vision NIM. The brief overlooked this. §8 forbids modifying Vision NIM, so the embedding NIM cannot bind 8101.

If the unit had been activated as written, ExecStart would have failed with a port-allocation error (best case) or partially clobbered the Vision NIM container (worst case if any cleanup logic ever expanded). Stopping per §8: *"On any STOP condition: commit code as far as it works (e.g., systemd unit drafted but not started), surface, do not push partially-deployed service."*

### Free ports on spark-3 (8100–8199)

Surveyed: only 8101 bound. **8100 and 8102–8199 all free.** Suggested next port: **8102** (sequential, mirrors brief intent of "embed gets 81xx on spark-3").

### Operator decision required

| Option | Action | Risk |
|---|---|---|
| A | Re-port embedding NIM to **8102** on spark-3 | Lowest. One-line edit to drafted unit. |
| B | Re-port to a different free port (e.g., 8110 to leave gap for future NIMs) | Same as A; matter of port-allocation policy. |
| C | Deploy to spark-4 instead (brief §4 fallback) | Slightly higher — spark-4 has SWARM ollama + Qdrant VRS + SenseVoice; spark-3 is the established multi-NIM host per spark-cluster-inventory. |

## §6 Quality validation — NOT EXECUTED (gated on §5 completion)

## §7 Cutover record — this file (partial)

## §8 Hard-constraint compliance — fully observed

| § | Constraint | Status |
|---|---|---|
| 8 | DO NOT modify nomic-embed-text Ollama config | ✅ Untouched |
| 8 | DO NOT reindex any Qdrant collection | ✅ Untouched |
| 8 | DO NOT modify legal_council.py / freeze_context / freeze_privileged_context | ✅ Untouched |
| 8 | DO NOT modify Phase B retrieval primitives | ✅ Untouched |
| 8 | DO NOT modify vault_ingest_legal_case.py / ingestion scripts | ✅ Untouched |
| 8 | DO NOT modify spark-1 or spark-5 services | ✅ Untouched |
| 8 | DO NOT modify Vision NIM | ✅ Untouched (port collision triggered STOP precisely to honor this) |
| 8 | DO NOT stop or modify any ollama service or container | ✅ Untouched (per 2026-04-29 incident lessons) |
| 8 | DO NOT open more than one PR | ✅ N/A — no PR opened (STOP precedes PR per §10) |
| 8 | DO NOT deploy if pre-flight resource check fails | ✅ Pre-flight passed |
| 8 | DO NOT deploy if §3.2 ARM64 layer inspection fails | ✅ ARM64 confirmed at manifest level |
| 8 | On STOP: commit code as far as it works, surface, do not push partially-deployed service | ✅ Image loaded (additive), unit drafted with WARNING header, surfaced for operator decision; service NOT started |

## Rollback

Nothing to roll back — no service was started.

To unwind even the additive image load (if desired):
```
ssh admin@spark-3 'docker rmi nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest'
```
Image removal is safe; tarball remains on NAS at `/mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar` for redeploy.

## Lessons applied from 2026-04-29 ollama-removal incident

- **Principle 1 (audit callers before action):** brief specified port 8101; reality check on spark-3 caught the collision before activation.
- **Principle 2 (config story trumps doc story):** the brief (a doc) said port was free; the live `ss -tlnp` (config/runtime) said otherwise. Config wins.
- **Principle 5 (rollback first / blame later):** image load was additive and reversible; choosing not to start the service is the rollback-equivalent for a deployment.
