# Iron Dome — Fortress-Prime Sovereign AI Defense System

**Version:** 3.0
**Date:** April 18, 2026
**Author:** Gary Knight (with Claude)
**Supersedes:** v2 (commit 8649e8236)

---

## Why v3

v2 documented Iron Dome as five phases that assumed the cluster's
AI routing worked as intended. A late-night infrastructure audit on
April 18 revealed the sovereign tier was broken: ai_router was calling
`http://192.168.0.100:11434` expecting `deepseek-r1:70b`, but that
model lives on `192.168.0.104` (spark-1) and `192.168.0.106` (spark-4).
Every deep-reasoning sovereign call was 404-ing and silently falling
through to cloud inference.

This changes everything. Phase 4's distillation was targeted at a
model ai_router couldn't route to. Phase 4c was scaffolded against
a serving path that bypassed the default sovereign tier. v3 corrects
the foundation before building further.

---

## What Iron Dome actually defends

Same four threats as v2 — vendor lock-in, privilege leakage, compute
economics, model quality drift. The threats haven't changed. What
changed is our understanding of the assets defending against them.

---

## The cluster as it actually exists

Four nodes, each NVIDIA GB10 with ~120GB unified memory. Tailscale
mesh. k3s cluster with spark-2 as control plane. Synology 1825+
NAS at `192.168.0.112` (`/mnt/fortress_nas`).

### Current node roles (reality, not intent)

| Node | IP | GB10 | Services | Models loaded |
|---|---|---|---|---|
| spark-2 (Captain) | 192.168.0.100 | Yes | fortress-backend, workers, k3s control plane, NIM llama-3.1-8b (~60GB), Ollama | qwen2.5:0.5b, qwen2.5:7b, nomic-embed-text |
| spark-1 (Muscle) | 192.168.0.104 | Yes | Ollama | deepseek-r1:70b, qwen2.5:32b, llama3.2-vision:90b, qwen2.5:7b, llava, mistral |
| spark-3 (Ocular) | 192.168.0.105 | Yes | Ollama | llama3.2-vision:90b, nomic-embed-text |
| spark-4 (Sovereign) | 192.168.0.106 | Yes | Ollama + docker nim-swarm | deepseek-r1:70b, qwen2.5:32b, llava, mistral |

### What's working

- spark-2 NIM serves legal_council and SEO archive via direct URL
- spark-2 Ollama serves ai_router fast-path calls (qwen2.5:7b)
- spark-3 serves vision workloads via direct URL
- All nodes reachable via Tailscale mesh

### What's broken

- ai_router deep-tier calls 404 silently (wrong endpoint)
- spark-2 simultaneously runs control plane + NIM + Ollama, leaving
  no headroom for training without stopping inference
- No health-aware routing: if spark-1 restarts, all deep calls fail
- No load balancing between spark-1 and spark-4 despite both hosting
  deepseek-r1:70b
- Single-node distillation target (Llama-3.3-70B-FP4 on spark-2)
  doesn't match what ai_router serves to production traffic

---

## Target node roles (where we're going)

### spark-2 — Control plane + fast tier + training
Responsibilities:
- fortress-backend and all worker processes
- ai_router decision-making (the brain, not the inference)
- k3s control plane
- Fast-tier inference: qwen2.5:7b for concierge, routine VRS, pricing
  heuristics
- Nightly training runs (when GB10 is free of inference load)

Explicitly NOT on spark-2 going forward:
- NIM llama-3.1-8b — move to spark-1 or spark-4 where it doesn't
  compete with control plane

### spark-1 — Primary heavy reasoning
Responsibilities:
- deepseek-r1:70b (deep tier default)
- qwen2.5:32b (mid tier default)
- llama3.2-vision:90b (vision overflow)
- NIM llama-3.1-8b (migrated from spark-2)
- Primary target for legal_council deliberations, complex analysis,
  acquisitions work

### spark-3 — Vision specialist
Responsibilities:
- llama3.2-vision:90b (primary)
- OCR and image analysis workflows
- No general-purpose traffic — specialized node

### spark-4 — Heavy-reasoning redundancy + audio
Responsibilities:
- deepseek-r1:70b (active-active with spark-1)
- qwen2.5:32b (active-active with spark-1)
- Speech/audio workloads when added
- Automatic failover target if spark-1 offline

