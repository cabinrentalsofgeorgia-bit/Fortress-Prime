# ADR-003 Lock + Phase 1 Execution Brief

**Target:** Claude Code on spark-2
**Branch:** `feat/adr-003-lock-phase-1-litellm-cutover`
**Date:** 2026-04-29
**Decisions captured 2026-04-29 (operator):**
- ADR-003 LOCKED as written
- Phase 3 sizing: Pattern 1 (TP=2 + hot replica)
- Phase 1 includes LiteLLM legal-routes cutover (cloud → spark-5 NIM) — this session

**Stacks on:** PR #277 (BRAIN), PR #278 (Phase A1), PR #280 (Phase A5), PR #281 (Track A) — all merged today.

---

## 1. Mission

Land ADR-003 on main, locked. Close audit finding A-02 (cloud legal inference) by cutting LiteLLM's legal routes to spark-5 NIM. Update topology docs to reflect app/inference split. Single PR, doc-only + LiteLLM config change. No infrastructure migration in this PR — that's Phase 2 (Spark-6 cable cutover).

---

## 2. Scope

**In scope:**
- Commit ADR-003 to `docs/architecture/cross-division/_architectural-decisions.md` with status LOCKED + operator decision date
- Amend ADR-001 entry to note ADR-003 carve-out (one-spark-per-app-division, inference is shared tier)
- Resolve ADR-002 to Option A (Captain/Council/Sentinel stay on spark-2 control plane)
- Update `docs/architecture/shared/infrastructure.md` — DEFCON tier table, allocation table, migration milestones
- Update `docs/architecture/system-map.md` — current state diagram (app/inference split), target state diagram (Phase 3 endpoint)
- Update `docs/architecture/cross-division/006-nemoclaw-ray-deployment.md` — Ray worker list narrows to spark-4/5/6
- LiteLLM config edit — legal routes cloud → `http://spark-5:8100/v1` (Tailscale or LAN, whichever is canonical from Phase A5 BRAIN_BASE_URL)
- Verification probe — single legal call through LiteLLM gateway, confirm it terminates on spark-5 not cloud
- Update IRON_DOME v6.1 doc to mark sovereignty claim accurate post-cutover

