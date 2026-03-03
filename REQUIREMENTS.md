# TECHNICAL REQUIREMENTS

**Fortress Prime | CROG-Fortress-AI Ecosystem**
**Effective: 2026-02-13 | Classification: Non-Negotiable Specifications**
**Governing Document: [CONSTITUTION.md](./CONSTITUTION.md)**

---

## System Requirements & Infrastructure (Summary)

- **Control Node:** Windows PC, 32GB DDR5 RAM (Permitted tasks: IDE control, deep codebase indexing, linting, and context mapping).
- **Storage Vault:** Synology DS1825 NAS (Permitted tasks: High-speed I/O for SQL schemas, vector databases, and ledger backups).
- **Compute Engine:** Multi-node DGX Spark Cluster (Permitted tasks: Local LLM execution, vision processing, heavy data pipelines).

## Core Modules

| Module | Name | Domain |
|--------|------|--------|
| CF-01  | GuardianOps | Vision / Security |
| CF-02  | QuantRevenue | Pricing / Market API |
| CF-03  | CounselorCRM | Legal / Guest RAG |
| CF-04  | AuditLedger | Financial Core |

---

## 1. Hardware & Networking

### 1.1 Compute Fleet (DGX Spark Cluster)

| Node       | Hostname  | Management IP  | Fabric IP (RoCEv2) | GPU            | RAM   | Role                              |
|------------|-----------|----------------|---------------------|----------------|-------|-----------------------------------|
| Spark-01   | Captain   | 192.168.0.100  | 10.10.10.2          | GB10 Blackwell | 128GB | Swarm Manager, Postgres, Qdrant, Nginx LB |
| Spark-02   | Muscle    | 192.168.0.104  | 10.10.10.1          | GB10 Blackwell | 128GB | NIM worker, Swarm Worker          |
| Spark-03   | Ocular    | 192.168.0.105  | 10.10.10.3          | GB10 Blackwell | 128GB | NIM worker, Swarm Worker, Vision  |
| Spark-04   | Sovereign | 192.168.0.106  | 10.10.10.4          | GB10 Blackwell | 128GB | NIM worker, Swarm Worker          |

**Total Unified Memory:** 512 GB (128 GB per node, GB10 Blackwell unified architecture).

### 1.2 Interconnect Fabric

| Network        | Subnet          | Speed            | Protocol   | MTU  | Purpose                           |
|----------------|-----------------|------------------|------------|------|-----------------------------------|
| Management LAN | 192.168.0.x/24  | 1 GbE            | Ethernet   | 1500 | SSH, Docker Swarm, web dashboards |
| Fabric-A       | 10.10.10.x/24   | 200 Gb/sec NDR   | RoCEv2     | 9000 | Model sharding, RPC, NCCL         |
| Fabric-B       | 192.168.2.x/24  | 200 Gb/sec NDR   | RoCEv2     | 9000 | Captain <-> Muscle direct link    |

**Interconnect Switch:** 400GbE MikroTik CRS518-16XS-2XQ (or equivalent) utilizing
RDMA (Remote Direct Memory Access) for zero-copy data transfer between Spark nodes.

**Requirement:** All compute-path communication (inference, RPC, model sharding) MUST
use the 10.10.10.x fabric subnet. Management LAN IPs (192.168.0.x) are forbidden
for inference traffic.

### 1.3 Storage

| Component       | Hardware          | Mount Point              | Protocol       | Capacity |
|-----------------|-------------------|--------------------------|----------------|----------|
| Synology NAS    | DS1825            | `/mnt/fortress_nas`      | NVMe-oF / NFS  | 48 TB    |
| Model Storage   | NAS (SSD tier)    | `/mnt/fortress_nas/nim_cache/` | NVMe-oF  | 2 TB     |
| Golden Snapshots| NAS (RAID6)       | `/mnt/fortress_nas/backups/`| NFS          | 4 TB     |

**NVMe-over-Fabrics (NVMe-oF):** The NAS MUST be mounted via NVMe-oF to all 4 Spark
nodes for near-wire-speed model weight loading. This is critical for TITAN mode, where
404 GB of DeepSeek-R1 shards must stream from NAS into distributed RAM across 4 nodes.

