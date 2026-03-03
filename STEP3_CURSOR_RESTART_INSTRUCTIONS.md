# Step 3: Connect Cursor to MCP Server

**Status:** Ready to Execute  
**Estimated Time:** 5 minutes

---

## Prerequisites ✅

- [x] MCP server code created (`src/sovereign_mcp_server.py`)
- [x] FastMCP installed
- [x] Configuration file created (`.cursor/mcp_config.json`)
- [x] Qdrant API key configured
- [x] All tests passing (Step 2 complete)

---

## Step 3A: Restart Cursor

### Option 1: Normal Restart (Recommended)

1. **Close Cursor completely**
   - Click: File > Exit (or Cmd/Ctrl+Q)
   - Make sure ALL Cursor windows close

2. **Wait 2-3 seconds**

3. **Reopen Cursor**
   - Launch from your applications menu
   - Or run: `cursor` (if in PATH)

### Option 2: Force Restart (If Option 1 Doesn't Work)

```bash
# Kill any running Cursor processes
pkill -f Cursor

# Wait 3 seconds
sleep 3

# Restart Cursor
cursor &
```

---

## Step 3B: Verify MCP Connection

### Test 1: Check MCP Tools Are Visible

In Cursor chat, type:

```
List available MCP tools
```

**Expected Response:**
```
Available tools from fortress-prime-sovereign:
- search_jordi_knowledge
- search_fortress_legal
- search_oracle
- search_email_intel
- list_collections
- get_fortress_stats
- get_jordi_status
```

**If you see these tools, ✅ SUCCESS! Continue to Test 2.**

**If not visible, see Troubleshooting below.**

---

### Test 2: Test Basic Query

```
Get fortress stats
```

**Expected Response:**
```json
{
  "qdrant": {
    "status": "online",
    "collections_count": 3
  },
  "chromadb": {
    "status": "online",
    "vectors": 224209,
    "files": 16883
  },
  "nas": {
    "mounted": true
  }
}
```

---

### Test 3: Test Oracle Search

```
Search the Oracle for "Toccoa"
```

**Expected Response:**
Should return JSON with multiple documents:
- Construction of Toccoa He.pdf
- Survey Lot 6.pdf
- Railroad Research, Fannin.PDF
- (plus 7+ more)

---

### Test 4: Test Legal Search

```
Search fortress legal documents for "easement"
```

**Expected Response:**
Should return legal document chunks with:
- file_name
- category (e.g., "easement", "property_deed")
- text preview
- score

---

## Step 3C: Test Natural Language Queries

Once basic tests work, try these natural language queries:

### Query 1: Multi-Step Legal Research
```
I need to find any documents about easement rights on Morgan Ridge. Search the legal library and summarize what you find.
```

**This will:**
1. Trigger `search_fortress_legal("easement rights Morgan Ridge")`
2. Get relevant chunks from 15.6K legal vectors
3. Summarize the findings

---

### Query 2: Historical Document Recovery
```
Find documents related to Toccoa Heights construction, surveys, or permits in our archives.
```

**This will:**
1. Trigger `search_oracle("Toccoa Heights construction survey permit")`
2. Search 224K vectors in ChromaDB
3. Return file locations and existence status

---

### Query 3: System Health Check
```
Give me a complete status report of the Fortress Prime knowledge systems.
```

**This will:**
1. Call `get_fortress_stats()`
2. Call `list_collections()`
3. Format a comprehensive report

---

## Troubleshooting

### Issue 1: "MCP tools not showing after restart"

**Diagnosis:**
```bash
# Check config exists
cat /home/admin/Fortress-Prime/.cursor/mcp_config.json

# Verify Python path
which python3

# Test MCP server manually
python3 /home/admin/Fortress-Prime/src/test_mcp_server.py fortress-stats
```

**Solutions:**

**A) Check Cursor Developer Console:**
1. In Cursor: Help > Toggle Developer Tools
2. Look for errors in Console tab
3. Search for "MCP" or "fortress-prime"

**B) Verify Python Path in Config:**
```bash
# Get Python path
which python3

# Update .cursor/mcp_config.json if needed
# Change "command": "python" to full path if necessary
```

**C) Force Kill and Restart:**
```bash
pkill -9 -f Cursor
sleep 3
cursor &
```

---

### Issue 2: "Connection refused" or "Cannot connect"

