# Phase 4 — Model + container stage evidence

**Date:** 2026-04-30 11:00–11:5x EDT
**Driver:** ADR-006 TP=2 cutover Phase 4. Stage Nemotron-3-Super-120B-NVFP4
weights + community vLLM container on spark-3 + spark-4. Community
Docker (`eugr/spark-vllm-docker`) per operator pivot from NGC vllm
container.

**Status:** Drafted, **uncommitted** — operator's Phase 8 grouping
decision: this evidence folds into the ADR-007 PR.

---

## 4.1 — HF_TOKEN sourcing

| Probe | Result |
|---|---|
| `/etc/fortress/secrets.env` on spark-3 | Does not exist |
| `/etc/fortress/secrets.env` on spark-4 | Does not exist (only `nim.env`, 84 bytes) |
| `/etc/fortress/secrets.env` on spark-2 (operator option 3 fallback) | Exists (400 bytes), but **only `ANTHROPIC_API_KEY` key** — no `HF_TOKEN`/`HUGGING_FACE_TOKEN`/`HF_HUB_TOKEN` |
| Model public-vs-gated check | `curl -I https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/raw/main/config.json` → **HTTP/2 200** unauthenticated |

**Decision:** No HF token required. Model is public on HF. `HF_TOKEN`
env var omitted everywhere downstream (4.6 download, Phase 5 launch).

## 4.2 — hf-cache path

| Node | `/raid` | NVMe | Free | Choice |
|---|---|---|---|---|
| spark-3 (192.168.0.105) | exists, empty (root:root, 4096 bytes; not a separate FS) | `/dev/nvme0n1p2` mounted at `/`, 3.0 TiB free | OK | **`/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/`** |
| spark-4 (192.168.0.106) | same as spark-3 | `/dev/nvme0n1p2` mounted at `/`, 3.3 TiB free | OK | **`/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/`** |

**Decision (operator-confirmed):** flat dir under `/home/admin/`, no
sudo, no `/raid` path. `/raid/hf-cache` references in brief swapped to
`/home/admin/hf-cache` everywhere downstream.

## 4.3 — spark-vllm-docker clone on spark-3

```
Repo:         https://github.com/eugr/spark-vllm-docker
Path:         /home/admin/spark-vllm-docker
HEAD SHA:     9fbed882bcbf051fbe6c9f651cdf8633a1f4b0c9
Last commits:
  9fbed88 Added EXPERIMENTAL mod for b12x - initial support
  97e51d5 fixed gemma4 recipe
  87cb9f6 Reverted gemma4 to safetensors. Fixes #214 and #217.
  ...
Files:        Dockerfile (13701 B), build-and-copy.sh (28100 B),
              launch-cluster.sh (39611 B), recipes/, etc.
```

## 4.4 — Dockerfile cu130/cu132 patch evaluation

Brief expected lines 48 + ~259 to reference `cu132`. Reality on
HEAD `9fbed88`: lines 53 + 318 reference `cu130` (production
channel) with `torch==2.11.0` pinned.

PR #141 metadata via `gh pr view 141 --repo eugr/spark-vllm-docker`:
- state=CLOSED, mergedAt=null, headRefName=`fix/cu132-pytorch-abi`
- title: "fix: cu130 → cu132 PyTorch index to match prebuilt vLLM wheel ABI"

`gh pr diff 141 → /tmp/pr-141.patch`. `git apply --check` on spark-3:
```
error: patch failed: Dockerfile:45
error: Dockerfile: patch does not apply
EXIT=1
```

PR #141 was written against an earlier Dockerfile that had:
`uv pip install torch torchvision torchaudio triton --index-url
https://download.pytorch.org/whl/nightly/cu130 && \`

Current HEAD has:
`uv pip install torch==2.11.0 torchvision torchaudio triton
--index-url https://download.pytorch.org/whl/cu130 && \`

Two material differences (`torch==2.11.0` pin + production channel
vs nightly). PR #141 was apparently closed because main moved to a
different fix.

**Decision (operator option 1):** build as-is (no patch). Upstream's
torch 2.11.0+cu130 pin is deliberate, tested state. Override on
speculation regresses. If launch hits `_ZN3c1013MessageLogger`
undefined symbol error, re-evaluate then; otherwise proceed.

## 4.5 — vllm-node image build on spark-3

Command: `./build-and-copy.sh` (default args; image tag `vllm-node`,
GPU arch `12.1a` = sm_121a = GB10).

| Field | Value |
|---|---|
| Build duration | **15:32** (within 5-15 min field report estimate) |
| Image tag | `vllm-node:latest` |
| Image SHA | `sha256:330ba87d78eb939efc0212485f346ff4b06db3562140137ad60b06bcc1ca066f` |
| Image size | 18.5 GB |
| Hard-stop signatures encountered | None |
| `_ZN3c1013MessageLogger` symbol error | Not encountered (cu130 build clean) |
| `ptxas fatal sm_121a` error | Not encountered (build script handled) |
| Final docker tag step | `naming to docker.io/library/vllm-node done` |

Build log at `/tmp/vllm-build.log` on spark-3.

## 4.6 — HF model download to NAS (from spark-2)

Per operator option 3 fallback: download initiated from spark-2 (where
NAS is mounted and HF tooling is installed). Token not needed (model
public).

