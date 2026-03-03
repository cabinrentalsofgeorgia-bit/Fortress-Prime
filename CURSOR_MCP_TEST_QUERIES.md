# Cursor MCP Test Queries

After restarting Cursor, use these test queries to verify the MCP server connection.

## Step 1: Verify MCP Connection

In Cursor chat, type:

```
List available MCP tools
```

**Expected Response:** Should show available tools from `fortress-prime-sovereign` server:
- search_fortress_legal
- search_oracle
- search_email_intel
- list_collections
- get_fortress_stats
- get_jordi_status

---

## Step 2: Test Basic Queries

### Test 1: System Status
```
Get fortress stats
```

**Expected:** JSON response showing Qdrant (3 collections), ChromaDB (224K vectors), NAS (mounted)

### Test 2: List Collections
```
Show me the available Qdrant collections
```

**Expected:** List of 3 collections:
- fortress_knowledge (1.28M vectors)
- email_embeddings (56K vectors)
- legal_library (15.6K vectors)

---

## Step 3: Test Knowledge Search

### Test 3A: Legal Search
```
Search fortress legal documents for "easement rights"
```

**Expected:** JSON with relevant legal document chunks, file names, categories, scores

### Test 3B: Oracle Search (General Knowledge)
```
Search the Oracle for "Toccoa Heights survey"
```

**Expected:** Multiple PDF documents related to Toccoa Heights surveys, with file paths

### Test 3C: Email Search
```
Search email intelligence for "vendor invoices" in the REAL_ESTATE division
```

**Expected:** Email excerpts matching the query, with sender, subject, date

---

## Step 4: Test Godhead Prompts (Personas)

### Test 4A: Get Jordi Godhead
```
Show me the Jordi Visser persona prompt
```

**Expected:** ~1,690 character system prompt defining Jordi's personality, beliefs, communication style

### Test 4B: Check Jordi Status
```
What is the status of the Jordi Visser knowledge base?
```

**Expected:** JSON showing collection status (not created yet), source files count

---

## Step 5: Combined Queries (Natural Language)

Once the basic tests work, try these natural language queries:

### Query 1: Legal Research
```
I need to understand easement rights on Morgan Ridge property. Search the legal documents and summarize what you find.
```

**This will:**
1. Call `search_fortress_legal("easement rights Morgan Ridge")`
2. Get relevant legal document chunks
3. Summarize using Claude/your current model

### Query 2: Historical Document Search
```
Find any documents related to Toccoa Heights construction or surveys in our archives.
```

**This will:**
1. Call `search_oracle("Toccoa Heights construction survey")`
2. Return historical documents from ChromaDB
3. List file locations with existence status

### Query 3: Email Intelligence
```
Search our real estate emails for any communications about maintenance or repairs.
```

**This will:**
1. Call `search_email_intel("maintenance repairs", division="REAL_ESTATE")`
2. Return relevant email excerpts
3. Show sender, subject, dates

---

## Step 6: Advanced Multi-Tool Queries

### Query 6A: Cross-Database Search
```
Search both the legal library and the Oracle for documents about "septic systems" or "septic easements". Compare what's in each database.
```

**This will:**
1. Call `search_fortress_legal("septic easement")`
2. Call `search_oracle("septic systems")`
3. Compare and synthesize results

### Query 6B: System Health Check
```
Give me a complete health check of the Fortress Prime knowledge systems. Check Qdrant, ChromaDB, and show me what collections are available.
```

**This will:**
1. Call `get_fortress_stats()`
2. Call `list_collections()`
3. Format a comprehensive report

---

## Troubleshooting

### Issue 1: "MCP tools not showing"

**Solution:**
1. Close Cursor completely (not just the window, kill the process)
2. Run: `pkill -f Cursor`
3. Restart Cursor
4. Check Developer Tools (Help > Toggle Developer Tools) for errors

### Issue 2: "Cannot connect to MCP server"

**Check:**
```bash
# Verify config location
cat /home/admin/Fortress-Prime/.cursor/mcp_config.json

# Test MCP server manually
python /home/admin/Fortress-Prime/src/test_mcp_server.py fortress-stats

# Check Python path
which python3
```

### Issue 3: "MCP tools show but queries fail"

**Verify infrastructure:**
```bash
# Test from terminal first
./bin/sovereign stats
./bin/sovereign collections
./bin/sovereign oracle "test"

# Check logs if available
# (Cursor may show MCP logs in Developer Tools)
```

---

## Expected Behavior

### ✅ **Working Correctly:**
- Tools appear in Cursor's tool list
- Queries return JSON results
- Natural language queries trigger appropriate tools
- Results are formatted and summarized by Cursor AI

### ❌ **Not Working:**
- No tools visible after restart
- "Tool not found" errors
- Empty results from all queries
- Connection timeout errors

---

## Next Steps After Testing

Once all tests pass:

1. **Start using the Hive Mind in your daily workflow:**
   - Legal research: Query the 15.6K legal documents
   - Document recovery: Search the 224K Oracle vectors
   - Email intelligence: Query 56K classified emails

2. **Set up Jordi Visser:**
   ```bash
   mkdir -p /mnt/fortress_nas/Intelligence/Jordi_Visser
   # Add transcripts
   python src/ingest_jordi_knowledge.py
   ```

3. **Replicate for other personas:**
   - Raoul Pal (Real Vision)
   - Lyn Alden (Macro + Bitcoin)
   - Balaji Srinivasan (Tech + Crypto)
   - See: `docs/MCP_INTEGRATION_GUIDE.md`

4. **Integrate with CLI tools:**
   - Add Sovereign to your `yltra` scripts
   - Connect to `deepseek_max_launch.sh`
   - Use in automation scripts

---

## Quick Reference: MCP Server Details

**Server Name:** `fortress-prime-sovereign`

**Command:** `python /home/admin/Fortress-Prime/src/sovereign_mcp_server.py`

**Tools:**
- `search_jordi_knowledge(query, top_k, date_filter)` → Jordi Visser transcripts
- `search_fortress_legal(query, top_k, category)` → Legal documents (15.6K vectors)
- `search_oracle(query, max_results)` → General knowledge (224K vectors)
- `search_email_intel(query, division, top_k)` → Email archive (56K vectors)
- `list_collections()` → Qdrant inventory
- `get_fortress_stats()` → System health
- `get_jordi_status()` → Jordi collection status

**Resources (Godheads):**
- `sovereign://godhead/jordi` → Jordi Visser persona
- `sovereign://godhead/legal` → Legal Counselor persona
- `sovereign://godhead/crog` → CROG Controller persona
- `sovereign://godhead/comp` → Comptroller persona
- `sovereign://atlas` → Full Fortress org chart

---

## Success Criteria

You'll know Step 3 is complete when:

✅ Cursor shows MCP tools after restart
✅ `Get fortress stats` returns system info
✅ `Search the Oracle for "Toccoa"` finds documents
✅ `Search legal documents for "easement"` returns results
✅ Natural language queries trigger appropriate tools

---

**Ready to restart Cursor!**

Close Cursor completely, then reopen and start with the Step 1 test query above.