**Fallback:** If NVMe-oF is unavailable, NFS v4.1 over the management LAN is acceptable
for non-model data (backups, documents, email archives). Model weights MUST use high-speed
mount.

### 1.4 VRAM / Memory Allocation

#### SWARM Mode (DEFCON 5 — Production)

| Node     | NIM Model Profile                     | Embedding Service | System Reserve |
|----------|---------------------------------------|-------------------|----------------|
| All 4    | `nvcr.io/nim/nvidia/nv-embedqa-e5-v5` | NIM embeddings    | ~8 GB          |
| Captain  | + Postgres, Qdrant, Nginx             |                   | ~16 GB         |

#### TITAN Mode (DEFCON 1 — Strategic)

| Resource              | Allocation                  | Notes                          |
|-----------------------|-----------------------------|--------------------------------|
| DeepSeek-R1-671B      | 377 GB (Q4_K_M, 9 shards)  | Distributed across 4 nodes     |
| KV Cache              | 83 GB minimum               | For 8192 token context window  |
| System/OS Reserve     | ~52 GB total (13 GB/node)   | Docker, OS, monitoring         |
| **Total Required**    | **~460 GB**                 | Of 512 GB available            |

**Hard Rule:** SWARM and TITAN modes are mutually exclusive. They compete for the same
128 GB unified memory per node. Controlled exclusively via `switch_defcon.sh`.

### 1.5 Compute Runtime Prerequisites (Non-Negotiable)

1. `NGC_API_KEY` MUST be set for all DGX deployments; orchestration fails closed if missing.
2. Every DGX node MUST provide NAS cache mount `/mnt/fortress_nas/nim_cache` and every NIM container MUST mount it at `/opt/nim/.cache`.
3. Production DGX networking baseline is Docker bridge mode with explicit port mappings (for example `8000:8000`).
4. Production compose files MUST pin NVIDIA NIM images by immutable SHA digest; `:latest` is forbidden.
5. All DGX Spark nodes are ARM platforms (`aarch64`/`linux/arm64`). Docker images, NIM artifacts, and binaries MUST be ARM64-compatible; AMD64/x86 artifacts are forbidden.
6. Before allowing Docker compute services to start, the NUC orchestrator MUST verify Synology NAS is actively mounted at OS level (`findmnt -T /mnt/fortress_nas`) as a remote share. Local-directory fallback on `/dev/nvme*` is forbidden.

---

## 2. Integration & Routing

### 2.1 Edge Gateway (Cloudflare)

```
Internet --> Cloudflare Worker (api.crog-ai.com)
                |
                |--> JWT Auth (validate token)
                |--> Rate Limiting (per API key)
                |--> Cloudflare Tunnel --> Local Cluster (Captain:80)
                        |
                        |--> Nginx LB --> NVIDIA NIM (SWARM mode)
                        |--> Nginx LB --> NVIDIA NIM (HYDRA/TITAN profiles)
```

**Cloudflare Worker at `api.crog-ai.com`:**
- Handles ALL ingress traffic from external consumers.
- Performs JWT authentication before tunneling to the local cluster.
- Strips PII from request logs (Constitution Article I compliance).
- Rate limits: 100 req/min per API key (default), configurable per consumer.

**Security Model:**
- External developers receive an **API Key**, NOT cluster credentials.
- All public endpoints serve "Finished Intelligence" — derived data, never raw records.
- The Cloudflare Tunnel is the ONLY authorized ingress path from the public internet.

### 2.2 Hybrid Control Plane (Brain Trust + Local Execution)

| Call Type       | Route                              | Engine           | Use Case                    |
|-----------------|-------------------------------------|------------------|-----------------------------|
| External (strategy) | Google AI Studio API            | Gemini (non-sensitive only) | Architecture and planning directives |
| External (strategy) | Anthropic API                   | Opus/Sonnet (non-sensitive only) | Legal strategy drafting and review directives |
| External (strategy) | xAI API                         | Grok (non-sensitive only) | Strategic analysis directives |
| External (strategy) | OpenAI API                      | GPT-family (non-sensitive only) | Orchestration and code-generation directives |
| Internal (fast) | Nginx LB (192.168.0.100:80)        | NVIDIA NIM SWARM | Email classification, vectorization, ops |
| Internal (deep) | Fabric (10.10.10.2:8080)           | NVIDIA NIM HYDRA/TITAN | Contract review, legal, strategy |
| Embedding       | Nginx LB (192.168.0.100/api/embeddings) | NVIDIA NIM embedding profile | Vector search, semantic indexing |

