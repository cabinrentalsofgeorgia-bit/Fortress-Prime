# IRON DOME — Enterprise AI Supercluster Architecture

**Version:** 1.0 (draft)
**Date:** 2026-04-16
**Status:** Approved architecture, pending implementation
**Owner:** Gary Knight
**Location:** ~/Fortress-Prime/docs/IRON_DOME_ARCHITECTURE.md

---

## 0. Executive Summary

Iron Dome is the unified routing, policy, classification, and capture layer for all AI inference
across the Fortress-Prime platform. It is not a new service built from scratch — it is the
consolidation and hardening of existing pieces (ai_router.py, the godhead abstraction,
legal_hive_mind, the distillation_queue, circuit breakers, the
sovereign/recursive_core/titan_engine scaffolds) into a single coherent gate.

Every AI request across CROG-VRS, Fortress Legal, Master Accounting, and future divisions flows
through Iron Dome, which classifies by domain and sensitivity, routes to the appropriate inference
tier (local sovereign or cloud frontier), enforces policy, and captures teacher-student pairs for
nightly distillation.

The cluster operates in discrete modes (swarm, hydra, ingestion, training) that reconfigure the
three GB10 DGX Spark nodes on demand via the NVIDIA NIM Operator, with a 3-minute mobilization
SLO for hydra mode. Models live canonically on NVMe-backed NAS and are auto-cached on node-local
storage by NIMCache. The control plane (spark-2) hosts a small router NIM plus Postgres, vector
stores, and Iron Dome itself; the muscle tier (spark-1/3-1/4) hosts serving and training
workloads.

A teacher-student flywheel closes the gap between frontier and local capability over time by
logging non-privileged frontier interactions, filtering for quality, and nightly QLoRA-training
domain-specific adapters that must pass held-out evaluation before promotion.

---

## 1. Operating Concepts

### 1.1 Tiered model fabric

Inference happens at one of six tiers, selected by Iron Dome at request time based on the
request's classification.

| Tier | Identifier | Location | Purpose |
|------|-----------|----------|---------|
| T1 | sovereign/router | spark-2 | Classification + general queries. Llama-3.1-8B NIM. |
| T2 | sovereign/fast | spark-3-1 | High-volume, low-latency. Llama-3.1-8B NIM. |
| T3 | sovereign/workhorse | spark-1 | Deep reasoning, privileged data. Llama-3.3-70B NIM. |
| T4a | godhead/teacher | Anthropic API | Claude. Highest-quality oracle, distillation teacher. |
| T4b | godhead/generalist | OpenAI / Google APIs | GPT-4o, Gemini 2.5 Pro. Peer fallback. |
| T4c | godhead/specialist | DeepSeek / xAI APIs | DeepSeek Reasoner, Grok. Task-specific. |

Privileged data (Legal, Accounting) can only route to T1–T3. Non-privileged data can escalate
to T4 with logging. Classification happens at T1 before any T2/T3/T4 call.

### 1.2 Mode-driven cluster

The cluster is a fleet, not a fixed topology. The three GB10 muscle nodes collectively implement
one of four operating modes at any time. Mode switches are declarative
(`kubectl apply -k overlays/mode-<name>/`) and take ≤3 minutes with warm local NIMCache.

| Mode | Purpose | Node layout (spark-1 / 3-1 / 4) |
|------|---------|--------------------------------|
| swarm | Normal ops. Default 95% of the time. | 70B / 8B+Docling+Ollama / Embeddings+Reranker (opportunistic training) |
| hydra | Deep single-problem work (discovery runs, year-end close, research dumps) | Nemotron-3-Super 120B tensor-parallel across all 3 GB10s |
| ingestion | Backlog burn-down (email lakes, document dumps) | 70B paused / 8B bulk-classifier / Embeddings + NeMo Curator at max parallelism |
| training | Deliberate multi-epoch fine-tuning beyond nightly QLoRA | 70B serving / 8B serving / dedicated training worker with fabric-backed gradient sync |

### 1.3 Classification-first data flow

Every document, email, and interaction gets classified at the first point of entry — not at query
time. Classification tags (domain, sensitivity, privilege, entity, matter) propagate into RAG
chunks, training examples, and routing decisions. Clean data in, clean models out.

This is the single most important change from the existing system, which embeds email into vector
stores without classification and therefore cannot safely serve RAG across divisions.

