# Shared: Infrastructure

Last updated: 2026-04-26

## Technical overview

Fortress Prime runs on a local NVIDIA DGX Spark cluster (4 nodes). No cloud databases for sovereign data; transient cloud inference is allowed only for non-PII payloads with ephemeral guarantees per CONSTITUTION.md Article I.

### Cluster topology — app + dedicated inference cluster (per [ADR-001 amended](../cross-division/_architectural-decisions.md) + [ADR-002 amended](../cross-division/_architectural-decisions.md) + [ADR-003 (2026-04-29) LOCKED](../cross-division/_architectural-decisions.md))

The 2026-04-29 architectural decisions:
- **ADR-001 (LOCKED 2026-04-26, amended 2026-04-29):** one spark per *app* division. Inference is a shared cross-division resource on a dedicated cluster (Sparks 4/5/6) per ADR-003. Acquisitions + Wealth co-tenant on Spark-3 with Financial until Spark-7+ lands.
- **ADR-002 (LOCKED 2026-04-26, amended 2026-04-29):** Captain + Council + Sentinel all stay on Spark 2 permanent (control plane). The previous Council → Spark-4 Option B decision is reversed by ADR-003 (2026-04-29); Spark-4 becomes an inference-tier node, not a Council host.
- **ADR-003 (LOCKED 2026-04-29):** Sparks 4/5/6 form a dedicated inference cluster. No division apps tenant on these nodes. All BRAIN-tier and TITAN-tier inference traffic terminates on the 4/5/6 cluster via the LiteLLM gateway on spark-2. Phase 3 sizing locked: **Pattern 1 — TP=2 + 1 hot replica**.

| Spark | Network | Status | Role | Tenants |
|---|---|---|---|---|
| **Spark 1** | `192.168.0.X` | **ACTIVE** | App | Fortress Legal — vault ingestion, privileged communications, Council legal retrieval consumer. **No inference tenancy under ADR-003** (BRAIN moved to spark-5). |
| **Spark 2** | `192.168.0.100` (ctrl @ `100.80.122.100`); hostname `spark-2` / `spark-node-2` | **ACTIVE** | App + control plane | CROG-VRS, **Captain**, **Council**, **Sentinel**, Postgres, Qdrant (legal), Redis, ARQ, FastAPI, **LiteLLM gateway**. SWARM tier kept here for fast-path / degraded-mode (Ollama qwen2.5:7b + `nomic-embed-text`). |
| **Spark 3** | TBD | **PLANNED — not yet provisioned** | App | Financial (Master Accounting + Market Club replacement); **Acquisitions + Wealth co-tenants** until Spark-7+ lands. Receives `division_a.*` + `hedge_fund.*` migration from Spark 2. |
| **Spark 4** | ConnectX | **PLANNED — Phase 3** | Inference | Ray worker — joins the inference cluster at Phase 3 (software-only cutover). |
| **Spark 5** | ConnectX | **ACTIVE** | Inference | Ray head; **Nemotron-Super-49B-FP8 NIM** (current BRAIN tier; port 8100). |
| **Spark 6** | 10GbE → ConnectX (cable pending) | **STAGED — Phase 2** | Inference | Ray worker; pairs with Spark 5 for `--tensor-parallel-size 2` over NCCL/RDMA once cable lands. |

### Inference plane (per [ADR-003](../cross-division/_architectural-decisions.md))

Inference compute is **decoupled from division ownership**. Any division can consume inference from any spark via the LiteLLM proxy. This is an architectural separation between the data plane (per-division, ADR-001) and the inference plane (cluster-wide, ADR-003).

- **Router:** LiteLLM proxy on Spark 2 (already running). All LLM + embedding calls from FastAPI, ARQ workers, Captain, Council, and Sentinel route through LiteLLM rather than direct endpoint URLs.
- **Endpoints:** Each spark hosts its own embedding model (`nomic-embed-text`) + an LLM tier. Endpoints register with LiteLLM as a model pool.
- **Transport:** 100Gbps ConnectX interconnect; cross-spark inference is operationally fine.
- **Per-division accounting (ADR-003 Phase 4):** LiteLLM virtual keys per division → cost/token tracking per case_slug, deliberation, ingestion.
- **Embedding queue (ADR-003 Phase 2):** Redis-backed (Spark 2 hosts Redis); workers on each spark consume from queue; `process_vault_upload` enqueues chunks rather than blocking on synchronous embedding.

Implementation is gated work — each ADR-003 phase is its own PR with operator authorization. Today, only Spark 2 contributes to the inference plane (Ollama qwen2.5:7b + nomic). Spark 1 hosts TITAN/BRAIN for legal-only direct calls. Phase 1 multiplies endpoints across all sparks.

