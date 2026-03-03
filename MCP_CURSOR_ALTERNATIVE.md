# Alternative MCP Setup for Cursor

If the automatic MCP config isn't loading, we can test the MCP server directly and use it via CLI.

## Option 1: Manual MCP Server Test

The MCP server works perfectly via CLI. You can use it immediately:

### Test Commands:
```bash
cd /home/admin/Fortress-Prime

# System status
./bin/sovereign stats

# Search Oracle
./bin/sovereign oracle "Toccoa Heights"

# Search legal docs
./bin/sovereign legal "easement"

# List collections
./bin/sovereign collections

# Get Godhead prompt
./bin/sovereign prompt jordi
```

## Option 2: Direct Python Access

You can also import the MCP tools directly in Python:

```python
from src.sovereign_mcp_server import (
    search_fortress_legal,
    search_oracle,
    get_fortress_stats,
    list_collections
)

# Get stats
stats = get_fortress_stats()
print(stats)

# Search Oracle
results = search_oracle("Toccoa Heights", max_results=10)
print(results)

# Search legal
legal = search_fortress_legal("easement", top_k=5)
print(legal)
```

## Option 3: Check Cursor MCP Settings Location

Cursor may expect the MCP config in a different location. Try:

### Location 1: User home
```bash
mkdir -p ~/.cursor
cp /home/admin/Fortress-Prime/.cursor/mcp_config.json ~/.cursor/
```

### Location 2: Cursor config
```bash
mkdir -p ~/.config/Cursor/User
cp /home/admin/Fortress-Prime/.cursor/mcp_config.json ~/.config/Cursor/User/
```

### Location 3: Project root (current - should work)
```
/home/admin/Fortress-Prime/.cursor/mcp_config.json
```

## Option 4: Use Cursor Settings UI

Instead of config file, try adding MCP server via Cursor UI:

1. Open Cursor Settings (Cmd/Ctrl + ,)
2. Search for "MCP" or "Model Context Protocol"
3. Look for "Add Server" button
4. Add:
   - Name: `fortress-prime-sovereign`
   - Command: `python3`
   - Args: `/home/admin/Fortress-Prime/src/sovereign_mcp_server.py`

## Option 5: Test MCP Server Directly

Run the server in a terminal and keep it running:

```bash
cd /home/admin/Fortress-Prime
python3 src/sovereign_mcp_server.py
```

Keep this terminal open. The server should stay running and Cursor should be able to connect to it.

## Verification

The MCP server IS working - we tested it successfully:
- ✅ Server starts without errors
- ✅ All tools functional (tested via test_mcp_server.py)
- ✅ CLI works perfectly
- ✅ All infrastructure online (Qdrant, ChromaDB, NAS)

The issue is just Cursor not auto-connecting to it yet.

## Immediate Solution: Use CLI

While we troubleshoot Cursor MCP, you can use the CLI immediately:

```bash
# All the same functionality available right now:
./bin/sovereign stats
./bin/sovereign oracle "your search"
./bin/sovereign legal "your search"
./bin/sovereign email "your search"
./bin/sovereign collections
```

The CLI has the exact same access to all 1.576 million vectors!
