# Phase 9 — Wave 1 Close + Wave 2 Alias Surgery + BRAIN-49B Retirement

**Target:** Claude Code on spark-2
**Branch:** `feat/phase-9-wave-2-alias-surgery-2026-04-30`
**Date:** 2026-04-30
**Operator:** Gary Knight
**Driver:** Phase 7 smoke validated (Section 2 ✅, Section 5 mixed→accepted per operator B/C decision). Wave 1 close + Wave 2 reconceived as LiteLLM alias surgery against the existing spark-3+4 TP=2 endpoint. No new model deployment.
**Stacks on:**
- PR #321 (ADR-007 + TP=2 deployment evidence pack, draft, locks pending soak)
- nemotron-super-stack-architecture-brief.md (PR landed; ADR-005 needs amendment per this brief §6)
- MASTER-PLAN v1.7
**Resolves:** Wave 1 close criteria; Wave 2 routing surgery; ADR-005 amendment; BRAIN-49B retirement

---

## 0. Post-execution reconciliation (added 2026-05-01 ~01:30 UTC after Step 1 + Step 1.5 inspection)

> **Reader: this brief was authored as a future-tense execution plan. Execution happened ahead of the brief commit, with a defect. Read this section first.**

### 0.1 Headline — schema defect on the wire

The live LiteLLM config (`/home/admin/Fortress-Prime/litellm_config.yaml`, mtime 2026-04-30 13:12 EDT) implements the alias surgery described in §5 below. Step 1.5 LiteLLM serialization probe (single curl per of two diagnostic aliases at 2026-05-01 01:28 UTC) confirmed: **the per-alias reasoning controls do not reach the model on the wire.** All five legal-* aliases run on default reasoning depth despite the YAML's apparent differentiation.

Two independently-sufficient failure modes each produce this observation. Either or both may apply; the schema fix below addresses both.

| Failure mode | Mechanism | Evidence |
|---|---|---|
| **(1) LiteLLM extra_body silently dropped at gateway** | The live YAML wraps `chat_template_kwargs` and `reasoning_effort` inside `extra_body`. PR #330 Probe E proved that vLLM's OpenAI-compat server doesn't introspect `extra_body` — fields wrapped inside are silently dropped. LiteLLM 1.83.4's serialization behavior at the gateway-to-vLLM boundary was not previously characterized; the §1.5 probe couldn't uniquely identify whether LiteLLM unwraps or forwards verbatim, only that the wire-level effect is "not reaching the model." | §1.5 probes — `legal-summarization` (configured `thinking=false`) produced 105 chars of `reasoning_content`. If `thinking=false` had reached the model, it would be 0. |
| **(2) Chat-template key mismatch** | The chat template (`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/blob/main/chat_template.jinja`) defines two reasoning variables: `enable_thinking` (default True) and `low_effort` (default False). The live YAML uses key `thinking`, which is not a chat-template variable. Even if (1) is fully resolved, a request with `chat_template_kwargs.thinking=false` at top level would still produce reasoning because the chat template ignores that key. | `nemotron-3-super-deep-research-2026-04-30.md` §1; live YAML lines for legal-reasoning / legal-drafting / legal-summarization. |
| **(3) `reasoning_effort` is OpenAI-class, not honored** | OpenAI-class kwarg, not a Nemotron chat-template variable. PR #331 confirmed it's silently dropped by LiteLLM's `drop_params: true` and not honored by Nemotron regardless. Documented inert. | PR #331 deprecation notice; live YAML uses it for all three aliases. |

**Layer-attribution caveat.** The §1.5 probes definitively establish that reasoning controls are not reaching the model. They do NOT uniquely identify the failure layer between (1) and (2) — both are independently sufficient and would produce the same observable. The schema fix below addresses both layers; readers should not infer that LiteLLM is the proximate cause.

### 0.2 Schema-fix PR scope (small, surgical, follow-up)

Three alias entries rewritten in `/home/admin/Fortress-Prime/litellm_config.yaml`:

| Alias | enable_thinking | low_effort | force_nonempty_content | Drop `reasoning_effort`? | `extra_body` wrapper? |
|---|---|---|---|---|---|
| legal-reasoning | True | False | True | yes | no — top level |
| legal-drafting | True | False | True | yes | no — top level |
| legal-summarization | False | (n/a — controlled by enable_thinking) | True | yes | no — top level |

`legal-drafting` middle-ground note: medium-effort is not engageable on this frontier without `--reasoning-config` on the vLLM serve command. `thinking_token_budget` requires it per `nemotron-3-super-deep-research-2026-04-30.md` §2. Until frontier is redeployed with `--reasoning-config`, `legal-drafting` defaults to full reasoning (same as `legal-reasoning`) — surfaced explicitly so consumers don't expect different reasoning depth.

`thinking_token_budget` is **deferred**. Separate ticket: redeploy frontier with `--reasoning-config '{"reasoning_start_str": "<think>", "reasoning_end_str": "</think>"}'` to engage the middle-ground reasoning lever. Out of scope for the schema-fix PR.

After config edit: `sudo systemctl reload litellm-gateway.service` + post-fix probe matching the §1.5 protocol to confirm differentiation reaches the model.

### 0.3 Sampling defaults — deviation surfaced, decision pending

Live YAML uses `temperature=0.3/0.5/0.4`, `top_p=0.95` for the three aliases. NVIDIA model card and advanced deployment guide specify `temperature=1.0, top_p=0.95` for **all modes** (reasoning, tool-calling, general chat). The current values are off-distribution per Nemotron's calibration.

