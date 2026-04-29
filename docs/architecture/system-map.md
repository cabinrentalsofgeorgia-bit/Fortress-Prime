# Fortress Prime System Map

Last updated: 2026-04-29 (ADR-004 LOCKED; inference cluster expanded to 3/4/5/6; non-Legal divisions consolidate on spark-2)

This map shows **two states** — what runs today, and what we're migrating toward — plus the migration path between them. Source-of-truth for the architectural decisions that shape both: [`cross-division/_architectural-decisions.md`](cross-division/_architectural-decisions.md). The app-tier ↔ inference-tier split below reflects ADR-004 (LOCKED 2026-04-29 — App vs Inference Boundary), which expands ADR-003's inference cluster from Sparks 4/5/6 to Sparks 3/4/5/6 and retires "one spark per division" (ADR-001) for everything except Fortress Legal on Spark 1.

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
   │   (single tenant, ADR-004)           ConnectX, Tailscale         │
   │   ─ Legal email intake              ─ fortress-nim-brain :8100  │
   │   ─ Vault ingestion (PR D)          ─ Llama-3.3-Nemotron-Super- │
   │   ─ Privileged comms                  49B-v1.5-FP8 (NIM 2.0.1)  │
   │     Qdrant (UUID5 IDs)              ─ Ray head                  │
   │   ─ Legal app (no inference)                                    │
   │                                     SPARK 6 — staged            │
   │   SPARK 2 — multi-tenant + ctrl     10GbE → ConnectX (cable     │
   │   (192.168.0.100,                    pending; Phase 2)          │
   │    ctrl @ 100.80.122.100) ACTIVE    ─ Docker / NGC login done   │
   │   ─ FastAPI :8000                   ─ NIM image cached on NAS   │
   │   ─ All Postgres DBs                ─ No inference traffic yet  │
   │     (fortress_prod, fortress_db,                                │
   │      fortress_shadow, *_test)       SPARK 4 — pre-wipe          │
   │   ─ Qdrant (legal collections)      ─ Currently lightweight     │
   │   ─ Redis + ARQ                       (Qdrant VRS + SenseVoice)│
   │   ─ NAS mount                       ─ Wipes + joins inference   │
   │   ─ SWARM tier                        cluster at ADR-004 Phase  │
   │     (Ollama qwen2.5:7b)               3 (post-Spark-6 cable)    │
   │   ─ LiteLLM gateway                                              │
   │     ▸ legal routes →                SPARK 3 — pre-wipe          │
   │       http://spark-5:8100           ─ Currently has Vision NIM  │
   │       (ADR-003 Phase 1, MERGED)       (nemotron-nano-12b-v2-vl) │
   │   ─ Captain / Council / Sentinel    ─ Wipes + joins inference   │
   │     (ADR-002 Option A — perm.)        cluster at ADR-004 Phase  │
   │   ─ Financial (Master Acct +          4 (after Phase 3 valid.)  │
   │     Market Club replacement)        ──────────────────────────  │
   │   ─ Acquisitions                    LiteLLM (spark-2) routes    │
   │   ─ Wealth                          BRAIN tier → spark-5.       │
   │   ─ All non-Legal divisions         SWARM stays on spark-2 as   │
   │     (ADR-004 — multi-tenant         fast-path / degraded-mode.  │
   │      with logical isolation)                                    │
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

