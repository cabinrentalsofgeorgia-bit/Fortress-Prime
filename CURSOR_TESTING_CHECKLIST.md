# Cursor MCP Testing Checklist

**Date:** 2026-02-15  
**Status:** Ready for Testing

---

## ✅ Pre-Testing Verification

Before testing in Cursor chat, verify:

- [x] MCP config exists: `.cursor/mcp_config.json` ✅
- [x] FastMCP installed ✅
- [x] Qdrant online: 3 collections ✅
- [x] ChromaDB online: 224K vectors ✅
- [x] MCP server tested: All tools working ✅
- [x] CLI tested: `./bin/sovereign` functional ✅
- [ ] **Cursor restarted** (REQUIRED!)

---

## 🔄 Step 1: Restart Cursor (CRITICAL)

**You MUST restart Cursor for MCP config to load!**

### Option A: Normal Restart
```
1. Close ALL Cursor windows (File > Exit or Cmd/Ctrl+Q)
2. Wait 3-5 seconds
3. Reopen Cursor from your applications
```

### Option B: Force Restart
```bash
pkill -9 -f Cursor
sleep 3
cursor &
```

**After restart, come back to this chat and continue with Step 2.**

---

## 🧪 Step 2: Verify MCP Connection

### Test 2.1: List Tools

**In Cursor chat, type:**
```
List available MCP tools
```

**Expected Result:**
```
fortress-prime-sovereign server with 7 tools:
- search_jordi_knowledge
- search_fortress_legal
- search_oracle
- search_email_intel
- list_collections
- get_fortress_stats
- get_jordi_status
```

**Status:** [ ] Pass [ ] Fail

**If FAIL:** See Troubleshooting section below

---

## 🎯 Step 3: Basic Function Tests

### Test 3.1: System Health

**Query:**
```
Get fortress stats
```

**Expected Response:**
```json
{
  "timestamp": "2026-02-15T...",
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

**Status:** [ ] Pass [ ] Fail

---

### Test 3.2: List Collections

**Query:**
```
List all available Qdrant collections
```

**Expected Response:**
```json
{
  "collections": [
    {"name": "fortress_knowledge", "vectors": 1279804},
    {"name": "email_embeddings", "vectors": 56635},
    {"name": "legal_library", "vectors": 15596}
  ]
}
```

**Status:** [ ] Pass [ ] Fail

---

## 🔍 Step 4: Knowledge Search Tests

### Test 4.1: Oracle Search (ChromaDB)

**Query:**
```
Search the Oracle for "Toccoa Heights"
```

**Expected Results:**
- Should find ~10 documents
- File names like: "Construction of Toccoa He.pdf", "Survey Lot 6.pdf"
- Should show file paths and existence status

**Status:** [ ] Pass [ ] Fail

**Documents Found:** _______

---

### Test 4.2: Legal Document Search

**Query:**
```
Search fortress legal documents for "easement rights"
```

**Expected Results:**
- Should return legal document chunks
- Should show file_name, category, text preview, score
- Should cite sources from legal_library collection (15,596 vectors)

**Status:** [ ] Pass [ ] Fail

**Documents Found:** _______

---

### Test 4.3: Email Intelligence Search

**Query:**
```
Search email intelligence for "vendor invoice" in the REAL_ESTATE division
```

**Expected Results:**
- Should return email excerpts
- Should show sender, subject, date, body_preview
- Should be filtered by division="REAL_ESTATE"

**Status:** [ ] Pass [ ] Fail

**Emails Found:** _______

---

## 🎨 Step 5: Natural Language Tests

### Test 5.1: Multi-Step Legal Research

**Query:**
```
I need to understand easement rights on Morgan Ridge property. Search the legal documents and summarize what you find, including specific document names and relevant clauses.
```

**Expected Behavior:**
1. Cursor calls `search_fortress_legal("easement rights Morgan Ridge")`
2. Gets relevant chunks from 15.6K legal vectors
3. Summarizes findings with citations

**Status:** [ ] Pass [ ] Fail

**Notes:**
```




