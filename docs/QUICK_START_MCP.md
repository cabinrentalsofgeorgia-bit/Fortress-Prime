# Sovereign Context Protocol — Quick Start

**Goal:** Get the MCP server running and connected to Cursor in < 10 minutes.

## Prerequisites

- ✅ Qdrant running (port 6333)
- ✅ Ollama running (port 11434) with `nomic-embed-text` model
- ✅ PostgreSQL (fortress_db)
- ✅ Python 3.10+

## Step 1: Install FastMCP (2 min)

```bash
cd /home/admin/Fortress-Prime
pip install "mcp[server]>=1.0.0"
```

## Step 2: Test the Server (3 min)

```bash
# Run all tests
python src/test_mcp_server.py

# Test specific tools
python src/test_mcp_server.py fortress-stats
python src/test_mcp_server.py list-collections
python src/test_mcp_server.py search-oracle "survey"
```

**Expected Output:**
```json
{
  "qdrant": {
    "status": "online",
    "collections_count": 2
  },
  "chromadb": {
    "status": "online",
    "vectors": 224209
  }
}
```

## Step 3: Connect Cursor (2 min)

The config file is already created at `.cursor/mcp_config.json`.

**Restart Cursor** to load the MCP server.

### Verify Connection

In Cursor chat:
```
List available MCP tools
```

You should see:
- search_fortress_legal
- search_oracle
- search_email_intel
- list_collections
- get_fortress_stats

## Step 4: Test in Cursor (3 min)

Try these queries:

```
Search fortress legal documents for "easement rights"
```

```
Search the Oracle for "Toccoa Heights Survey"
```

```
Get fortress stats
```

## Step 5: Set Up Jordi Visser (Optional)

If you have Jordi transcripts:

```bash
# Create directory
mkdir -p /mnt/fortress_nas/Intelligence/Jordi_Visser

# Add your PDFs/transcripts to that directory

# Run ingestion
python src/ingest_jordi_knowledge.py

# Test
python src/test_mcp_server.py search-jordi "Bitcoin"
```

## Troubleshooting

### "Cannot connect to Qdrant"

```bash
# Check Qdrant is running
curl http://localhost:6333/collections

# If not running, start it
docker start qdrant
# OR
sudo systemctl start qdrant
```

### "Embedding service not available"

```bash
# Check Ollama
curl http://localhost:11434/api/embeddings \
  -d '{"model":"nomic-embed-text","prompt":"test"}'

# If model not found, pull it
ollama pull nomic-embed-text
```

### "Cursor doesn't see MCP server"

1. Close Cursor completely
2. Kill any orphaned processes: `pkill -f sovereign_mcp_server`
3. Restart Cursor
4. Check Developer Tools (Help > Toggle Developer Tools) for errors

### "No search results"

```bash
# Check collections exist
python src/test_mcp_server.py list-collections

# For legal docs, verify Qdrant has data
curl http://localhost:6333/collections/legal_library

# For Oracle, verify ChromaDB exists
ls -lh /mnt/fortress_nas/chroma_db/chroma.sqlite3
```

## Next Steps

1. **Read full documentation:** `docs/SOVEREIGN_CONTEXT_PROTOCOL.md`
2. **Add Jordi transcripts** (if available)
3. **Replicate for other personas** (Raoul Pal, Lyn Alden, etc.)
4. **Integrate with CLI tools** (yltra, deepseek_max_launch.sh, etc.)

## Quick Reference

### Test Commands
```bash
# Full test suite
python src/test_mcp_server.py

# Specific tests
python src/test_mcp_server.py search-legal "query"
python src/test_mcp_server.py search-oracle "query"
python src/test_mcp_server.py search-jordi "query"
python src/test_mcp_server.py list-collections
python src/test_mcp_server.py fortress-stats
python src/test_mcp_server.py jordi-status
```

### Cursor Usage
```
@fortress-prime-sovereign search_fortress_legal("easement rights")
@fortress-prime-sovereign search_oracle("survey")
@fortress-prime-sovereign get_fortress_stats()
```

### Direct Python Usage
```python
from src.sovereign_mcp_server import search_fortress_legal, search_oracle

# Search legal docs
result = search_fortress_legal("easement rights", top_k=5)
print(result)

# Search Oracle
result = search_oracle("Toccoa Heights", max_results=10)
print(result)
```

---

**Need Help?** See full docs: `docs/SOVEREIGN_CONTEXT_PROTOCOL.md`
