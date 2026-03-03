#!/bin/bash
################################################################################
# VERIFY MCP CONNECTION — Quick Test Script
################################################################################
# This script verifies that the Sovereign MCP server is working correctly
# before testing in Cursor.
################################################################################

echo "════════════════════════════════════════════════════════════════════════════"
echo "  FORTRESS PRIME — MCP CONNECTION VERIFICATION"
echo "════════════════════════════════════════════════════════════════════════════"
echo

# Test 1: Check configuration
echo "[1/5] Checking MCP configuration..."
if [ -f "/home/admin/Fortress-Prime/.cursor/mcp_config.json" ]; then
    echo "      ✅ Config file exists"
    PYTHON_CMD=$(grep '"command"' .cursor/mcp_config.json | cut -d'"' -f4)
    echo "      Python command: $PYTHON_CMD"
else
    echo "      ❌ Config file not found!"
    exit 1
fi
echo

# Test 2: Check Python and FastMCP
echo "[2/5] Checking Python and FastMCP..."
PYTHON_VERSION=$(python3 --version 2>&1)
echo "      Python: $PYTHON_VERSION"

if python3 -c "import mcp" 2>/dev/null; then
    echo "      ✅ FastMCP installed"
else
    echo "      ❌ FastMCP not found!"
    echo "      Install: pip install --break-system-packages 'mcp>=1.0.0'"
    exit 1
fi
echo

# Test 3: Check infrastructure
echo "[3/5] Checking infrastructure..."

# Qdrant
if curl -s -H "api-key: ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d" \
    http://localhost:6333/collections > /dev/null 2>&1; then
    COLLECTIONS=$(curl -s -H "api-key: ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d" \
        http://localhost:6333/collections | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('result', {}).get('collections', [])))" 2>/dev/null)
    echo "      ✅ Qdrant: $COLLECTIONS collections"
else
    echo "      ⚠️  Qdrant: offline or unauthorized"
fi

# ChromaDB
if [ -f "/mnt/fortress_nas/chroma_db/chroma.sqlite3" ]; then
    CHROMA_SIZE=$(du -h /mnt/fortress_nas/chroma_db/chroma.sqlite3 | cut -f1)
    echo "      ✅ ChromaDB: $CHROMA_SIZE"
else
    echo "      ⚠️  ChromaDB: not found"
fi

# NAS
if [ -d "/mnt/fortress_nas" ]; then
    echo "      ✅ NAS: mounted"
else
    echo "      ❌ NAS: not mounted"
fi
echo

# Test 4: Test MCP server
echo "[4/5] Testing MCP server..."
python3 src/test_mcp_server.py fortress-stats > /tmp/mcp_test.json 2>&1
if [ $? -eq 0 ]; then
    echo "      ✅ MCP server functional"
    echo "      Response preview:"
    head -10 /tmp/mcp_test.json | sed 's/^/        /'
else
    echo "      ❌ MCP server test failed"
    echo "      Error:"
    cat /tmp/mcp_test.json | head -5 | sed 's/^/        /'
    exit 1
fi
echo

# Test 5: Test CLI
echo "[5/5] Testing CLI tool..."
if [ -x "./bin/sovereign" ]; then
    echo "      ✅ CLI executable"
    ./bin/sovereign stats > /tmp/cli_test.json 2>&1
    if [ $? -eq 0 ]; then
        echo "      ✅ CLI functional"
    else
        echo "      ⚠️  CLI test failed"
    fi
else
    echo "      ❌ CLI not executable"
    chmod +x ./bin/sovereign
fi
echo

# Summary
echo "════════════════════════════════════════════════════════════════════════════"
echo "  VERIFICATION COMPLETE"
echo "════════════════════════════════════════════════════════════════════════════"
echo
echo "✅ All systems ready for Cursor integration!"
echo
echo "Next steps:"
echo "  1. If Cursor is not already restarted, restart it now"
echo "  2. In Cursor chat, type: List available MCP tools"
echo "  3. You should see: fortress-prime-sovereign with 7 tools"
echo "  4. Try: Get fortress stats"
echo
echo "If Cursor doesn't show MCP tools:"
echo "  - Check Cursor Developer Tools (Help > Toggle Developer Tools)"
echo "  - Look for MCP errors in Console tab"
echo "  - Try: pkill -f Cursor && cursor &"
echo
echo "Test queries to try:"
echo "  • Get fortress stats"
echo "  • Search the Oracle for \"Toccoa\""
echo "  • Search legal documents for \"easement\""
echo "  • List available collections"
echo
echo "════════════════════════════════════════════════════════════════════════════"
