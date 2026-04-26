# Shared: Infrastructure

Last updated: 2026-04-26

## Technical overview

Fortress Prime runs on a local NVIDIA DGX Spark cluster (4 nodes). No cloud databases for sovereign data; transient cloud inference is allowed only for non-PII payloads with ephemeral guarantees per CONSTITUTION.md Article I.

### Cluster topology — division allocation (per [ADR-001](../cross-division/_architectural-decisions.md))

The 2026-04-26 architectural decision: **one spark per division.** Cross-division services (Captain / Council / Sentinel) placement is OPEN per ADR-002.

| Spark | Network | Status | Division | Role / what's hosted today |
|---|---|---|---|---|
| **Spark 1** | `192.168.0.X` | **ACTIVE** | Fortress Legal | Legal email intake, vault ingestion, privileged communications, Council legal retrieval. Also TITAN tier inference (DeepSeek-R1 671B local) + BRAIN tier (NIM Nemotron 49B). |
| **Spark 2** | `192.168.0.100` (control plane @ `100.80.122.100`); hostname `spark-2` / `spark-node-2` | **ACTIVE** | CROG-VRS — currently double-duty as **temporary Financial host** (Market Club replacement scaffolding) until Spark 3 provisions; **temporary control plane** (Captain / Council / Sentinel) per ADR-002 OPEN | All Postgres DBs (`fortress_prod`, `fortress_db`, `fortress_shadow`, `fortress_shadow_test`), Qdrant (legal collections), NAS mount, Redis, ARQ, FastAPI for storefront + command-center, cron infra. SWARM tier inference (qwen2.5:7b on Ollama). |
| **Spark 3** | TBD | **PLANNED — not yet provisioned** | Financial (Master Accounting + Market Club replacement) | Will host: `division_a.*`, `hedge_fund.*` schema (migrated from Spark 2), Market Club scoring engine, accounting services, all financial intelligence. Migration plan blocked on provisioning timeline (see ADR-002 + `divisions/financial.md`). |
| **Spark 4** | TBD | **PLANNED — not yet provisioned** | TBD; likely **Acquisitions** OR **Wealth** | Operator decides which division ramps first. Current `crog` tmux + Track B migration scratch space lives on `spark-4` informally today, but that's a transient state not a division allocation. |

### Migration milestones still to schedule

1. Spark 3 hardware acquired and provisioned
2. `hedge_fund.*` schema migration from Spark 2 → Spark 3 (with dual-write window per Issue-209 lessons learned)
3. ADR-002 resolved → Captain / Council / Sentinel placement decision
4. Spark 4 destination (Acquisitions vs Wealth) confirmed
5. CROG-VRS sheds its tenant duties (Spark 2 becomes single-purpose)

### AI inference tiers ("DEFCON modes")

| Tier | Service | Model | Use |
|---|---|---|---|
| DEFCON 5 — SWARM | Ollama LB | qwen2.5:7b on Spark-02 | Fast routing, guest comms, light classification |
| DEFCON 3 — BRAIN | `fortress-nim-brain.service` on spark-1 | `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` via NIM (vLLM backend, port 8100, 32k context) | Tier-2 sovereign reasoning |
| DEFCON 1 — TITAN | DeepSeek-R1 671B local on spark-1 (llama.cpp RPC) | DeepSeek-R1 | Deep reasoning: legal, finance |
| ARCHITECT | Google Gemini (cloud, planning only) | Gemini 2.5+ | Strategic planning. Never PII / sovereign data. |

⚠️ As of 2026-04-23: BRAIN service uses ≥99% of spark-1's 121 GiB unified memory after load. Track B workload migration (Qdrant, fortress-event-console / redpanda, RAG retriever, chromadb, open-webui → spark-4) is required before BRAIN can carry production traffic at the ≥15% headroom rule.

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
