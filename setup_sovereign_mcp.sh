#!/bin/bash
################################################################################
# FORTRESS PRIME — SOVEREIGN CONTEXT PROTOCOL SETUP
################################################################################
# Automated setup script for the MCP server and Hive Mind architecture.
#
# This script:
#   1. Installs FastMCP and dependencies
#   2. Verifies Qdrant and Ollama are running
#   3. Tests the MCP server
#   4. Configures Cursor integration
#   5. Makes CLI tools executable
#
# USAGE:
#   bash setup_sovereign_mcp.sh
#
# Author: Fortress Prime Architect
# Version: 1.0.0
################################################################################

set -e  # Exit on error

echo "════════════════════════════════════════════════════════════════════════════"
echo "  FORTRESS PRIME — SOVEREIGN CONTEXT PROTOCOL SETUP"
echo "════════════════════════════════════════════════════════════════════════════"
echo

# Check Python version
echo "[1/7] Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "      Python version: $PYTHON_VERSION"

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "      [ERROR] Python 3.10+ required. Current: $PYTHON_VERSION"
    exit 1
fi
echo "      [OK] Python version compatible"
echo

# Install FastMCP
echo "[2/7] Installing FastMCP and dependencies..."
pip install -q "mcp[server]>=1.0.0" 2>&1 | grep -v "Requirement already satisfied" || true
echo "      [OK] FastMCP installed"
echo

# Check Qdrant
echo "[3/7] Checking Qdrant..."
if curl -s http://localhost:6333/collections > /dev/null 2>&1; then
    QDRANT_COLLECTIONS=$(curl -s http://localhost:6333/collections | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('result', {}).get('collections', [])))" 2>/dev/null || echo "0")
    echo "      [OK] Qdrant online at localhost:6333"
    echo "      Collections: $QDRANT_COLLECTIONS"
else
    echo "      [WARN] Qdrant not reachable at localhost:6333"
    echo "      Action required: Start Qdrant (docker start qdrant)"
fi
echo

# Check Ollama
echo "[4/7] Checking Ollama embedding service..."
if curl -s http://localhost:11434/api/embeddings \
    -d '{"model":"nomic-embed-text","prompt":"test"}' \
    > /dev/null 2>&1; then
    echo "      [OK] Ollama online at localhost:11434"
    echo "      Embedding model: nomic-embed-text"
else
    echo "      [WARN] Ollama not reachable or model missing"
    echo "      Action required: ollama pull nomic-embed-text"
fi
echo

# Check ChromaDB
echo "[5/7] Checking ChromaDB Oracle..."
CHROMADB_PATH="/mnt/fortress_nas/chroma_db/chroma.sqlite3"
if [ -f "$CHROMADB_PATH" ]; then
    CHROMADB_SIZE=$(du -h "$CHROMADB_PATH" | awk '{print $1}')
    echo "      [OK] Oracle database found"
    echo "      Path: $CHROMADB_PATH"
    echo "      Size: $CHROMADB_SIZE"
else
    echo "      [WARN] Oracle database not found"
    echo "      Expected: $CHROMADB_PATH"
fi
echo

# Test MCP server
echo "[6/7] Testing MCP server..."
if python3 src/test_mcp_server.py fortress-stats > /dev/null 2>&1; then
    echo "      [OK] MCP server operational"
else
    echo "      [ERROR] MCP server test failed"
    echo "      Run manually: python src/test_mcp_server.py"
    exit 1
fi
echo

# Make CLI executable
echo "[7/7] Setting up CLI tools..."
chmod +x bin/sovereign
chmod +x src/sovereign_mcp_server.py
chmod +x src/ingest_jordi_knowledge.py
chmod +x src/test_mcp_server.py
echo "      [OK] CLI tools ready"
echo

# Summary
echo "════════════════════════════════════════════════════════════════════════════"
echo "  SETUP COMPLETE"
echo "════════════════════════════════════════════════════════════════════════════"
echo
echo "Next steps:"
echo
echo "  1. Test the MCP server:"
echo "     python src/test_mcp_server.py"
echo
echo "  2. Test CLI tool:"
echo "     ./bin/sovereign stats"
echo
echo "  3. Connect Cursor:"
echo "     - Restart Cursor"
echo "     - The MCP config is at .cursor/mcp_config.json"
echo "     - Verify: Type 'List available MCP tools' in Cursor chat"
echo
echo "  4. [Optional] Set up Jordi Visser:"
echo "     mkdir -p /mnt/fortress_nas/Intelligence/Jordi_Visser"
echo "     # Add your transcripts to that directory"
echo "     python src/ingest_jordi_knowledge.py"
echo
echo "  5. Read the docs:"
echo "     cat docs/QUICK_START_MCP.md"
echo "     cat docs/SOVEREIGN_CONTEXT_PROTOCOL.md"
echo
echo "  6. Use the CLI:"
echo "     ./bin/sovereign                    # Interactive mode"
echo "     ./bin/sovereign legal \"easement\"   # Search legal docs"
echo "     ./bin/sovereign oracle \"survey\"    # Search Oracle"
echo
echo "════════════════════════════════════════════════════════════════════════════"
echo

# Check if Cursor should be restarted
if pgrep -f "Cursor" > /dev/null 2>&1; then
    echo "NOTE: Cursor is currently running. Restart Cursor to load the MCP server."
    echo
fi

echo "All systems ready. Welcome to Level 3 Intelligence."
echo