## Target state (full ADR-004 endpoint — 4-node inference cluster, Pattern 2)

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
   │   APP TIER                          INFERENCE TIER (Pattern 2) │
   │   ━━━━━━━━━━━━━━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━━━━━━━━━━━ │
   │   SPARK 1 — Fortress Legal          INSTANCE A: TP=2 (5+6)      │
   │   single tenant (ADR-004)           ─ Spark 5 — TP=2 head       │
   │   ─ Legal vault                       Ray head, Nemotron-49B    │
   │   ─ Privileged communications       ─ Spark 6 — TP=2 worker     │
   │   ─ Council legal-retrieval           pairs with Spark 5        │
   │     consumer (no inference)         ─ ConnectX RDMA / NCCL      │
   │                                                                │
   │   SPARK 2 — multi-tenant + ctrl     INSTANCE B: TP=2 (3+4)      │
   │   (ADR-004 — non-Legal cohabit)     ─ Spark 3 — TP=2 head       │
   │   ─ FastAPI :8000                     (post-wipe, ADR-004 Ph 4)│
   │   ─ All Postgres                    ─ Spark 4 — TP=2 worker     │
   │   ─ Qdrant (legal)                    (post-wipe, ADR-004 Ph 3)│
   │   ─ Redis + ARQ                                                 │
   │   ─ NAS mount                       ──────────────────────────  │
   │   ─ SWARM tier                      LiteLLM (spark-2) load-     │
   │     (Ollama qwen2.5:7b)             balances 2× TP=2 instances. │
   │   ─ LiteLLM gateway                 If one instance fails, the  │
   │     ▸ load-balances 2× TP=2        other carries the BRAIN-tier│
   │       BRAIN instances              traffic; SWARM tier on       │
   │   ─ Captain (perm.)                 spark-2 carries fast-path / │
   │   ─ Council (perm.)                 degraded-mode operation.    │
   │   ─ Sentinel (perm.)                                            │
   │   ─ CROG-VRS                        Why Pattern 2:              │
   │   ─ Financial (Master Acct +        49B has 64 attention heads. │
   │     Market Club replacement)        TP=4 divides cleanly (16    │
   │   ─ Acquisitions                    heads/node) but is single   │
   │   ─ Wealth                          point of failure. TP=2 +    │
   │   ─ All non-Legal divisions         TP=2 doubles ADR-003 Phase  │
   │     (logical isolation —            3 capacity at the Pattern-1 │
   │      Postgres roles +               redundancy floor.           │
   │      schemas + ARQ queues)                                      │
   └────────────────────────────────────────────────────────────────┘
```

---

## Migration path

### Stage 1 — ADR-003 Phase 1 — LiteLLM legal-routes cutover (DONE 2026-04-29, PR #285)

Cloud → spark-5 NIM. Closed audit finding A-02 at the routing layer. LiteLLM gateway on spark-2 routes BRAIN-tier traffic to `http://spark-5:8100`. Cloud routes preserved as commented-out emergency fallback. Verification probe PASS captured in `docs/operational/litellm-legal-cutover-2026-04-29.md`.

### Stage 2 — ADR-003 Phase 2 — Spark-6 cable cutover (TP=2)

Spark-6 moves from 10GbE to ConnectX-7. Spark-5 (head) + Spark-6 (worker) form a Ray cluster running vLLM with `--tensor-parallel-size 2` over NCCL/RDMA. Single OpenAI-compatible endpoint, 128K context, 2× throughput. Cable acquisition is the gating dependency. **Gates the Spark-3/4 wipe per ADR-004.**

### Stage 3 — ADR-004 Phase 3 — Spark-4 wipe-and-rebuild

Per ADR-004 (LOCKED 2026-04-29) and the operational brief at `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`. Spark-4 OS reinstall (Ubuntu 24, baseline matching spark-5), NIM + Ray + Docker stack, Ray worker registration to spark-5 head. Pre-wipe inventory captured first (Qdrant VRS data exported, SenseVoice migration plan executed). Lighter-load node — wiped before Spark-3.

### Stage 4 — ADR-004 Phase 4 — Spark-3 wipe-and-rebuild

Spark-3 OS reinstall and Ray-cluster join, after Phase 3 validated. Vision NIM container documented and redeployed (or retired). 4-node inference cluster goes live with default sizing **Pattern 2 (TP=2 + TP=2)** — two independent TP=2 instances, LiteLLM load-balances, one instance can fail without taking the other down.

### Stage 5 — Spark-7+ — future hardware

Spark-7+ acquisitions are open-ended. ADR-004 puts no division on a planned-but-not-provisioned future spark; if spark-7 lands and operator decides to peel a division off Spark-2, that's a future ADR-005+. Until then: Spark-2 carries every non-Legal division permanently.

**Canceled stages (per ADR-004):**
- ~~Spark-3 provisioning + Financial migration~~ — Spark-3 wipes and joins inference cluster instead. Financial stays on Spark-2 permanently. The Issue #209 CASCADE-safety concern is moot — no migration runs.
- ~~Spark-4 PLANNED for Acquisitions / Wealth co-tenancy~~ — both stay on Spark-2 permanently. Spark-4 wipes and joins inference cluster.

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
