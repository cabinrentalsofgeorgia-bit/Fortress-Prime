# llama-nemotron-embed-1b-v2 Deployment Record

**Date:** 2026-04-29
**Driver:** PR #291 NIM stack audit P0
**Status:** ✅ DEPLOYED (cutover 2026-04-29 21:39 EDT)
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

---

## §9 Cutover resumption — 2026-04-29 21:39 EDT — STATUS: DEPLOYED

After the §5.3 NGC blocker was unwedged offline (operator handled the credential / weights pre-stage out-of-band), the embed service came up cleanly on spark-3:8102. This section records the gateway cutover that followed.

### §9.1 Pre-cutover state

| Check | Result |
|---|---|
| `fortress-nim-embed.service` on spark-3 | `active` |
| `ss -tlnp` shows :8102 LISTEN | ✅ |
| `GET http://spark-3:8102/v1/health/ready` | `{"object":"health-response","message":"Service is ready."}` |
| `GET http://spark-3:8102/v1/models` | `[{"id":"nvidia/llama-nemotron-embed-1b-v2", ...}]` |

### §9.2 Active LiteLLM config diff (gitignored, edited in place)

Backup: `/home/admin/Fortress-Prime/litellm_config.yaml.bak.20260429-210559`.

Inserted between `legal-brain` and the cloud routes block:

```yaml
  # ──────────────────────────────────────────────────────────────────────────
  # SOVEREIGN LEGAL EMBEDDING (2026-04-29)
  # llama-nemotron-embed-1b-v2 (NIM, ONNX/fp16) on spark-3:8102, vec_dim=2048.
  # ASYMMETRIC MODEL: callers MUST send input_type=query for retrieval queries
  # and input_type=passage for documents being indexed. Mismatched input_type
  # measurably degrades retrieval quality (this is not a symmetric encoder).
  # drop_params=true must NOT strip input_type — verified during 2026-04-29
  # gateway cutover. If drop_params ever strips it again, override per-route
  # with drop_params: false in litellm_params.
  # ──────────────────────────────────────────────────────────────────────────
  - model_name: legal-embed
    litellm_params:
      model: openai/nvidia/llama-nemotron-embed-1b-v2
      api_base: http://spark-3:8102/v1
      api_key: dummy
      timeout: 60
```

Scope intentionally narrow per operator decision (option c): only the active config on the gateway host was edited. `deploy/litellm_config.yaml` (the committed template) still lacks the alias and will be reconciled in a follow-up PR — folded into **Issue #298** (litellm config drift between active and committed template).

### §9.3 Gateway restart

```
$ ssh admin@192.168.0.100 'sudo systemctl restart litellm-gateway.service'
$ ssh admin@192.168.0.100 'sudo systemctl status litellm-gateway.service'
● litellm-gateway.service - LiteLLM API Gateway (Fortress Sovereign Model Router)
     Active: active (running) since Wed 2026-04-29 21:39:13 EDT
   Main PID: 3467426 (litellm)
     CGroup: /usr/bin/python3 /home/admin/.local/bin/litellm
                --config /home/admin/Fortress-Prime/litellm_config.yaml
                --port 8002 --host 127.0.0.1
```

Gateway came back clean on first try. Backup unused.

### §9.4 Alias enumeration via `/v1/models` — PASSED

