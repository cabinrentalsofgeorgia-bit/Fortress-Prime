# Cluster NIM Deployment Conventions

**Audience:** anyone deploying a NIM to the Fortress-Prime DGX Spark cluster
(spark-1/-3/-4/-5 — all GB10 ARM64). Captures conventions discovered during
Wave 3 v2 deployment 2026-05-01 that differ from how the deployment briefs
were originally written.

This is the durable artifact from Wave 3 v2: even though Components A
(Reranker) and B (Extraction) were deferred to Wave 3.5, the conventions
below are what every future NIM deployment on this cluster needs to follow.

---

## 1. NIM_MODEL_PROFILE — pin the SHA256, never use `auto`

### Why `auto` is broken

From the verbatim header of `/etc/systemd/system/fortress-nim-embed.service`
on spark-3 (activated 2026-04-29):

```
# 2. NIM_MODEL_PROFILE pinned to the only compatible profile on this GB10
#    host (model_type:onnx|precision:fp16). Brief default `auto` failed with
#    "no matching profile_id or profile description in manifest" — that
#    keyword is not supported by this NIM. Profile discovered via
#    `docker run --rm --gpus all <image> list-model-profiles` 2026-04-29.
```

This is reproducible on Wave 3's reranker NIM as well: container manifests
list one ONNX|fp16 profile compatible with GB10 and ~22 incompatible
profiles for H100/A100/B200/L40S/L4/A10G/compute_capability:8.6/8.9/9.0/10.0/12.0.

### Reranker pinned profile (Wave 3 v2)

For `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2:1.8.0`:

```
NIM_MODEL_PROFILE=f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f
```

(profile description: `backend:onnx|model_type:onnx|precision:fp16`)

> NOTE: this profile loads cleanly but inference fails at the ReduceSum
> kernel with `cudaErrorSymbolNotFound`. See `wave-3-final-report.md` for
> defer-to-3.5 disposition. The hash itself is correct; what's broken is
> the ONNX runtime in the NIM container vs GB10 CUDA driver, not profile
> selection.

### Procedure for deriving the hash for any new NIM

```bash
# 1. Run list-model-profiles against the image (requires GPU on the target host)
sudo docker run --rm --gpus all \
  -v /mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache:/opt/nim/.cache \
  --env-file /etc/fortress/nim.env \
  nvcr.io/nim/nvidia/<model>:<tag> list-model-profiles 2>&1

# 2. Read the "Compatible with system:" stanza
#    Format:    - <SHA256> - backend:...|gpu:...|precision:...

# 3. If multiple profiles compatible: prefer ONNX > tensorrt; prefer fp16 > fp8
#    (cluster has only encountered single-profile cases so far)

# 4. Record the SHA256 in the systemd unit's ExecStart -e NIM_MODEL_PROFILE=...
#    Pin it. Never use `auto`. Never rely on profile selectors.
```

---

## 2. NAS cache directory layout

### Convention

```
/mnt/fortress_nas/nim-cache/nim/<model>/
├── <tag>/                       # one dir per pulled tag
│   ├── image.tar                # docker-loadable tar archive
│   ├── image.sha256             # tar digest
│   └── verification.json        # ARM64 verify gate result
├── nim-weights-cache/           # MUST be admin:admin 775
│                                # mounted into container as /opt/nim/.cache
│                                # this is where NIM downloads model weights
│                                # at first boot (HF cache + NGC blobs)
└── (other tag dirs as needed)
```

### Reranker tree (Wave 3 v2 — what the layout actually looks like)

```
/mnt/fortress_nas/nim-cache/nim/llama-3.2-nv-rerankqa-1b-v2/
├── 1.8.0/
│   ├── image.tar          (2.3 GB)
│   ├── image.sha256       (71 B)
│   └── verification.json  (556 B — verdict PASS)
└── nim-weights-cache/     (admin:admin 775)
    └── ngc/hub/models--nim--nvidia--llama-3.2-nv-rerankqa-1b-v2/
        ├── snapshots/.../tokenizer_config.json
        ├── snapshots/.../tokenizer.json
        └── blobs/...                       (model.onnx.tar etc.)
```

### nim-weights-cache permissions GOTCHA

If you pre-create `nim-weights-cache/` via `sudo mkdir`, it lands as
`root:root 755` and the NIM container hits `Permission denied (os error 13)`
at first weight download. Always:

