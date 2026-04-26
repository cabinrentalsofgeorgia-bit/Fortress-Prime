# Shared: Infrastructure

Last updated: 2026-04-26

## Technical overview

Fortress Prime runs on a local NVIDIA DGX Spark cluster (4 nodes). No cloud databases for sovereign data; transient cloud inference is allowed only for non-PII payloads with ephemeral guarantees per CONSTITUTION.md Article I.

### Cluster topology — division + shared-services allocation (per [ADR-001](../cross-division/_architectural-decisions.md) + [ADR-002](../cross-division/_architectural-decisions.md))

The 2026-04-26 architectural decisions:
- **ADR-001 (LOCKED):** one spark per division (default rule).
- **ADR-002 (LOCKED):** Captain + Sentinel stay on Spark 2 permanent (control plane). Council moves to Spark 4 alongside Acquisitions + Wealth — "shared services + intermittent divisions" multi-purpose pattern, an explicit allowable exception to ADR-001.

| Spark | Network | Status | Role | What's hosted (target state) |
|---|---|---|---|---|
| **Spark 1** | `192.168.0.X` | **ACTIVE** | Single-division | Fortress Legal — vault ingestion, privileged communications, Council legal retrieval (queries Spark 4's Council post-cutover). TITAN (DeepSeek-R1 671B) + BRAIN (NIM Nemotron 49B). |
| **Spark 2** | `192.168.0.100` (ctrl @ `100.80.122.100`); hostname `spark-2` / `spark-node-2` | **ACTIVE** | Multi-purpose: division + shared services | CROG-VRS (storefront + command-center FastAPI + Postgres + Qdrant for legal collections + NAS mount + Redis + ARQ + cron) + **Captain (permanent)** + **Sentinel (permanent)** + SWARM tier inference (qwen2.5:7b on Ollama). |
| **Spark 3** | TBD | **PLANNED — not yet provisioned** | Single-division | Financial — Master Accounting + Market Club replacement scoring engine. Will receive `division_a.*` + `hedge_fund.*` migration from Spark 2. |
| **Spark 4** | TBD | **PLANNED — not yet provisioned** | Multi-purpose: shared services + intermittent divisions | **Council** (post-Spark-4 cutover from Spark 2) + Acquisitions + Wealth. Council's bursty workload + the two divisions' intermittent compute profile are compatible on one node. |

### Migration milestones still to schedule

1. Spark 3 hardware acquired and provisioned
2. `hedge_fund.*` + `division_a.*` schema migration from Spark 2 → Spark 3 (dual-write window + Issue-209 CASCADE-safety lessons)
3. Spark 4 hardware acquired and provisioned (gating dependency for Council migration + Acquisitions/Wealth ramp)
4. Council Spark 2 → Spark 4 migration (warm-spare → parallel verification week → command-center cutover → 7-day soak → Spark 2 instance retires)
5. Acquisitions division ramps on Spark 4
6. Wealth division ramps on Spark 4
7. Spark 2 sheds Financial tenant (after Spark 3 cutover) — Spark 2's permanent role is "CROG-VRS + Captain + Sentinel" multi-purpose by ADR-002 design, not transitional

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
