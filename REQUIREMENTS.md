# TECHNICAL REQUIREMENTS

**Fortress Prime | CROG-Fortress-AI Ecosystem**
**Effective: 2026-02-13 | Classification: Non-Negotiable Specifications**
**Governing Document: [CONSTITUTION.md](./CONSTITUTION.md)**

---

## 1. Hardware & Networking

### 1.1 Compute Fleet (DGX Spark Cluster)

| Node       | Hostname  | Management IP  | Fabric IP (RoCEv2) | GPU            | RAM   | Role                              |
|------------|-----------|----------------|---------------------|----------------|-------|-----------------------------------|
| Spark-01   | Captain   | 192.168.0.100  | 10.10.10.2          | GB10 Blackwell | 128GB | Swarm Manager, Postgres, Qdrant, Nginx LB |
| Spark-02   | Muscle    | 192.168.0.104  | 10.10.10.1          | GB10 Blackwell | 128GB | Ollama worker, Swarm Worker       |
| Spark-03   | Ocular    | 192.168.0.107  | 10.10.10.3          | GB10 Blackwell | 128GB | Ollama worker, Swarm Worker, Vision |
| Spark-04   | Sovereign | 192.168.0.108  | 10.10.10.4          | GB10 Blackwell | 128GB | Ollama worker, Swarm Worker       |

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
| Synology NAS    | DS1621+ (or equiv)| `/mnt/fortress_nas`      | NVMe-oF / NFS  | 48 TB    |
| Model Storage   | NAS (SSD tier)    | `/mnt/fortress_nas/models/` | NVMe-oF     | 2 TB     |
| Golden Snapshots| NAS (RAID6)       | `/mnt/fortress_nas/backups/`| NFS          | 4 TB     |

**NVMe-over-Fabrics (NVMe-oF):** The NAS MUST be mounted via NVMe-oF to all 4 Spark
nodes for near-wire-speed model weight loading. This is critical for TITAN mode, where
404 GB of DeepSeek-R1 shards must stream from NAS into distributed RAM across 4 nodes.

**Fallback:** If NVMe-oF is unavailable, NFS v4.1 over the management LAN is acceptable
for non-model data (backups, documents, email archives). Model weights MUST use high-speed
mount.

### 1.4 VRAM / Memory Allocation

#### SWARM Mode (DEFCON 5 — Production)

| Node     | Ollama Models                | Embedding    | System Reserve |
|----------|------------------------------|--------------|----------------|
| All 4    | qwen2.5:7b (~4.5 GB each)   | nomic-embed-text | ~8 GB     |
| Captain  | + Postgres, Qdrant, Nginx    |              | ~16 GB         |

#### TITAN Mode (DEFCON 1 — Strategic)

| Resource              | Allocation                  | Notes                          |
|-----------------------|-----------------------------|--------------------------------|
| DeepSeek-R1-671B      | 377 GB (Q4_K_M, 9 shards)  | Distributed across 4 nodes     |
| KV Cache              | 83 GB minimum               | For 8192 token context window  |
| System/OS Reserve     | ~52 GB total (13 GB/node)   | Docker, OS, monitoring         |
| **Total Required**    | **~460 GB**                 | Of 512 GB available            |

**Hard Rule:** SWARM and TITAN modes are mutually exclusive. They compete for the same
128 GB unified memory per node. Controlled exclusively via `switch_defcon.sh`.

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
                        |--> Nginx LB --> Ollama (SWARM mode)
                        |--> Direct   --> llama.cpp (TITAN mode)
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

### 2.2 Hybrid Orchestration (Dual-Brain Routing)

| Call Type       | Route                              | Engine           | Use Case                    |
|-----------------|-------------------------------------|------------------|-----------------------------|
| External (fast) | Google AI Studio API                | Gemini 3 Pro     | Planning, marketing drafts, 1M-token analysis |
| Internal (fast) | Nginx LB (192.168.0.100:80)        | Ollama (qwen2.5) | Email classification, vectorization, ops |
| Internal (deep) | Fabric (10.10.10.2:8080)           | DeepSeek-R1-671B | Contract review, legal, strategy |
| Embedding       | Nginx LB (192.168.0.100/api/embeddings) | nomic-embed-text | Vector search, semantic indexing |

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
    # Production ops — local Ollama swarm
    client = OpenAI(base_url="http://192.168.0.100/v1", api_key="not-needed")
    model = "qwen2.5:7b"
```

### 2.3 Service Mesh

| Service         | Host (SWARM)           | Host (TITAN)           | Port  | Protocol |
|-----------------|------------------------|------------------------|-------|----------|
| PostgreSQL      | Captain (192.168.0.100)| Captain (192.168.0.100)| 5432  | TCP      |
| Qdrant          | Captain (192.168.0.100)| (stopped)              | 6333  | HTTP     |
| Redis           | Captain (192.168.0.100)| (stopped)              | 6379  | TCP      |
| Nginx LB        | Captain (192.168.0.100)| (stopped)              | 80    | HTTP     |
| Ollama          | All nodes (:11434)     | (stopped)              | 11434 | HTTP     |
| llama.cpp API   | (stopped)              | Captain (10.10.10.2)   | 8080  | HTTP     |
| RPC Server      | (stopped)              | All nodes (10.10.10.x) | 50052 | RPC      |

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
| Swarm Worker Count     | 60s       | `docker service ls`       | < 4 replicas           |
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

*End of Technical Requirements. All specifications are binding per the
[Sovereign Constitution](./CONSTITUTION.md).*