**One-way control-plane boundary (mandatory):**
- External APIs are authorized to provide strategic directives to local systems.
- Local systems MUST NOT send sensitive, proprietary, or un-anonymized legal/financial/PII data to external APIs.
- Sensitive execution, synthesis, and runtime decisions remain local on NVIDIA NIM.
- Outbound API egress from the NUC orchestrator is explicitly allowed for Master Architect directive retrieval and planning.

**Routing Logic (code pattern):**

```python
import os
from openai import OpenAI

DEFCON = os.getenv("FORTRESS_DEFCON", "SWARM")

if DEFCON == "TITAN":
    # Deep reasoning — local R1 on fabric
    client = OpenAI(base_url="http://10.10.10.2:8080/v1", api_key="not-needed")
    model = "deepseek-r1"
elif DEFCON == "ARCHITECT":
    # Strategic planning — Google AI Studio (no PII payloads!)
    client = OpenAI(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=os.getenv("GOOGLE_AI_API_KEY"),
    )
    model = "gemini-2.5-pro"
else:
    # Production ops — local NVIDIA NIM swarm
    client = OpenAI(base_url="http://192.168.0.100/v1", api_key="not-needed")
    model = "nv-embedqa-e5-v5"
```

### 2.3 Service Mesh

| Service         | Host (SWARM)           | Host (TITAN)           | Port  | Protocol |
|-----------------|------------------------|------------------------|-------|----------|
| PostgreSQL      | Captain (192.168.0.100)| Captain (192.168.0.100)| 5432  | TCP      |
| Qdrant          | Captain (192.168.0.100)| (stopped)              | 6333  | HTTP     |
| Redis           | Captain (192.168.0.100)| (stopped)              | 6379  | TCP      |
| Nginx LB        | Captain (192.168.0.100)| Captain (192.168.0.100)| 80    | HTTP     |
| NIM SWARM API   | All nodes (:8000)      | (stopped)              | 8000  | HTTP     |
| NIM HYDRA API   | (stopped)              | Captain (10.10.10.2)   | 8080  | HTTP     |
| RPC Server      | (stopped)              | All nodes (10.10.10.x) | 50052 | RPC      |

---

## 2.4 CROG-VRS Service Architecture

CROG-VRS is the enterprise vacation rental management platform that replaces
Streamline VRS via the Strangler Fig pattern. It runs as three services behind
the nginx reverse proxy.

### 2.4.1 Service Topology

```
Internet → Cloudflare Tunnel → Nginx (Captain:80/443)
                                  │
                    ┌─────────────┼──────────────┐
                    ▼             ▼              ▼
              Command Center  VRS Backend   Next.js Frontend
              (port 9800)    (port 8100)    (port 3001)
              master_console   FastAPI       [internal only]
              .py             run.py
                    │             ▲
                    └─────────────┘
                   /api/vrs/* proxy
```

| Service            | Port | Process                | Serves                          |
|--------------------|------|------------------------|---------------------------------|
| **Command Center** | 9800 | `tools/master_console.py` | HTML pages, auth, API proxy  |
| **VRS Backend**    | 8100 | `fortress-guest-platform/run.py` | REST API, DB, integrations |
| **VRS Frontend**   | 3001 | `frontend-next` (Next.js) | Internal/development only    |

**Routing Rule:** Users access the VRS exclusively through the Command Center
(port 9800 → nginx port 80/443). The VRS Backend (8100) and Next.js Frontend
(3001) are internal services — NEVER exposed directly to users via nav links
or redirects.

### 2.4.2 Command Center Pages (Production UI)

Every VRS page is a self-contained HTML file in `tools/`. No build step required.