**Check MCP server runs manually:**
```bash
cd /home/admin/Fortress-Prime
python3 src/sovereign_mcp_server.py
```

**Look for:**
```
SOVEREIGN CONTEXT PROTOCOL
MCP Server Online
Resources: 5
Tools: 7
```

**If server starts manually but Cursor can't connect:**
- Check firewall settings
- Verify file permissions: `ls -l src/sovereign_mcp_server.py`
- Try absolute paths in mcp_config.json

---

### Issue 3: "Tools visible but queries return errors"

**Verify infrastructure:**
```bash
# Test Qdrant
curl http://localhost:6333/collections \
  -H "api-key: ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d"

# Test ChromaDB
ls -lh /mnt/fortress_nas/chroma_db/chroma.sqlite3

# Test from CLI
./bin/sovereign stats
./bin/sovereign oracle "test"
```

---

### Issue 4: "Results are empty"

**Check data sources:**
```bash
# Verify Qdrant collections
./bin/sovereign collections

# Verify ChromaDB vectors
sqlite3 /mnt/fortress_nas/chroma_db/chroma.sqlite3 \
  "SELECT COUNT(*) FROM embedding_metadata WHERE key='source'"

# Test search directly
./bin/sovereign oracle "Toccoa"
```

---

## Alternative: Manual MCP Server Launch

If Cursor can't auto-start the server, you can run it manually:

### Terminal 1: Launch MCP Server
```bash
cd /home/admin/Fortress-Prime
python3 src/sovereign_mcp_server.py
```

**Keep this terminal open.**

### Terminal 2: Test Queries
Use CLI to verify:
```bash
./bin/sovereign stats
./bin/sovereign collections
./bin/sovereign oracle "Toccoa"
```

### Update Cursor Config
If manual launch is needed, update `.cursor/mcp_config.json` to use `stdio` transport instead of starting the server.

---

## Success Criteria

✅ **Step 3 is complete when:**

1. ✅ Cursor shows MCP tools after restart
2. ✅ "Get fortress stats" returns system information
3. ✅ "Search the Oracle for 'Toccoa'" finds documents
4. ✅ "Search legal documents for 'easement'" returns results
5. ✅ Natural language queries trigger the correct MCP tools

---

## What Happens Next

Once Step 3 is complete, you'll have:

### ✅ **Level 3 Intelligence Operational**

1. **Unified Context Across All Tools**
   - Same Godhead prompts in Cursor, CLI, and future web UIs
   - No more copy-paste between interfaces
   - Consistent persona behavior

2. **Instant Knowledge Access**
   - 15.6K legal documents at your fingertips
   - 224K general knowledge vectors (Oracle)
   - 56K classified emails
   - 1.28M fortress_knowledge vectors

3. **Natural Language Queries**
   - "Find easement documents about Morgan Ridge"
   - "What's in our Toccoa Heights archives?"
   - "Search emails about vendor invoices"

4. **Ready for Expansion**
   - Gather Jordi Visser transcripts
   - Add Raoul Pal, Lyn Alden, Balaji personas
   - Connect to yltra/ultra CLI tools
   - Integrate with automation scripts

---

## Quick Reference Card

**Config Location:** `/home/admin/Fortress-Prime/.cursor/mcp_config.json`

**Test Commands:**
```
List available MCP tools
Get fortress stats
Search the Oracle for "Toccoa"
Search legal documents for "easement"
```

**Manual Server:**
```bash
python3 /home/admin/Fortress-Prime/src/sovereign_mcp_server.py
```

**CLI Fallback:**
```bash
./bin/sovereign stats
./bin/sovereign oracle "query"
./bin/sovereign legal "query"
```

**Troubleshooting:**
```bash
# Check logs
Help > Toggle Developer Tools (in Cursor)

# Kill and restart
pkill -f Cursor && cursor &

# Verify manually
python3 src/test_mcp_server.py
```

---

## Final Notes

- **Cursor restart is required** (MCP config loaded on startup)
- **First launch may take 2-3 seconds** (MCP server initialization)
- **All queries are local** (no cloud APIs, Level 3 data sovereignty)
- **Test queries provided** in `CURSOR_MCP_TEST_QUERIES.md`

---

**Ready to proceed!**

**Next Action:** Close Cursor and reopen, then test with:
```
List available MCP tools
```

Good luck! 🚀
