# Cursor MCP — Quick Test Guide

**Time to complete:** 5 minutes  
**Prerequisite:** Cursor must be restarted

---

## 🚀 Quick Test Sequence

Copy and paste these queries into Cursor chat **one at a time**:

---

### 1. Verify Connection ✅
```
List available MCP tools
```
**Expected:** Should show `fortress-prime-sovereign` with 7 tools

---

### 2. System Health 🏥
```
Get fortress stats
```
**Expected:** JSON with Qdrant (3 collections), ChromaDB (224K vectors), NAS (mounted)

---

### 3. Oracle Search 🔍
```
Search the Oracle for "Toccoa Heights"
```
**Expected:** ~10 PDF documents about Toccoa Heights construction, surveys, etc.

---

### 4. Legal Search ⚖️
```
Search fortress legal documents for "easement"
```
**Expected:** Legal document chunks with file names, categories, text previews

---

### 5. Collections List 📚
```
Show me all available Qdrant collections
```
**Expected:** 3 collections: fortress_knowledge (1.28M), email_embeddings (56K), legal_library (15.6K)

---

## ✅ Success = All 5 Tests Return Data

If all 5 queries return results, **congratulations!** The Hive Mind is operational. 🐝

---

## ❌ If Tests Fail

**1. MCP tools don't show:**
- Restart Cursor completely (File > Exit, then reopen)
- Check: `Help > Toggle Developer Tools > Console` for errors

**2. Queries fail:**
```bash
# Test CLI as fallback
./bin/sovereign stats
./bin/sovereign oracle "Toccoa"
```

**3. Empty results:**
```bash
# Verify data
./bin/sovereign collections
```

---

## 🎨 Advanced Tests (After Basic Tests Pass)

### Natural Language Query
```
I need to find any documents about Toccoa Heights construction, surveys, or permits. Search both the Oracle and legal library, then summarize what you find with specific file names.
```

### Multi-Tool Query
```
Give me a complete intelligence briefing: system health, available collections, and search for any documents about "property acquisition"
```

### Persona Query
```
Show me the Jordi Visser persona prompt and check the status of his knowledge base
```

---

## 📊 What You Get

Once tests pass, you have access to:

- **1,279,804** fortress_knowledge vectors
- **224,209** Oracle (general knowledge) vectors  
- **56,635** email archive vectors
- **15,596** legal library vectors
- **Total: 1,576,244 vectors** searchable via natural language

---

**Start testing now!** 🚀

First step: **Restart Cursor if you haven't already**
