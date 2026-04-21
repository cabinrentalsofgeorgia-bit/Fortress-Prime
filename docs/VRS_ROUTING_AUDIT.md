# VRS Routing Audit — 2026-04-21

**Auditor:** Claude Code (autonomous audit, no code changes)
**Branch:** audit/vrs-routing-2026-04-21
**Scope:** Verify CROG-VRS traffic routes to spark-4 per Iron Dome v5 design intent

---

## Summary

**FINDING: VRS traffic is NOT routing to spark-4.**

Two distinct problems:

1. **Atlas misconfiguration** — `fortress_atlas.yaml` tier_routing puts `fast` on `["spark-2", "spark-1"]`. spark-4 is absent from the fast tier routing list. VRS concierge traffic (`task_type='vrs_concierge'`) resolves to `qwen2.5:7b` / `fast` tier, so spark-4 is never a candidate regardless of load or latency.

2. **Spark-2 circuit breaker is open** — The live inference fired during this audit returned `source='fallback'` with `breaker_state='open'`, meaning the primary endpoint (spark-2, 192.168.0.100) has accumulated enough failures to trip the circuit breaker. VRS traffic is currently falling through to the cloud fallback (Anthropic / external API), not staying sovereign.

---

## Audit Trail

### 1. Model chosen for `vrs_concierge`

`ai_router._preferred_ollama_model(task_type='vrs_concierge')`:
- `vrs_concierge` ∉ `_DEEP_TASK_TYPES = {"legal", "reasoning", "analysis"}`
- Returns `settings.ollama_fast_model` = **`qwen2.5:7b`**

`ai_router._tier_for_task(task_type='vrs_concierge')`:
- Returns **`"fast"`**

No special-case routing for `vrs_concierge` anywhere in ai_router.py.

### 2. Atlas tier routing for `fast`

From `fortress_atlas.yaml`:
```yaml
tier_routing:
  fast: ["spark-2", "spark-1"]   # spark-4 NOT listed
```

Registry ranking for a `fast`/`qwen2.5:7b` request:
| Node | Priority | Latency (live) | Has qwen2.5:7b | Selected? |
|---|---|---|---|---|
| spark-2 | 0 (primary) | 131ms | ✅ | **YES** |
| spark-1 | 1 (overflow) | 29ms | ✅ | only if spark-2 unhealthy |
| spark-4 | 999 (not in list) | 28ms | ✅ (live, not in atlas) | **NEVER** |

Registry resolution output: `http://192.168.0.100:11434` (spark-2)

### 3. Live inference result

```
source:        fallback
breaker_state: open
latency_ms:    47230
```

The circuit breaker on the Ollama path (spark-2) is open. VRS traffic is currently escaping to the cloud fallback. Sovereign routing is broken end-to-end.

### 4. Live node model inventory (as of audit)

| Node | IP | `qwen2.5:7b` | In atlas? | In fast tier routing? |
|---|---|---|---|---|
| spark-2 | 192.168.0.100 | ✅ | ✅ | ✅ primary |
| spark-1 | 192.168.0.104 | ✅ | ✅ | ✅ overflow |
| spark-3 | 192.168.0.105 | ❌ | ❌ | ❌ |
| spark-4 | 192.168.0.106 | ✅ **live but missing from atlas** | ❌ | ❌ |

spark-4 has `qwen2.5:7b` loaded live (confirmed via `/api/tags`) but is NOT listed in the atlas node model config for that model. The probe thread would pick this up after 30s and add it to candidates — but it still wouldn't be selected because it's not in the `fast` tier_routing list.

### 5. READ_FROM_VRS_STORE flag

```
READ_FROM_VRS_STORE=true   (fortress-guest-platform/.env)
```

VRS Qdrant read path is active.

---

## Root Cause Analysis

Two independent failures:

### A. Atlas not updated for Iron Dome v5 fast-tier assignment

The atlas designates spark-4 as `role: "deep_reasoning_redundancy"` and excludes it from `fast` tier routing. If Iron Dome v5 intended VRS (fast tier) to run on spark-4, the atlas `tier_routing.fast` must be updated to include `"spark-4"` and the atlas must list `qwen2.5:7b` under spark-4's models.

Minimum atlas change required:
```yaml
# In cluster.nodes, spark-4 models — add:
- name: "qwen2.5:7b"
  tier: "fast"

# In tier_routing — update:
fast: ["spark-4", "spark-2", "spark-1"]  # if spark-4 is primary
# OR
fast: ["spark-2", "spark-4", "spark-1"]  # if spark-4 is secondary
```

### B. Spark-2 circuit breaker open

The `breaker_state='open'` on spark-2 means 3+ consecutive Ollama failures have been recorded. Possible causes: Ollama process crashed, GPU memory pressure from training (`legal_train` tmux session is active), or port 11434 unreachable. Even if the atlas is fixed, spark-2's circuit breaker will need to reset (auto-resets after the back-off window expires, or manually by restarting the probe cycle / checking Ollama on spark-2).

---

## Verdict

**Incorrectly routing — two compounding failures:**
- Fast-tier routing excludes spark-4 (atlas gap, not updated for Iron Dome v5)
- Spark-2's circuit breaker is open (VRS currently hitting cloud fallback, not sovereign)

---

## Recommended Actions (Gary to decide whether to patch tonight)

1. **Immediate:** Check Ollama health on spark-2 (`curl http://192.168.0.100:11434/api/tags`). If down, restart Ollama. Training on spark-2 GPU may be competing for memory.

2. **Atlas update:** Add `qwen2.5:7b` to spark-4's atlas model list. Decide the fast-tier priority order (spark-4 first vs overflow) and update `tier_routing.fast` accordingly. Restart FastAPI backend to reload atlas (or wait 30s for probe cycle — the probe thread refreshes model lists live, but tier_routing comes only from the atlas file loaded at startup).

3. **Verify after fix:** Re-run `backend.services.model_registry.registry.get_endpoint_for_model('qwen2.5:7b', tier='fast')` — should return spark-4's URL if that's the intent.

---

*No code changes made. Findings only.*
