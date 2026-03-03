# Sovereign Context Protocol (MCP) — The Hive Mind

> **"No more copy-paste. No more fragmented context. One source of truth."**

## What Is This?

The **Sovereign Context Protocol** is Fortress Prime's unified intelligence layer that eliminates fragmentation between Cursor, CLI tools, web interfaces, and AI agents.

Instead of copying prompts and context between tools, you now have a **single MCP server** ("The Hive Mind") that all your AI systems can query.

### Before (Level 2: Fragmented)
```
❌ Copy Jordi Visser prompt into Cursor
❌ Paste same prompt into CLI script
❌ Manually search for transcripts
❌ Context drifts over time
❌ Different answers in different tools
```

### After (Level 3: Unified)
```
✅ One Godhead prompt per persona (Jordi, Legal, CROG, etc.)
✅ All tools query the same MCP server
✅ Live vector DB search (Qdrant, ChromaDB)
✅ Consistent persona across all interfaces
✅ Single source of truth
```

## Quick Start (10 minutes)

### 1. Install

```bash
bash setup_sovereign_mcp.sh
```

### 2. Test

```bash
# Test all systems
python src/test_mcp_server.py

# Test CLI
./bin/sovereign stats
./bin/sovereign oracle "survey"
```

### 3. Connect Cursor

Restart Cursor. The MCP config is already at `.cursor/mcp_config.json`.

Verify:
```
List available MCP tools
```

### 4. Use It

**In Cursor:**
```
Search fortress legal documents for "easement rights"
Get fortress stats
```

**In Terminal:**
```bash
./bin/sovereign legal "easement rights"
./bin/sovereign oracle "Toccoa Heights"
./bin/sovereign stats
```

## What's Included

### 1. MCP Server (`src/sovereign_mcp_server.py`)
- FastMCP-based server
- Runs on localhost
- Exposes 10+ tools and 5+ resources

### 2. Persona Layers (Godheads)
- **Jordi Visser** — Macro hedge fund manager, crypto investor
- **Legal Counselor** — CROG legal analyst (2,455 doc vectors)
- **CROG Controller** — Property management operations
- **Comptroller** — Enterprise CFO / financial oversight

### 3. Vector Search Tools
- `search_jordi_knowledge()` — Jordi transcripts/interviews
- `search_fortress_legal()` — Legal docs (Qdrant)
- `search_oracle()` — 224K general knowledge (ChromaDB)
- `search_email_intel()` — Email archive
- `list_collections()` — Vector DB inventory
- `get_fortress_stats()` — System health

### 4. CLI Tool (`bin/sovereign`)
- Interactive mode
- Direct queries
- System commands
- Works with yltra/ultra

### 5. Ingestion Pipeline
- `ingest_jordi_knowledge.py` — Populate Jordi vector DB
- Supports PDF, TXT, MD
- Auto-extracts metadata (date, podcast, episode)
- Chunks and embeds with nomic-embed-text

### 6. Documentation
- `docs/SOVEREIGN_CONTEXT_PROTOCOL.md` — Full spec
- `docs/QUICK_START_MCP.md` — 10-min guide
- `docs/MCP_INTEGRATION_GUIDE.md` — How to connect everything

## Use Cases

### 1. Cursor Development
```
Ask @fortress-prime-sovereign to search legal documents for "easement rights"

Then: What are the key terms of the Morgan Ridge easement?
```

### 2. CLI Research
```bash
# Get Jordi's Bitcoin outlook
./bin/sovereign jordi "Bitcoin outlook 2024"

# Search legal precedent
./bin/sovereign legal "septic setback requirements"

# Find old project files
./bin/sovereign oracle "Toccoa Heights survey"
```

### 3. Integrate with yltra/ultra
```bash
# Get Godhead prompt
JORDI_PROMPT=$(./bin/sovereign prompt jordi)

# Get knowledge context
CONTEXT=$(./bin/sovereign jordi "Bitcoin")

# Send to LLM with full context
yltra --system "$JORDI_PROMPT" --context "$CONTEXT" "What is your Bitcoin outlook?"
```

