# Sovereign Context Protocol (MCP)

**Status:** Level 3 Intelligence — Unified, Sovereign, Local

## Overview

The Sovereign Context Protocol is Fortress Prime's **unified knowledge layer** that eliminates fragmentation between Cursor, CLI tools, web interfaces, and AI agents. Instead of copy-pasting context or rebuilding prompts across tools, you now have a **single source of truth** that all AI systems can query.

### The Problem (Level 2: Fragmented High-Power)

**Before:**
```
┌─────────┐     ┌─────────┐     ┌─────────┐
│ Cursor  │     │   CLI   │     │ Web UI  │
│ (Copy)  │     │ (Paste) │     │ (Retype)│
└─────────┘     └─────────┘     └─────────┘
     │               │                │
     └───────────────┼────────────────┘
                     │
         ❌ Fragmented Context
         ❌ Duplicated Prompts
         ❌ Drift Over Time
```

**After (Level 3: Unified Intelligence):**
```
┌─────────────────────────────────────────────────────────┐
│         SOVEREIGN MCP SERVER (The Hive Mind)            │
│  Resources: Godhead Prompts | Tools: Vector Search      │
└──────────────────┬──────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐    ┌────▼────┐    ┌───▼────┐
│ Cursor │    │   CLI   │    │ Web UI │
│ @jordi │    │  yltra  │    │  Chat  │
└────────┘    └─────────┘    └────────┘

✅ Single Source of Truth
✅ Live Data Access
✅ Consistent Persona
```

## Architecture

### Core Components

1. **MCP Server** (`src/sovereign_mcp_server.py`)
   - Lightweight Python FastMCP server
   - Runs on localhost (DGX/Synology)
   - Exposes tools and resources via MCP protocol

2. **Vector Databases**
   - **Qdrant** (primary): legal_library (2,455 vectors), email_embeddings
   - **ChromaDB** (legacy): 224K vectors, 16,883 source files
   - **PostgreSQL**: fortress_db (structured data)

3. **Persona Layers** (Godheads)
   - Each persona is a pre-configured knowledge domain
   - Includes: system prompt, vector collections, search filters, custom tools
   - Current personas: Jordi, Legal, CROG, Comptroller

4. **Client Integrations**
   - **Cursor**: Native MCP support via `.cursor/mcp_config.json`
   - **CLI**: Direct Python imports or HTTP API
   - **Web UI**: OpenAI-compatible proxy (future)

## Installation

### 1. Install FastMCP

```bash
cd /home/admin/Fortress-Prime
pip install "mcp[server]>=1.0.0"
```

### 2. Verify Dependencies

The MCP server uses existing Fortress infrastructure:
- ✅ Qdrant (already running on port 6333)
- ✅ Ollama embeddings (nomic-embed-text)
- ✅ PostgreSQL (fortress_db)
- ✅ ChromaDB (at `/mnt/fortress_nas/chroma_db/chroma.sqlite3`)

### 3. Test the Server

```bash
# Test MCP server tools
python src/test_mcp_server.py

# Test specific queries
python src/test_mcp_server.py search-legal "easement rights"
python src/test_mcp_server.py search-oracle "Toccoa Heights"
python src/test_mcp_server.py fortress-stats
```

### 4. Connect Cursor

**Option A: Using MCP Config (Recommended)**

Cursor will automatically detect `.cursor/mcp_config.json`:

```json
{
  "mcpServers": {
    "fortress-prime-sovereign": {
      "command": "python",
      "args": ["/home/admin/Fortress-Prime/src/sovereign_mcp_server.py"],
      "env": {
        "QDRANT_HOST": "localhost",
        "QDRANT_PORT": "6333"
      }
    }
  }
}
```

**Option B: Manual Configuration**

1. Open Cursor Settings
2. Navigate to **Features > Model Context Protocol**
3. Click **Add Server**
4. Configure:
   - **Name**: `fortress-prime-sovereign`
   - **Command**: `python`
   - **Arguments**: `/home/admin/Fortress-Prime/src/sovereign_mcp_server.py`