| Page               | File                       | Route               | API Dependencies              |
|--------------------|----------------------------|----------------------|-------------------------------|
| VRS Full Dashboard | `vrs_hub.html`             | `/vrs`               | properties, reservations, arrivals, departures, guests, messages |
| Properties         | `vrs_properties.html`      | `/vrs/properties`    | `/api/vrs/properties`         |
| Reservations       | `vrs_reservations.html`    | `/vrs/reservations`  | `/api/vrs/reservations`, damage-claims |
| Guests             | `vrs_guests.html`          | `/vrs/guests`        | `/api/vrs/guests`             |
| Work Orders        | `vrs_work_orders.html`     | `/vrs/work-orders`   | `/api/vrs/workorders`         |
| Contracts          | `vrs_contracts.html`       | `/vrs/contracts`     | `/api/vrs/agreements`         |
| Analytics          | `vrs_analytics.html`       | `/vrs/analytics`     | `/api/vrs/analytics/dashboard` |
| Payments           | `vrs_payments.html`        | `/vrs/payments`      | `/api/vrs/payments/*`, reservations |
| Utilities          | `vrs_utilities.html`       | `/vrs/utilities`     | `/api/vrs/utilities/*`, properties |
| Channels           | `vrs_channels.html`        | `/vrs/channels`      | `/api/vrs/reservations` (derived) |
| Owners             | `vrs_owners.html`          | `/vrs/owners`        | properties, reservations (derived) |
| Direct Booking     | `vrs_direct_booking.html`  | `/vrs/direct-booking`| properties, reservations (derived) |
| IoT & Smart Home   | `vrs_iot.html`             | `/vrs/iot`           | properties (localStorage for devices) |
| Guest Agent        | `guest_agent.html`         | `/guest-agent`       | `/api/vrs/agent/*`, messages  |

### 2.4.3 API Proxy Chain

The Command Center proxies all VRS API requests to the backend. Browser JS calls
the Command Center; the Command Center calls the backend.

```
Browser JS                Command Center              VRS Backend
─────────                 ──────────────              ───────────
fetch('/api/vrs/properties')  ──►  _vrs_get('/api/properties/')  ──►  GET :8100/api/properties/
     {credentials:'include'}         adds auth check                    returns JSON
```

**Proxy routes in `master_console.py`:**

| Command Center Route                    | Backend Target                        |
|-----------------------------------------|---------------------------------------|
| `/api/vrs/properties`                   | `/api/properties/`                    |
| `/api/vrs/reservations`                 | `/api/reservations/`                  |
| `/api/vrs/reservations/arriving/today`  | `/api/reservations/arriving/today`    |
| `/api/vrs/reservations/departing/today` | `/api/reservations/departing/today`   |
| `/api/vrs/reservations/{id}`            | `/api/reservations/{id}`              |
| `/api/vrs/reservations/{id}/full`       | `/api/reservations/{id}/full`         |
| `/api/vrs/guests`                       | `/api/guests/`                        |
| `/api/vrs/guests/{id}`                  | `/api/guests/{id}`                    |
| `/api/vrs/guests/{id}/360`              | `/api/guests/{id}/360`                |
| `/api/vrs/workorders`                   | `/api/workorders/`                    |
| `/api/vrs/workorders/{id}`              | `/api/workorders/{id}`                |
| `/api/vrs/damage-claims/`              | `/api/damage-claims/`                 |
| `/api/vrs/damage-claims/stats`          | `/api/damage-claims/stats`            |
| `/api/vrs/agreements`                   | `/api/agreements/`                    |
| `/api/vrs/agreements/dashboard`         | `/api/agreements/dashboard`           |
| `/api/vrs/agreements/templates`         | `/api/agreements/templates`           |
| `/api/vrs/analytics/dashboard`          | `/api/analytics/dashboard`            |
| `/api/vrs/payments/config`              | `/api/payments/config`                |
| `/api/vrs/payments/reservation/{id}`    | `/api/payments/reservation/{id}`      |
| `/api/vrs/payments/create-intent`       | `/api/payments/create-intent`         |
| `/api/vrs/payments/refund`              | `/api/payments/refund`                |
| `/api/vrs/utilities/property/{id}`      | `/api/utilities/property/{id}`        |
| `/api/vrs/utilities/analytics/{id}`     | `/api/utilities/analytics/{id}`       |
| `/api/vrs/utilities/analytics/portfolio/summary` | `/api/utilities/analytics/portfolio/summary` |
| `/api/vrs/utilities/property/{id}`      | `/api/utilities/property/{id}`        |
| `/api/vrs/utilities/analytics/{id}`     | `/api/utilities/analytics/{id}`       |
| `/api/vrs/messages/stats`               | `/api/messages/stats`                 |