### 1.4 Teacher-student distillation flywheel

Every non-privileged T4 frontier call is captured as a teacher example. Quality-filtered pairs
drive nightly QLoRA fine-tuning of domain-specific LoRA adapters. New adapters must beat the
current on held-out evals before being promoted to serving. Over time, the fraction of queries
served locally rises and the fraction escalating to cloud falls. This is the strategic return on
the hardware investment.

---

## 2. Physical Topology

### 2.1 Node roles

**spark-2 — Control plane + router brain**

- Small GPU hosts a Llama-3.1-8B NIM for classification + general work
- Runs: Iron Dome (the gate), Postgres (fortress_guest, 113 tables), Qdrant (21 collections),
  ChromaDB×2 (legacy, migration target), RAG retriever, Redpanda event bus, Ray dashboard,
  Docling orchestration control, k3s control plane, Cloudflare tunnel origin, Open WebUI,
  nightly_finetune scheduler
- Tailscale IP: 100.80.122.100, LAN IP: 192.168.0.100
- Never serves production heavy inference. The 8B is routing only.

**spark-1 — Sovereign muscle (default)**

- GB10 Superchip, Grace Blackwell, unified memory
- Default: Llama-3.3-70B-Instruct NIM (single-node serving)
- Hydra mode: participates in tensor-parallel Nemotron-3-Super
- Tailscale: 100.127.241.36

**spark-3-1 — Fast tier**

- GB10 Superchip
- Default: Llama-3.1-8B NIM, retains existing Ollama and Docling services
- Hydra mode: participates in tensor-parallel Nemotron-3-Super
- Tailscale: 100.96.44.85

**spark-4 — Training / reserve / embeddings**

- GB10 Superchip
- Default: embeddings NIM (nvidia/nv-embedqa-e5-v5), NeMo Retriever reranker,
  nightly QLoRA training worker, retains SenseVoice
- Hydra mode: participates in tensor-parallel Nemotron-3-Super
- Tailscale: 100.125.35.42

### 2.2 Fabric

NVIDIA ConnectX (100 Gbps RDMA-capable, GPUDirect). Used for:

- Tensor-parallel serving in hydra mode (NCCL-backed)
- Gradient sync during distributed training
- NAS read-through during NIMCache cold population

### 2.3 Storage tiers

**Tier 1 — Local NVMe per node** (`/mnt/ai_fast/nim_cache` on each spark)

- Pre-warmed with base models for every mode the node might serve
- Target: 500GB–1TB per node for model cache
- Managed by NIMCache CRDs
- Where NIM pods mount model weights at startup

**Tier 2 — NAS canonical library** (`/mnt/fortress_nas/model_vault/`)

- NVMe/SSD-backed, multi-GB/s reads to cluster
- Layout:
  ```
  model_vault/
    nvidia_nim/              # NIM container model caches (exists)
    huggingface/             # raw HF weights (exists)
    adapters/                # domain LoRA adapters
      crog-vrs/v1/
      legal/v1/
      accounting/v1/
    merged/                  # merged adapter+base checkpoints
    manifests/
      available_models.yaml  # canonical registry Iron Dome reads
  ```
- Backup/source-of-truth. Local caches can be destroyed and rebuilt from here.

### 2.4 Network boundaries

- k3s internal ClusterIP network (10.43.0.0/16)
- Pod network (10.42.0.0/16)
- LAN (192.168.0.0/24)
- Tailscale mesh (100.64.0.0/10) for remote/out-of-band

---

## 3. Logical Tiers in Depth

### 3.1 Routing policy

Iron Dome decides routing based on a YAML policy table. Minimum viable table:

```yaml
# iron_dome/policies/v1.yaml
classification:
  domains: [crog_vrs, legal, accounting, marketing, general]
  sensitivities: [public, internal, confidential, privileged]

routing_rules:
  - match: { domain: legal, sensitivity: privileged }
    allow_tiers: [sovereign/workhorse]
    block_tiers: [sovereign/fast, godhead/*]
    fail_closed: true

  - match: { domain: accounting, sensitivity: confidential }
    allow_tiers: [sovereign/workhorse, sovereign/fast]
    block_tiers: [godhead/*]
    fail_closed: true

  - match: { domain: crog_vrs, sensitivity: public }
    prefer_tier: sovereign/fast
    escalate_to: [sovereign/workhorse, godhead/teacher]
    escalation_triggers: [uncertainty_high, novel_query]
    capture_for_distillation: true

  - match: { domain: general }
    prefer_tier: sovereign/fast
    allow_tiers: [sovereign/workhorse, godhead/generalist]

defaults:
  fallback_tier: sovereign/router
  never_silently_fail: true
```

