# Fortress Prime System Map

Last updated: 2026-04-26 (architecture foundation PR)

## ASCII layout

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
                  │                                      │
                  │         Cloudflare Tunnel            │
                  │         (only authorized ingress)    │
                  ▼                                      ▼
        ╔═══════════════════════════════════════════════════════════╗
        ║              FastAPI :8000 (DGX Spark-2)                  ║
        ║              backend/api/* + backend/services/*           ║
        ╚════╤═══════════════╤═══════════════╤════════════╤═════════╝
             │               │               │            │
   ┌─────────▼────┐  ┌───────▼─────┐  ┌──────▼────┐  ┌────▼────────┐
   │ DIVISIONS    │  │ SHARED SVCS │  │ DATA      │  │ EXTERNAL    │
   │              │  │             │  │ STORES    │  │ INTEGRATIONS│
   │ ✓ legal      │  │ Captain     │  │ Postgres  │  │ Stripe      │
   │ ✓ crog-vrs   │  │ Council     │  │ ─prod     │  │ Twilio      │
   │ ✓ master-acc │  │ Sentinel    │  │ ─db       │  │ Streamline  │
   │ ☐ acquisitions│  │ Privilege   │  │ ─shadow   │  │ Channex     │
   │ ☐ market-club │  │  classifier │  │ ─shadow_t │  │ IMAP cPanel │
   │ ☐ wealth     │  │ Auth/JWT    │  │ Qdrant    │  │ QuickBooks  │
   │              │  │ MCP         │  │ Redis     │  │ Plaid       │
   └──────────────┘  └─────────────┘  │ NAS       │  └─────────────┘
                                      │  (NFS)    │
                                      └───────────┘
                                            │
                          ┌─────────────────▼────────────────┐
                          │  AI INFERENCE (DEFCON modes)     │
                          │  ─SWARM     Ollama qwen2.5:7b   │
                          │  ─BRAIN     NIM Nemotron 49B    │
                          │  ─TITAN     DeepSeek-R1 671B    │
                          │  ─ARCHITECT Gemini (planning)   │
                          └──────────────────────────────────┘
```

## Connection legend

| Edge | Description |
|---|---|
| Storefront → Tunnel → FastAPI | Public guest traffic. Booking, listings, content. **No DB driver in the frontend.** |
| Command-center → Tunnel → FastAPI | Internal staff + AI agent traffic. Vault, Council, deliberation, dashboards. |
| FastAPI → Postgres | All four DBs. `fortress_prod` (canonical), `fortress_db` (operational legal target via `LegacySession`), `fortress_shadow` (runtime VRS via `AsyncSessionLocal`), `fortress_shadow_test` (CI). |
| FastAPI → Qdrant | Vector retrieval. Multiple collections: `legal_ediscovery`, `legal_privileged_communications`, `fortress_knowledge`, `email_embeddings`, etc. |
| FastAPI → Redis | Pub/sub for ARQ background workers + transient state. |
| FastAPI → NAS (`/mnt/fortress_nas`) | Document store: `/legal_vault/`, `/Corporate_Legal/`, `/audits/`, `/Financial_Ledger/`, `/Business_Prime/`, etc. |
| FastAPI → AI Inference | DEFCON-tiered: SWARM for routing/light tasks, BRAIN for sovereign reasoning, TITAN for deep legal/finance work, ARCHITECT (Gemini) for planning. Per Constitution: planning may use cloud, sovereign reasoning must stay local. |
| Captain → IMAP → Email DB | Inbound email capture from cPanel mailboxes (`gary@garyknight.com`, `gary@cabin-rentals-of-georgia.com`, `info@cabin-rentals-of-georgia.com`). |
| Sentinel → NAS → Qdrant | Crawls NAS folders, embeds, writes to `fortress_knowledge`. Sentinel-owned (do not write into `fortress_knowledge` from other code paths). |

## Division ownership of data flow

| From | To | Owned by |
|---|---|---|
| Storefront → bookings, listings, guest content | crog-vrs |
| Stripe webhooks → trust ledger | master-accounting |
| IMAP → email_archive / email_embeddings → division-routed | shared (Captain) → division (legal/crog/etc.) |
| Council deliberation → frozen context → personas | shared (Council) |
| NAS document → Qdrant chunks | shared (Sentinel for `fortress_knowledge`; per-division for `legal_*`) |
| Vault upload → privilege classifier → vault row + chunks | fortress-legal |
| Property listing → Channex egress | crog-vrs |

## Cross-references

- [`fortress_atlas.yaml`](../../fortress_atlas.yaml) — runtime division config (Sectors 01–05; this map mirrors that taxonomy)
- [`shared/infrastructure.md`](shared/infrastructure.md) — DGX cluster topology, GPU memory budget, network layout
- [`shared/postgres-schemas.md`](shared/postgres-schemas.md) — every Postgres DB, every schema, every key table
- [`shared/qdrant-collections.md`](shared/qdrant-collections.md) — every Qdrant collection, owner, populator