### 5. Verify Connection

In Cursor, open the chat and type:

```
@fortress-prime-sovereign list available tools
```

You should see:
- `search_jordi_knowledge()`
- `search_fortress_legal()`
- `search_oracle()`
- `search_email_intel()`
- `list_collections()`
- `get_fortress_stats()`

## Usage

### In Cursor

Once connected, you can reference the MCP server using `@fortress-prime-sovereign`:

```
@fortress-prime-sovereign search_fortress_legal("easement rights Morgan Ridge")
```

Or use the shorthand persona (once configured):

```
@jordi what is your stance on Bitcoin in 2024?
@legal what are the terms of the Rolling River lease?
@crog which properties need turnover this week?
```

### In Terminal

#### Direct Python Import

```python
from src.sovereign_mcp_server import search_fortress_legal

result = search_fortress_legal("easement rights", top_k=5)
print(result)
```

#### Via Test Script

```bash
python src/test_mcp_server.py search-legal "easement rights"
python src/test_mcp_server.py search-oracle "survey"
python src/test_mcp_server.py jordi-status
```

### In Web UI

For OpenWebUI or other web interfaces, you can expose the MCP server via HTTP proxy (future enhancement).

## Persona Layers (Godheads)

Each persona is a **pre-configured knowledge domain** with:
1. **System Prompt** (The Godhead) - defines personality, rules, context
2. **Vector Collections** - which databases to search
3. **Search Filters** - metadata filters (date, category, division)
4. **Custom Tools** - persona-specific functions

### Available Personas

#### 1. Jordi Visser Intelligence Engine (VIE)

**Purpose:** Digital twin of macro hedge fund manager Jordi Visser

**System Prompt:** `sovereign://godhead/jordi`

**Knowledge Base:**
- Podcast transcripts (Blockworks, Bankless, Unchained)
- Newsletter archives
- Interview notes
- YouTube commentary

**Personality Traits:**
- Contrarian but data-driven
- Focuses on risk/reward asymmetry
- Skeptical of hype cycles
- Values liquidity and exit strategies

**Example Queries:**
```
@jordi what is your Bitcoin outlook for 2024?
@jordi how do you think about altcoin allocation?
@jordi what are the biggest risks in crypto right now?
```

#### 2. Fortress Legal Counselor

**Purpose:** Senior Legal Analyst for CROG and Fortress Prime Holdings

**System Prompt:** `sovereign://godhead/legal`

**Knowledge Base:**
- Qdrant `legal_library` (2,455 vectors)
- Categories: leases, deeds, easements, contracts, Georgia statutes

**Rules:**
- Base answers EXCLUSIVELY on provided documents
- Always cite sources with format `[Source: filename.pdf]`
- Quote relevant passages directly
- NEVER provide legal advice (recommend consulting attorney)

**Example Queries:**
```
@legal what are the easement terms on Morgan Ridge?
@legal summarize the Rolling River lease agreement
@legal what does O.C.G.A. say about septic setbacks?
```

#### 3. CROG Controller

**Purpose:** Operational brain for Cabin Rentals of Georgia (36 rental properties)

**System Prompt:** `sovereign://godhead/crog`

**Knowledge Base:**
- PostgreSQL: `division_b` schema, `public.ops_*` tables
- Qdrant `email_embeddings` (filtered by `division = 'REAL_ESTATE'`)
- Streamline VRS integration

**Responsibilities:**
- Guest communications
- Maintenance dispatch
- Pricing optimization
- Trust accounting

**Example Queries:**
```
@crog which properties need turnover this week?
@crog show me outstanding maintenance tickets
@crog what is the occupancy rate for Blue Ridge cabins?
```

#### 4. Fortress Comptroller

**Purpose:** CFO / Venture Capitalist for enterprise-wide financial oversight

