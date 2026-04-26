# Fortress Prime System Map

Last updated: 2026-04-26

This map shows **two states** — what runs today, and what we're migrating toward — plus the migration path between them. Source-of-truth for the architectural decisions that shape both: [`cross-division/_architectural-decisions.md`](cross-division/_architectural-decisions.md).

---

## Current state (2026-04-26)

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
   │   SPARK 1 — Fortress Legal       SPARK 2 — CROG-VRS + control  │
   │   (192.168.0.X) ACTIVE           (192.168.0.100,                │
   │                                   ctrl @ 100.80.122.100)        │
   │   ─ Legal email intake            ACTIVE                        │
   │   ─ Vault ingestion (PR D)       ─ FastAPI :8000                │
   │   ─ Privileged communications    ─ All Postgres DBs             │
   │     Qdrant (UUID5 IDs)             (fortress_prod, fortress_db, │
   │   ─ Council legal retrieval        fortress_shadow, *_test)     │
   │   ─ TITAN tier                   ─ Qdrant (legal collections)   │
   │     (DeepSeek-R1 671B)           ─ Redis + ARQ                  │
   │   ─ BRAIN tier                   ─ NAS mount                    │
   │     (NIM Nemotron 49B FP8)       ─ SWARM tier                   │
   │                                    (Ollama qwen2.5:7b)          │
   │                                  ─ DOUBLE-DUTY ⚠                │
   │                                    + temp Financial scaffolding │
   │                                    + temp control plane         │
   │                                      (Captain/Council/Sentinel) │
   │                                                                │
   │   SPARK 3 — Financial            SPARK 4 — TBD                  │
   │   PLANNED (not provisioned)      PLANNED (not provisioned)      │
   │   ─ Will host:                   ─ Likely Acquisitions OR       │
   │     division_a.* schema             Wealth (operator picks      │
   │     hedge_fund.* schema             which division ramps first) │
   │     Master Accounting svc                                       │
   │     Market Club scoring                                         │
   │     Financial NAS                                               │
   │                                                                │
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

### Connection legend (current)

| Edge | Description |
|---|---|
| Storefront → Tunnel → Spark 2 FastAPI | Public guest traffic; bookings, listings, content. No DB driver in the frontend. |
| Command-center → Tunnel → Spark 2 FastAPI | Internal staff + AI agent traffic. Vault, Council, deliberation, dashboards. |
| Spark 1 ↔ Spark 2 (LAN) | Cross-spark for legal Postgres reads (Spark 2's DBs, Spark 1's services), Council retrieval (Spark 1 reads Spark 2's Qdrant) |
| Spark 2 → External | Stripe webhooks (in), Twilio SMS (out), Streamline + Channex (PMS sync), Plaid (banking), QuickBooks (accounting mirror), cPanel IMAP (Captain) |
| Spark 1 → External | TITAN/BRAIN inference local; ARCHITECT (Gemini) cloud — planning only, no PII |

---

## Target state (post-migration)

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
   │   SPARK 1            SPARK 2            SPARK 3        SPARK 4 │
   │   Fortress           CROG-VRS           Financial      TBD     │
   │   Legal              (single duty)      (active)       (Acq    │
   │   ACTIVE             ACTIVE             ACTIVE          or     │
   │                                                         Wealth)│
   │   ─ Legal vault      ─ Storefront       ─ division_a.* ACTIVE  │
   │   ─ Privileged       ─ Command-center   ─ hedge_fund.*         │
   │     comms            ─ Properties /     ─ Master Acc           │
   │   ─ Council legal      Bookings           services             │
   │   ─ TITAN/BRAIN      ─ Stripe handoff   ─ Market Club          │
   │                        to Spark 3         scoring              │
   │                                         ─ Financial NAS        │
   │                                                                │
   │     ┌─────────────────────────────────────────────────────┐   │
   │     │  SHARED INFRASTRUCTURE — placement OPEN per ADR-002 │   │
   │     │  Captain / Council / Sentinel / Auth / MCP          │   │
   │     │                                                      │   │
   │     │  Option A: stays on Spark 2 (control-plane host)    │   │
   │     │  Option B: dedicated shared-infra spark (+1 node?)  │   │
   │     │  Option C: per-division replicas                    │   │
   │     └─────────────────────────────────────────────────────┘   │
   │                                                                │
   └────────────────────────────────────────────────────────────────┘
```

---

## Migration path

### Stage 1 — Spark 3 provisioning (gating dependency)

**Status:** Hardware not yet acquired. Timeline operator-confirmed (open question per ADR-002 / `divisions/financial.md`).

When Spark 3 lands:
1. Provision Postgres (matched version + tuning to Spark 2's instance)
2. Provision Qdrant if Financial collections move (open question — most Qdrant stays on Spark 2 because legal collections live there; Financial may not need a Qdrant of its own)
3. Stand up Master Accounting services as warm-spare on Spark 3 (no traffic yet)
4. Stand up Market Club scoring engine on Spark 3 in parallel with Spark 2 scaffolding

### Stage 2 — `hedge_fund.*` + `division_a.*` schema migration

Patterns to apply (informed by PR G phase C lessons + Issue #209):

1. **Dual-write window:** scripts on Spark 2 begin writing to both Spark 2 and Spark 3 Postgres; reads still served by Spark 2
2. **Verification window:** compare row counts + checksums daily
3. **Read switchover:** Spark 3 becomes the read source; Spark 2 becomes follower
4. **Write switchover:** Spark 3 becomes the canonical writer; Spark 2 stops accepting Financial-domain writes
5. **Cleanup:** drop Financial schemas from Spark 2 (after operator-confirmed verification window)

⚠️ Per Issue #209, the FK on `legal.ingest_runs.case_slug → legal.cases.case_slug ON DELETE CASCADE` ate the audit row for the PR D 7IL ingestion when Phase C renamed the slug. The Spark 2→3 migration must NOT trigger similar CASCADEs across `division_a.*` audit tables.

### Stage 3 — ADR-002 resolution (Captain / Council / Sentinel placement)

Operator picks Option A (stay Spark 2 permanent), Option B (dedicated spark), or Option C (per-division replicas). Decision encoded in `_architectural-decisions.md`. Migration plan written for the chosen option.

### Stage 4 — Spark 4 destination

Operator picks: Acquisitions or Wealth gets Spark 4. The other waits.

### Stage 5 — Spark 2 sheds tenant duties

Once Stages 1-4 land, Spark 2 returns to single-purpose CROG-VRS hosting. Resource budget recovers. The "double-duty" warning in the current-state diagram resolves.

---

## Cross-references

- [`cross-division/_architectural-decisions.md`](cross-division/_architectural-decisions.md) — ADR-001 (locked: one spark per division) + ADR-002 (open: shared services)
- [`shared/infrastructure.md`](shared/infrastructure.md) — Spark allocation table + migration milestones
- [`divisions/financial.md`](divisions/financial.md) — Spark 3 target details + open questions
- [`divisions/market-club.md`](divisions/market-club.md) — Spark 3 cutover blocked on operator answers (6 questions)
- [`fortress_atlas.yaml`](../../fortress_atlas.yaml) — runtime sector routing (currently spark-agnostic; future amendment may add per-sector spark allocation)