### 4. Multi-Persona Comparison
```bash
# Compare Jordi vs Raoul on Bitcoin
./bin/sovereign jordi "Bitcoin" > jordi.txt
./bin/sovereign raoul "Bitcoin" > raoul.txt
diff jordi.txt raoul.txt
```

## Architecture

```
                  SOVEREIGN MCP SERVER
                    (The Godhead)
                          │
         ┌────────────────┼────────────────┐
         │                │                │
    ┌────▼────┐      ┌────▼────┐     ┌────▼────┐
    │ Cursor  │      │   CLI   │     │  yltra  │
    │ @jordi  │      │sovereign│     │  ultra  │
    └─────────┘      └─────────┘     └─────────┘
         │                │                │
         └────────────────┼────────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
    ┌────▼────┐      ┌────▼────┐     ┌────▼────┐
    │ Qdrant  │      │ChromaDB │     │Postgres │
    │ 2.4K    │      │  224K   │     │fortress │
    │ legal   │      │ Oracle  │     │   _db   │
    └─────────┘      └─────────┘     └─────────┘
```

## Replication for Other Personas

Want to replicate for Raoul Pal, Lyn Alden, Balaji, etc.?

**Steps:**
1. Define Godhead prompt (personality, beliefs, communication style)
2. Create search tool in `sovereign_mcp_server.py`
3. Copy `ingest_jordi_knowledge.py` to `ingest_{name}_knowledge.py`
4. Gather transcripts (20+ hours recommended)
5. Run ingestion: `python src/ingest_{name}_knowledge.py`
6. Test: `./bin/sovereign {name} "test query"`

**See:** `docs/MCP_INTEGRATION_GUIDE.md` for detailed replication guide.

## Files Reference

### Core System
- `src/sovereign_mcp_server.py` — MCP server (FastMCP)
- `bin/sovereign` — CLI tool
- `.cursor/mcp_config.json` — Cursor integration config
- `setup_sovereign_mcp.sh` — Automated setup

### Ingestion
- `src/ingest_jordi_knowledge.py` — Jordi Visser ingestion
- (Template for other personas)

### Testing
- `src/test_mcp_server.py` — Test suite for all tools

### Documentation
- `README_SOVEREIGN_MCP.md` — This file
- `docs/SOVEREIGN_CONTEXT_PROTOCOL.md` — Full specification
- `docs/QUICK_START_MCP.md` — Quick start guide
- `docs/MCP_INTEGRATION_GUIDE.md` — Integration patterns

### Data Sources
- `/mnt/fortress_nas/Intelligence/Jordi_Visser/` — Jordi transcripts
- `/mnt/fortress_nas/chroma_db/chroma.sqlite3` — Oracle (224K vectors)
- Qdrant `legal_library` — 2,455 legal document vectors
- Qdrant `email_embeddings` — Email archive
- PostgreSQL `fortress_db` — Structured data

## Requirements

- Python 3.10+
- FastMCP: `pip install "mcp[server]>=1.0.0"` (installed by setup script)
- Qdrant (running on port 6333)
- Ollama (running on port 11434) with `nomic-embed-text` model
- PostgreSQL (fortress_db)

## Commands

### Setup
```bash
bash setup_sovereign_mcp.sh          # Install and configure
```

### Testing
```bash
python src/test_mcp_server.py        # Test all tools
python src/test_mcp_server.py search-legal "query"
python src/test_mcp_server.py search-oracle "query"
python src/test_mcp_server.py fortress-stats
```

### CLI Usage
```bash
./bin/sovereign                      # Interactive mode
./bin/sovereign legal "query"        # Search legal docs
./bin/sovereign jordi "query"        # Search Jordi knowledge
./bin/sovereign oracle "query"       # Search Oracle (224K)
./bin/sovereign email "query"        # Search email archive
./bin/sovereign collections          # List all collections
./bin/sovereign stats                # System statistics
./bin/sovereign prompt jordi         # Show Jordi Godhead
```