**System Prompt:** `sovereign://godhead/comp`

**Knowledge Base:**
- PostgreSQL: `division_a` schema, `hedge_fund` schema
- QuickBooks Online mirror
- Market signals and watchlists

**Responsibilities:**
- Cash flow tracking across all divisions
- Gold/BTC positions monitoring
- Tax strategy optimization
- Challenge every transaction

**Example Queries:**
```
@comp what is our current cash position?
@comp show me hedge fund signals from last week
@comp compare CROG revenue vs Bloom revenue YTD
```

## Jordi Visser Setup

### Step 1: Gather Source Material

Create a directory for Jordi transcripts:

```bash
mkdir -p /mnt/fortress_nas/Intelligence/Jordi_Visser
```

Add transcripts in supported formats:
- PDF (preferred for podcasts with metadata)
- TXT (plain transcripts)
- MD (markdown with timestamps)

**Filename Convention:**
```
Blockworks_2024-12-15_Episode_342.pdf
Bankless_2024-06-10_Jordi_Visser.txt
Unchained_2024-03-20_Interview.md
```

The ingestion script will auto-extract:
- Date (YYYY-MM-DD)
- Podcast name
- Episode number
- Speaker attribution

### Step 2: Run Ingestion

```bash
python src/ingest_jordi_knowledge.py
```

This will:
1. Create Qdrant collection `jordi_intel`
2. Extract text from all PDFs/TXT/MD files
3. Chunk text (1000 chars, 200 overlap)
4. Generate embeddings (nomic-embed-text)
5. Upload to Qdrant with metadata

**Options:**
```bash
# Custom source path
python src/ingest_jordi_knowledge.py --source-path /custom/path

# Force recreate (drops existing collection)
python src/ingest_jordi_knowledge.py --force-recreate
```

### Step 3: Test Jordi Knowledge

```bash
# Check status
python src/test_mcp_server.py jordi-status

# Test search
python src/test_mcp_server.py search-jordi "Bitcoin outlook"
python src/test_mcp_server.py search-jordi "Ethereum vs Solana"
```

### Step 4: Use in Cursor

```
@jordi what is your stance on Bitcoin for 2024?
@jordi how do you think about risk management in crypto?
@jordi what are your thoughts on the current macro environment?
```

## Extending to Other Personas

Want to replicate this for other people you listen to? Follow this pattern:

### 1. Define the Godhead Prompt

Add to `src/sovereign_mcp_server.py`:

```python
RAOUL_PAL_GODHEAD = """You are the Real Vision Intelligence Engine.

BACKGROUND:
Raoul Pal is a macro investor, founder of Real Vision, and crypto advocate...

PERSONALITY TRAITS:
- Exponential thinking (technology adoption curves)
- Macro focus (liquidity, demographics, debt cycles)
- Optimistic on crypto as "the great reset"
- Focuses on network effects and adoption metrics

COMMUNICATION STYLE:
- Uses charts and visual metaphors
- References macro cycles (the "Banana Zone")
- Cites on-chain metrics (NVT, active addresses)
- Enthusiastic about democratizing finance

CORE BELIEFS:
- "Everything is going to infinity" (crypto vs fiat debasement)
- Bitcoin + Ethereum = the base layer of the new financial system
- DeFi will replace TradFi
- Solana as "the Mac to Ethereum's Linux"
...
"""

@mcp.resource("sovereign://godhead/raoul")
def get_raoul_prompt() -> str:
    return RAOUL_PAL_GODHEAD
```

### 2. Create the Search Tool

```python
@mcp.tool()
def search_raoul_knowledge(query: str, top_k: int = 5) -> str:
    """Search Raoul Pal's Real Vision content."""
    collection = "raoul_intel"
    # Same pattern as search_jordi_knowledge
    ...
```

### 3. Create the Ingestion Script