### Migration milestones still to schedule

1. **ADR-003 Phase 1** — LiteLLM legal-routes cutover cloud → spark-5 NIM (this PR; closes audit A-02)
2. M3 trilateral additive write (PR `feat/m3-trilateral-spark1-mirror`, default-OFF)
3. M3 activation prereq: alembic merge on spark-2 (Issue #279)
4. **ADR-003 Phase 2** — Spark-6 cable cutover (10GbE → ConnectX); Spark-5 + Spark-6 form Ray cluster running vLLM with TP=2 over NCCL/RDMA
5. Spark-3 hardware acquired and provisioned (Financial)
6. `hedge_fund.*` + `division_a.*` migration from Spark-2 → Spark-3
7. **ADR-003 Phase 3** — Spark-4 joins inference cluster (software-only cutover); Acquisitions + Wealth co-tenant on Spark-3
8. CROG-VRS sheds tenant duties (Spark-2 single-purpose control plane)

### AI inference tiers ("DEFCON modes")

These tiers consolidate on the **dedicated inference cluster (Sparks 4/5/6)** per ADR-003 (2026-04-29). The LiteLLM gateway on spark-2 routes BRAIN-tier and TITAN-tier traffic to the cluster. SWARM tier remains on spark-2 for fast-path / degraded-mode operation.

| Tier | Service | Model | Host | Use |
|---|---|---|---|---|
| DEFCON 5 — SWARM | Ollama LB | qwen2.5:7b | spark-2 | Fast routing, guest comms, light classification, degraded-mode fallback |
| DEFCON 3 — BRAIN | `fortress-nim-brain.service` (port 8100) | `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` via NIM 2.0.1 | **spark-5** (Phase 1, today); spark-5 + spark-6 TP=2 (Phase 2); 4/5/6 Pattern 1 (Phase 3) | Tier-2 sovereign reasoning; legal RAG; case briefing |
| DEFCON 1 — TITAN | DeepSeek-R1 671B local (llama.cpp RPC) | DeepSeek-R1 | TBD inference cluster placement | Deep reasoning: legal, finance |
| ARCHITECT | Google Gemini (cloud, planning only) | Gemini 2.5+ | external | Strategic planning. Never PII / sovereign data. |

### Network

- All public ingress through Cloudflare Tunnels. UFW denies all public inbound.
- Internal cluster network: 192.168.0.0/24 (LAN). Embed services typically on `192.168.0.100:11434` (Ollama), Qdrant on `192.168.0.106:6333` (VRS) and `localhost:6333` (legal).
- Storefront: `cabin-rentals-of-georgia.com`
- Command-center: `crog-ai.com`

### Storage

- NAS at `/mnt/fortress_nas/` mounted via NFS on every cluster node
- PostgreSQL 16 on `127.0.0.1:5432`, four DBs (`fortress_prod`, `fortress_db`, `fortress_shadow`, `fortress_shadow_test`) — see [`postgres-schemas.md`](postgres-schemas.md)
- Qdrant clusters: `localhost:6333` (legal collections), `192.168.0.106:6333` (VRS dual-write)
- Redis on Spark-02 for ARQ + transient state

## Consumers

- All FastAPI routers (`backend/api/*`)
- All ARQ workers (`backend/tasks/jobs.py`)
- Captain mailbox watchers
- Sentinel NAS walker
- Council deliberation
- Hermes daily auditor

## Contract / API surface

- DGX network: read-only contract — services on Spark-02 talk to Spark-01 inference via internal HTTP/RPC; no agent code may directly modify the inference services
- Cloudflare Tunnel: ingress identity = trust boundary. Internal API routes check the `Host:` header for `crog-ai.com` (command-center) before serving privileged data
- Postgres connection strings via env vars (`POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`); see [`auth-and-secrets.md`](auth-and-secrets.md)

## Where to read the code

- `deploy/systemd/` — every systemd unit + run-script (28 files)
- `fortress_atlas.yaml` — runtime cluster + sector config
- `backend/core/config.py` — Pydantic settings + DB URL resolution
- `backend/core/database.py` — async engine, `AsyncSessionLocal` (fortress_shadow target)
- `backend/services/ediscovery_agent.py::LegacySession` — fortress_db target
- `infra/`, `docker-compose.local.yml` — local dev composition

## Cross-references

- CONSTITUTION.md Article I (Data Sovereignty)
- CLAUDE.md — operator runbook for working with this codebase
- [`auth-and-secrets.md`](auth-and-secrets.md) — secrets management

Last updated: 2026-04-26