Fail-closed for privileged domains. If the allowed tier is unavailable, requests queue or
error — they do not fall back to cloud. This is the hard part of the air-gap.

### 3.2 Tier selection heuristics

- T1 router always receives the request first. Classifies + decides downstream tier.
- T2 fast handles 80%+ of CROG-VRS traffic after pilot stabilizes.
- T3 workhorse handles all privileged work and anything T1 flags as high-complexity.
- T4 teacher (Claude) receives the hardest non-privileged queries and generates all distillation
  training signal. Treat Claude as the gold-standard oracle.
- T4 generalist/specialist receives escalations when T4 teacher is unavailable or when task type
  matches (e.g., realtime queries → Grok, math → DeepSeek Reasoner).

### 3.3 Claude-in-the-system evolution

- Today: Claude Code as terminal cockpit. You + I drive the build.
- Phase 2: Claude via Anthropic API as godhead/teacher, programmatic.
- Phase 3+: Claude Code as a sub-agent for autonomous file/code operations where chat-level
  interaction isn't enough. Deferred — evaluate after Iron Dome v2 is stable.

---

## 4. Operating Modes

### 4.1 Mode definitions

Modes are implemented as Kustomize overlays under `~/Fortress-Prime/infra/iron-dome/overlays/`.

**mode-swarm (default)**

```
spark-1:   NIMService llama-3.3-70b-instruct (1 GPU)
spark-3-1: NIMService llama-3.1-8b-instruct (1 GPU)
           + existing Ollama + Docling
spark-4:   NIMService nv-embedqa-e5-v5 (embeddings)
           + NeMo Retriever reranker
           + nightly QLoRA job (scheduled 02:00 UTC)
spark-2:   NIMService llama-3.1-8b-instruct (router)
           + Iron Dome + data plane + orchestration
```

**mode-hydra (deep work)**

```
spark-1+3-1+4: NIMService nemotron-3-super-120b-a12b
               tensor-parallel across 3 GB10s via ConnectX
               (1M context, reasoning on/off, MoE efficient)
spark-2:       NIMService llama-3.1-8b-instruct (router unchanged)
               + Iron Dome + data plane
```

**mode-ingestion (backlog burn)**

```
spark-1:   Paused (70B drained) or minimal serving
spark-3-1: Llama-3.1-8B bulk classifier (max parallelism)
           + Docling at max parallelism
spark-4:   nv-embedqa-e5-v5 bulk embedding
           + NeMo Curator for dedup/PII/quality filtering
spark-2:   Router + Iron Dome + orchestration
```

**mode-training (deliberate fine-tune)**

```
spark-1:   70B serving (continues)
spark-3-1: Training worker (QLoRA target)
spark-4:   Training worker (QLoRA target)
           fabric-backed gradient sync via NCCL
spark-2:   Router + Iron Dome + training coordinator
```

### 4.2 Mode-switch procedure

```bash
# Example: swarm → hydra
cd ~/Fortress-Prime/infra/iron-dome
kubectl apply -k overlays/mode-hydra/

# Watch pods drain and rematerialize
kubectl get pods -A -w

# Iron Dome detects mode change via NIMService state and updates
# its internal routing table. No Iron Dome restart required.
```

### 4.3 3-minute SLO breakdown

The hydra mobilization budget:

| Phase | Target | Mechanism |
|-------|--------|-----------|
| Pod termination (current mode) | 20–30s | gracefulShutdown in NIMService |
| Scheduling (new pods) | 5–15s | k3s scheduler with pre-reserved GPU |
| Container image pull | 5s (cached) | NIM images pre-pulled on all GPU nodes |
| Model load local→GPU memory | 60–120s | NIMCache-warmed local NVMe, GB10 unified memory, parallel on 3 nodes |
| NIM engine warmup + CUDA graphs | 30–60s | First-boot overhead amortized by warmup generation |
| Iron Dome routing table reload | 5s | Event-driven, no polling |
| **Total** | **125–240s** | Under the 3-minute ceiling with margin |