Copy `src/ingest_jordi_knowledge.py` to `src/ingest_raoul_knowledge.py`:
- Update `COLLECTION_NAME = "raoul_intel"`
- Update `DEFAULT_SOURCE_PATH = "/mnt/fortress_nas/Intelligence/Raoul_Pal"`
- Update metadata extraction patterns

### 4. Run the Pipeline

```bash
# Gather transcripts
mkdir -p /mnt/fortress_nas/Intelligence/Raoul_Pal
# ... download Real Vision episodes ...

# Ingest
python src/ingest_raoul_knowledge.py

# Test
python src/test_mcp_server.py search-raoul "banana zone"
```

### 5. Use in Cursor

```
@raoul what is the banana zone?
@raoul how do you think about Solana vs Ethereum?
```

## Replication Template

For any new persona, you need:

### Files to Create
1. **Godhead Prompt** - System prompt in `sovereign_mcp_server.py`
2. **Search Tool** - MCP tool function in `sovereign_mcp_server.py`
3. **Ingestion Script** - Copy and customize `ingest_jordi_knowledge.py`
4. **Test Cases** - Add to `test_mcp_server.py`

### Data Required
1. **Source Material**
   - Podcast transcripts (PDF/TXT/MD)
   - Newsletter archives
   - Interview notes
   - YouTube commentary
   - Twitter threads (future)

2. **Metadata**
   - Date (YYYY-MM-DD)
   - Source (podcast name, publication)
   - Episode/article number
   - Speaker/author attribution

3. **Personality Profile**
   - Background
   - Core beliefs
   - Communication style
   - Common phrases/terminology
   - Typical subjects discussed

### Ingestion Checklist
- [ ] Create source directory: `/mnt/fortress_nas/Intelligence/{Name}`
- [ ] Gather transcripts (aim for 20+ hours of content)
- [ ] Organize files with consistent naming
- [ ] Run ingestion script
- [ ] Verify vector count in Qdrant
- [ ] Test 5 representative queries
- [ ] Document persona quirks and limitations

## Advanced Features

### Multi-Persona Queries

Future enhancement: Ask multiple personas the same question and compare:

```
@compare Bitcoin outlook
  -> @jordi: [contrarian, risk-focused answer]
  -> @raoul: [exponential adoption curve answer]
  -> @lyn: [sound money fundamentals answer]
```

### Time-Travel Queries

Filter by date to see opinion evolution:

```python
search_jordi_knowledge(
    "Bitcoin outlook",
    date_filter="2024-01",  # Only Jan 2024 content
)
```

### Cross-Persona Synthesis

Ask Fortress AI to synthesize multiple perspectives:

```
@fortress synthesize: What do Jordi, Raoul, and Lyn think about Ethereum?
```

### Disagreement Detection

Identify where personas disagree:

```
@fortress conflicts: Find where Jordi and Raoul disagree on Solana
```

## Troubleshooting

### MCP Server Won't Start

**Check dependencies:**
```bash
pip list | grep mcp
# Should show: mcp>=1.0.0
```

**Check Qdrant:**
```bash
curl http://localhost:6333/collections
```

**Check Ollama:**
```bash
curl http://localhost:11434/api/embeddings \
  -d '{"model":"nomic-embed-text","prompt":"test"}'
```

### Cursor Can't See MCP Server

**Verify config location:**
```bash
cat /home/admin/Fortress-Prime/.cursor/mcp_config.json
```

**Check Cursor logs:**
- Open Cursor Developer Tools (Help > Toggle Developer Tools)
- Look for MCP connection errors in Console

**Try manual restart:**
1. Close Cursor completely
2. Kill any orphaned MCP processes: `pkill -f sovereign_mcp_server`
3. Restart Cursor

### No Search Results

**Check collection exists:**
```bash
python src/test_mcp_server.py list-collections
```

**Verify embeddings:**
```bash
python src/test_mcp_server.py jordi-status
# Should show: vectors > 0
```