```bash
huggingface-cli download nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
    --local-dir /mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4
```

| Field | Value |
|---|---|
| Download duration | **11:46** |
| Files (incl. config + tokenizer + safetensors) | 36 |
| Total size on NAS | **75 GB** (75GB measured via `du -sh`) |
| Tool version | `huggingface_hub` 0.36.2 |
| Parallel shard download | 17× safetensors in parallel (per HF Hub default) |
| Token used | None (public repo) |

SHA256 manifest generated at
`/mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/MANIFEST.sha256`
(3446 bytes — one line per file).

> Note: `super_v3_reasoning_parser.py` was **not** pulled because the
> recipe (`recipes/nemotron-3-super-nvfp4.yaml`) uses
> `--reasoning-parser nemotron_v3` which is a built-in vLLM parser,
> not a plugin file. Recipe defaults override brief amendment per
> operator decision.

## 4.7 — NAS → spark-3 local NVMe rsync

```bash
rsync -av --partial \
    /mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/ \
    /home/admin/hf-cache/nemotron-3-super-120b-nvfp4/
```

| Field | Value |
|---|---|
| Source | `/mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/` (NFS) |
| Dest | `/home/admin/hf-cache/nemotron-3-super-120b-nvfp4/` |
| Files transferred | 36 (model files; MANIFEST.sha256 copied separately post-rsync) |
| Dest size | **75 GB** (matches NAS) |
| File count post-manifest-copy | 37 |
| SHA256 verify | All 36 model files **OK** (per `sha256sum -c MANIFEST.sha256`); one stale `MANIFEST.sha256.tmp` line (manifest gen artifact, benign — file no longer exists, only the manifest line remains) |

## 4.8 — NAS → spark-4 local NVMe rsync (revised path)

**Brief originally specified spark-3 → spark-4 over fabric A.**
Reality: spark-3 → spark-4 ssh authentication is **not configured**
(both fabric and mgmt LAN return `Permission denied (publickey,password)`
from spark-3 to spark-4 — fortress key apparently not deployed for
this pair). P3 follow-up to set up the spark-3→spark-4 trust path;
not blocking Phase 4.

**Revised:** spark-4 pulls from NAS directly in parallel with spark-3
4.7. Both nodes have NAS mounted; NAS handles concurrent reads. Matches
operator's option 3 instruction: "Phase 4.7+4.8 stage from NAS to local
hf-cache on each node".

```bash
rsync -av --partial \
    /mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/ \
    /home/admin/hf-cache/nemotron-3-super-120b-nvfp4/
```

| Field | Value |
|---|---|
| Files transferred | 36 (model files; MANIFEST.sha256 copied separately post-rsync) |
| Dest size | **75 GB** (matches NAS) |
| File count post-manifest-copy | 37 |
| SHA256 verify | All 36 model files **OK**; same benign `MANIFEST.sha256.tmp` artifact as spark-3 |

## 4.9 — vllm-node image distribution spark-3 → spark-4 (revised path)

**Brief originally specified `docker save vllm-node | ssh admin@10.10.10.4 "docker load"`.**
Reality: same spark-3 → spark-4 ssh auth gap blocks this pipe. NAS
relay used instead.

```bash
# spark-3:
docker save vllm-node > /mnt/fortress_nas/vllm-node-image-20260430.tar
# spark-4:
docker load < /mnt/fortress_nas/vllm-node-image-20260430.tar
```

| Field | Value |
|---|---|
| NAS tarball | `/mnt/fortress_nas/vllm-node-image-20260430.tar` |
| Tarball size | **18,578,124,288 bytes (17.3 GiB / 18.58 GB)** |
| spark-3 save duration | ~5 min (NFS write) |
| spark-4 load duration | ~5 min (NFS read + docker import) |
| Image ID match (both nodes) | **`330ba87d78eb`** ✅ identical |
| `vllm-node:latest` on spark-3 | sha256:330ba87d78eb939efc0212485f346ff4b06db3562140137ad60b06bcc1ca066f |
| `vllm-node:latest` on spark-4 | sha256:330ba87d78eb939efc0212485f346ff4b06db3562140137ad60b06bcc1ca066f |

## Out of scope

- spark-3 → spark-4 ssh trust setup (P3 follow-up; routed around via NAS for Phase 4)
- super_v3_reasoning_parser.py (not needed; recipe uses built-in `nemotron_v3` parser)
- `/raid/hf-cache` path migration (deferred; flat `~/hf-cache/` adopted instead)

---

## Raw transcripts on spark-2 / spark-3 / spark-4

- `/tmp/vllm-build.log` (spark-3) — build full log
- `/tmp/hf-download.log` (spark-2) — HF download progress
- `/tmp/rsync-nas-to-local.log` (spark-3) — 4.7 rsync
- `/tmp/rsync-nas-to-local.log` (spark-4) — 4.8 rsync
- `/tmp/docker-save.log` (spark-3) — 4.9 step A
- `/tmp/docker-load.log` (spark-4) — 4.9 step B
- `/tmp/sha256-manifest.log` (spark-2) — 4.6 manifest gen
- `/tmp/pr-141.patch` (spark-2) — PR #141 diff for record
- `/mnt/fortress_nas/models/nemotron-3-super-120b-nvfp4/MANIFEST.sha256` — full SHA256 manifest of 36 model files

End of evidence (pending final completion data).