Achieving this requires NIMCache pre-warming: every model that could be activated in any mode
must have its weights already present on the local NVMe cache of every node that might serve it.
This is a one-time cost when new models are added — NIMCache pulls from NAS once, then subsequent
activations are local.

### 4.4 Mode governance

- **Invocation:** Manually by operator (initial phase), via Iron Dome proposal → human approve
  (Phase 2+), auto (Phase 3+ after trust established)
- **Audit:** Every mode change logged to openshift_audit_logs with operator, timestamp, previous
  mode, new mode, reason
- **Lockout:** Hydra mode requires reason string + expected duration. Auto-exits to swarm after
  duration unless extended.

---

## 5. Iron Dome Routing Layer

### 5.1 Architectural placement

Iron Dome is `backend/services/ai_router.py v2` — an extension of the existing router, not a
replacement. It runs in-process with the FastAPI backend on spark-2. Eventually migratable to a
standalone k8s Deployment if scale demands.

### 5.2 Responsibilities

1. **Classification** — For every incoming request, call T1 router NIM to classify domain +
   sensitivity + privilege
2. **Policy enforcement** — Look up routing rules from YAML. Reject disallowed routes fail-closed.
3. **Tier selection** — Choose specific NIM endpoint or frontier provider
4. **Execution** — Make the call (via LiteLLM for T4, direct HTTP for T1–T3)
5. **Capture** — Write full request/response pair to distillation_queue with metadata
6. **Audit** — Log routing decision to intelligence_ledger or new iron_dome_audit
7. **Circuit breaking** — Retry, fail-over within tier, queue when all endpoints down
   (separate queue from distillation)
8. **Mode awareness** — Query k8s API for current mode, adjust routing table accordingly

### 5.3 Extension points vs rewrites

**Keep and extend:**

- `ai_router.py` — core routing logic
- godhead namespace — becomes T4 tier label
- `legal_hive_mind.py::get_godhead_exemplars` — teacher-exemplar retrieval
- `seo_grading_service.py::seo_godhead_min_score` — quality gating pattern
- `backend/integrations/circuit_breaker.py` — retry/deferred-write infrastructure
- Postgres as distillation backing store

**Replace:**

- Hardcoded `192.168.0.100` refs (9 files) → service discovery via k8s DNS
- `http://192.168.0.100/api/embeddings` → embeddings NIM service URL
- Bare `.env` API keys → k8s Secrets + sealed-secrets or external-secrets-operator

**Deprecate over time:**

- `yzy-retriever` → NeMo Retriever NIMPipeline
- ChromaDB×2 → consolidated into Qdrant
- Direct Anthropic/OpenAI calls from individual services → always via Iron Dome

### 5.4 Policy YAML location and ownership

`~/Fortress-Prime/fortress-guest-platform/backend/services/iron_dome/policies/v1.yaml`
(canonical, checked into git). Hot-reloaded on change via file watcher. Changes require PR
review for sensitive domains.

### 5.5 Audit and observability

Every Iron Dome decision emits:

- Structured JSON log line (journald → log aggregation)
- Prometheus counter (by tier, domain, sensitivity, outcome)
- Row in `iron_dome_audit` Postgres table (append-only, 90-day retention)

Dashboard panels: routing rate per tier, classification confusion matrix, fail-closed rate,
mode-switch latency, distillation queue depth.

---

## 6. Distillation Flywheel

### 6.1 Current state

- `distillation_queue` table exists with thin schema (7 columns)
- 48 legacy rows from 2026-03-13/14, all pending, all legal_chronology failures
- `nightly_finetune.py` script exists, `fortress-nightly-finetune.service` defined,
  enablement status unknown
- Writer logic: TBD — need to locate

### 6.2 Extended schema

```sql
-- Run in Phase 1 migration
CREATE TABLE distillation_archive_legacy AS
  SELECT * FROM distillation_queue;

TRUNCATE distillation_queue;

ALTER TABLE distillation_queue
  ADD COLUMN domain                   varchar(50),
  ADD COLUMN sensitivity              varchar(20),
  ADD COLUMN privileged               boolean NOT NULL DEFAULT false,
  ADD COLUMN entity_id                uuid,
  ADD COLUMN matter_id                uuid,
  ADD COLUMN user_id                  uuid,
  ADD COLUMN frontier_response        text,
  ADD COLUMN frontier_model           varchar(100),
  ADD COLUMN quality_signal           varchar(30),
  ADD COLUMN quality_score            numeric(3,2),
  ADD COLUMN approved_for_training    boolean NOT NULL DEFAULT false,
  ADD COLUMN classification_version   varchar(20),
  ADD COLUMN iron_dome_decision_id    uuid,
  ADD COLUMN reviewed_by              varchar(100),
  ADD COLUMN reviewed_at              timestamptz;

CREATE INDEX ix_dq_domain_sensitivity ON distillation_queue (domain, sensitivity);
CREATE INDEX ix_dq_approved ON distillation_queue (approved_for_training)
  WHERE approved_for_training = true;
```

