# FORTRESS JD — Full Operational Capability (FOC)

**Sector:** S05 (Legal)
**Persona:** The Counselor
**Activation Date:** 2026-02-13
**Status:** ACTIVE

---

## Executive Summary

Fortress JD is the on-premise AI Law Firm running entirely on the DGX Spark cluster. It combines a 21,444-document legal corpus (deeds, ordinances, permits, statutes, contracts) with dual-brain legal reasoning to act as a tireless General Counsel for Cabin Rentals of Georgia.

**Capabilities at FOC:**
- RAG-powered legal analysis with cited sources
- 12-category document classification
- Dual-brain routing (SWARM for quick lookups, TITAN for contract review)
- ADA/Fair Housing compliance detection
- Zoning and permit conflict flagging
- Full OODA audit trail on every query
- Incremental document indexing from NAS

---

## Architecture

```
                    ┌─────────────────────────┐
                    │   api.crog-ai.com        │
                    │   (Cloudflare Worker)     │
                    └──────────┬──────────────┘
                               │ JWT + tunnel
                    ┌──────────▼──────────────┐
                    │  Gateway (FastAPI :8000)  │
                    │  /v1/legal/*              │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼─────────┐
    │ /analyze       │  │ /search    │  │ /index         │
    │ Legal Sentinel │  │ CF-03 RAG  │  │ Legal Steward  │
    │ (OODA Agent)   │  │ (retrieve) │  │ (OODA Indexer) │
    └───────┬────────┘  └─────┬──────┘  └──────┬─────────┘
            │                 │                │
    ┌───────▼─────────────────▼────────────────▼─────────┐
    │              Qdrant legal_library                    │
    │              (2,455+ vectors, 768-dim cosine)        │
    │              nomic-embed-text (local Ollama)         │
    └───────┬─────────────────┬────────────────┬─────────┘
            │                 │                │
    ┌───────▼──────┐  ┌──────▼──────┐  ┌──────▼─────────┐
    │ SWARM Mode   │  │ TITAN Mode  │  │ NAS Corpus     │
    │ qwen2.5:7b   │  │ R1-671B     │  │ Corporate_     │
    │ (quick)      │  │ (deep)      │  │ Legal/         │
    └──────────────┘  └─────────────┘  └────────────────┘
```

---

## Components

### 1. Legal Sentinel (`src/agents/legal_sentinel.py`)

The primary Counselor agent. Takes a legal question, runs the full OODA cycle:

| OODA Phase | Action |
|---|---|
| **OBSERVE** | Classify question into legal domains (zoning, permits, ADA, contracts, etc.) |
| **ORIENT** | Retrieve top-K chunks from Qdrant `legal_library` via CF-03 |
| **DECIDE** | Route to SWARM (fast) or TITAN (deep) based on complexity |
| **ACT** | Generate cited legal analysis with risk flags |
| **POST-MORTEM** | Log to `system_post_mortems` (Article III) |

**Risk Detection:** Automatically flags conflicts, violations, expired permits, ADA implications, zoning issues, and liens in the generated analysis.

**Domain Classifier:** Routes questions across 8 legal domains:
- `zoning` — setbacks, variances, land use
- `permits` — building, septic, certificates of occupancy
- `property` — deeds, easements, boundaries, liens
- `contracts` — leases, amendments, liability
- `tax` — assessments, exemptions, depreciation
- `ada_compliance` — service animals, fair housing, HUD
- `hospitality` — guest agreements, cancellations, pet fees
- `corporate` — LLC formation, operating agreements

### 2. Legal Steward (`src/agents/legal_steward.py`)

Document indexing agent. Scans NAS, extracts text, generates embeddings, pushes to Qdrant.

| Feature | Detail |
|---|---|
| Source | `/mnt/fortress_nas/Corporate_Legal/` + `division_legal/knowledge_base/` |
| Formats | PDF, TXT, MD, DOCX |
| Chunking | 1200 chars, 300 overlap (legal-optimized) |
| Embedding | `nomic-embed-text` (768-dim, local Ollama) |
| Resume | Incremental by file hash (skip already-indexed) |
| Categories | 12 legal document types |

### 3. Legal API (`src/legal_api.py`)

Gateway router mounted at `/v1/legal`:

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/v1/legal/analyze` | POST | admin, operator | Full OODA legal analysis |
| `/v1/legal/search` | POST | admin, operator | Semantic search only (no LLM) |
| `/v1/legal/index` | POST | admin | Trigger Steward indexing |
| `/v1/legal/collection` | GET | any auth | Qdrant collection stats |
| `/v1/legal/matters` | GET | admin, operator | List legal matters |
| `/v1/legal/matters/{id}` | GET | admin, operator | Matter detail with docket |

### 4. Existing Infrastructure (Integrated)

| Component | Role | Location |
|---|---|---|
| CF-03 CounselorCRM | RAG pipeline (retrieve + reason) | `Modules/CF-03_CounselorCRM/` |
| Thunderdome | Adversarial legal swarm | `division_legal/thunderdome.py` |
| ChromaDB `law_library` | 1,334 O.C.G.A. statutes | `division_legal/chroma_loader.py` |
| Knowledge Base | 6 GA Code titles (9, 13, 16, 44, 48, 51) | `division_legal/knowledge_base/` |
| Legal Analyst | Direct RAG via ChromaDB | `src/legal_analyst.py` |
| Legal Partner R1 | Multi-mode reasoning | `src/legal_partner_r1.py` |

---

## Deployment Commands

### Deploy the Steward (Index Documents)

```bash
# Dry run — count and classify documents
python3 -m src.agents.legal_steward --dry-run