When adding a new VRS backend endpoint, a corresponding proxy route MUST be added
to `master_console.py` so the Command Center pages can reach it.

### 2.4.4 VRS Backend Modules

The VRS Backend (`fortress-guest-platform/backend/`) contains these modules:

| Module              | Endpoint Prefix          | Purpose                               |
|---------------------|--------------------------|---------------------------------------|
| Properties          | `/api/properties/`       | CRUD for cabins, amenities, photos    |
| Reservations        | `/api/reservations/`     | Booking lifecycle, check-in/out       |
| Booking Engine      | `/api/booking/`          | Calendar, availability, pricing       |
| Guests              | `/api/guests/`           | CRM, 360-degree profiles, loyalty     |
| Messages            | `/api/messages/`         | SMS/email, threads, auto-response     |
| Damage Claims       | `/api/damage-claims/`    | Post-stay inspections, legal drafts   |
| Work Orders         | `/api/workorders/`       | Maintenance, repairs, assignments     |
| Agreements          | `/api/agreements/`       | E-sign contracts, PDF generation      |
| Payments            | `/api/payments/`         | Stripe integration, refunds           |
| Utilities           | `/api/utilities/`        | Provider accounts, cost analytics     |
| Analytics           | `/api/analytics/`        | Revenue, occupancy, performance       |
| AI Agent            | `/api/agent/`            | Lifecycle automation, AI responses    |
| Review Queue        | `/api/review/`           | Human-in-the-loop AI review           |
| Channel Manager     | `/api/channel-manager/`  | OTA sync, iCal, rate parity           |
| Direct Booking      | `/api/direct-booking/`   | Website booking engine                |
| Owner Portal        | `/api/owner/`            | Owner statements, documents           |
| IoT                 | `/api/iot/`              | Smart locks, thermostats              |
| Auth                | `/api/auth/`             | Staff login, SSO, user management     |
| Search              | `/api/search/`           | Global search across all entities     |

### 2.4.5 Navigation Consistency Requirement

The CROG-VRS dropdown menu is defined identically across every HTML file in `tools/`.
The canonical structure is:

```
VRS Full Dashboard  →  /vrs
Properties          →  /vrs/properties
Reservations        →  /vrs/reservations
Guests              →  /vrs/guests
Work Orders         →  /vrs/work-orders
Contracts           →  /vrs/contracts
Analytics           →  /vrs/analytics
─── (separator) ───
Guest Agent         →  /guest-agent
```

**Adding a new VRS page requires ALL of the following:**
1. Create `tools/vrs_<name>.html` with the full nav bar (copy from any existing page).
2. Add a route in `master_console.py`: `@app.get("/vrs/<name>")` serving the HTML.
3. Add the nav item to the dropdown in EVERY existing HTML file in `tools/`.
4. Add API proxy routes in `master_console.py` for any backend endpoints the page needs.
5. Update this section of `REQUIREMENTS.md` with the new page entry.
6. Update the Constitution nav structure in `002-sovereign-constitution.mdc`.

### 2.4.6 Integrations

| Integration   | Protocol      | Purpose                                    | Status          |
|---------------|---------------|--------------------------------------------|-----------------|
| Streamline    | REST API      | Legacy PMS — reservation/property sync     | Active (bridge) |
| Stripe        | SDK + Webhook | Payment processing (test mode)             | Configured      |
| Twilio        | REST + Webhook| SMS guest communication                    | Active          |
| Cloudflare    | Tunnel        | Public ingress, DDoS protection            | Active          |
| OpenAI        | REST API      | AI guest responses, language detection      | Active          |

---

## 3. Development Standards

### 3.1 Frameworks & Libraries