The 48 legacy rows go into `distillation_archive_legacy`, tagged `privileged=true`,
`approved_for_training=false`, and never enter training.

### 6.3 Capture pipeline

Iron Dome writes every T4 call to `distillation_queue` with:

- Full prompt (the request as sent to T4)
- Full T4 response (the teacher answer)
- T3 response (if T3 also answered, for student-teacher pair)
- Domain + sensitivity from classification
- Quality signal (populated later when user reacts)

### 6.4 Quality signals

User-side signals that populate `quality_signal`:

- `accepted` — user used the output without edit
- `edited` — user modified the output (diff distance captured)
- `thumbs_up` / `thumbs_down` — explicit feedback
- `ignored` — no engagement (not training signal)
- `escalated` — user re-asked or escalated to human

Only `accepted`, `edited` with small diff, and `thumbs_up` become training candidates.
`approved_for_training` gets flipped true after domain review for sensitive domains,
auto-approved for public domains with clean signals.

### 6.5 Training pipeline

Nightly job (`nightly_finetune.py v2`, extended):

```
1. Export approved rows from last 30 days, partitioned by domain
2. Validate per-domain: skip if < MIN_EXAMPLES=20 for that domain
3. Switch cluster to mode-training (or use mode-swarm idle capacity)
4. QLoRA fine-tune per domain:
   - Base: Llama-3.3-70B-Instruct
   - LoRA rank: 16, batch: 1, grad_accum: 8, epochs: 1
   - Tensor-parallel across spark-3-1 + spark-4 via ConnectX
5. Save adapter → /mnt/fortress_nas/model_vault/adapters/{domain}/v{N}/
6. Run eval: new adapter vs current on held-out set of 100-200 golden pairs
7. Promote if new > current (metric: accuracy on golden set, no regression on other domains)
8. Load promoted adapter into spark-1 NIM for serving
9. Switch back to mode-swarm
10. Record in adapter_provenance table
```

### 6.6 Eval sets

Per-domain golden eval sets in NAS:

```
/mnt/fortress_nas/evals/
  crog_vrs/
    golden_v1.jsonl          # 100-200 prompt/response pairs
    adversarial_v1.jsonl     # edge cases
  legal/
    golden_v1.jsonl          # curated by legal review
  accounting/
    golden_v1.jsonl
```

Eval sets are the backbone of "is the flywheel actually working." Without them, training is
hope. Initial eval sets: 50-100 pairs per domain, manually curated. Grow to 200-500 over time
as real production traffic accumulates.

### 6.7 Adapter provenance

```sql
CREATE TABLE adapter_provenance (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  domain              varchar(50) NOT NULL,
  version             varchar(20) NOT NULL,
  base_model          varchar(100) NOT NULL,
  training_data_hash  varchar(64) NOT NULL,
  example_count       integer NOT NULL,
  eval_score_current  numeric(5,4),
  eval_score_previous numeric(5,4),
  promoted            boolean NOT NULL DEFAULT false,
  promoted_at         timestamptz,
  promoted_by         varchar(100),
  adapter_path        text NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  notes               text
);
```

You will thank yourself for this table in six months.

---

## 7. Data Plane

### 7.1 Model library structure

As shown in §2.3. NIMCache CRDs are the interface; raw filesystem is source of truth.

### 7.2 Vector DB consolidation

**Current state:** 21 Qdrant collections + 2 ChromaDB instances. Overlap unclear.

**Target state:** Qdrant as primary, ChromaDB deprecated.

**Migration:** Phase 2. Enumerate what's in each Chroma, determine if duplicated in Qdrant,
migrate unique data, decommission Chroma containers.

**Classification backfill:** Every chunk in every collection needs domain, sensitivity, privilege,
entity, matter metadata. Largest effort is `email_embeddings` — likely needs re-classification
from source `.eml` files through Iron Dome's classification pipeline.

