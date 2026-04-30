# Phase 9 — Wave 1 close + Wave 2 alias surgery + BRAIN-49B retirement (evidence)

**Date:** 2026-04-30 13:11–13:21 EDT
**Branch:** `feat/phase-9-wave-2-alias-surgery-2026-04-30`
**Driver:** Phase 9 brief at `docs/operational/phase-9-wave-2-alias-surgery-brief.md`. ADR-007 (PR #321) PROPOSED + Phase 7 smoke validated (Section 2 ✅, Section 5 mixed → operator decision B/C accepted). This PR wires the LiteLLM consumers at the spark-3+spark-4 TP=2 endpoint, retires BRAIN-49B on spark-5, and stands up 14-day soak instrumentation.
**Operator scope decision:** Option (e) — defer §6 ADR-005 amendment from this PR pending the TITAN-vs-postgres ADR-005 numbering reconciliation. ADR pre-flight gate cleared in §4 enumeration; all other gates honored.

---

## 1. Wave 1 close (§3 of brief)

### 1.1 Phase 7 smoke status (PR #321 supplemental)

| Section | Output tokens | Citations | First-person in content | `<think>` in content | Verdict |
|---|---|---|---|---|---|
| §2 Critical Timeline | 5,560 ✅ | 18 (7 unique) ✅ | 0 ✅ | 0 ✅ | **PASS** all 4 criteria |
| §5 Key Defenses | 2,771 (below 3000 floor) | 7 (3 unique; 6 considered in reasoning) | 0 ✅ | 0 ✅ | Format compliance ✅; volume below floor |

**Operator B/C decision (recorded in PR #321 supplemental):** Section 5 precision-filter behavior (6 sources considered → 3 cited) is correct quality, not under-citation. The Nano-9B citation count floor (≥18) was calibrated against promiscuous-cite behavior; under a precision-filter model, the floor is the wrong metric for argumentative sections. Section-type-specific criteria → §9.4 follow-up issue. Format compliance held both sections — Nano-9B failure modes (first-person bleed, `<think>` leakage in content) **NOT recurring**. ADR-007 structural decision validated.

### 1.2 EMBED NIM status

| Probe | Result |
|---|---|
| `curl http://192.168.0.105:8102/v1/health/ready` | Connection refused |
| `systemctl is-active fortress-nim-embed` | **inactive** |
| `systemctl is-enabled` | enabled |

EMBED is **stopped** from Phase 5 Q2 prereq (when spark-3 NIMs were stopped to clear GPU for the TP=2 launch). Per brief §3.2: "Wave 2 alias surgery proceeds independently of EMBED (frontier endpoint does not depend on EMBED), but Wave 3 retrieval pipeline does." Wave 2 unaffected. Wave 3 will require operator authorization to restart EMBED on spark-3 (or relocate per ADR-007 follow-up F4).

---

## 2. ADR pre-flight enumeration (§4)

Filed registry on `main` at PR cut-time:

| # | Title | Status | Path |
|---|---|---|---|
| ADR-001 | One spark per division | LOCKED, partially superseded | registry only |
| ADR-002 | Captain/Council/Sentinel placement | LOCKED, amended | registry only |
| ADR-003 (2026-04-26) | Inference plane: shared swarm | SUPERSEDED-BY ADR-003 (2026-04-29) | registry only |
| ADR-003 (2026-04-29) | Dedicated inference cluster on Sparks 4/5/6 | LOCKED | `ADR-003-inference-cluster-topology.md` |
| ADR-004 (2026-04-29) | App vs Inference Boundary | LOCKED + Amendment v2 | `ADR-004-app-vs-inference-boundary.md` |
| **ADR-005** | **MISSING** | — | — |
| ADR-006 (2026-04-30) | Phase 2 Partner Reassignment | LOCKED | `ADR-006-phase-2-partner-reassignment.md` |
| ADR-007 | TP=2 deployment evidence | PROPOSED in PR #321 (not on main) | branch only |

**Conflict:** Phase 9 brief §6 expected ADR-005 to exist as TITAN service path (PROPOSED via stack-architecture brief). Reality: that stack-architecture brief PR did not land; ADR-005 was never filed. Separately, MASTER-PLAN.md references ADR-005 as "per-service postgres role pattern" (lines 73, 214, 254) — different semantic occupation.

**Operator decision:** Option (e) — defer §6 ADR-005 amendment from this PR. File follow-up issue "ADR-005 numbering reconciliation — TITAN vs postgres-role" (P3) post-merge.

---

## 3. Wave 2 alias surgery (§5)

### 3.1 Service location (§5.1)

| Field | Value |
|---|---|
| Service unit | `litellm-gateway.service` |
| PID (pre-mutation) | 3467426 |
| Bind | `127.0.0.1:8002` |
| Config | `/home/admin/Fortress-Prime/litellm_config.yaml` (gitignored; 106 lines pre-mutation) |
| Drop-in | `/etc/systemd/system/litellm-gateway.service.d/secrets.conf` |
| Config backup | `/home/admin/Fortress-Prime/litellm_config.yaml.bak.phase-9-20260430_131140` (5,153 B = full pre-mutation file) |

### 3.2 Caller surface (§5.3)

100% covered by 5 new aliases + `legal-embed` unchanged. **No code changes needed.**

| Caller file | Aliases used | Covered |
|---|---|---|
| `fortress-guest-platform/backend/services/legal_council.py` | `legal-reasoning` × 7 seats, `legal-summarization` × 1 (Gemini) | ✅ |
| `fortress-guest-platform/backend/services/knowledge_retriever.py` | `legal-embed` | ✅ unchanged |
| `fortress-guest-platform/backend/core/vector_db.py` | `legal-embed` | ✅ |
| `fortress-guest-platform/backend/api/intelligence.py` | `legal-embed` | ✅ |
| `fortress-guest-platform/backend/services/legal_auditor.py` | `legal-embed` (comment) | ✅ |
| `src/reindex_legal_qdrant_to_legal_embed.py` | `legal-embed` | ✅ |
| `src/validate_reindex_quality.py` | `legal-embed` | ✅ |
| `fortress-guest-platform/backend/tests/test_legal_council_sovereign_aliases.py` | `legal-reasoning`, `legal-classification`, `legal-summarization`, `legal-brain` | ✅ all present (3 new + 2 transitional) |

### 3.3 Mutation (§5.4)

Replaced the `# SOVEREIGN LEGAL ROUTES` block (4 entries pointing at spark-5 BRAIN-49B `:8100`) with **5 entries** pointing at the TP=2 frontier `http://10.10.10.3:8000/v1`. Preserved `general_settings`, all CLOUD ROUTES, the `input_type=query` operational comment block, the disabled-fallback section, and the `legal-embed` block verbatim.

| Alias | Profile (max_tokens / temp / reasoning_effort / thinking) |
|---|---|
| `legal-reasoning` | 6000 / 0.3 / high / true |
| `legal-drafting` | 4000 / 0.5 / medium / true |
| `legal-summarization` | 2000 / 0.4 / low / false |
| `legal-brain` (transitional) | same as `legal-reasoning` |
| `legal-classification` (transitional) | same as `legal-summarization` |

YAML validated via `yaml.safe_load`. 13 model_list entries (5 legal + legal-embed + 7 cloud).

### 3.4 Reload + per-alias smoke (§5.5)

`sudo systemctl restart litellm-gateway.service` (the unit doesn't support reload; restart is operationally equivalent for our config-only change). Service `active` at PID 1372307. All 5 alias smokes PASS:

```
=== legal-reasoning ===       wall=2s  finish_reason=stop  has_PONG=True  completion_toks=23
=== legal-drafting ===        wall=2s  finish_reason=stop  has_PONG=True  completion_toks=53
=== legal-summarization ===   wall=1s  finish_reason=stop  has_PONG=True  completion_toks=19
=== legal-brain ===           wall=1s  finish_reason=stop  has_PONG=True  completion_toks=19
=== legal-classification ===  wall=1s  finish_reason=stop  has_PONG=True  completion_toks=23
=== SMOKE TOTAL: PASS=5 FAIL=0 ===
```

Hard gate (any failure → STOP) cleared.

> **Methodology note:** initial smoke with `max_tokens=20` returned empty content — reasoning trace consumed the budget before content emission. Re-ran with `max_tokens=400` and all 5 returned clean PONG. The 20-token brief default is too small for reasoning-enabled aliases; future smokes should use ≥400.

### 3.5 Council deliberation smoke (§5.6, informational)

`POST /api/internal/legal/cases/fish-trap-suv2026000013/deliberate` returned **HTTP 403** immediately. Endpoint exists, auth layer rejected the request — this is an internal API auth issue, not a routing issue (per-alias smoke proves routing works). Per brief §5.6: informational, not gating; file follow-up, do NOT roll back. **Roll-back not invoked.**

Follow-up issue filed post-merge: "Council deliberation 403 post Wave 2 alias surgery" (P3).

---

## 4. ADR-005 amendment (§6)

**DEFERRED** per operator decision (option e). See §2 above. No ADR file changes in this PR.

---

## 5. BRAIN-49B retirement (§7)

### 5.1 Service location confirmed (§7.1)

| Field | Value |
|---|---|
| Host | spark-5 (`192.168.0.109`) |
| Service unit | `fortress-nim-brain.service` |
| Pre-stop state | active running 32+ hours, enabled |
| Container | `fortress-nim-brain` running `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1` (21.3 GB) |
| Pre-stop endpoint | `http://192.168.0.109:8100/v1/health/ready` returned `{"status":"ready"}` |
| Sidecar | `fortress-nim-brain-drift-check.service` + `.timer` |

### 5.2 Stop sequence (§7.2)

```
fortress-nim-brain-drift-check.timer    stopped
fortress-nim-brain-drift-check.service  stopped
fortress-nim-brain-drift-check.timer    disabled
fortress-nim-brain.service              stopped
```

Pre-retirement state captured to `/tmp/brain-49b-pre-retirement-state.txt` on spark-5 (4,898 B). Image preserved (no `docker rmi`).

### 5.3 Post-stop verification

| Check | Result |
|---|---|
| `systemctl is-active fortress-nim-brain.service` | `inactive` ✅ |
| `systemctl is-active fortress-nim-brain-drift-check.service` | `inactive` ✅ |
| `systemctl is-active fortress-nim-brain-drift-check.timer` | `inactive` ✅ |
| `docker ps --filter name=fortress-nim-brain` | empty ✅ |
| `curl http://192.168.0.109:8100/v1/health/ready` | Connection refused ✅ |
| Image preserved | `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1` 21.3 GB ✅ |

### 5.4 Unit file preservation

```
/etc/systemd/system/fortress-nim-brain.service                          (active path, inactive state)
/etc/systemd/system/fortress-nim-brain.service.retired-2026-04-30       (NEW preservation)
/etc/systemd/system/fortress-nim-brain.service.bak-perhost-20260426     (historical, preserved)
/etc/systemd/system/fortress-nim-brain.service.bak-pre-overnight-20260427  (historical, preserved)
/etc/systemd/system/fortress-nim-brain.service.bak-pre-r1-20260427      (historical, preserved)
/etc/systemd/system/fortress-nim-brain-drift-check.service              (active path, inactive state)
/etc/systemd/system/fortress-nim-brain-drift-check.service.retired-2026-04-30  (NEW)
/etc/systemd/system/fortress-nim-brain-drift-check.timer                (active path, inactive state)
/etc/systemd/system/fortress-nim-brain-drift-check.timer.retired-2026-04-30  (NEW)
```

### 5.5 Restart runbook

`docs/operational/runbooks/brain-49b-retirement.md` — restart sequence symmetric to retirement (BRAIN service first, then drift-check service + timer). Includes LiteLLM rollback to pre-Phase-9 config backup. Documents the stale "on spark-1" Description text that should be fixed on restoration.

---

## 6. Soak instrumentation (§8)

### 6.1 Collector script

`fortress-guest-platform/backend/scripts/phase_9_soak_collect.py` (~190 lines). Collects 10 metrics per run:

- 1× endpoint health (`http://10.10.10.3:8000/health` — vLLM path, NOT `/v1/health/ready` which is NIM-style and returned 404 on first attempt)
- 3× alias probe (`legal-reasoning`, `legal-drafting`, `legal-summarization` — PONG smoke via LiteLLM gateway)
- 2× node memory (spark-3 + spark-4 via SSH)
- 2× node GPU temp (spark-3 + spark-4 via SSH)
- 2× sysctl bbr (spark-3 + spark-4 via SSH)

`LITELLM_MASTER_KEY` sourced from env, falling back to read from `/home/admin/Fortress-Prime/litellm_config.yaml` directly (cron-friendly; no separate secrets file).

### 6.2 Cron deployment

`deploy/cron.d/phase-9-soak` (committed) → `/etc/cron.d/phase-9-soak` (deployed, mode 644 root:root). Runs hourly: `0 * * * * admin /usr/bin/python3 /home/admin/Fortress-Prime/fortress-guest-platform/backend/scripts/phase_9_soak_collect.py`.

### 6.3 First collection — sample JSONL (verbatim from `/mnt/fortress_nas/audits/phase-9-soak/2026-04-30.log`)

```jsonl
{"ts": "2026-04-30T17:20:08.170994+00:00", "metric": "endpoint_health", "host": "spark-3", "alias": null, "value": "ready", "ok": true, "ms": 18.9}
{"ts": "2026-04-30T17:20:09.216295+00:00", "metric": "alias_probe", "host": "spark-2", "alias": "legal-reasoning", "value": 200, "ok": true, "ms": 1045.2}
{"ts": "2026-04-30T17:20:10.084149+00:00", "metric": "alias_probe", "host": "spark-2", "alias": "legal-drafting", "value": 200, "ok": true, "ms": 867.7}
{"ts": "2026-04-30T17:20:11.767915+00:00", "metric": "alias_probe", "host": "spark-2", "alias": "legal-summarization", "value": 200, "ok": true, "ms": 1683.6}
{"ts": "2026-04-30T17:20:12.074498+00:00", "metric": "node_memory", "host": "spark-3", "alias": null, "value": {"total_gib": 121.69, "used_gib": 96.9, "available_gib": 24.79, "used_pct": 79.63}, "ok": true, "ms": null}
{"ts": "2026-04-30T17:20:12.536823+00:00", "metric": "node_memory", "host": "spark-4", "alias": null, "value": {"total_gib": 121.69, "used_gib": 94.56, "available_gib": 27.13, "used_pct": 77.7}, "ok": true, "ms": null}
{"ts": "2026-04-30T17:20:12.842951+00:00", "metric": "node_gpu_temp", "host": "spark-3", "alias": null, "value": "44", "ok": true, "ms": null}
{"ts": "2026-04-30T17:20:13.155564+00:00", "metric": "node_gpu_temp", "host": "spark-4", "alias": null, "value": "50", "ok": true, "ms": null}
{"ts": "2026-04-30T17:20:13.445067+00:00", "metric": "sysctl_bbr", "host": "spark-3", "alias": null, "value": "bbr", "ok": true, "ms": null}
{"ts": "2026-04-30T17:20:13.773765+00:00", "metric": "sysctl_bbr", "host": "spark-4", "alias": null, "value": "bbr", "ok": true, "ms": null}
```

### 6.4 Halt triggers (per brief §8.3)

Manual / out-of-band triggers (NOT in collector):
- Endpoint availability < 99% over rolling 24h
- OOM kill on spark-3 or spark-4
- Format-compliance regression (sampled output spot-check; separate cadence)
- Sustained NCCL fabric error rate

Halt action: stop sending traffic at LiteLLM (mark aliases unhealthy), preserve all logs, file P0 incident, no auto-rollback.

### 6.5 14-day pass criteria (per brief §8.4)

Soak target: 2026-05-14. If all metrics within thresholds and zero halt triggers fire:
- ADR-007 (PR #321) locks
- BRAIN-49B permanent removal authorized (operator-gated; runbook §"Permanent removal")
- Phase 9 brief archived to `docs/operational/post-mortems/`

---

## 7. Wave 3 prep (§9)

### 7.1 spark-5 readiness post BRAIN retirement

| Resource | State |
|---|---|
| RAM used | **4.5 GiB / 121 GiB (3.7%)** — was ~92% pre-retirement |
| RAM available | 117 GiB |
| Disk used | 104 GiB / 3.7 TiB (3%) |
| GPU compute apps | empty |
| Cached NIM images | `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:2.0.1` (21.3 GB, retired-preserved), `nvcr.io/nim/nvidia/llm-nim:latest` (19.3 GB), `nvcr.io/nim/nvidia/llm-nim:1.15.4` (19.1 GB) |

spark-5 has massive headroom for Wave 3 retrieval co-tenancy. Once cables land (spark-6), retrieval moves and spark-5 + spark-6 become TP=2 HA replica pair.

### 7.2 Reranker NIM staging (no pull)

NGC API probe for `nvidia/llama-nemotron-rerank-1b-v2`:
```
ngc registry resource info nvidia/llama-nemotron-rerank-1b-v2
→ Client Error: 403 Access Denied
```

Public API access denied — Wave 3 brief input. Operator authorizes specific resource path + auth before pull. ARM64 manifest verification per PR #128 tooling REQUIRED before any pull (Nemotron-Nano-9B incident principle).

### 7.3 NeMo Retriever Extraction NIM staging (no pull)

Components per MASTER-PLAN v1.7 §6.2: `nv-ingest`, page-elements, table-structure, graphic-elements. **None cached** anywhere in cluster. Wave 3 brief will pin exact NGC paths + auth approach.

### 7.4 Cluster-wide NIM cache inventory

| Spark | Cached NIM images |
|---|---|
| spark-3 (192.168.0.105) | `llama-nemotron-embed-1b-v2` (4.49 GB) ×2 tags, `nv-embedqa-e5-v5` (4.27 GB), `nemotron-nano-12b-v2-vl` (19.9 GB) ×2 tags, `cosmos-reason2-2b` (19.5 GB), `llama-3.1-8b-instruct` (19.3 GB), `llama-3.3-70b-instruct` (19.3 GB), `deepseek-r1-distill-llama-70b` (15 GB) |
| spark-4 (192.168.0.106) | (none) |
| spark-5 (192.168.0.109) | BRAIN-49B retired-preserved + 2× llm-nim base |

Reranker / extraction NIMs NOT cached anywhere. Wave 3 will need fresh NGC pulls.

### 7.5 §9.4 follow-up issue

Filed post-merge: "Section-type-specific quality criteria for Phase B smoke" (P3). Phase 7 Section 5 surfaced that raw citation count is misleading under a precision-filter model. Section 2/6 (enumerative) retain count floor; Sections 4/5/9 (argumentative) need theory-coverage criterion; Section 7 (mechanical) entity attribution; Section 8 (financial) figure provenance. Tool: NeMo Evaluator (Wave 5).

### 7.6 §9.5 citation-density Track A (no execution)

Capture as Wave 4 brief input. Run full 5-section synthesis on Case I (closed; no risk) using new alias map; compare per-section citation density to PR #311 Nano-9B-era full synthesis. Yields empirical curve for tuning Wave 4 prompts. **Not run under this PR.**

---

## 8. Files in PR

| Path | Status | Purpose |
|---|---|---|
| `fortress-guest-platform/backend/scripts/phase_9_soak_collect.py` | NEW | Soak collector |
| `deploy/cron.d/phase-9-soak` | NEW | Cron entry (also deployed to `/etc/cron.d/` on spark-2) |
| `docs/operational/runbooks/brain-49b-retirement.md` | NEW | Retirement runbook + restart procedure |
| `docs/operational/phase-9-wave-2-alias-surgery-evidence-2026-04-30.md` | NEW | This evidence doc |

**Plus separate amendment to PR #321** (different branch): append operator B/C decision to `phase-7-smoke-section-5-supplemental-2026-04-30.md`.

### State changes (production)

- LiteLLM gateway reloaded with new alias map (`/home/admin/Fortress-Prime/litellm_config.yaml`, gitignored, backed up)
- BRAIN-49B service stopped on spark-5 (image + unit preserved)
- `/etc/cron.d/phase-9-soak` deployed (live on spark-2)
- spark-3 → spark-4 ssh trust deployed (Phase 5 prereq, durable change)

### NOT in this PR (deferred)

- ADR-005 amendment (§6) — operator option (e); separate small PR after numbering reconciliation
- `_architectural-decisions.md` — untouched
- `deploy/litellm_config.yaml` template — drifted vs live; P4 follow-up to sync or formally deprecate template
- spark-5 NIM weights pulls (Wave 3 territory; no execution under Phase 9)
- spark-3 EMBED restart (Wave 3 territory; gating retrieval)

---

## 9. Follow-up issues to file post-merge

| Title | Priority | Reason |
|---|---|---|
| ADR-005 numbering reconciliation — TITAN vs postgres-role | P3 | Phase 9 enumeration found ADR-005 unfiled; MASTER-PLAN.md occupies it semantically for postgres-role pattern; Phase 9 brief expected TITAN. Resolve before any ADR-005 file write |
| Council deliberation 403 post Wave 2 alias surgery | P3 | Per-alias smokes 5/5 PASS; Council endpoint `/api/internal/legal/cases/{slug}/deliberate` returned 403. Auth layer issue, not routing |
| `deploy/litellm_config.yaml` staging template drift | P4 | Live config diverged from template per Phase 9 mutation; sync template or formally deprecate |
| Section-type-specific quality criteria for Phase B smoke | P3 | Citation count floor wrong metric for argumentative sections under precision-filter model; section-specific criteria needed |

---

End of evidence.