This is a real active-active pair for the deep tier, not hot-standby.
Load balances across both.

---

## The three cornerstones

Iron Dome rebuilt around three architectural pieces:

### 1. Model registry (new)

A module (`backend/services/model_registry.py`) that knows:

- Which models are on which nodes (loaded from a config + live probing)
- Each node's health (last successful request, rolling latency,
  consecutive failures)
- Routing policy per tier: affinity rules, failover chains, load
  balancing

Signature:

    def get_endpoint_for_model(model_name: str, tier: str) -> Endpoint:
        """Returns healthiest node endpoint that has model_name.
        Raises NoHealthyEndpoint if none available."""

ai_router calls the registry. Registry returns the right URL. If
spark-1 has been failing recently, registry returns spark-4 instead.
When both deep-tier nodes are down, registry raises, and ai_router
falls through to cloud.

No more hardcoded endpoints anywhere.

### 2. Health-aware routing (new)

Probe each known endpoint every 30 seconds:

- GET /api/tags on Ollama
- GET /v1/models on NIM/vLLM

Track three signals per endpoint:
- Reachable (boolean)
- Rolling latency (last 20 requests)
- Consecutive failures (reset on success)

Endpoint is "healthy" if reachable AND consecutive_failures < 3.
Registry returns only healthy endpoints. If tier has multiple healthy
endpoints, pick by lowest rolling latency (primitive load balancing).

### 3. Observability (new)

Metrics exposed at /api/v1/system-health (already exists, extend):

- Per-endpoint request count
- Per-endpoint latency p50, p95
- Per-tier fallback count (how often did registry have to use backup)
- Per-model request count (separates "what's being asked for" from
  "what's being served")

This is how we notice spark-4 is idle while spark-1 is saturated. Or
that a specific prompt type always falls through to cloud.

---

## Distillation redesigned

### What we got wrong in v1/v2

Trained LoRA adapter for Llama-3.3-70B-FP4. Nothing in production
actually serves Llama-3.3-70B — it existed because NIM deployment
chose it. ai_router serves qwen2.5:7b (fast) and tries to serve
deepseek-r1:70b (deep, broken). Training a model production doesn't
serve means the adapter serves nobody.

### What to train instead

Primary target: qwen2.5:7b (fast tier).

Reasoning:
- Most production VRS/concierge traffic lands on the fast tier
- 7B model is cheap to fine-tune (minutes, not hours)
- Fits in every node's memory with room for base + adapter loaded
  simultaneously
- Adapter improvements show up in real user-facing latency
- Easy to A/B test by running base qwen2.5:7b alongside
  qwen2.5:7b-crog on same node

Secondary target (later): qwen2.5:32b (mid tier).

Reasoning:
- Deeper reasoning for complex concierge, pricing analysis
- Same model family — lessons from 7b fine-tune transfer
- Larger base requires more training compute per iteration but
  same pipeline

Explicitly NOT training targets:
- deepseek-r1:70b — too large, too specialized. Keep as frontier-local
  substitute for hard reasoning.
- llama3.2-vision:90b — vision training is a different problem
- Llama-3.3-70B-FP4 — not in production routing path

### Training infrastructure

Two paths, decide based on usage patterns:

Path A (simpler): Train on spark-2 GB10 when inference load is low.
Nightly at 2am when traffic is minimal. Requires spark-2 to NOT
hold 60GB of NIM. If NIM moves to spark-1, spark-2 has full GPU
free for training.

Path B (cleaner isolation): Dedicate spark-4 to training during
defined windows. spark-4 stops serving inference for N minutes,
trains, resumes. spark-1 carries all deep traffic during window.
Requires active-active routing to handle redirect cleanly.

Start with Path A for operational simplicity. Reconsider if training
frequency exceeds once daily.

---

## Phase plan v3

### Phase 1 — Plumbing deployed (DONE)
Running in production April 18, 2026.

### Phase 2 — Privilege filter (DONE)
Live and tested. 4-layer defense.

### Phase 2.5 — Model registry + health-aware routing (NEW, NEXT)
The foundation this v3 document describes. Without this, Phase 4+
cannot meaningfully improve production.

### Phase 3 — Flywheel capture (DONE, but flawed)
Timer armed. Exports capture pairs. BUT: captures flow through
ai_router which is currently mis-routing. A capture pair's
teacher_response may not reflect what production actually served.
Phase 2.5 must land before flywheel data is trusted for training.

