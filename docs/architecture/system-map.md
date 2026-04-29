# Fortress Prime System Map

Last updated: 2026-04-29 (ADR-003 v2 LOCKED; app/inference split)

This map shows **two states** — what runs today, and what we're migrating toward — plus the migration path between them. Source-of-truth for the architectural decisions that shape both: [`cross-division/_architectural-decisions.md`](cross-division/_architectural-decisions.md). The app-tier ↔ inference-tier split below reflects ADR-003 (2026-04-29 LOCKED — dedicated inference cluster on Sparks 4/5/6) which supersedes the 2026-04-26 "shared swarm across all sparks" ADR-003.

---

## Current state (2026-04-29 — Phase 1 of ADR-003 v2)

```
                    ┌─────────────────────────────────────┐
                    │         HUMAN OPERATOR              │
                    │     (Gary Mitchell Knight)          │
                    └────────────────┬────────────────────┘
                                     │
                  ┌──────────────────┴───────────────────┐
                  │                                      │
        ┌─────────▼──────────┐              ┌────────────▼───────────┐
        │  STOREFRONT        │              │  COMMAND-CENTER        │
        │  cabin-rentals-of  │              │  crog-ai.com           │
        │  -georgia.com      │              │  (internal staff/AI)   │
        │  (Next.js public)  │              │  (Next.js internal)    │
        └─────────┬──────────┘              └────────────┬───────────┘
                  │           Cloudflare Tunnel          │
                  ▼                                      ▼
   ┌────────────────────────────────────────────────────────────────┐
   │                                                                │
   │   APP TIER                          INFERENCE TIER             │
   │   ━━━━━━━━━━━━━━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━━━━━━━━    │
   │   SPARK 1 — Fortress Legal          SPARK 5 — BRAIN (active)   │
   │   (192.168.0.X) ACTIVE              ConnectX, Tailscale         │
   │   ─ Legal email intake              ─ fortress-nim-brain :8100  │
   │   ─ Vault ingestion (PR D)          ─ Llama-3.3-Nemotron-Super- │
   │   ─ Privileged comms                  49B-v1.5-FP8 (NIM 2.0.1)  │
   │     Qdrant (UUID5 IDs)              ─ Ray head (Phase 2 ready)  │
   │   ─ Legal app (no inference)                                    │
   │                                     SPARK 6 — staged            │
   │   SPARK 2 — CROG-VRS + control      10GbE → ConnectX (cable     │
   │   (192.168.0.100,                    pending)                   │
   │    ctrl @ 100.80.122.100) ACTIVE    ─ Docker / NGC login done   │
   │   ─ FastAPI :8000                   ─ NIM image cached on NAS   │
   │   ─ All Postgres DBs                ─ No inference traffic yet  │
   │     (fortress_prod, fortress_db,                                │
   │      fortress_shadow, *_test)       SPARK 4 — app today,        │
   │   ─ Qdrant (legal collections)      inference at Phase 3        │
   │   ─ Redis + ARQ                     ─ ConnectX                  │
   │   ─ NAS mount                       ─ Currently planned for     │
   │   ─ SWARM tier                        Acquisitions OR Wealth;   │
   │     (Ollama qwen2.5:7b)               will join inference       │
   │   ─ LiteLLM gateway                   cluster at Phase 3 with   │
   │     ▸ legal routes →                  Acq+Wealth co-tenanting   │
   │       http://spark-5:8100             on Spark-3                │
   │       (ADR-003 Phase 1)             ──────────────────────────  │
   │   ─ Captain / Council / Sentinel    LiteLLM (spark-2) routes    │
   │     (ADR-002 Option A — perm.)      BRAIN tier → spark-5.       │
   │                                     SWARM stays on spark-2 as   │
   │   SPARK 3 — Financial               fast-path / degraded-mode.  │
   │   PLANNED (not provisioned)                                     │
   │   ─ Will host:                                                  │
   │     division_a.* + hedge_fund.*                                 │
   │     Master Accounting + Market                                  │
   │     Club + Acquisitions + Wealth                                │
   │     co-tenants                                                  │
   │                                                                 │
   └────────────────────────────────────────────────────────────────┘
                                     │
                          ┌──────────▼─────────┐
                          │  EXTERNAL          │
                          │  Stripe / Twilio   │
                          │  Streamline        │
                          │  Channex / Plaid   │
                          │  cPanel IMAP       │
                          │  QuickBooks        │
                          │  Google (Gemini)   │
                          └────────────────────┘
```