### 7.3 RAG stack evolution

**Current:** `yzy-retriever` (custom FastAPI service on :8010) + ChromaDB + Qdrant

**Target:** NeMo Retriever NIMPipeline (embedder + reranker as NIMs) + Qdrant as storage

**Transition:** Run both in parallel during Phase 2. Compare retrieval quality on labeled test
set. Cut over when NeMo Retriever matches or beats yzy-retriever.

### 7.4 Ingestion pipeline

**Current:** Miners (`document_miner.py`, `email_miner.py`, `email_miner_maildir.py`,
`nas_worker.py`) write files to `ingestion_queue.db` (SQLite), then process into Qdrant without
classification.

**Target:** Miners write to queue → Iron Dome classification hook → tagged write to Qdrant with
full metadata. Classification failures halt the chunk, not just log-and-continue.

**Key change:** `ingestion_queue.db` SQLite gets replaced with a Postgres table
`ingestion_queue_v2` that includes classification results.

### 7.5 Email data lake

**Location:** `/mnt/fortress_nas/Communications/System_MailPlus_Server/ENTERPRISE_DATA_LAKE`,
plus `Business_CROG`, `Personal_Documents` subdirectories, plus `ingestion_queue_eml/` for
sweeper output.

**Format:** Maildir (based on `email_miner_maildir.py` existence).

**Priority:** Re-classify into new schema during mode-ingestion runs. Privileged (legal) emails
go to isolated Qdrant collection with matter-level ACL. Personal emails may be excluded from
enterprise RAG entirely.

---

## 8. Observability & Operations

### 8.1 Metrics stack

- **Prometheus** — scrape NIMs (native vLLM metrics), Iron Dome (custom counters), k3s, Postgres
- **Grafana** — dashboards for fleet, Iron Dome, distillation, per-domain eval trends
- **Redpanda** — already running. Becomes the event bus for Iron Dome audit events (downstream
  to Postgres + S3-compatible archive)

### 8.2 Key dashboards

1. **Fleet** — which mode, per-node GPU util, NIM pod health, NIMCache hit rate
2. **Iron Dome routing** — req/sec per tier, classification latency, fail-closed events
3. **Distillation pipeline** — queue depth by domain, approved-for-training rate, last nightly
   run status
4. **Eval trends** — per-domain golden set score over time, regression alerts
5. **Cost** — T4 tokens consumed per day per provider, estimated monthly spend

### 8.3 Alerting thresholds (initial)

- Any NIMService not Ready > 5 min → page
- Iron Dome classification latency p99 > 500ms → page
- Mode-switch duration > 4 min → warn
- Fail-closed rate > 1% → warn (may indicate legitimate policy match, investigate)
- Distillation queue depth > 10,000 → warn
- Nightly finetune job failure → page

### 8.4 Disaster recovery

**Model vault backup:** `/mnt/fortress_nas/model_vault/` → off-site nightly snapshot (Synology
replication or rclone to cloud). Canonical artifacts must survive NAS loss.

**Postgres backup:** Already has `backup.log` and `/backups` dir. Verify cadence, verify restore
procedure. Offsite copy required for critical tables (`adapter_provenance`, `iron_dome_audit`,
`distillation_queue`).

**Config as code:** All k8s manifests, Iron Dome policies, systemd units in
`~/Fortress-Prime/deploy/` and `~/Fortress-Prime/infra/` in git. Cluster reconstruction =
`git clone` + `apply`.

**Secrets recovery:** Use sealed-secrets or external-secrets-operator with an encrypted backup
of the seal key. Losing all secrets = losing access to all frontier APIs + NGC + databases,
which is worse than losing the code.

---

## 9. Migration Path

### Phase 0 — Diagnose & secure (Week 1)

**Secrets hygiene (day 1):**

- Rotate LiteLLM master key (`sk-fortress-master-123` → strong random)
- Rotate NGC API key (exposed in chat transcript)
- Bind Postgres to localhost or Tailscale-only
- Move all `.env` secrets into k8s Secrets
- Pin SSH host keys across fleet

**Finish discovery:**

- Read `ai_router.py`, `legal_hive_mind.py`, `crog_concierge_engine.py`,
  `seo_grading_service.py`, `settings/config`, distillation_queue writer