| Framework        | Purpose                                    | Requirement Level |
|------------------|--------------------------------------------|-------------------|
| **LangGraph**    | Stateful multi-agent workflow orchestration | Required for all new agent flows |
| **Pydantic**     | Strict schema enforcement on all data models| Required for all API boundaries |
| **FastAPI**      | API gateway and internal service endpoints  | Required for new HTTP services |
| **SQLAlchemy**   | Database ORM with Alembic migrations        | Required for schema changes |
| **OpenAI SDK**   | Unified inference client (mode-aware)       | Required for all LLM calls |
| **Qdrant Client**| Vector search with division filtering       | Required for RAG pipelines |

**Dependency Management:** All packages MUST be declared in `requirements.txt` with
rationale comments. No ad-hoc `pip install` commands.

### 3.2 Migration Pattern: Strangler Fig

All new features MUST be built as independent agents that progressively replace
("strangle") legacy Streamline VRS functionality:

```
                    +-----------------------+
                    |   Cloudflare Edge     |
                    |   (api.crog-ai.com)   |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |   Fortress API        |
                    |   Gateway (FastAPI)   |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |   Feature Router      |
                    +-+---+---+---+---+---+-+
                      |   |   |   |   |   |
                      v   v   v   v   v   v
                    [New] [New] [New] [Legacy] [Legacy] [Legacy]
                    Agent Agent Agent  VRS      VRS      VRS
                                       |        |        |
                                    (Streamline PHP SDK)
```

**Rules:**
1. New agents are built in Python (FastAPI + LangGraph + Pydantic).
2. Each agent owns ONE capability (pricing, availability, guest comms, etc.).
3. The Feature Router directs traffic to the new agent OR the legacy bridge
   (`src/bridges/streamline_legacy_connect.py`) based on a feature flag in `config.py`.
4. Legacy endpoints are decommissioned only after the new agent passes acceptance tests
   AND runs in parallel for 2 weeks without regressions.
5. The Streamline bridge code is NEVER modified to add new features — only new agents
   absorb new requirements.

### 3.3 Code Quality Standards

**Config-Driven Topology:**
All node IPs, ports, model assignments, and fabric routes MUST be defined in
`config.py` (via environment variables). Never hardcode cluster addresses.

**GPU Health Check:**
Every script that performs inference MUST check GPU temperature before submitting
work. Abort if temperature exceeds 85C. Pattern defined in
`.cursor/rules/001-titan-protocol.mdc`.

**Traffic Control:**
All ingestion scripts MUST check `config.SENDER_BLOCKLIST` before processing.
All ingestion flows MUST pass through the sender registry (Postgres) for
classification and routing.

**Database as Truth:**
Business logic belongs in Postgres (`fortress_db`) or the Sovereign prompt, not
hardcoded Python regex. Schema changes require Alembic migrations.

**Sector Awareness:**
Before building any tool, agent, or data pipeline, consult `fortress_atlas.yaml`.
New sectors must be registered in the atlas BEFORE code is written (see
`.cursor/rules/001-titan-protocol.mdc`, Sector Expansion Workflow).

### 3.4 Pydantic Schema Enforcement

All data crossing module boundaries MUST use Pydantic models:

```python
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional

class MarketSignal(BaseModel):
    """Schema for hedge_fund.market_signals rows."""
    ticker: str = Field(..., min_length=2, max_length=10)
    price: float = Field(..., gt=0, le=100_000)
    confidence: float = Field(..., ge=0, le=1)
    source: str
    extracted_at: datetime
    sector: str = Field(default="comp")

    @field_validator("ticker")
    @classmethod
    def ticker_uppercase(cls, v: str) -> str:
        return v.upper().strip()

class GuestLead(BaseModel):
    """Schema for public.guest_leads rows — PII-bearing, never cloud."""
    name: str = Field(..., min_length=1)
    email: Optional[str] = None
    phone: Optional[str] = None
    property_id: int
    source: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 3.5 LangGraph Agent Pattern

All new multi-step agent workflows MUST use LangGraph for state management:

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    sector: str
    query: str
    context: list[str]
    response: str
    confidence: float
    audit_trail: list[str]

def route_to_sector(state: AgentState) -> str:
    """Route based on fortress_atlas.yaml keyword hints."""
    # Load atlas, match keywords, return sector slug
    ...

def invoke_inference(state: AgentState) -> AgentState:
    """Call the appropriate model based on DEFCON level."""
    # Use mode-aware client from Section 2.2
    ...

def write_audit(state: AgentState) -> AgentState:
    """Persist decision to Audit Ledger (Constitution Article III)."""
    ...

# Build the graph
graph = StateGraph(AgentState)
graph.add_node("route", route_to_sector)
graph.add_node("infer", invoke_inference)
graph.add_node("audit", write_audit)
graph.add_edge("route", "infer")
graph.add_edge("infer", "audit")
graph.add_edge("audit", END)
graph.set_entry_point("route")

agent = graph.compile()
```