### Connection legend (current — Phase 1 of ADR-003 v2)

| Edge | Description |
|---|---|
| Storefront → Tunnel → Spark 2 FastAPI | Public guest traffic; bookings, listings, content. No DB driver in the frontend. |
| Command-center → Tunnel → Spark 2 FastAPI | Internal staff + AI agent traffic. Vault, Council, deliberation, dashboards. |
| Spark 1 ↔ Spark 2 (LAN) | Cross-spark for legal Postgres reads (Spark 2's DBs, Spark 1's services), Council retrieval (Spark 2 Council reads Spark 2's Qdrant — Council is now spark-2-permanent per ADR-002 amended). |
| Spark 2 → Spark 5 (LAN / Tailscale) | LiteLLM gateway routes BRAIN-tier inference to spark-5 NIM at `http://spark-5:8100` (ADR-003 Phase 1; closes audit A-02). |
| Spark 2 → External | Stripe webhooks (in), Twilio SMS (out), Streamline + Channex (PMS sync), Plaid (banking), QuickBooks (accounting mirror), cPanel IMAP (Captain) |
| Spark 1 → External | ARCHITECT (Gemini) cloud — planning only, no PII. **No more local TITAN/BRAIN on spark-1 — moved to inference cluster.** |

---

## Target state (Phase 3 endpoint of ADR-003 v2 — Pattern 1)

```
                  ┌──────────────────────────────────────┐
                  │         HUMAN OPERATOR               │
                  └────────────────┬─────────────────────┘
                                   │
                                   │  Cloudflare Tunnels
                                   │  (storefront + command-center)
                                   ▼
   ┌────────────────────────────────────────────────────────────────┐
   │                                                                │
   │   APP TIER                          INFERENCE TIER (Pattern 1) │
   │   ━━━━━━━━━━━━━━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━━━━━━━━━━━ │
   │   SPARK 1 — Fortress Legal          SPARK 4 — Pattern 1        │
   │   ─ Legal vault                       hot replica host         │
   │   ─ Privileged communications        ─ Single 49B instance     │
   │   ─ Council legal-retrieval            (failover target)       │
   │     consumer (no inference)           ─ Joins inference cluster│
   │                                         at Phase 3             │
   │   SPARK 2 — Control plane           SPARK 5 — TP=2 head         │
   │   (CROG-VRS + ctrl)                  ─ vLLM TP=2 with Spark-6  │
   │   ─ FastAPI :8000                    ─ Ray head node            │
   │   ─ All Postgres                     ─ Instance 1 of 2          │
   │   ─ Qdrant (legal)                                              │
   │   ─ Redis + ARQ                     SPARK 6 — TP=2 worker      │
   │   ─ NAS mount                        ─ vLLM TP=2 with Spark-5  │
   │   ─ SWARM tier                       ─ ConnectX (Phase 2 cable)│
   │     (Ollama qwen2.5:7b)                                        │
   │   ─ LiteLLM gateway                 ──────────────────────────  │
   │     ▸ load-balances 2               LiteLLM (spark-2) load-     │
   │       BRAIN instances:              balances 2 instances:       │
   │       1. TP=2 (5+6)                  1. TP=2 over 5+6           │
   │       2. Single (4)                  2. Single 49B on 4         │
   │   ─ Captain (perm.)                 Hot failover if instance    │
   │   ─ Council (perm.)                 fails (Pattern 1, locked    │
   │   ─ Sentinel (perm.)                at decision time per        │
   │                                     ADR-003 Phase 3 sizing).    │
   │   SPARK 3 — Financial +                                         │
   │   Acquisitions + Wealth                                         │
   │   (until Spark-7+)                                              │
   │   ─ division_a.* + hedge_fund.*                                 │
   │   ─ Master Accounting               Why Pattern 1:              │
   │   ─ Market Club replacement         49B has 64 attention heads. │
   │   ─ Acquisitions deal pipe           TP requires n_heads %      │
   │   ─ Wealth intelligence              tp_size == 0. 64 / 3 ≠ 0,  │
   │                                     so literal TP=3 won't run.  │
   │                                     TP=2 + hot replica gives    │
   │                                     2× throughput AND failover. │
   └────────────────────────────────────────────────────────────────┘
```

---

## Migration path

### Stage 1 — ADR-003 Phase 1 (this PR) — LiteLLM legal-routes cutover

Cloud → spark-5 NIM. Closes audit finding A-02 (sovereign legal inference). LiteLLM gateway on spark-2 routes BRAIN-tier traffic to `http://spark-5:8100`. Cloud routes preserved as commented-out emergency fallback. Single verification probe gates the cutover.

### Stage 2 — ADR-003 Phase 2 — Spark-6 cable cutover (TP=2)

Spark-6 moves from 10GbE to ConnectX-7. Spark-5 (head) + Spark-6 (worker) form a Ray cluster running vLLM with `--tensor-parallel-size 2` over NCCL/RDMA. Single OpenAI-compatible endpoint, 128K context, 2× throughput. Cable acquisition is the gating dependency.

### Stage 3 — Spark-3 provisioning + Financial migration

When Spark-3 hardware lands:

1. Provision Postgres (matched version + tuning to spark-2's instance)
2. Provision Qdrant if Financial collections move (open question — most Qdrant stays on spark-2 because legal collections live there; Financial may not need a Qdrant of its own)
3. Stand up Master Accounting services as warm-spare on Spark-3 (no traffic yet)
4. Stand up Market Club scoring engine on Spark-3 in parallel with spark-2 scaffolding
5. Migrate `hedge_fund.*` + `division_a.*` schemas spark-2 → spark-3 using dual-write → verify → read switchover → write switchover → cleanup pattern (informed by PR G phase C lessons + Issue #209)

⚠️ Per Issue #209, the FK on `legal.ingest_runs.case_slug → legal.cases.case_slug ON DELETE CASCADE` ate the audit row for the PR D 7IL ingestion when Phase C renamed the slug. The spark-2 → spark-3 migration must NOT trigger similar CASCADEs across `division_a.*` audit tables.

### Stage 4 — ADR-003 Phase 3 — Spark-4 joins inference cluster

Software-only cutover. Spark-4 already on ConnectX. Acquisitions and Wealth co-tenant on Spark-3 with Financial. Inference cluster reaches **Pattern 1 sizing (TP=2 + 1 hot replica)** as locked at the 2026-04-29 decision.

Trigger criteria for Phase 3 (operator confirms at Phase 2 completion): (a) Acquisitions/Wealth workloads stay light enough to co-tenant on Spark-3, OR (b) BRAIN-tier traffic outgrows TP=2 throughput.

### Stage 5 — Spark-7+ — Acquisitions or Wealth gets dedicated app spark

Once additional hardware is acquired, the first of Acquisitions / Wealth ramps off Spark-3 onto its own app spark. Order is operator's call.

---

## Cross-references

- [`cross-division/_architectural-decisions.md`](cross-division/_architectural-decisions.md) — ADR-001 (LOCKED, amended 2026-04-29: one spark per app division; inference is shared cluster) + ADR-002 (LOCKED, amended 2026-04-29: Captain/Council/Sentinel all permanent on spark-2 control plane — reverses the earlier Council → Spark-4 decision) + ADR-003 (LOCKED 2026-04-29: dedicated inference cluster on Sparks 4/5/6, Phase 3 sizing Pattern 1 TP=2 + hot replica)
- [`cross-division/ADR-003-inference-cluster-topology.md`](cross-division/ADR-003-inference-cluster-topology.md) — canonical ADR-003 v2 document
- [`shared/infrastructure.md`](shared/infrastructure.md) — Spark allocation table + DEFCON tier table + migration milestones (post-ADR-003 v2)
- [`shared/council-deliberation.md`](shared/council-deliberation.md) — Council on spark-2 control plane (ADR-002 Option A across the board)
- [`shared/captain-email-intake.md`](shared/captain-email-intake.md) — Captain on spark-2 control plane
- [`shared/sentinel-nas-walker.md`](shared/sentinel-nas-walker.md) — Sentinel on spark-2 control plane
- [`divisions/_template.md`](divisions/_template.md) — "Inference consumers" subsection per division (now consume spark-5 NIM via LiteLLM)
- [`divisions/financial.md`](divisions/financial.md) — Spark-3 target details + Acquisitions/Wealth co-tenancy until Spark-7+
- [`fortress_atlas.yaml`](../../fortress_atlas.yaml) — runtime sector routing (currently spark-agnostic; future amendment may add per-sector spark allocation)