- Identify spark-2's actual GPU model
- Enumerate enabled vs defined systemd units
- Complete NAS size inventory (run `du` in background, collect results)
- Enumerate ChromaDB contents for migration plan
- Verify `nightly_finetune.service` state (enabled/running/dormant)

Fix the broken `192.168.0.100/api/embeddings` references — three services degraded. Replace
with proper service URL.

### Phase 1 — Foundation (Weeks 2–3)

- Install NVIDIA NIM Operator (and cert-manager) in k3s
- Define NIMCache CRDs for: Llama-3.1-8B, Llama-3.3-70B, nv-embedqa-e5-v5
- Pre-warm NIMCache on all 3 GB10 nodes for swarm-mode models
- Deploy NIMService on spark-1 (70B), spark-3-1 (8B), spark-4 (embeddings)
- Migrate nim-sovereign off spark-2 (or keep the 8B there as router — per decision log)
- Extend distillation_queue schema; archive 48 legacy rows
- Stand up Prometheus + Grafana; wire NIM and Iron Dome metrics
- Disable fortress-nightly-finetune.service until Phase 3

### Phase 2 — Iron Dome v1 & CROG-VRS pilot (Weeks 4–6)

- Build Iron Dome as ai_router v2: classification step, policy YAML, multi-tier routing,
  audit logging
- Write initial policy YAML for CROG-VRS, general domains
- Route all CROG-VRS LLM traffic through Iron Dome
- Ingestion-time classification hook in miners
- Wire user-side quality signals (thumbs, accept, edit-distance) in storefront UI
- Begin collecting real distillation pairs from T4 calls
- Build initial CROG-VRS golden eval set (100 pairs)

### Phase 3 — Flywheel & extend domains (Weeks 7–10)

- Re-enable fortress-nightly-finetune.service with extended pipeline
- First CROG-VRS LoRA training run → eval → manual promotion
- Add mode-training and mode-ingestion overlays
- Bring Master Accounting online: Qdrant collection, domain policy, eval set
- Bring Fortress Legal online: matter-level ACL, privileged routing, eval set
- NeMo Retriever deployment; A/B test vs yzy-retriever
- Begin Qdrant classification backfill for email_embeddings

### Phase 4 — Hardening & hydra (Weeks 11–13)

- Stand up mode-hydra with Nemotron-3-Super tensor-parallel
- First hydra-mode exercise: pick a real deep-work task (year-end close? legal discovery?)
- Measure actual mode-switch latency; tune to 3-min SLO
- ChromaDB decommission
- Automate adapter promotion with guardrails
- DR drill: rebuild a muscle node from scratch via NIMCache re-population

### Phase 5 — Autonomy (ongoing)

- Auto-mode-switching based on workload patterns
- Claude-as-sub-agent for autonomous ops tasks
- Per-user / per-tenant policy (when staff > 5 people)
- Nemotron-3-Ultra evaluation as replacement for Llama-3.3-70B

---

## 10. Open Questions & Deferred Decisions

These are flagged for explicit future decision, not unresolved architecture:

| Question | Status | Trigger to decide |
|---------|--------|------------------|
| Nemotron-3-Super as default sovereign (vs Llama-3.3-70B) | Deferred | After Phase 1; depends on NIM image availability for DGX Spark |
| Claude Code as runtime sub-agent (vs dev-tool only) | Deferred | After Iron Dome v2 stable |
| ChromaDB deprecation timing | Deferred | After content enumeration in Phase 0 |
| Paperclip integration with Iron Dome | Won't do | Paperclip is vendor SaaS; no integration planned |
| Per-tenant / per-matter ACL granularity in Qdrant | Deferred | Before Fortress Legal goes live (Phase 3) |
| Auto-promotion of LoRA adapters | Deferred | After 4+ weeks of manual promotion provides baseline trust |
| Multi-region / off-site muscle cluster | Out of scope v1 | Revisit in 6 months |

---

## 11. Appendices

### A. Hardware inventory (current)

| Node | Role | GPU | Storage | Network |
|------|------|-----|---------|---------|
| spark-2 | Control plane | TBD (running NIM 8B) | Local + NAS mount | LAN 192.168.0.100 + TS 100.80.122.100 |
| spark-1 | Muscle | NVIDIA GB10 (Grace Blackwell) | NVMe + NAS | TS 100.127.241.36 |
| spark-3-1 | Muscle | NVIDIA GB10 | NVMe + NAS | TS 100.96.44.85 |
| spark-4 | Muscle | NVIDIA GB10 | NVMe + NAS | TS 100.125.35.42 |
| NAS | Model vault + data | — | NVMe/SSD tier | Mounted on all nodes |