This brief surfaces the deviation. **Sampling alignment is NOT rolled into the schema-fix PR.** Sampling alignment is a separate decision the operator hasn't made for non-§5 aliases. (PR #335 Wave 4 §5 took Path A — NVIDIA-spec sampling — scoped to §5 only via per-section policy. Whether to extend Path A to per-alias defaults globally is a different conversation.)

### 0.4 force_nonempty_content per alias

Wave 4 §5 amendment carry-forward (PR #335 / `super_v3_reasoning_parser.py`). Cheap insurance, no behavioral cost on success path: when reasoning hits `max_tokens` without emitting `</think>`, the `super_v3` parser routes the buffer to `content` rather than stranding it in `reasoning_content`. Add to all three legal-* aliases as part of the schema-fix PR.

### 0.5 Impact statement

Live alias surgery committed at **2026-04-30 13:12 EDT** (litellm_config.yaml mtime). §1.5 probe verdict at **2026-05-01 01:28 UTC** (= 2026-04-30 21:28 EDT). **Window: ~8h 16min.**

All Council deliberations, drafting outputs, and other gateway-routed legal-* requests during this window ran on default reasoning depth — not the configured per-alias differentiation. Outputs are intact (model produced valid responses). Wall-time and token-cost regressed (full reasoning where shorter was intended). **Not a quality fire, an economic one.**

Wave 4 §5 production runs (PR #335) used BrainClient direct-to-frontier, **bypassing LiteLLM entirely** — those runs are unaffected. The Track A v3 brief on NAS at `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260501T002431Z.md` is unaffected.

Investigation ticket (separate, not blocking the brief PR or the schema-fix PR): identify which specific Council deliberations / drafting outputs since 13:12 EDT touched the gateway. Light-touch — most likely not actionable beyond noting the window for the operator's own audit.

### 0.6 Reconciled state captured (snapshot 2026-05-01 ~01:30 UTC)

| Item | Status (per Step 1 inspection) |
|---|---|
| Wave 1 close — EMBED on spark-3:8102 | **DONE.** Verified post-restart in PR #336 (merged `81cdeb7a7` at 2026-05-01 01:08 UTC). vec_dim=2048, zero cloud outbound, cosine quality 0.5242 PASS. |
| Alias surgery YAML wiring | **DONE** at 13:12 EDT 2026-04-30 (live config). |
| Alias surgery wire-level effective | **NO** (per §0.1 schema defect). Pending schema-fix PR per §0.2. |
| BRAIN-49B service on spark-5 | **RETIRED** at 13:16:39 EDT 2026-04-30 (clean systemctl stop, 28.7M unit RAM peak, image+unit preserved on spark-5 per implicit rollback pattern). |
| `deploy/litellm_config.yaml` template | **STALE** — 227-line drift from live; still references "ADR-003 Phase 1 — All legal-tier inference terminates on spark-5 NIM" (old direction). Sync via separate template-sync PR (or fold into schema-fix). |
| Council seat env-default reassignment | **DONE** at code level (`legal_council.py:141-149` — ANTHROPIC/OPENAI/XAI/DEEPSEEK_MODEL → `legal-reasoning`; GEMINI_MODEL → `legal-summarization`). One stale comment at line 1 references "spark-5 NIM" — comment-only cleanup pending. |
| BrainClient supports per-call reasoning kwargs | **DONE** via PR #331 (Phase 2 wiring) + PR #335 (Wave 4 §5 — added `force_nonempty_content` + `top_p`). Top-level placement schema, dual response-shape parsing, deprecation warnings on `reasoning_effort` / `thinking`. |
| ADR-005 reference (cited in original brief §6) | **NOT FOUND** in `_architectural-decisions.md`. Repo has ADR-006 (Phase 2 Partner Reassignment). Reconcile to **ADR-007** (PR #321 OPEN — "Nemotron-3-Super-120B TP=2 spark-3+4 as Fortress Legal synthesizer") which is the actual architectural ratification this brief sits downstream of. Original §6 ADR-005-amendment plan supersedes to ADR-007 acceptance via PR #321 merge + downstream Wave 2 ratification PR. |
| spark-5 freed for Wave 3 | **YES** — BRAIN retirement freed it; retrieval co-tenancy plan stays per §2 below. |

### 0.7 PR sequence

1. **This brief PR (doc-only).** Captures reconciled state + schema defect. No LiteLLM edits, no service changes, no code changes.
2. **Schema-fix PR (small, surgical).** Three alias entries rewritten in live `litellm_config.yaml`. Top-level `chat_template_kwargs.{enable_thinking, low_effort}`. Drop `reasoning_effort`. Drop `extra_body` wrapper. Add `force_nonempty_content: True` per alias. Reload gateway. Post-fix probe per §1.5 protocol.
3. **Template-sync PR.** Bring `deploy/litellm_config.yaml` to match the post-fix live config. Could fold into #2.
4. **ADR-007 / Wave 2 ratification PR.** Formalize BRAIN-49B retirement (runbook commit per §7.3 below). ADR-007 acceptance (PR #321 merges or ratification PR amends in place). Council seat comment-only cleanup. ADR numbering reconciliation.

Each independently small. Each independently reviewable. None touch the model, the deployment, or the deep-research-validated frontier topology.

### 0.8 What this brief does NOT do

Doc-only. Does not edit `litellm_config.yaml` (live or template). Does not stop/start any service. Does not modify any code. Does not amend any ADR. Does not pull any Wave 3 NIM weights. Each downstream PR addresses one of those scopes.

---

> *Sections 1–12 below preserved as the historical execution plan. Where execution at 13:12/13:16 EDT 2026-04-30 has overtaken the plan, sections carry an inline `[Status: …]` note pointing back to §0.6.*

---

## 1. Mission

> **[Status: §0.6 — Wave 1 closed via PR #336 (merged 2026-05-01 01:08 UTC). Alias surgery YAML wiring done 2026-04-30 13:12 EDT but wire-level effective NO per §0.1 schema defect. BRAIN-49B retired 2026-04-30 13:16:39 EDT. spark-5 freed.]**

Close Wave 1. Execute Wave 2 reconceived: route all three Fortress Legal LLM aliases (`legal-reasoning`, `legal-drafting`, `legal-summarization`) at the existing spark-3+4 TP=2 endpoint with differentiated invocation profiles. Retire BRAIN-49B. Repurpose spark-5 as retrieval co-tenant. Amend ADR-005 in place to reflect operator-corrected topology. Stage Wave 3 prep without execution.

The frontier model is already deployed. This brief wires the consumers to it.

---

## 2. Operator-corrected topology (foundational)

Replaces stack-architecture brief §3.5, §5 Tier 2/3, §7 Decision, and §8 row 6.

**Operator correction:** Super-120B does NOT fit single-Spark cleanly under real workload (KV cache + MTP + concurrent requests + Mamba SSM cache exceed theoretical NVFP4 headroom). The TP=2 endpoint on spark-3+4 IS the frontier model. Not "drafting tier waiting for TITAN." The frontier.

**No separate single-Spark TITAN deployment.** Wave 2 = LiteLLM alias surgery, same model, differentiated calls.

**Topology under reorientation:**

```
┌─────────────────────────────────────────────────────────────────┐
│ FRONTIER (spark-3 + spark-4, TP=2, Ray distributed executor)    │
│   Endpoint:  http://10.10.10.3:8000/v1                          │
│   Model:     nemotron-3-super (Nemotron-3-Super-120B-A12B-NVFP4)│
│   Backend:   vLLM 0.20.1rc1.dev96+gefdc95674.d20260430          │
│   Config:    max-model-len 262144, max-num-seqs 10, gpu-mem 0.7 │
│   Reasoning: nemotron_v3 parser (architectural separation)       │
│   Fabric:    NCCL_IB_HCA dual rocep, MTU 9000, 97.98 Gbps        │
│   Aliases:   legal-reasoning, legal-drafting, legal-summarization│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ RETRIEVAL CO-TENANT (spark-5, single-node) — Wave 3 target      │
│   • llama-nemotron-rerank-1b-v2 NIM                             │
│   • NeMo Retriever Extraction NIM(s)                            │
│   • Migrates to HA replica role (TP=2 with spark-6) when cables │
│     land. Interim use: relieves spark-3 of retrieval workload.  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ EMBED + VISION (spark-3 co-tenant, restored post Phase 8)       │
│   • llama-nemotron-embed-1b-v2 NIM (port 8102)                  │
│   • nemotron-nano-12b-v2-vl NIM (port 8101)                     │
│   • Restart sequence per PR #321 evidence                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ CONTROL PLANE (spark-2)                                         │
│   • LiteLLM gateway (alias map; this PR mutates)                │
│   • Captain, FLOS, Sentinel (existing)                          │
│   • SWARM Qwen2.5 (privilege classifier)                        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ FORTRESS LEGAL APP (spark-1, sole tenant per ADR-001)           │
│   Consumes frontier via aliases through LiteLLM                 │
└─────────────────────────────────────────────────────────────────┘

spark-6: holds for cables. When ConnectX lands, spark-5 + spark-6
become TP=2 HA replica pair; retrieval moves elsewhere.
```

---

## 3. Wave 1 close criteria

> **[Status: §0.6 — Wave 1 closed via PR #336 (merged `81cdeb7a7` at 2026-05-01 01:08 UTC). Phase 7 smoke results retained per PR #321 supplementals; EMBED post-restart verification matrix in PR #336 confirms reproducibility.]**

Verify both pass before any Wave 2 mutation.

### 3.1 Phase 7 smoke (Phase 4 frontier endpoint)

Both Section 2 and Section 5 smoke results captured in PR #321 supplemental docs.

- ✅ Section 2: 5,560 output tokens; 18 citations / 7 unique sources; 0 first-person in content; 0 `<think>` blocks in content.
- ✅ Section 5: 2,771 output tokens; 7 citations / 3 unique sources; 0 first-person in content; 0 `<think>` blocks in content. **Operator decision (B/C):** accepted — Super-120B's precision-filter behavior (6 sources considered, 3 cited) is correct quality, not under-citation. Section 5 specifically validated by content: 5 distinct defense theories, 2 explicitly flagged as "thin or contradicted" per prompt instruction. `finish_reason=stop` (clean termination).
- Format compliance held across both sections — Nano-9B failure modes (first-person bleed, `<think>` leakage in content) NOT recurring. ADR-007 structural decision validated.
- Citation count floor (≥18) calibrated against Nano-9B promiscuous-cite behavior. Floor was the wrong metric for argumentative sections under a precision-filter model. Documented in ADR-007 lock note (this brief §7) and in follow-up issue (§9.4).

**Action:** Append decision to PR #321 supplemental file.

### 3.2 EMBED NIM (spark-3:8102) status

Verification commands:

```bash
ssh admin@192.168.0.105 'curl -fsS http://localhost:8102/v1/health/ready'
# Expected: HTTP 200

ssh admin@192.168.0.105 'curl -fsS http://localhost:8102/v1/models'
# Expected: model list including llama-nemotron-embed-1b-v2

ssh admin@192.168.0.105 'curl -fsS http://localhost:8102/v1/embeddings \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"llama-nemotron-embed-1b-v2\", \"input\": \"test\"}" \
  | jq ".data[0].embedding | length"'
# Expected: integer (vector dimension count, non-zero)
```

**If any test fails:** STOP. EMBED restart per PR #321 evidence required first. Wave 2 alias surgery proceeds independently of EMBED (frontier endpoint does not depend on EMBED), but Wave 3 retrieval pipeline does.

**If all pass:** Wave 1 closed. Proceed to Wave 2.

---

## 4. ADR pre-flight enumeration

> **[Status: §0.6 — enumeration done. ADR-005 NOT found in `_architectural-decisions.md`; repo has ADR-006 (Phase 2 Partner Reassignment); ADR-007 OPEN as PR #321 (TP=2 ratification) — the actual upstream architectural decision. ADR-005-amendment plan in §6 supersedes to ADR-007 acceptance per §0.7 step 4.]**

**Action:** Before any file write, surface the actual filed ADR state.

```bash
git fetch origin
git status
git log origin/main..HEAD --oneline

cat docs/architecture/cross-division/_architectural-decisions.md
ls docs/architecture/cross-division/adr/ 2>/dev/null || \
  ls docs/architecture/adr/ 2>/dev/null || \
  find docs -path "*adr*" -type f 2>/dev/null | head -30
```

Confirm filed status of:
- **ADR-001** — One-spark-per-app-division (LOCKED 2026-04-26)
- **ADR-002** — Captain/Council/Sentinel = Option A on spark-2 (LOCKED 2026-04-29)
- **ADR-003** — Sparks 4/5/6 inference cluster, Phase 3 sizing TP=2 + hot replica (LOCKED + Phase 1 cutover PR #285)
- **ADR-004** — App vs inference boundary (LOCKED + Amendment v2 PR #293)
- **ADR-005** — TITAN service path (PROPOSED via stack-architecture brief). **VERIFY: did the architecture brief PR land? At what status?** This brief amends in place; need to know what to amend.
- **ADR-006** — TP=2 cutover (referenced in user memory as "LOCKED in PR #315"). **VERIFY: is this filed at ADR-006 or another number?**
- **ADR-007** — TP=2 deployment evidence (draft PR #321, PROPOSED). Confirm not yet locked.

If ADR numbering conflicts (e.g., ADR-006 occupies a different decision than expected), report the actual numbering inline before writing. Numbering reconciliation may require this brief to use a different number for any net-new ADR (this brief does not file a net-new ADR; it amends ADR-005 only).

**STOP after pre-flight enumeration. Surface the report.** Operator confirms enumeration matches expectations before any file write.

---

## 5. Wave 2 — LiteLLM alias surgery

> **[Status: §0.6 — YAML wiring committed to live config 2026-04-30 13:12 EDT, but wire-level effective NO per §0.1 schema defect. The alias structure documented below is correct in shape but uses incorrect schema (`extra_body` wrapper, key `thinking` instead of `enable_thinking`, deprecated `reasoning_effort`). Schema-fix PR per §0.2 reissues these three entries with corrected schema. Sampling defaults retained per §0.3 deviation note.]**

### 5.1 Locate current LiteLLM config

```bash
ssh admin@192.168.0.100 '
  systemctl status litellm-gateway.service --no-pager 2>/dev/null | head -20
  systemctl status litellm.service --no-pager 2>/dev/null | head -20

  # Find config file path
  ps aux | grep -i litellm | grep -v grep | head -3
  find /etc /home/admin -name "*.yaml" -path "*litellm*" 2>/dev/null
  find /etc /home/admin -name "*.yaml" -path "*config*" -exec grep -l "model_list\|litellm_settings" {} \; 2>/dev/null | head -10
'
```

Surface:
- Service unit name (litellm-gateway.service or litellm.service)
- Config file path (full path)
- Current contents (first 200 lines, or full file if smaller)
- Current alias map (every `model_name` entry under `model_list`)

**STOP after surfacing. Operator confirms config location before mutation.**

### 5.2 Define the three alias profiles

Single endpoint, three calling conventions. The differentiation is in the invocation profile, not the model.

**`legal-reasoning`** — Section 4 (Claims), Section 5 (Defenses), Section 9 (Strategy), Council reasoning seats.

```yaml
- model_name: legal-reasoning
  litellm_params:
    model: openai/nemotron-3-super
    api_base: http://10.10.10.3:8000/v1
    api_key: "EMPTY"
    max_tokens: 6000
    temperature: 0.3
    top_p: 0.95
    extra_body:
      reasoning_effort: high  # if supported by nemotron_v3 parser; else omit
      chat_template_kwargs:
        thinking: true
  model_info:
    mode: chat
    base_model: nemotron-3-super-120b-a12b-nvfp4
```

**`legal-drafting`** — Section 1 (Summary), Section 3 (Parties), Section 6 (Evidence Inventory), Section 10 (Filing Checklist), general drafting.

```yaml
- model_name: legal-drafting
  litellm_params:
    model: openai/nemotron-3-super
    api_base: http://10.10.10.3:8000/v1
    api_key: "EMPTY"
    max_tokens: 4000
    temperature: 0.5
    top_p: 0.95
    extra_body:
      reasoning_effort: medium
      chat_template_kwargs:
        thinking: true
  model_info:
    mode: chat
    base_model: nemotron-3-super-120b-a12b-nvfp4
```

**`legal-summarization`** — Section 7 (Email Intelligence), Section 8 (Financial Exposure), short-form synthesis, mechanical extraction.

```yaml
- model_name: legal-summarization
  litellm_params:
    model: openai/nemotron-3-super
    api_base: http://10.10.10.3:8000/v1
    api_key: "EMPTY"
    max_tokens: 2000
    temperature: 0.4
    top_p: 0.95
    extra_body:
      reasoning_effort: low  # or thinking: false if supported
      chat_template_kwargs:
        thinking: false
  model_info:
    mode: chat
    base_model: nemotron-3-super-120b-a12b-nvfp4
```

**Notes:**
- All three aliases hit the SAME endpoint. Concurrency is handled at endpoint level via `max-num-seqs 10` plus LiteLLM queueing.
- `reasoning_effort` and `chat_template_kwargs.thinking` keys depend on what the deployed vLLM build's `nemotron_v3` parser actually accepts. Verify by reading parser source or running a single test request with each variant.
- Temperature/top_p values are starting points. Tune via Wave 4 dry-run feedback.
- Token limits are starting points. The 1M context is available; max_tokens caps OUTPUT, not context. These outputs sized to typical section length.

### 5.3 Caller surface enumeration

Before flipping aliases, find every caller. Failure mode is silently broken consumers when an alias they depend on disappears or changes shape.

```bash
ssh admin@192.168.0.100 '
  # Search Fortress-Prime repo for alias references
  cd /home/admin/Fortress-Prime
  grep -rn "legal-reasoning\|legal-drafting\|legal-summarization\|legal-classification\|legal-brain\|legal-embed" \
    --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.md" \
    | grep -v node_modules | grep -v __pycache__ | grep -v ".git/"
'
```

Categorize each hit:
- **Caller code** — actually invokes the alias (Council seat handlers, Phase B drafter, FLOS, Captain, etc.)
- **Documentation** — describes the alias (briefs, runbooks, READMEs)
- **Config** — defines the alias (litellm config itself)
- **Test fixtures** — mock the alias

Surface table inline:

```
| Path | Line | Alias | Category | Action under this PR |
|---|---|---|---|---|
| ... | ... | legal-reasoning | caller | no change (same alias name) |
| ... | ... | legal-brain | caller | RENAME → legal-reasoning |
```

If any caller uses an alias that doesn't exist in the new map (e.g., `legal-brain` from BRAIN-49B era), it needs a code change in the same PR or a transitional alias entry pointing the old name at the new endpoint.

**Decision:** Add transitional aliases (`legal-brain` → same as `legal-reasoning`) in the LiteLLM config for backward compat. File follow-up issue (§9) for caller cleanup. Don't break consumers in this PR.

### 5.4 LiteLLM config mutation

Apply the new model_list block. Preserve everything else (master key, callbacks, telemetry config, rate limits).

Atomic write pattern:

```bash
ssh admin@192.168.0.100 '
  CONFIG=<path from §5.1>
  cp "$CONFIG" "${CONFIG}.bak.phase-9-2026-04-30"
  # Edit: replace model_list section with new aliases + transitional entries
  # Preserve: litellm_settings, general_settings, router_settings, callbacks
  # Validate YAML before move
  python3 -c "import yaml; yaml.safe_load(open(\"${CONFIG}.new\"))" \
    || { echo "YAML INVALID — aborting"; exit 1; }
  mv "${CONFIG}.new" "$CONFIG"
'
```

### 5.5 Reload + smoke test

```bash
ssh admin@192.168.0.100 '
  sudo systemctl reload litellm-gateway.service \
    || sudo systemctl restart litellm-gateway.service
  sleep 5
  systemctl is-active litellm-gateway.service
'
```

Smoke each alias with a small probe:

```bash
ssh admin@192.168.0.100 '
  for ALIAS in legal-reasoning legal-drafting legal-summarization; do
    echo "=== $ALIAS ==="
    curl -fsS http://localhost:4000/v1/chat/completions \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\": \"$ALIAS\", \"messages\": [{\"role\":\"user\",\"content\":\"Reply with only PONG.\"}], \"max_tokens\": 20}" \
      | jq ".choices[0].message.content"
    echo
  done
'
```

Expected: each returns "PONG" (or content containing PONG). Latency varies by reasoning_effort but all should return < 30s for a trivial prompt.

If any alias fails: capture the error inline, do NOT roll back yet (the endpoint itself is unaffected). Diagnose alias config; fix; retest. Rollback is restoring the `.bak` config and reload.

### 5.6 Council deliberation smoke

After per-alias probes pass, run a stored Council deliberation prompt to validate seat routing.

```bash
ssh admin@192.168.0.100 '
  curl -fsS http://localhost:8000/api/internal/legal/cases/fish-trap-suv2026000013/deliberate \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"Smoke probe — which counts have the strongest grounded defenses?\", \"max_seats\": 3}" \
    --max-time 600 \
    > /tmp/council-smoke-$(date +%Y%m%dT%H%M%SZ).json
  jq ".result.consensus_summary | length, .result.contains_privileged" /tmp/council-smoke-*.json | tail -5
'
```

Expected: non-zero `consensus_summary` length, `contains_privileged` present (true or false). FYEO warning text appended if true.

If Council errors (model not found, wrong shape, etc.): the seat routing code is hardcoded against old aliases. File the rename as a follow-up code PR; transitional aliases prevent immediate breakage but caller cleanup follows.

---

## 6. ADR-005 amendment

> **[Status: §0.6 — ADR-005 not found in `_architectural-decisions.md`. The TITAN-on-spark-5 decision this section meant to amend was never filed under that number. Reconcile to **ADR-007** (PR #321 OPEN — "Nemotron-3-Super-120B TP=2 spark-3+4 as Fortress Legal synthesizer"), which is the actual architectural ratification. Wave 2 ratification PR per §0.7 step 4 either amends ADR-007 in place or stacks acceptance behind PR #321 merge.]**

**File:** `docs/architecture/cross-division/_architectural-decisions.md` (or wherever ADR-005 actually lives per §4 enumeration)

**Action:** Edit ADR-005 in place. Single source of truth on TITAN; no superseding ADR.

### 6.1 Mutations

**Decision section** — replace:

> ~~TITAN = Nemotron-3-Super-120B-A12B (NVFP4) deployed single-node on spark-5.~~

with:

> **TITAN = Nemotron-3-Super-120B-A12B (NVFP4) deployed across spark-3 + spark-4 with TP=2 (Ray distributed executor). Endpoint: `http://10.10.10.3:8000/v1`. The TP=2 endpoint IS the frontier model. Three LiteLLM aliases (`legal-reasoning`, `legal-drafting`, `legal-summarization`) route to this endpoint with differentiated invocation profiles.**

**Rationale section** — amend item 1:

> ~~1. Fits one Spark with comfortable headroom. NVFP4 native. ~60GB weights, ~60GB headroom on 128GB GB10. No multi-node tensor-parallel overhead.~~

> 1. **Single-Spark fit was the wrong model.** Real-workload memory footprint (KV cache + MTP shared-weight head + concurrent requests + Mamba SSM cache + 1M context buffers) exceeds the theoretical NVFP4 weight headroom. TP=2 across spark-3+spark-4 with ConnectX 100Gbps fabric (97.98 Gbps verified, MTU 9000) provides the working memory envelope. NCCL_IB_HCA dual-rocep configuration confirmed in PR #321 evidence.

**Add new item 8:**

> 8. **Aliases differentiate calls, not models.** Reasoning depth, max_tokens, temperature, and reasoning budget vary per alias. Same underlying weights serve Section 6 (mechanical) and Section 9 (strategic) without model swapping or model duplication. Endpoint concurrency handled by `max-num-seqs 10` + LiteLLM queueing.

**Consequences section** — amend:

> ~~LiteLLM alias `legal-reasoning` reroutes to TITAN at Wave 2 cutover.~~

> **All three LiteLLM aliases (`legal-reasoning`, `legal-drafting`, `legal-summarization`) point at the spark-3+spark-4 TP=2 endpoint with differentiated invocation profiles per Phase 9 brief §5.2. Transitional aliases (e.g., `legal-brain`) preserve consumer compatibility during caller migration.**

Add:

> **spark-5 role under reorientation:** Retrieval co-tenant (Wave 3 target — reranker NIM + NeMo Retriever Extraction NIM). Migrates to HA replica role (TP=2 with spark-6) when ConnectX cables land. Not a separate TITAN deployment.

> **BRAIN-49B retires.** See Phase 9 brief §7.

### 6.2 Update review trigger

Add bullet:

> - spark-5 + spark-6 cables land and HA replica configuration becomes viable

---

## 7. BRAIN-49B retirement

> **[Status: §0.6 — completed. `fortress-nim-brain.service` on spark-5 stopped at 2026-04-30 13:16:39 EDT (clean systemctl stop, exit 0, 28.7M unit RAM peak). Image (`nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8`) preserved on spark-5; systemd unit still `enabled` (not yet `disabled`). Runbook commit per §7.3 below moves to the Wave 2 ratification PR per §0.7 step 4.]**

### 7.1 Locate current BRAIN service

```bash
# spark-5 was the originally documented BRAIN host per MASTER-PLAN v1.7 §5.1
ssh admin@<spark-5-ip-or-tailscale>  '
  systemctl status brain-49b.service 2>/dev/null || \
  systemctl status nemotron-super-49b.service 2>/dev/null || \
  systemctl list-units --type=service --no-pager | grep -i -E "brain|nemotron|llama"
  docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>/dev/null | grep -i -E "brain|nemotron|49b"
  ls /etc/systemd/system/ | grep -i brain
'
```

If spark-5 IP/tailscale unknown at execution time: surface what is found and STOP for operator clarification.

### 7.2 Stop service, preserve image

```bash
ssh admin@<spark-5> '
  # Capture current state
  sudo systemctl status brain-49b.service > /tmp/brain-49b-status-before-stop.txt 2>&1 || true
  docker ps -a --filter "name=brain" --format "{{.Names}} {{.Image}} {{.Status}}" > /tmp/brain-49b-docker-state.txt 2>&1 || true

  # Stop (do not disable yet — disable is operator action after soak)
  sudo systemctl stop brain-49b.service 2>/dev/null || true
  docker stop $(docker ps -q --filter "name=brain") 2>/dev/null || true

  # Verify stopped
  sudo systemctl is-active brain-49b.service
  docker ps --filter "name=brain" --format "{{.Names}}"

  # Image preserved intentionally — DO NOT docker rmi
  docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | grep -i -E "nemotron.*49b|brain"

  # Preserve systemd unit file in case of restart
  sudo cp /etc/systemd/system/brain-49b.service /etc/systemd/system/brain-49b.service.retired-2026-04-30 2>/dev/null || true
'
```

### 7.3 Document restart procedure

Append to a new runbook at `docs/operational/runbooks/brain-49b-retirement.md`:

```markdown
# BRAIN-49B Retirement Runbook

**Date retired:** 2026-04-30 (Phase 9 PR — Wave 2 alias surgery)
**Reason:** Replaced by Nemotron-3-Super-120B-A12B-NVFP4 (TP=2 spark-3+4) per ADR-005 (amended).
**State:** Service stopped. Image preserved. systemd unit preserved with `.retired-2026-04-30` suffix.

## Restart procedure (rollback)

If TITAN endpoint becomes unavailable for extended period and BRAIN-49B
needs to come back:

1. SSH to spark-5: ssh admin@<spark-5>
2. Restore unit file:
   sudo cp /etc/systemd/system/brain-49b.service.retired-2026-04-30 \
           /etc/systemd/system/brain-49b.service
3. Reload + start:
   sudo systemctl daemon-reload
   sudo systemctl start brain-49b.service
4. Verify health:
   curl -fsS http://<spark-5-ip>:<brain-port>/v1/health/ready
5. Update LiteLLM config to point legal-reasoning alias at BRAIN endpoint
   temporarily (preserve .bak first)
6. Reload LiteLLM
7. File incident issue documenting the restart

## Permanent removal

After 14-day soak (2026-05-14) plus operator confirmation:
- docker rmi <image>
- Delete .retired-2026-04-30 unit file
- Delete this runbook
- Update ADR-005 consequences to reflect permanent removal
```

### 7.4 Update LiteLLM transitional aliases

If any caller still uses `legal-brain` or similar BRAIN-49B-era aliases, the transitional aliases added in §5.3 keep them working by routing to the new endpoint. No code change required this PR.

---

## 8. 14-day soak instrumentation

Soak clock continues from Phase 7 smoke per operator directive. Phase 9 adds instrumentation; doesn't reset clock.

### 8.1 Metrics

Capture daily at 00:00 UTC for 14 days starting 2026-04-30:

| Metric | Source | Threshold |
|---|---|---|
| Endpoint availability | `curl /v1/health/ready` | < 99% over 24h triggers halt |
| TP=2 fabric throughput | `nccl-tests` periodic | drop > 20% from 97.98 Gbps baseline triggers diagnostic |
| Per-alias request count | LiteLLM telemetry | informational |
| Per-alias mean latency | LiteLLM telemetry | drift > 50% from Phase 7 baseline triggers diagnostic |
| Per-alias error rate | LiteLLM telemetry | > 1% over 24h triggers diagnostic |
| spark-3 + spark-4 GPU memory | `nvidia-smi` | OOM kill triggers immediate halt |
| spark-3 + spark-4 GPU temp | `nvidia-smi` | > 85C sustained triggers diagnostic |
| KV cache utilization | vLLM logs | sustained > 90% triggers diagnostic |
| Format compliance | sampled output spot-checks | first-person bleed or `<think>` leakage in content triggers halt |

### 8.2 Cadence

```bash
# /etc/cron.d/phase-9-soak (deploy in this PR)
# Runs hourly on spark-2; aggregates daily
0 * * * * admin /home/admin/Fortress-Prime/backend/scripts/phase_9_soak_collect.py >> /mnt/fortress_nas/audits/phase-9-soak/$(date +\%Y-\%m-\%d).log 2>&1
```

Collector script at `backend/scripts/phase_9_soak_collect.py`:
- Hits health endpoint
- Pulls LiteLLM telemetry from gateway DB (or logs)
- Polls `nvidia-smi` on spark-3 + spark-4 over SSH
- Writes structured JSONL line per metric per hour
- Daily rollup script (separate cron at 00:05 UTC) aggregates to daily summary

Daily summary lands in operator command-bridge as a Phase 9 soak report.

### 8.3 Halt triggers

Any of the following triggers immediate halt + operator notification:

- Endpoint availability < 99% over rolling 24h
- OOM kill on either spark-3 or spark-4
- Format-compliance regression (Nano-9B failure modes recur)
- Sustained NCCL fabric error rate (any non-zero on either fabric)

Halt action: stop sending traffic at LiteLLM (mark aliases unhealthy), preserve all logs, file P0 incident issue, no auto-rollback.

### 8.4 14-day pass criteria

If by 2026-05-14 all metrics within thresholds and zero halt triggers fired:
- ADR-007 (PR #321) locks
- BRAIN-49B permanent removal authorized (operator-gated)
- ADR-005 amendment status moves PROPOSED → LOCKED
- Phase 9 brief archived to `docs/operational/post-mortems/`

---

## 9. Wave 3 prep checklist (NO EXECUTION)

Stage Wave 3 retrieval pipeline work without pulling weights or starting services. Wave 3 brief follows separately after soak passes.

### 9.1 Reranker NIM staging

```bash
# Identify the NIM in NGC catalog
ssh admin@192.168.0.100 '
  ngc registry resource info nvidia/llama-nemotron-rerank-1b-v2 2>&1 | head -40
  # Or whichever exact path the NeMo Retriever rerank NIM lives at
'
```

Surface:
- Exact NGC repo path
- Available profile classes (cc_12_0 / fp16 / etc.)
- ARM64 manifest verification status (per PR #128 tooling — Phase 1 verification REQUIRED before pull, per Nemotron-Nano-9B incident principle)
- Approximate weights size

DO NOT pull weights. Surface findings, file Wave 3 brief input.

### 9.2 NeMo Retriever Extraction NIM staging

Same pattern. Identify the Extraction NIM(s) — `nv-ingest`, page-elements, table-structure, graphic-elements per MASTER-PLAN v1.7 §6.2.

Surface inventory. DO NOT pull.

### 9.3 spark-5 readiness for retrieval co-tenancy

```bash
ssh admin@<spark-5> '
  # Free GPU and disk after BRAIN-49B stop
  nvidia-smi
  df -h /
  docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
  systemctl list-units --type=service --no-pager --state=active | head -30
'
```

Surface:
- Free GPU memory (should be near full after BRAIN stop)
- Free disk
- Active services
- Existing cached NIM images (per MASTER-PLAN, distill-70b candidate cached on spark-3, possibly other models cached cluster-wide)

### 9.4 Section-type-specific quality criteria — follow-up issue

File issue post-PR-merge:

```
Title: Section-type-specific quality criteria for Phase B smoke
Priority: P3
Body:
Phase 7 smoke citation count floor (≥18) was calibrated against
Nano-9B's promiscuous-cite behavior. Super-120B's precision filter
(6 sources considered → 3 cited in Section 5) makes raw citation
count a misleading metric for argumentative sections.

Action: Define section-type-specific criteria.
- Sections 2/6 (enumerative): retain citation count floor; tune
  per section
- Sections 4/5/9 (argumentative): theory coverage + flagging
  discipline (e.g., "≥4 distinct theories with explicit
  thin/contradicted flagging where applicable")
- Section 7 (mechanical): own metric (correct entity attribution,
  date accuracy)
- Section 8 (financial): own metric (figure provenance, calculation
  reproducibility)

Tool: NeMo Evaluator (Wave 5 of stack-architecture brief) is the
right harness to formalize these.

Blocks: nothing P0. Defer to post-Wave-4 Phase B dry-run.
```

### 9.5 Citation-density measurement plan — Track A

Run full 5-section synthesis on Case I (closed, no risk) using the new alias map. Compare per-section citation density to PR #311 baseline (Nano-9B-era full synthesis).

DO NOT execute under Phase 9. Capture as a separate brief input. Track A runs after soak begins, before Wave 3 weights pull. Provides empirical citation-density curve under Super-120B for tuning Wave 4 prompts.

---

## 10. PR scope

**Files added/modified:**

- `docs/operational/phase-9-wave-2-alias-surgery-2026-04-30.md` — this brief, full content
- `docs/architecture/cross-division/_architectural-decisions.md` — ADR-005 amendments per §6
- `docs/operational/runbooks/brain-49b-retirement.md` — new runbook per §7.3
- LiteLLM gateway config file — alias map mutation per §5.4 (path determined in §5.1)
- `backend/scripts/phase_9_soak_collect.py` — new collector per §8.2
- `/etc/cron.d/phase-9-soak` — new cron entry per §8.2
- PR #321 supplemental: append operator B/C decision per §3.1

**State changes:**
- BRAIN-49B service stopped on spark-5 (image + unit preserved)
- LiteLLM gateway reloaded with new alias map
- Soak collector active

**No state changes:**
- spark-3 + spark-4 frontier endpoint (untouched)
- EMBED, Vision NIMs (untouched)
- Captain, FLOS, Sentinel (untouched — they consume aliases, transitional aliases keep them working)
- Council orchestration code (untouched — it consumes aliases)
- Spark-5 NIM weights (no Wave 3 pulls)

---

## 11. Constraints

- Branches from `origin/main` only. `git fetch origin && git status && git log origin/main..HEAD` at session start.
- Single Claude Code session at a time on the cluster.
- Never `--admin`, never self-merge, never force-push main.
- ADR pre-flight enumeration (§4) is a hard gate. STOP after enumeration. Operator confirms before file writes.
- LiteLLM config location surfacing (§5.1) is a hard gate. STOP after surfacing. Operator confirms before mutation.
- BRAIN-49B service location surfacing (§7.1) is a hard gate. STOP if location unclear.
- Per-alias smoke (§5.5) is a hard gate. If any alias fails, diagnose; don't proceed to Council smoke until aliases pass.
- Council deliberation smoke (§5.6) is informational, not gating. If it errors, file follow-up; don't roll back.
- Soak clock continues from Phase 7. This PR adds instrumentation; doesn't reset clock.
- DO NOT pull any Wave 3 NIM weights in this PR.
- DO NOT modify the spark-3+4 frontier endpoint.
- DO NOT run the full 5-section Track A measurement under this PR.

---

## 12. Report format

After Phase 9 lands, surface to operator:

**Wave 1 close:**
- Phase 7 smoke status (Section 2 + Section 5 with operator decision applied)
- EMBED health status (200 / vector dimension count / any restart needed)

**ADR pre-flight enumeration:**
- ADR-001 through ADR-007 actual filed status (number, status, file path)
- Any conflicts flagged

**Wave 2 alias surgery:**
- LiteLLM config path
- Pre-mutation alias map (snapshot)
- Post-mutation alias map (3 new + transitional entries)
- Per-alias smoke results (3 PONGs)
- Council deliberation smoke result (consensus_summary length, contains_privileged value)
- Caller surface table (every alias reference with category + action)

**ADR-005 amendment:**
- Diff of `_architectural-decisions.md`
- Old Decision text replaced
- New Rationale items added
- Consequences updated

**BRAIN-49B retirement:**
- Service location confirmed (spark-5 host, IP, service name)
- Stop confirmation
- Image preservation confirmation (`docker images` output showing image still present)
- Unit file preservation confirmation
- Runbook landed at `docs/operational/runbooks/brain-49b-retirement.md`

**Soak instrumentation:**
- Collector script landed
- Cron deployed
- First collection run executed (sample JSONL line)
- Halt triggers documented

**Wave 3 prep:**
- Reranker NIM NGC path + ARM64 verification status
- Extraction NIM(s) NGC paths + ARM64 verification status
- spark-5 readiness state (free GPU mem, free disk, active services)

**PR:**
- Branch name
- PR number
- PR URL
- Any merge conflicts

End of brief.