```bash
sudo chown -R admin:admin /mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache
sudo chmod 775 /mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache
```

(Container UID inside the NIM image happens to match host `admin` UID 1000
on this cluster. If that ever changes, dir needs to be `777` or owned by
the matching UID.)

---

## 3. systemd unit pattern

### Verbatim from `/etc/systemd/system/fortress-nim-embed.service` (canonical)

```ini
ExecStartPre=-/usr/bin/docker stop fortress-nim-embed
ExecStartPre=-/usr/bin/docker rm fortress-nim-embed

# Load from NAS if pinned image not in local Docker daemon cache
# Image: nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest
# arm64, image ID sha256:c559ea63...
# (loaded 2026-04-29 from /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar)
ExecStartPre=/bin/bash -c '\
  if ! docker image inspect nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest >/dev/null 2>&1; then \
    echo "Loading NIM from NAS cache..."; \
    docker load < /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/latest/image.tar; \
  fi'

ExecStart=/usr/bin/docker run \
  --name fortress-nim-embed \
  --rm \
  --gpus all \
  --shm-size=4g \
  -p 8102:8000 \
  -v /mnt/fortress_nas/nim-cache/nim/llama-nemotron-embed-1b-v2/nim-weights-cache:/opt/nim/.cache \
  --env-file /etc/fortress/nim.env \
  -e NIM_MODEL_PROFILE=e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528 \
  nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest

ExecStop=/usr/bin/docker stop fortress-nim-embed
```

### Conventions (vs brief defaults)

| Aspect | Brief default | Cluster reality |
|---|---|---|
| Env file | `EnvironmentFile=/etc/fortress/nim.env` + `-e NGC_API_KEY=${NGC_API_KEY}` | `--env-file /etc/fortress/nim.env` directly on `docker run` |
| Container lifecycle | `--rm` | `--rm` (matches brief) |
| Restart policy | `Restart=on-failure` | `Restart=always`, `RestartSec=30`, `TimeoutStartSec=300` |
| Image source | `docker pull` at run time | `docker load` from NAS tar in ExecStartPre (avoids nvcr.io TLS issues on ARM64 daemon) |
| Cache mount | `…/hf-cache:/opt/nim/.cache` | `…/nim-weights-cache:/opt/nim/.cache` |
| Profile env | `NIM_MODEL_PROFILE=auto` | Pinned SHA256 (see §1) |
| `--ipc=host` | not specified | not used (`--shm-size` instead) |
| `--ulimit memlock=-1` | not specified | recommended for reranker per container's own warning |
| Standard out/err | not specified | `StandardOutput=journal`, `SyslogIdentifier=...` |

### Port assignment pattern

- 8101 — Vision NIM (`fortress-nim-vision-concierge.service` on spark-3)
- 8102 — EMBED NIM (`fortress-nim-embed.service` on spark-3)
- 8103 — Reranker NIM (`fortress-nim-rerank.service` on spark-5) — Wave 3 v2 reservation
- 8110 / 8111 / 8112 — Extraction NIMs (page / graphic / table) on spark-5 — Wave 3 v2 reservation; deferred

---

## 4. ARM64 verification tooling

### Brief said
```
/home/admin/Fortress-Prime/backend/scripts/verify_nim_arm64.sh
```

### Cluster reality

Two cooperating files, BOTH at the repo root, NOT under `backend/scripts/`:

- `scripts/nim_pull_to_nas.py` — main library, contains
  `verify_arm64_with_docker()` and `verify_nas_tar()`.
- `tools/nim_arm64_probe.py` — standalone CLI wrapper around those
  two functions.

### Working invocation

```bash
# Audit an existing NAS tar:
python3 tools/nim_arm64_probe.py --verify-nas \
  /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

# Audit an image-ref directly (pulls manifest, runs ELF check via docker):
python3 tools/nim_arm64_probe.py --models nvcr.io/nim/nvidia/<model>:<tag>

# Machine-readable:
python3 tools/nim_arm64_probe.py --models … --json
```

Two-stage gate: Stage 1 = arm64 platform present in manifest list; Stage 2
= layer-0 extracted binary's ELF header is `ARM aarch64`. Both must PASS
or the verdict is `MANIFEST_FAIL` / `ELF_FAIL` / `ERROR`.