### Ingestion
```bash
python src/ingest_jordi_knowledge.py              # Ingest Jordi
python src/ingest_jordi_knowledge.py --force-recreate  # Re-ingest
```

## Troubleshooting

### Setup Issues

**"Cannot connect to Qdrant"**
```bash
curl http://localhost:6333/collections
# If fails: docker start qdrant
```

**"Embedding service not available"**
```bash
curl http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'
# If fails: ollama pull nomic-embed-text
```

### Cursor Issues

**"MCP server not showing"**
```bash
# Verify config
cat .cursor/mcp_config.json

# Kill zombies and restart
pkill -f sovereign_mcp_server
# Then restart Cursor
```

**"No search results"**
```bash
# Check collections
python src/test_mcp_server.py list-collections

# Re-ingest if needed
python src/ingest_jordi_knowledge.py --force-recreate
```

### Performance Issues

**"Embeddings too slow"**
- Use GPU Ollama: `CUDA_VISIBLE_DEVICES=0 ollama serve`
- Batch process: Embed multiple chunks at once
- Add caching: Use Redis for frequent queries

**"Search too slow"**
- Tune Qdrant indexing: Increase `indexing_threshold`
- Adjust HNSW params: `{"m": 16, "ef_construct": 100}`
- Add result caching

## Roadmap

### Phase 1: Foundation ✅
- [x] MCP server infrastructure
- [x] Qdrant/ChromaDB integration
- [x] Basic persona layers
- [x] Cursor integration
- [x] CLI tool

### Phase 2: Jordi Visser (In Progress)
- [ ] Gather 20+ hours of transcripts
- [ ] Ingest to vector DB
- [ ] Test search quality
- [ ] Refine Godhead prompt
- [ ] Integrate with yltra/ultra

### Phase 3: Multi-Persona
- [ ] Raoul Pal (Real Vision)
- [ ] Lyn Alden (Macro + Bitcoin)
- [ ] Balaji Srinivasan (Tech + Crypto)
- [ ] Cathie Wood (Innovation)

### Phase 4: Advanced Features
- [ ] Multi-persona synthesis
- [ ] Time-travel queries (date filtering)
- [ ] Disagreement detection
- [ ] Twitter/X integration

### Phase 5: Enterprise
- [ ] HTTP API for web UIs
- [ ] Redis caching
- [ ] PostgreSQL audit log
- [ ] Multi-user access control

## Philosophy

This is **Level 3 Intelligence**: Unified, Sovereign, Local.

- **Unified**: One source of truth for all AI systems
- **Sovereign**: No cloud APIs, no data leaving your network
- **Local**: All embeddings and search on DGX/Synology

Per Fortress Constitution Article IV.2:
> "Level 3 data (proprietary intelligence) shall remain local-only. No cloud APIs."

## Contributing

To add a new persona:
1. Read `docs/MCP_INTEGRATION_GUIDE.md` (Replication section)
2. Define Godhead in `sovereign_mcp_server.py`
3. Create ingestion script
4. Gather source material (20+ hours recommended)
5. Test thoroughly
6. Document quirks and limitations

## Support

- Documentation: `docs/SOVEREIGN_CONTEXT_PROTOCOL.md`
- Quick Start: `docs/QUICK_START_MCP.md`
- Integration: `docs/MCP_INTEGRATION_GUIDE.md`
- Constitution: `.cursor/rules/002-sovereign-constitution.mdc`
- Fortress Atlas: `fortress_atlas.yaml`

## License

Fortress Prime — Proprietary Intelligence

---

**Status:** Operational, Level 3

**Last Updated:** 2026-02-15

**Next Steps:**
1. Run `bash setup_sovereign_mcp.sh`
2. Test with `python src/test_mcp_server.py`
3. Connect Cursor (restart Cursor)
4. Start gathering Jordi transcripts
5. Replicate for other personas

Welcome to the Hive Mind.