---

## 4. Testing & Observability

### 4.1 Health Checks

| Check                  | Frequency | Tool                      | Alert Threshold        |
|------------------------|-----------|---------------------------|------------------------|
| GPU Temperature        | 60s       | pynvml                    | > 85C                 |
| Postgres Disk          | 300s      | `pg_stat_database`        | > 90% usage           |
| NAS Mount              | 60s       | `mountpoint -q`           | Unmounted              |
| Qdrant Collections     | 300s      | Qdrant REST API           | 0 vectors              |
| Watchdog Heartbeat     | 30s       | `fortress-watchdog`       | Container unhealthy    |
| Fabric Latency         | 300s      | `ping -c 3 10.10.10.x`   | > 1ms avg              |

### 4.2 Audit Trail Requirements

Every autonomous action must produce an audit record containing:
- Timestamp (UTC)
- Agent identity (which AI or script)
- Sector context (from `fortress_atlas.yaml`)
- Action taken
- Data touched (table, row count)
- Outcome (success / failure / escalated)

### 4.3 Acceptance Test Gates

Before any new agent replaces a legacy Streamline function:
1. Unit tests covering all Pydantic models (schema validation).
2. Integration test against `fortress_db` test schema.
3. 2-week parallel run with legacy, comparing outputs.
4. Human sign-off on the comparison report.

### 4.4 CROG-VRS UI Testing Requirements

Every VRS page MUST pass these checks before it is considered complete:

| Check                                    | Method                                     |
|------------------------------------------|--------------------------------------------|
| Page loads without JS errors             | Browser console — zero errors              |
| All nav dropdown items are present       | Verify 8 items in CROG-VRS dropdown        |
| Every KPI card is clickable              | Click → navigates to detail view           |
| Every table row is clickable/expandable  | Click → shows detail or expands inline     |
| Every button performs its action         | Click → API call fires, feedback appears   |
| API proxy returns real data              | `curl /api/vrs/*` returns JSON, not error  |
| Filter/search controls work             | Apply filter → table updates               |
| Page handles empty state gracefully      | Zero records → shows "No data" message     |
| Page handles API failure gracefully      | Backend down → shows error, no crash       |
| URL query params are respected           | `?filter=arriving` pre-filters on load     |
| Auth redirect works                      | Unauthenticated → 302 to `/login`          |

**Testing Protocol:** Do NOT rely solely on `curl` or API-level testing. The final
verification MUST be a click-through in an actual browser. If a link does not work
when you click it, it is not done.

---

## 5. Security Requirements

### 5.1 Network Segmentation

- **Management LAN (192.168.0.x):** SSH, Docker Swarm control plane, dashboards.
- **Fabric LAN (10.10.10.x):** Compute only. No SSH, no web dashboards.
- **Public ingress:** Cloudflare Tunnel ONLY. No direct port exposure.

### 5.2 Credential Management

- All secrets in `.env` files (gitignored) or Docker secrets.
- No credentials in source code, commit history, or log output.
- API keys for external developers: rotated quarterly, scoped to specific endpoints.
- Streamline VRS tokens: stored in `.env`, accessed via `config.py`.

### 5.3 Data Classification

| Classification | Examples                          | Cloud OK? | Encryption Required? |
|---------------|-----------------------------------|-----------|---------------------|
| SOVEREIGN     | Financial ledgers, legal docs     | Never     | At rest + transit   |
| RESTRICTED    | Guest PII, email archive          | Never     | At rest + transit   |
| INTERNAL      | Market signals, agent outputs     | Never     | Transit only        |
| PUBLIC        | API responses, marketing content  | Yes       | Transit only        |