# Incremental index (skip already-indexed files)
python3 -m src.agents.legal_steward

# Full re-index (ignore resume)
python3 -m src.agents.legal_steward --full-reindex

# Include Georgia statutes from knowledge base
python3 -m src.agents.legal_steward --include-statutes

# Index a specific subdirectory
python3 -m src.agents.legal_steward --source /mnt/fortress_nas/Corporate_Legal/Leases/
```

### Query the Counselor (CLI)

```bash
# Interactive legal terminal
python3 -m Modules.CF-03_CounselorCRM.query_engine --interactive

# Single question
python3 -m Modules.CF-03_CounselorCRM.query_engine \
    "What are the setback requirements for deck construction in Fannin County?"

# Filter by category
python3 -m Modules.CF-03_CounselorCRM.query_engine \
    "Easement rights for Morgan Ridge" --category easement
```

### API Endpoints (via Gateway)

```bash
# Legal analysis (OODA)
curl -X POST http://192.168.0.100:8000/v1/legal/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Can I add a deck to the Whispering Pines cabin?", "brain": "auto"}'

# Semantic search only
curl -X POST http://192.168.0.100:8000/v1/legal/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "septic permit bedroom count", "category": "permit_license"}'

# Trigger indexing
curl -X POST http://192.168.0.100:8000/v1/legal/index \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"include_statutes": true}'

# Collection stats
curl http://192.168.0.100:8000/v1/legal/collection \
  -H "Authorization: Bearer $TOKEN"
```

---

## Phase 3: The Bar Exam (Mock Trial)

To declare Fortress JD "Fully Operational," the system must pass the following adversarial stress test:

### The Poison Pill Scenario

> "Draft a rental agreement for a guest bringing 3 dogs to a property zoned 'Strictly Residential' with a 'No Commercial Kennel' clause, but the guest claims ADA service animal status."

### Pass Conditions

1. R1 must identify the conflict between "Pet Fees" and "ADA Law"
2. R1 must cite specific HUD guidelines from the legal library
3. R1 must distinguish between ADA service animals (task-trained) and ESA (emotional support)
4. R1 must note that legitimate service animals cannot be charged pet fees
5. R1 must flag that 3 animals raises a "reasonable accommodation" question
6. R1 must draft a clause that protects the property without violating federal law
7. R1 must cite the specific O.C.G.A. and Fannin County provisions

### Running the Mock Trial

```bash
python3 -m Modules.CF-03_CounselorCRM.query_engine \
    "Draft a rental agreement for a guest bringing 3 dogs to a property \
    zoned 'Strictly Residential' with a 'No Commercial Kennel' clause, \
    but the guest claims ADA service animal status. Identify all legal \
    conflicts and draft protective clauses." \
    --brain captain --top-k 12
```

Or via API:
```bash
curl -X POST http://192.168.0.100:8000/v1/legal/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Draft a rental agreement for a guest bringing 3 dogs to a property zoned Strictly Residential with a No Commercial Kennel clause, but the guest claims ADA service animal status. Identify all legal conflicts and draft protective clauses.",
    "brain": "titan",
    "top_k": 12
  }'
```

---

## Data Sources

| Source | Type | Count | Location |
|---|---|---|---|
| Corporate Legal Corpus | PDF, TXT, DOCX | ~21,444 | `/mnt/fortress_nas/Corporate_Legal/` |
| O.C.G.A. Statutes | TXT | 6 titles | `division_legal/knowledge_base/` |
| Legal Library Vectors | Qdrant | 2,455+ | `legal_library` collection |
| Email Archive | Qdrant | filtered | `email_embeddings` (LEGAL_ADMIN) |
| Legal Matters | Postgres | variable | `public.legal_matters` |
| Legal Docket | Postgres | variable | `public.legal_docket` |

---

## Constitution Compliance

| Article | Requirement | Status |
|---|---|---|
| I — Data Sovereignty | Zero-cloud retention for legal data | COMPLIANT — all inference local |
| I — Classification | Legal docs = SOVEREIGN | COMPLIANT — never leaves cluster |
| III — OODA | Every query follows Observe-Orient-Decide-Act | COMPLIANT — via sovereign_ooda.py |
| III — Post-Mortem | Every query logged to system_post_mortems | COMPLIANT — automatic |
| IV — Sector Isolation | READ all schemas, WRITE only legal_* | COMPLIANT — firewall enforced |
| V — Wolfpack | Legal supports marketing readiness | COMPLIANT — protects before amplifying |

---

## Next Steps

1. **Run the Mock Trial** to validate R1's legal reasoning against the ADA scenario
2. **Schedule Steward cron** for nightly incremental indexing of new NAS documents
3. **Index Enterprise_War_Room/Legal_Evidence/** for case file coverage
4. **Bridge Thunderdome** to the OODA flow for adversarial case analysis
5. **Build the Paralegal** (Gemini 3 Flash) for citation formatting and PDF filing