```

---

### Test 5.2: Historical Document Recovery

**Query:**
```
Find any documents related to Toccoa Heights construction, surveys, or permits in our archives. List the files found and tell me if they still exist on disk.
```

**Expected Behavior:**
1. Cursor calls `search_oracle("Toccoa Heights construction survey permit")`
2. Searches 224K vectors in ChromaDB
3. Returns file list with existence status

**Status:** [ ] Pass [ ] Fail

**Documents Found:**
```




```

---

### Test 5.3: System Health Check

**Query:**
```
Give me a complete health check of the Fortress Prime knowledge systems. Check Qdrant status, ChromaDB status, show me what collections are available, and give me vector counts for each.
```

**Expected Behavior:**
1. Calls `get_fortress_stats()`
2. Calls `list_collections()`
3. Formats comprehensive report

**Status:** [ ] Pass [ ] Fail

**Summary:**
```




```

---

### Test 5.4: Cross-Database Search

**Query:**
```
Search both the legal library and the Oracle for documents about "septic systems" or "septic easements". Show me what's in each database and compare the results.
```

**Expected Behavior:**
1. Calls `search_fortress_legal("septic easement")`
2. Calls `search_oracle("septic systems")`
3. Compares and synthesizes results

**Status:** [ ] Pass [ ] Fail

**Legal Results:** _______
**Oracle Results:** _______

---

## 🧬 Step 6: Persona Tests (Godhead Prompts)

### Test 6.1: Get Jordi Godhead

**Query:**
```
Show me the Jordi Visser persona prompt
```

**Expected Response:**
- Should return ~1,690 character system prompt
- Should describe Jordi's personality, beliefs, communication style
- Should mention: contrarian, risk-focused, Bitcoin/crypto

**Status:** [ ] Pass [ ] Fail

---

### Test 6.2: Check Jordi Status

**Query:**
```
What is the status of the Jordi Visser knowledge base?
```

**Expected Response:**
```json
{
  "collection": "jordi_intel",
  "status": "not_created",
  "vectors": 0,
  "note": "Collection needs to be created and populated",
  "source_files": 0,
  "source_path": "/mnt/fortress_nas/Intelligence/Jordi_Visser (not found)"
}
```

**Status:** [ ] Pass [ ] Fail

---

## 🚀 Step 7: Advanced Integration Tests

### Test 7.1: Multi-Tool Query

**Query:**
```
I need a complete intelligence briefing: 
1. Show me system health
2. List all collections
3. Search for any documents about "property acquisition"
4. Search emails about the same topic
```

**Expected Behavior:**
- Should call multiple tools in sequence
- Should synthesize results into coherent briefing

**Status:** [ ] Pass [ ] Fail

---

### Test 7.2: Context-Aware Follow-Up

**First Query:**
```
Search the Oracle for "Toccoa Heights survey"
```

**Follow-Up Query:**
```
Now search the legal library for any easements or deeds related to those properties
```

**Expected Behavior:**
- Cursor should understand context from first query
- Should search legal docs with related terms

**Status:** [ ] Pass [ ] Fail

---

## 📊 Test Results Summary

| Test Category | Tests | Passed | Failed |
|---------------|-------|--------|--------|
| MCP Connection | 1 | [ ] | [ ] |
| Basic Functions | 2 | [ ] | [ ] |
| Knowledge Search | 3 | [ ] | [ ] |
| Natural Language | 4 | [ ] | [ ] |
| Persona Tests | 2 | [ ] | [ ] |
| Advanced | 2 | [ ] | [ ] |
| **TOTAL** | **14** | **__** | **__** |

---

## 🔧 Troubleshooting

### Issue 1: MCP Tools Not Showing

**Symptoms:** "List available MCP tools" shows no fortress-prime-sovereign

**Solutions:**

1. **Verify Cursor restarted:**
   ```bash
   ps aux | grep Cursor
   # Should show fresh process with recent start time
   ```

2. **Check Developer Console:**
   - In Cursor: `Help > Toggle Developer Tools`
   - Click `Console` tab
   - Search for "MCP" or "fortress-prime"
   - Look for error messages

3. **Verify config location:**
   ```bash
   ls -la /home/admin/Fortress-Prime/.cursor/mcp_config.json
   cat /home/admin/Fortress-Prime/.cursor/mcp_config.json
   ```

4. **Force restart:**
   ```bash
   pkill -9 -f Cursor
   sleep 3
   cursor &
   ```

---

### Issue 2: Tools Show But Queries Fail

**Symptoms:** MCP tools visible, but queries return errors

**Solutions:**

1. **Test MCP server manually:**
   ```bash
   cd /home/admin/Fortress-Prime
   python3 src/test_mcp_server.py fortress-stats
   ```

2. **Check infrastructure:**
   ```bash
   ./bin/sovereign stats
   ./bin/sovereign collections
   ```

3. **Verify Qdrant:**
   ```bash
   curl -H "api-key: ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d" \
     http://localhost:6333/collections
   ```

4. **Check ChromaDB:**
   ```bash
   ls -lh /mnt/fortress_nas/chroma_db/chroma.sqlite3
   ```

---

### Issue 3: Empty Results

**Symptoms:** Searches return no documents

**Solutions:**

1. **Test CLI search:**
   ```bash
   ./bin/sovereign oracle "Toccoa"
   ./bin/sovereign legal "easement"
   ```

2. **Verify data:**
   ```bash
   # Check Qdrant collections
   ./bin/sovereign collections
   
   # Check ChromaDB
   sqlite3 /mnt/fortress_nas/chroma_db/chroma.sqlite3 \
     "SELECT COUNT(*) FROM embedding_metadata WHERE key='source'"
   ```

---

### Issue 4: Slow Performance

**Symptoms:** Queries take > 30 seconds

**Solutions:**

1. **Check system load:**
   ```bash
   top
   # Look for high CPU/memory usage
   ```

2. **Verify Ollama is running:**
   ```bash
   curl http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'
   ```

3. **Restart services:**
   ```bash
   docker restart fortress-qdrant
   ```

---

## ✅ Success Criteria

**Step 3 is COMPLETE when:**

- [x] All 14 tests pass
- [x] MCP tools visible in Cursor
- [x] Searches return relevant results
- [x] Natural language queries work
- [x] Multi-tool queries function correctly

---

## 📁 Files Reference

**Test Scripts:**
- `VERIFY_MCP_CONNECTION.sh` - Pre-test verification
- `CURSOR_TESTING_CHECKLIST.md` - This file
- `CURSOR_MCP_TEST_QUERIES.md` - Additional test queries

**Configuration:**
- `.cursor/mcp_config.json` - MCP server config
- `src/sovereign_mcp_server.py` - MCP server code

**Documentation:**
- `STEP3_CURSOR_RESTART_INSTRUCTIONS.md` - Restart guide
- `TEST_RESULTS_STEP2.md` - Infrastructure tests
- `README_SOVEREIGN_MCP.md` - Main overview

---

## 🎉 After All Tests Pass

Once all tests complete successfully:

1. **You have Level 3 Intelligence operational!**
   - 1,576,244 vectors accessible via natural language
   - Unified context across Cursor, CLI, and future tools
   - No more copy-paste between interfaces

2. **Next: Set up Jordi Visser**
   ```bash
   mkdir -p /mnt/fortress_nas/Intelligence/Jordi_Visser
   # Add transcripts
   python src/ingest_jordi_knowledge.py
   ```

3. **Integrate with existing tools**
   - Add to yltra scripts
   - Connect to deepseek_max_launch.sh
   - Use in automation

---

**Good luck with testing!** 🚀

**Start with:** Restart Cursor, then "List available MCP tools"