**Re-ingest data:**
```bash
python src/ingest_jordi_knowledge.py --force-recreate
```

## Performance Tuning

### Embedding Speed

**Current:** ~2 embeddings/sec (CPU)

**Optimization:**
- Use GPU Ollama: `CUDA_VISIBLE_DEVICES=0 ollama serve`
- Batch embeddings: Process 10-20 chunks at once
- Cache frequent queries: Add Redis layer

### Search Speed

**Current:** ~100-200ms per query

**Optimization:**
- Increase Qdrant indexing: `"indexing_threshold": 1000`
- Use HNSW parameters: `{"m": 16, "ef_construct": 100}`
- Add result caching

### Chunk Size Tuning

**Current:** 1000 chars, 200 overlap

**Too small** (< 500 chars):
- More vectors (slower search)
- Less context per result
- Better for keyword matching

**Too large** (> 2000 chars):
- Fewer vectors (faster search)
- More context per result
- Worse for specific queries

**Recommendation:**
- Legal docs: 1500 chars (long-form analysis)
- Transcripts: 1000 chars (conversational chunks)
- Emails: 500 chars (concise messages)

## Security

### Local-Only Architecture

The MCP server runs **entirely local**:
- No cloud API calls
- No data leaves your network
- All embeddings generated on DGX/Synology
- All vector storage on NAS

### Access Control

Current: No authentication (localhost only)

For multi-user:
1. Add API key authentication
2. Use PostgreSQL user permissions
3. Filter Qdrant queries by user role
4. Audit log all queries

### Data Sovereignty

Per Constitution Article IV.2:
- **Level 1**: Public knowledge (can use cloud)
- **Level 2**: Business operations (local-first, cloud backup OK)
- **Level 3**: Proprietary intelligence (local ONLY, no cloud)

All Fortress MCP data is **Level 3**: Local only, no cloud APIs.

## Maintenance

### Weekly Tasks
- [ ] Backup Qdrant collections to NAS
- [ ] Check collection vector counts
- [ ] Review query logs for anomalies

### Monthly Tasks
- [ ] Update persona prompts based on new content
- [ ] Re-ingest updated transcripts
- [ ] Prune duplicate/outdated vectors

### Quarterly Tasks
- [ ] Audit MCP server performance
- [ ] Benchmark search quality
- [ ] Add new personas based on research priorities

## Roadmap

### Phase 1: Foundation (Complete)
- [x] MCP server infrastructure
- [x] Qdrant integration
- [x] Basic persona layers (Jordi, Legal, CROG, Comp)
- [x] Cursor integration

### Phase 2: Jordi Visser (In Progress)
- [ ] Gather 20+ hours of Jordi transcripts
- [ ] Ingest to `jordi_intel` collection
- [ ] Test search quality
- [ ] Document persona quirks

### Phase 3: Multi-Persona (Future)
- [ ] Raoul Pal (Real Vision)
- [ ] Lyn Alden (macro + Bitcoin)
- [ ] Balaji Srinivasan (tech + crypto)
- [ ] Cathie Wood (innovation + disruption)

### Phase 4: Advanced Features
- [ ] Multi-persona synthesis
- [ ] Time-travel queries (date filtering)
- [ ] Disagreement detection
- [ ] Twitter integration (X API)

### Phase 5: Enterprise Scaling
- [ ] HTTP API for web UIs
- [ ] Redis caching layer
- [ ] PostgreSQL query audit log
- [ ] Multi-user access control

## Support

For issues, questions, or enhancements:
1. Check this documentation
2. Run test suite: `python src/test_mcp_server.py`
3. Review Fortress Atlas: `sovereign://atlas`
4. Consult Constitution: `.cursor/rules/002-sovereign-constitution.mdc`

---

**Constitution Reference:** This is the implementation of Article V.3: "Unified Intelligence Infrastructure"

**Status:** Operational, Level 3

**Last Updated:** 2026-02-15