### Phase 4 — Trainer (DONE, but retargeted)
Currently trains Llama-3.3-70B-FP4. Needs retarget to qwen2.5:7b.
Tomorrow's work. Existing scaffolding (manifest, error handling,
vLLM process management, holdout, eval harness, promotion gate)
is reusable — only the base model and training config change.

### Phase 4b — Eval harness (DONE)
Works regardless of target model. Ships as-is.

### Phase 4c — Adapter routing (DONE, but realigned)
Currently scaffolded to serve Llama-3.3-FP4 adapter via separate
vLLM. When target moves to qwen2.5:7b, adapter serving becomes
native Ollama (ollama run qwen2.5:7b-crog) — no vLLM needed.
Phase 4c simplifies dramatically after retarget.

### Phase 5 — Node role migration
Move NIM off spark-2. Set up active-active deep tier. This is
multi-hour production work — maintenance window required.

### Phase 6 — Multi-node observability
Per-endpoint metrics, dashboard, alerting on endpoint failures.
Lower priority until Phases 2.5 + 4-retarget are stable.

---

## Migration sequence

Recommended order. Each has specific exit criteria; don't start
N+1 until N is verified.

1. Phase 2.5 — Model registry + routing (next session, ~1-2 hours)
2. Phase 4 retarget — qwen2.5:7b training (next session, ~2-3 hours)
3. Phase 4c simplification (when retarget ships, ~1 hour)
4. Phase 5 — NIM migration off spark-2 (separate session with
   maintenance window, ~2-3 hours, production impact)
5. Phase 6 — Observability extensions (incremental, ongoing)

---

## Solo-operator constraints

This architecture assumes:
- One person makes all decisions
- Maintenance windows are 30-60 minutes during quiet traffic
- Complexity must pay for itself; anything too clever is fragile
- When something breaks at 3am, the person recovering it is the
  same person who built it

Implications:
- Model registry is Python module, not dedicated service — one
  less moving part
- Health probing is in-process thread, not sidecar — one less
  moving part
- Observability is logs + /api/v1/system-health endpoint, not
  Prometheus/Grafana — deferrable until volume justifies
- All decisions documented in PRs and in this doc — future-you
  reads the same thing current-you wrote

---

## Decision log (April 18, 2026)

1. Adopt model registry pattern over continuing with hardcoded
   endpoints. Enables all downstream improvements.
2. Distillation target: qwen2.5:7b first, qwen2.5:32b later.
   NOT Llama-3.3-70B-FP4 (current tonight's target — will be
   retargeted tomorrow).
3. NIM migration off spark-2 is scheduled but deferred.
   Control-plane/inference coexistence is the root cause of the
   training-needs-inference-stop pattern; fixing it is worth a
   maintenance window.
4. Active-active deep tier (spark-1 + spark-4) over hot-standby.
   Utilizes both GB10s.
5. Phase 3 captures continue running tonight despite the
   mis-routing, because the filter itself works and restricted
   routing still blocks privileged content from training. Training
   data quality improves automatically once Phase 2.5 lands.

---

## Risks still live

R1-R5 from v2 unchanged (secrets rotation, .env key, event_consumer
NameError, etc.).

New risks from v3:

R6 — Mis-routed historical captures. Some entries in
llm_training_captures may have teacher_response fields that didn't
actually come from the advertised tier (because routing was broken).
Mitigation: after Phase 2.5 lands, tag future captures with
served_by_endpoint so we can distinguish clean captures from
pre-fix ones.

R7 — Active-active routing complexity. Two-node load balancing
sounds simple but split-brain failure modes (both nodes think the
other is down) need thinking. Mitigation: primitive approach first —
round-robin with health gate. If split-brain happens, degrade to
single-node cleanly.

R8 — Distilled model eval assumes production data volume. Current
eval threshold (30 prompts/domain) lowered to 13 for first iteration.
Real statistical confidence needs weeks of production capture.
Mitigation: document lowered threshold as MVP-only, revert when
volume reaches natural threshold.

---

## What this document is for

A future Claude session (or future you) opening this repo should
read this doc and know:
- What's running where
- Why we designed it this way
- What ships next and in what order
- What NOT to touch without understanding why

This replaces v2 because v2 was written without the cluster audit.
v3 is the real map.