### What the brief got wrong
- Wrong path (`backend/scripts/verify_nim_arm64.sh` doesn't exist).
- Wrong filename (`.sh` vs actual `.py`).
- Wrong invocation pattern. Brief calls `verify_nim_arm64.sh ./` against
  a directory; actual tool takes `--models <image-ref>` or
  `--verify-nas <tar-path>`.

---

## 5. ngc CLI query syntax

| Goal | Brief said | What works |
|---|---|---|
| Inspect a NIM image | `ngc registry resource info nim/nvidia/<name>` | `ngc registry image info nvcr.io/nim/nvidia/<name>:<tag>` |
| List image tags | `ngc registry resource list --query "<name>" --org nvidia` | `ngc registry image list "nvcr.io/nim/nvidia/<name>*"` |
| Pull image | `ngc registry resource download-version "nim/nvidia/<name>:<tag>"` | Use `scripts/nim_pull_to_nas.py` instead — see §6 |
| Auth probe | `ngc config current` + `ngc registry resource list --org cabin-rentals-of-georgia` | `ngc config current` works; the resource-list-by-org returns nothing because NIM images live under the `nim` org, not the cluster's billing org |

`ngc registry resource info` returns 403 for NIM container images because
they're container-image registry resources, not NGC `resource`-type
artifacts. Use `ngc registry image …` for containers.

### Auth itself
Auth lives in `/etc/fortress/nim.env` as `NGC_API_KEY=…` (root-owned 600).
`tools/ngc_login_workers.sh` distributes a `docker login nvcr.io` to the
worker hosts via SSH; ngc CLI on CAPTAIN authenticates from `~/.ngc/config`
which is set up out-of-band by the operator.

### Entitlement vs auth distinction

**Auth working ≠ access to all NIMs.** During Wave 3 v2, the cluster's NGC
key authenticated successfully and could pull
`llama-3.2-nv-rerankqa-1b-v2:1.8.0` (associated products: `nim-dev`,
`nv-ai-enterprise`) but returned **403 DENIED** at both `ngc registry
image info` and `docker manifest inspect` for all three YOLOX extraction
NIMs across every tag tried (`:latest`, `:1.0`, `:latest-dgx-spark`):

- `nv-yolox-page-elements-v2`
- `nv-yolox-graphic-elements-v1`
- `nv-yolox-table-structure-v1`

Inference: cluster's NGC subscription does not include the entitlement
that ships these specific repositories (likely a NeMo Retriever
subscription or NIM-Microservices entitlement separate from the base
`nv-ai-enterprise` plan). This is a billing/subscription axis, not a
technical fix. **Diagnose `ngc registry image …` 403s as
entitlement-side, not auth-side, before raising as a hard stop.**

---

## 6. NIM weight pull workflow — `scripts/nim_pull_to_nas.py`

### Why this is preferred over `ngc registry resource download-version`

- Streams via the NGC HTTPS API directly (skips Docker daemon TLS issues
  that nvcr.io has with the ARM64 daemon on Spark).
- Builds a Docker-loadable `image.tar` rather than NGC's resource-version
  artifact format.
- Runs the two-stage ARM64 gate (manifest + ELF) before committing the tar
  to NAS. If either gate fails, the partial download is purged.
- Writes a sidecar `verification.json` so subsequent operators can audit.

### Invocation

```bash
# Pull a specific tag:
sudo -E python3 scripts/nim_pull_to_nas.py <model-name> --tag <tag>

# Pull latest:
sudo -E python3 scripts/nim_pull_to_nas.py <model-name>

# Audit an existing NAS tar (no pull):
python3 scripts/nim_pull_to_nas.py --verify-only \
  /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar

# Emergency: skip ARM64 verification (NEVER use unless the ARM64-gate
# tooling itself is broken, not because the NIM is broken):
sudo -E python3 scripts/nim_pull_to_nas.py <model-name> --force-skip-verification
```

`sudo -E` is needed because the script reads `NGC_API_KEY` from
`/etc/fortress/nim.env` (root-owned 600) but otherwise runs as the invoking
user for HTTP+tarfile work. `-E` preserves PATH so `python3` and `docker`
resolve correctly.

### End-to-end

```
NGC pull (HTTPS API)
  ↓
  Stage 1 manifest probe — assert arm64 platform listed
  ↓
  Download all layers
  ↓
  Stage 2 ELF probe — `docker save | tar -x | file <layer-0-binary>`
                       must report ARM aarch64
  ↓
  Build /mnt/fortress_nas/nim-cache/nim/<model>/<tag>/image.tar
  Write image.sha256 sidecar
  Write verification.json sidecar
  ↓
  (operator) docker load < image.tar       # on each consumer host
  ↓
  (operator) discover NIM_MODEL_PROFILE via list-model-profiles (§1)
  ↓
  (operator) write systemd unit (§3) and start
```

### When to use each

- **Always use `nim_pull_to_nas.py`** for fresh pulls — it gates ARM64,
  bypasses daemon TLS, and centralizes weight cache to NAS so multiple
  hosts can `docker load` from the same tar.
- **Never use `ngc registry resource download-version`** for NIM container
  images — wrong artifact type for containers.
- **Never `docker pull` directly** to the host daemon on Spark — nvcr.io
  TLS issues on ARM64 daemon cause intermittent failures. Use the NAS tar
  + `docker load` pattern instead.

---

## 7. spark-3 GPU co-tenancy ceiling

The TP=2 frontier (vllm_node container, port 8000 via internal 10.10.10.3
endpoint) consumes the dominant share of spark-3's 121.69 GiB unified
GPU memory. As of 2026-05-01, only ~16 GiB is free with the frontier
serving traffic.

**Implication for any new spark-3 NIM:**
- A NIM requesting `gpu_memory_utilization=0.55` (= 66.93 GiB on this
  node) will fail at engine init with:
  ```
  ValueError: Free memory on device (16.18/121.69 GiB) on startup is less
  than desired GPU memory utilization (0.55, 66.93 GiB).
  ```
- Smaller services (EMBED at ~2 GiB) co-exist fine.
- Vision NIM (`fortress-nim-vision-concierge.service`,
  `nemotron-nano-12b-v2-vl`) at 0.55 utilization does NOT fit alongside
  the frontier.

**Brief constraint forbids modifying Vision config** (per
`fortress-nim-embed.service` header: "operator chose 8102 to avoid
colliding with Vision NIM and honor §8 hard constraint forbidding
Vision NIM modification") — so reducing Vision's `gpu_memory_utilization`
is not on the table without a separate config-change brief.

**Resolution path:** Vision restart is gated on either (a) frontier
relocation off spark-3, (b) frontier KV cache reduction, or (c) explicit
brief authorizing Vision config change.

---

## 8. Anti-patterns observed during Wave 3 v2

- ❌ `EnvironmentFile=` AND `-e KEY=${VAL}` in same unit — pick one. Cluster uses `--env-file` on docker run only.
- ❌ Pre-creating `nim-weights-cache/` with `sudo mkdir` (root:root) — container can't write.
- ❌ `NIM_MODEL_PROFILE=auto` — fails on every NIM tested so far on GB10.
- ❌ `ngc registry resource info <nim-image>` — wrong CLI subcommand for container images.
- ❌ `cp` of brief into repo via SSH at PR time — brief is already on `main` after its own PR merges; the §13.1 cp step in older brief drafts is dead code.
- ❌ Assuming `Restart=always` will recover — it will, but that just burns cycles re-failing if the underlying issue is OOM/entitlement/profile, not transient.
- ❌ Treating "auth works" as proof of "NIM accessible" — entitlement is a separate axis. Probe with `ngc registry image info <full-image-ref>` per NIM before assuming pullability.

---

## 9. Source incidents that informed this doc

- 2026-04-29 EMBED restart (`fortress-nim-embed.service` activation per `llama-nemotron-embed-deployment-brief.md`) — discovered the `NIM_MODEL_PROFILE=auto` failure and pinned-hash workaround; established `--env-file /etc/fortress/nim.env` and `--shm-size` patterns.
- 2026-05-01 Wave 3 v2 partial deployment — discovered the nim-weights-cache permissions gotcha, the entitlement vs auth distinction (YOLOX 403), the spark-3 GPU co-tenancy ceiling, and the cudaErrorSymbolNotFound failure family extending from EMBED v1.10.0 to reranker `:1.8.0`.