### B. Current service inventory (reference)

**On spark-2 (Docker):**

- portainer, portainer-agent
- fortress-event-console (Redpanda console)
- fortress-rag-retriever (yzy-retriever :8010)
- fortress-chromadb + fortress-chroma (two instances :8004, :8020)
- fortress-qdrant (:6333-6334)
- fortress_mission_control (Open WebUI)

**On spark-2 (k3s):**

- nim-sovereign (Llama-3.1-8B, default ns) — to be migrated or re-roled as router
- gpu-operator stack (full)
- paperclip + paperclip-glass-proxy (paperclip ns) — vendor tool, untouched

**On spark-3-1:** ollama, docling-shredder, portainer-agent

**On spark-4:** sensevoice, portainer-agent

### C. Key code locations

| Asset | Path |
|-------|------|
| Existing router | `~/Fortress-Prime/fortress-guest-platform/backend/services/ai_router.py` |
| Teacher-student framework | `~/Fortress-Prime/fortress-guest-platform/backend/services/legal_hive_mind.py` |
| Persona system | `~/Fortress-Prime/fortress-guest-platform/backend/services/crog_concierge_engine.py` |
| Quality scoring | `~/Fortress-Prime/fortress-guest-platform/backend/services/seo_grading_service.py` |
| Circuit breakers | `~/Fortress-Prime/fortress-guest-platform/backend/integrations/circuit_breaker.py` |
| Nightly finetune | `~/Fortress-Prime/src/nightly_finetune.py` |
| LiteLLM config | `~/Fortress-Prime/litellm_config.yaml` |
| Ingestion miners | `~/Fortress-Prime/document_miner.py`, `email_miner*.py`, `nas_worker.py` |
| Systemd units | `~/Fortress-Prime/deploy/systemd/`, `~/Fortress-Prime/fortress-guest-platform/deploy/systemd/` |

### D. Security hygiene checklist

- [ ] Rotate LiteLLM master key (`sk-fortress-master-123`)
- [ ] Rotate NGC API key (exposed)
- [ ] Postgres bind to localhost or Tailscale-only (currently 0.0.0.0:5432)
- [ ] Move all API keys into k8s Secrets
- [ ] Pin SSH host keys fleet-wide
- [ ] Audit and rotate all secrets listed in `.env.security`
- [ ] Firewall spark-1 (sovereign tier): no internet egress
- [ ] Review paperclip namespace for credential exposure
- [ ] Implement secret backup procedure (sealed-secrets key export)
- [ ] Annual secret rotation policy

### E. Decision log (captured from design sessions)

1. Logical air-gap (sensitive stays local, non-sensitive can hit frontier)
2. All three workstreams in parallel (inference + distillation + policy)
3. CROG-VRS is the pilot domain
4. Iron Dome = ai_router.py v2 (extend, don't rebuild)
5. Godhead = all frontier models unified under one tier
6. Archive 48 legacy distillation rows to distillation_archive_legacy
7. 70B sovereign on spark-1, 8B fast on spark-3-1, training/reserve on spark-4
8. Llama-3.3-70B-Instruct as default sovereign workhorse (matches finetune.py)
9. Keep 8B on spark-2 as router + general
10. spark-2 is control plane, GB10s are the muscle, ConnectX fabric for intra-cluster
11. Claude eventually in-system, Claude Code as cockpit today
12. NIM Operator as the k8s abstraction (CRDs for Cache/Service/Pipeline)
13. Mode-driven fleet with swarm/hydra/ingestion/training overlays
14. 3-minute mode-switch SLO (via NIMCache local-pinning)
15. Two-tier storage: local NVMe per node + NAS canonical library

### F. References

- NVIDIA NIM Operator: https://docs.nvidia.com/nim-operator/latest/
- NVIDIA Nemotron 3 family: https://developer.nvidia.com/nemotron
- NeMo Framework: https://developer.nvidia.com/nemo-framework
- NVIDIA DGX Spark documentation: https://docs.nvidia.com/dgx/dgx-spark/
- NeMo Retriever: https://docs.nvidia.com/nim/nemo-retriever/
- NeMo Curator: https://developer.nvidia.com/nemo-curator

---

End of document.