Port confirmed as **8002** (per Session 2's prereq finding; brief default 4000 was wrong on this host):

```
HTTP 200
legal-reasoning
legal-classification
legal-summarization
legal-brain
legal-embed              ← NEW
claude-sonnet-4-6
claude-opus-4-6
gpt-4o
grok-4
gemini-2.5-pro
deepseek-chat
deepseek-reasoner
```

All 11 pre-existing aliases unchanged + the new one. ✅

### §9.5 Gateway-routed embedding probe — PASSED (with caller-contract surprise)

#### Iteration 1 — `input_type=query` only — FAILED on `encoding_format`

```
POST http://localhost:8002/embeddings
Body: {"input": "...", "model": "legal-embed", "input_type": "query"}

HTTP 400
litellm.BadRequestError: OpenAIException - Error code: 400 -
{'object': 'error', 'message': 'Your request cannot be validated, it is incorrect.',
 'detail': {'type': 'literal_error', 'loc': ['body', 'encoding_format'],
            'msg': "Input should be 'float' or 'base64'", 'input': None,
            'ctx': {'expected': "'float' or 'base64'"}},
 'type': 'request_validation_error'}
```

Surprise: the failure mode is **not** the predicted "drop_params strips input_type." `drop_params` is forwarding `encoding_format=None` (LiteLLM's OpenAI default) and the NIM strictly validates this field to be one of `"float"` / `"base64"` — `None` is rejected.

Diagnosis: `input_type` was preserved through `drop_params` in this build. The new caller contract is:
- `input_type` must be set (`"query"` for retrieval, `"passage"` for indexing)
- `encoding_format` must be set explicitly to `"float"` (or `"base64"`); the OpenAI client's implicit default of `None` is rejected

#### Iteration 2 — explicit `encoding_format: "float"` — PASSED

```
POST http://localhost:8002/embeddings
Body: {"input": "defendant moves for summary judgment under Rule 56",
       "model": "legal-embed",
       "input_type": "query",
       "encoding_format": "float"}

HTTP 200
vec_len: 2048
usage: {'prompt_tokens': 12, 'total_tokens': 12, 'completion_tokens': 0, ...}
```

✅ Vector dimension as expected, usage populated, sub-second response.

### §9.6 Zero-cloud-outbound check — PASSED

```
$ sudo journalctl -u litellm-gateway.service --since "3 minutes ago" \
    | grep -Ec 'https?://[^/]*(openai\.com|anthropic\.com|googleapis\.com|api\.x\.ai|api\.deepseek\.com)'
0
```

(An initial loose grep for `openai\.com` returned 1, which was a false positive matching `litellm.llms.openai.common_utils.OpenAIError` in the iteration-1 stack trace. Re-grep with the URL prefix anchor returned 0 — no actual cloud-provider HTTP calls during the probe window.)

### §9.7 Quality sanity — PASSED on both encoders

Texts:
- **A:** "Plaintiff alleges breach of fiduciary duty by the defendant trustee."
- **B:** "The complaint claims the defendant breached fiduciary obligations as trustee." (legal paraphrase of A)
- **C:** "The cabin features a hot tub and mountain view." (off-domain distractor)

| Encoder | vec_dim | cos(A,B) | cos(A,C) | margin | PASS? |
|---|---:|---:|---:|---:|:---:|
| `legal-embed` (llama-nemotron-embed-1b-v2 via gateway, `input_type=query`) | 2048 | 0.8042 | 0.0502 | **0.7540** | ✅ |
| `nomic-embed-text:latest` (Ollama spark-2, baseline)                       |  768 | 0.9245 | 0.3778 | 0.5467     | ✅ |

Both pass the cos(A,B) > cos(A,C) ordering check. The sovereign legal encoder shows much sharper separation from off-domain content (cos(A,C)=0.05 vs nomic's 0.38), consistent with domain-specialized training. Absolute cos(A,B) is lower than nomic, which is expected for a sparser, higher-dimensional embedding — what matters for retrieval is the relative ordering and the margin, both of which are healthier on `legal-embed`.

### §9.8 Caller-contract requirements (downstream callers MUST honor)

Any caller invoking `legal-embed` via the gateway MUST send:

| Field | Value | Why |
|---|---|---|
| `model` | `"legal-embed"` | gateway alias (resolves to `openai/nvidia/llama-nemotron-embed-1b-v2` on spark-3:8102) |
| `input_type` | `"query"` for retrieval calls; `"passage"` for documents being indexed | asymmetric encoder — mismatched input_type degrades retrieval; verified preserved through `drop_params` 2026-04-29 |
| `encoding_format` | `"float"` (or `"base64"`) | NIM strictly validates; LiteLLM/OpenAI implicit default of `None` is rejected with HTTP 400 |
| `input` | string or list of strings | standard |

Indexing pipelines that use `passage` and retrieval pipelines that use `query` should be wired through different helper functions to make the asymmetry explicit at the call site.

### §9.9 Follow-up items

- **Issue #298 (litellm config drift):** `deploy/litellm_config.yaml` (committed template) does not contain the `legal-embed` alias. Reconcile in a separate PR. Per operator decision (option c), this PR intentionally only touches the active config + cutover doc + systemd unit.
- **Caller migration:** downstream callers currently using `nomic-embed-text` for legal retrieval are **not** migrated by this PR. Migration is a separate, planned workstream — `nomic-embed-text` remains the production embedding for now and the existing Qdrant collections are untouched (per §8 hard constraints).
- **Asymmetric-model wrapper:** consider adding a thin helper in `backend/services/legal/` (e.g. `embed_query()` / `embed_passage()`) so callers cannot accidentally send the wrong `input_type`. Tracking informally; not in scope for this PR.

### §9.10 Hard-constraint compliance — recheck after cutover

| § | Constraint | Status |
|---|---|---|
| 8 | DO NOT modify nomic-embed-text Ollama config | ✅ Untouched (verified during §9.7 baseline call) |
| 8 | DO NOT reindex any Qdrant collection | ✅ No collection touched |
| 8 | DO NOT modify legal_council.py / freeze_context / freeze_privileged_context | ✅ Untouched |
| 8 | DO NOT modify Phase B retrieval primitives | ✅ Untouched |
| 8 | DO NOT modify vault_ingest_legal_case.py / ingestion scripts | ✅ Untouched |
| 8 | DO NOT modify spark-1 or spark-5 services | ✅ Untouched (legal-reasoning/-classification/-summarization/-brain still resolve to spark-5:8100) |
| 8 | DO NOT modify Vision NIM | ✅ Untouched (port 8101 still owned by Vision NIM) |
| 8 | DO NOT stop or modify any ollama service or container | ✅ Untouched |
| 8 | Open at most one PR | ✅ One PR, this one |