**Out of scope (explicitly):**
- Spark-6 provisioning, cable cutover, RDMA setup — Phase 2
- Spark-4 inference cluster join — Phase 3
- Tensor-parallel sizing changes — Phase 2/3
- Acquisitions/Wealth migration off Spark-4 — Phase 3 prerequisite, separate brief
- Council deliberation BRAIN integration — separate Phase B brief (drafting orchestrator)
- Any spark-1 or spark-5 systemd unit changes — already correct
- M3 trilateral mirror activation — separate prereq chain (Issue #279)

---

## 3. File-level changes

| file | role | new/modified |
|---|---|---|
| `docs/architecture/cross-division/_architectural-decisions.md` | append ADR-003 LOCKED, amend ADR-001, resolve ADR-002 | MODIFIED |
| `docs/architecture/shared/infrastructure.md` | DEFCON table, allocation table, migration milestones | MODIFIED |
| `docs/architecture/system-map.md` | current + target state diagrams | MODIFIED |
| `docs/architecture/cross-division/006-nemoclaw-ray-deployment.md` | Ray worker list spark-4/5/6 only | MODIFIED |
| `<litellm-config-path>` | legal routes cloud → spark-5:8100 | MODIFIED |
| `IRON_DOME_ARCHITECTURE.md` (or v6.1 file) | sovereignty claim accurate post-cutover | MODIFIED |
| `docs/operational/litellm-legal-cutover-2026-04-29.md` | cutover record + verification probe output | NEW |

No code changes. No migrations. No new schemas.

---

## 4. ADR-003 commit content

Append to `_architectural-decisions.md` exactly the ADR-003 content from operator-uploaded `adr3.md`, with two fields updated:

- **Status:** `**LOCKED** — operator decision 2026-04-29`
- **Phase 3 sizing default:** explicit note that operator selected **Pattern 1 (TP=2 + hot replica)** at lock time

Then amend the existing ADR-001 entry — append a new paragraph:

```
**Amended 2026-04-29 by ADR-003:** ADR-001's "one spark per division" rule applies to *app* divisions. 
Inference is a shared cross-division resource hosted on a dedicated cluster (Sparks 4/5/6) per ADR-003. 
Acquisitions and Wealth co-tenant on Spark-3 with Financial until Spark-7+ lands.
```

Then update the existing ADR-002 entry — change status from OPEN to LOCKED:

```
**Status:** **LOCKED** — operator decision 2026-04-29 (resolved by ADR-003)

**Decision:** Option A. Captain, Council, and Sentinel remain on spark-2 control plane permanently. 
They consume inference from the spark-4/5/6 cluster via LiteLLM but are not tenants of inference Sparks.
```

---

## 5. infrastructure.md updates

### 5.1 Cluster topology table — replace existing with:

| Spark | Network | Status | Role | Tenants |
|---|---|---|---|---|
| **Spark 1** | `192.168.0.X` | ACTIVE | App | Fortress Legal |
| **Spark 2** | `192.168.0.100`, ctrl @ `100.80.122.100` | ACTIVE | App + control plane | CROG-VRS, Captain, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI |
| **Spark 3** | TBD | PLANNED | App | Financial; Acquisitions + Wealth co-tenant pending Spark-7+ |
| **Spark 4** | ConnectX | PLANNED — Phase 3 | Inference | Ray worker (joins inference cluster) |
| **Spark 5** | ConnectX | ACTIVE | Inference | Ray head; Nemotron-Super-49B-FP8 NIM |
| **Spark 6** | 10GbE → ConnectX (cable pending) | STAGED — Phase 2 | Inference | Ray worker |

### 5.2 DEFCON inference tier table — replace existing with:

| Tier | Service | Model | Host | Use |
|---|---|---|---|---|
| DEFCON 5 — SWARM | Ollama LB | qwen2.5:7b | spark-2 | Fast routing, guest comms, light classification, degraded-mode fallback |
| DEFCON 3 — BRAIN | `fortress-nim-brain.service` (port 8100) | Llama-3.3-Nemotron-Super-49B-v1.5-FP8 via NIM 2.0.1 | **spark-5** (Phase 1); spark-5+6 TP=2 (Phase 2); 4/5/6 Pattern 1 (Phase 3) | Tier-2 sovereign reasoning; legal RAG; case briefing |
| DEFCON 1 — TITAN | DeepSeek-R1 671B local llama.cpp RPC | DeepSeek-R1 | TBD inference cluster | Deep reasoning: legal, finance |
| ARCHITECT | Google Gemini (cloud, planning only) | Gemini 2.5+ | external | Strategic planning. Never PII / sovereign data. |

Remove the prior 2026-04-23 note about spark-1 ≥99% memory under BRAIN load (no longer applicable post-ADR-003 Phase 1).

### 5.3 Migration milestones — replace existing with:

1. ADR-003 Phase 1 — LiteLLM legal-routes cutover cloud → spark-5 NIM (this PR)
2. M3 trilateral additive write (PR `feat/m3-trilateral-spark1-mirror`, default-OFF)
3. M3 activation prereq: alembic merge on spark-2 (Issue #279)
4. ADR-003 Phase 2 — Spark-6 cable cutover, TP=2
5. Spark-3 hardware acquired and provisioned (Financial)
6. `hedge_fund.*` migration spark-2 → spark-3
7. ADR-003 Phase 3 — Spark-4 joins inference cluster; Acquisitions/Wealth co-tenant on Spark-3
8. CROG-VRS sheds tenant duties (Spark-2 single-purpose)

---

## 6. system-map.md updates

### 6.1 Current state diagram — redraw with app/inference split

Two side-by-side blocks:

```
APP TIER                              INFERENCE TIER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spark 1 (Fortress Legal)              Spark 5 (BRAIN — Nemotron 49B FP8)
Spark 2 (CROG-VRS + ctrl plane)        Spark 6 (staged, 10GbE)
Spark 3 (Financial — planned)
Spark 4 (planned — Phase 3 inference)
```

LiteLLM gateway on spark-2 routes BRAIN tier → spark-5. Captain/Council/Sentinel on spark-2 consume inference via LiteLLM.

### 6.2 Target state (Phase 3 endpoint) diagram

```
APP TIER                              INFERENCE TIER (Pattern 1)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spark 1 (Fortress Legal)              Spark 4 — TP=2 worker B / hot replica host
Spark 2 (CROG-VRS + ctrl plane)        Spark 5 — TP=2 head, instance 1
Spark 3 (Financial + Acq + Wealth)    Spark 6 — TP=2 worker A
                                      
                                      LiteLLM load-balances 2 instances
                                      One TP=2 instance (49B over 5+6)
                                      One single-Spark instance (49B on 4)
                                      Hot failover if instance fails
```

### 6.3 Migration path narrative

Replace existing Stages 1-5 with:

- **Stage 1 (this PR):** ADR-003 Phase 1 — cloud cutover, infra docs updated
- **Stage 2:** Spark-6 cable lands → ADR-003 Phase 2 (TP=2)
- **Stage 3:** Spark-3 provisions → Financial migration
- **Stage 4:** ADR-003 Phase 3 — Spark-4 joins inference cluster; Acq+Wealth co-tenant on Spark-3
- **Stage 5:** Spark-7+ → Acquisitions or Wealth gets dedicated app spark

---

## 7. 006-nemoclaw-ray-deployment.md updates

Update the live Ray baseline section. Ray workers narrow from "all four nodes" to inference cluster only:

| Service | Host | Phase |
|---|---|---|
| `fortress-ray-head.service` | spark-5 | Phase 1+ |
| `fortress-ray-worker.service` | spark-6 | Phase 2 (cable-gated) |
| `fortress-ray-worker.service` | spark-4 | Phase 3 (Acq/Wealth co-tenancy gated) |

Remove spark-2 and spark-1 from the Ray worker list. They are NOT inference cluster members under ADR-003.

NemoClaw orchestrator boundary remains on spark-2 control plane (`100.80.122.100:8000`) — that's correct, just clarify that orchestrator DOES NOT host Ray workers; it dispatches to the inference cluster.

---

## 8. LiteLLM cutover

### 8.1 Locate config

Search the repo for LiteLLM config (likely `litellm_config.yaml` or `fortress-guest-platform/configs/litellm.yaml` or similar). The 2026-04-22 audit referenced `evidence/litellm-config.txt` showing cloud-only routes for legal.

If config not found at expected path, surface and STOP — do not guess.

### 8.2 Edit pattern

Existing legal routes likely look like:

```yaml
- model_name: legal-reasoning
  litellm_params:
    model: claude-sonnet-4-...
    api_key: os.environ/ANTHROPIC_API_KEY
```

Replace with:

```yaml
- model_name: legal-reasoning
  litellm_params:
    model: openai/nvidia/llama-3.3-nemotron-super-49b-v1.5
    api_base: http://spark-5:8100/v1
    api_key: dummy   # NIM doesn't require auth on internal network
    timeout: 600     # streaming long-context calls
```

Apply same pattern to any other legal-tagged routes (legal-classification, legal-summarization, etc.).

**Do NOT remove cloud routes outright — leave them in the config as commented-out fallback for emergency:**

```yaml
# Cloud fallback (DISABLED 2026-04-29 per ADR-003 Phase 1):
# - model_name: legal-reasoning-cloud-fallback
#   litellm_params:
#     model: claude-sonnet-4-...
#     api_key: os.environ/ANTHROPIC_API_KEY
```

If LiteLLM is configured via DB rows (admin UI / virtual keys) instead of YAML, surface and STOP — that's a separate cutover path needing operator credential review.

### 8.3 Verify spark-5 reachability from spark-2

Before applying the edit, prove spark-5 is reachable on the route name LiteLLM will use:

```bash
# whichever resolves on spark-2
curl -s http://spark-5:8100/v1/health/ready
curl -s http://100.80.122.100:8100/v1/health/ready    # Tailscale fallback
```

Use the resolvable name in `api_base`. Phase A5 used `BRAIN_BASE_URL=http://spark-5:8100` per the brief — match that.

### 8.4 Restart LiteLLM service

```bash
sudo systemctl restart fortress-litellm.service   # or whatever the unit name is
sudo systemctl status fortress-litellm.service
```

If LiteLLM runs in Docker:

```bash
docker compose -f <litellm-compose-file> restart litellm
docker logs <litellm-container> --tail 50
```

Surface restart errors. Roll back the YAML if LiteLLM fails to load.

### 8.5 Verification probe

Single curl against LiteLLM gateway with the legal model name:

```bash
curl -s http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "legal-reasoning",
    "messages": [{"role":"user","content":"Reply with the single word: spark"}],
    "max_tokens": 10,
    "stream": false
  }' | tee /tmp/litellm-cutover-probe.json
```

(Adjust port if LiteLLM binds elsewhere; 8002 from audit memory.)

**PASS criteria:**
- HTTP 200
- Response body contains a coherent answer (one word; expect "spark" or close)
- LiteLLM logs show route resolved to `http://spark-5:8100/v1`, NOT to api.anthropic.com or openai.com

**FAIL criteria:**
- HTTP non-200
- Response empty / token salad
- LiteLLM logs show cloud route still active

On FAIL: roll back the YAML, restart, surface to operator with logs.

### 8.6 Cutover record

Write `docs/operational/litellm-legal-cutover-2026-04-29.md`:

```markdown
# LiteLLM Legal Routes Cutover (Cloud → Spark-5 NIM)

**Date:** 2026-04-29
**Driver:** ADR-003 Phase 1
**Closes:** Audit finding A-02 (2026-04-22 audit) — sovereign legal inference

## Before
- Legal routes targeted cloud (Anthropic, OpenAI, Gemini, Grok)
- IRON_DOME v6.1 sovereignty claim was inaccurate (cloud-routed)

## After
- Legal routes target http://spark-5:8100/v1 (NIM 2.0.1 + Llama-3.3-Nemotron-49B FP8)
- Cloud routes commented as emergency fallback only
- LiteLLM service restarted, health verified

## Verification
- Probe: <paste /tmp/litellm-cutover-probe.json>
- LiteLLM logs: <paste relevant route-resolution lines>

## Rollback
- Uncomment cloud fallback block in litellm_config.yaml
- Restart fortress-litellm.service
- ETA to rollback: <30 seconds
```

---

## 9. IRON_DOME v6.1 update

Locate the IRON_DOME doc (path likely `docs/IRON_DOME_ARCHITECTURE.md` or `iron-dome-v6.1.md`). Update the Fortress Legal section:

- Where it claimed sovereign legal inference and audit found cloud routing — mark "RESOLVED 2026-04-29 by ADR-003 Phase 1 cutover. Legal inference now terminates on spark-5 NIM."
- Update the inference-host references from spark-1 (or whatever they said) to spark-5.

If IRON_DOME doc not found, skip and surface — separate audit issue.

---

## 10. Definition of done

- Branch pushed, PR opened
- ADR-003 LOCKED on main with operator decision date
- ADR-001 amended; ADR-002 LOCKED to Option A
- infrastructure.md / system-map.md / 006-nemoclaw-ray-deployment.md updated
- LiteLLM legal routes resolve to spark-5:8100, verified via probe
- LiteLLM cloud routes preserved commented-out for emergency
- Cutover record committed
- IRON_DOME doc updated (or skip-and-surface)
- PR description includes:
  - Probe output (LiteLLM resolves to spark-5)
  - LiteLLM service status post-restart
  - Diff summary on each updated doc
- PR merge BLOCKED on operator review

---

## 11. Hard constraints

- **DO NOT** modify spark-5 systemd unit
- **DO NOT** restart spark-5 NIM service
- **DO NOT** spin up Ray workers on spark-1 or spark-2 (ADR-003 says inference cluster only)
- **DO NOT** provision spark-6 — Phase 2 work, separate brief
- **DO NOT** modify spark-1 (Phase A1 just merged; leave clean)
- **DO NOT** remove cloud fallback routes from LiteLLM — comment them, don't delete
- **DO NOT** touch BRAIN client code (Phase A5 just merged)
- **DO NOT** open more than one PR
- On any STOP condition (LiteLLM config not found, spark-5 unreachable, restart fails): commit nothing, push nothing, surface

---

## 12. Closing report

When PR is open, paste:

| Item | Result |
|---|---|
| Branch + PR number + URL | |
| ADR-003 committed | yes/no, location |
| ADR-001 amended | yes/no |
| ADR-002 LOCKED Option A | yes/no |
| infrastructure.md updated | yes/no |
| system-map.md updated | yes/no |
| 006-nemoclaw-ray-deployment.md updated | yes/no |
| LiteLLM config edit | path + diff summary |
| Spark-5 reachability check | api_base used, HTTP code |
| LiteLLM service restart | success/fail |
| Verification probe | PASS/FAIL with route-resolution log line |
| Cutover record committed | yes/no |
| IRON_DOME updated | yes/no/skip |
| Time elapsed | |

PR title: `ADR-003 LOCKED + Phase 1: LiteLLM legal cutover (cloud → spark-5 NIM)`

Mark "merge BLOCKED on operator review."

---

End of brief.