---

## 6. Fortress Guest Platform (FGP) Requirements

### 6.1 Architecture

- **Backend:** FastAPI + SQLAlchemy (async) on Python 3.12, port 8100
- **Frontend:** Next.js 14 (App Router) + shadcn/ui + Tailwind CSS, port 3001
- **Database:** PostgreSQL 16 (`fortress_guest`), 32+ tables, UUID primary keys
- **PMS Integration:** Streamline VRS JSON-RPC API (9-phase sync engine, 5-min cycle)
- **AI Legal Drafting:** HYDRA → SWARM → OpenAI fallback chain

### 6.2 Data Requirements

| Data Category | Source | Records | Sync Frequency |
|--------------|--------|---------|----------------|
| Properties | Streamline `GetPropertyList` + `GetPropertyInfo` | 14 | Every 5 min |
| Reservations | Streamline `GetReservations` (return_full:true) | 2,650+ | Every 5 min |
| Financial Detail | Streamline `GetReservationPrice` | 391+ enriched | Every 5 min (new only) |
| Staff Notes | Streamline `GetReservationNotes` | 494 with notes | Every 5 min (new only) |
| Rental Agreements | Streamline docs + template generation | 2,141 | Every 5 min (missing only) |
| Owner Balances | Streamline `GetUnitOwnerBalance` | 14 (all properties) | Every 5 min |
| Housekeeping | Streamline `GetHousekeepingCleaningReport` | 16+ tasks | Every 5 min |
| Guest Feedback | Streamline `GetAllFeedback` | 19+ reviews | Every 5 min (new only) |
| Work Orders | Streamline `GetWorkOrders` | Maintenance tickets | Every 5 min |

### 6.3 API Requirements

- 26+ REST endpoints across 3 routers (damage claims, integrations, owner portal)
- All mutation endpoints return the updated object
- All list endpoints support pagination (default 50, max 200)
- Error responses follow RFC 7807 format
- Rate limiting: 200 GET/min, 50 POST/min, 5 sync/min
- Authentication required on all endpoints except health checks

### 6.4 Financial Requirements

- Trust accounting compliance per Georgia O.C.G.A. § 43-40-20
- Owner fund segregation (owner funds, operating funds, escrow, security deposits)
- All financial columns use DECIMAL(12,2) — never FLOAT
- Financial records retained 7 years (IRS audit requirement)
- Owner balance reconciliation against Streamline (daily, automated)
- Monthly statement generation and comparison

### 6.5 Security Requirements

- RBAC with 5 roles: operator, admin, manager, agent, viewer
- JWT authentication (24-hour expiry, HttpOnly cookies in production)
- PII handling: minimum collection, redacted from logs, deletion on request
- Secrets in `.env` only, never in source code or database
- Streamline API credentials auto-renewed via `RenewExpiredToken`

### 6.6 Testing Requirements

- Unit test coverage: ≥80% on business logic
- Integration tests: 100% of mutation endpoints
- Contract tests: 100% of Streamline sync phase methods
- Smoke tests: Run after every deployment
- Test database: `fortress_guest_test` (never production)
- Coverage evidence artifact required: `coverage.xml` from CI or local gate command

### 6.7 Governance Documents

| Document | Location | Scope |
|----------|----------|-------|
| FGP Constitution | `.cursor/rules/005-fortress-guest-platform.mdc` | Schema, sync engine, API registry, AI drafting |
| Security & Compliance | `.cursor/rules/006-security-compliance.mdc` | RBAC, secrets, PII, audit, incident response |
| Financial Governance | `.cursor/rules/007-financial-data-governance.mdc` | Trust accounting, reconciliation, tax compliance |
| API Standards | `.cursor/rules/008-api-integration-standards.mdc` | Versioning, error codes, rate limiting, contracts |
| Testing Protocol | `.cursor/rules/009-testing-deployment.mdc` | Test categories, coverage, deployment checklist |

---

*End of Technical Requirements. All specifications are binding per the
[Sovereign Constitution](./CONSTITUTION.md) and the Fortress Guest Platform
Constitution (Amendment VII, effective 2026-02-20).*
