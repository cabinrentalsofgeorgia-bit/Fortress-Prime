# Sovereign Integration Examples

**Your existing tools now have access to the Hive Mind!**

## 🎯 Quick Start

You now have two new commands that integrate Sovereign with your LLMs:

### 1. **sovereign-yltra** (for yltra/ultra)
```bash
sovereign-yltra jordi "What is your Bitcoin outlook?"
sovereign-yltra legal "Summarize easement law"
sovereign-yltra "What's happening in crypto?"  # defaults to jordi
```

### 2. **sovereign-deepseek** (direct DeepSeek-R1)
```bash
sovereign-deepseek jordi "Bitcoin analysis"
sovereign-deepseek legal "Morgan Ridge easement"
sovereign-deepseek crog "Properties needing turnover"
```

---

## 📚 How It Works

Both commands follow the same pattern:

```
1. Load Godhead prompt (persona)
2. Search knowledge base for context
3. Combine both and send to LLM
4. Return enhanced response
```

**Before (fragmented):**
```bash
# You had to manually:
yltra "What's your Bitcoin outlook?"
# Generic response, no Jordi personality, no context
```

**After (unified):**
```bash
sovereign-yltra jordi "What's your Bitcoin outlook?"
# Gets:
# - Jordi's personality (contrarian, risk-focused)
# - Relevant context from knowledge base
# - Unified response with persona + data
```

---

## 🎨 Usage Examples

### Example 1: Jordi Visser Market Analysis

**Command:**
```bash
sovereign-deepseek jordi "What is your outlook on Bitcoin for 2024?"
```

**What happens:**
1. Loads Jordi Godhead (contrarian, risk-focused personality)
2. Searches Jordi knowledge base (or Oracle as fallback)
3. DeepSeek-R1 responds as Jordi with relevant context
4. Strips `<think>` tags automatically

**Expected response style:**
```
Based on the current macro environment and on-chain metrics, I'm cautiously 
optimistic on Bitcoin for 2024. Here's why:

Risk factors to watch:
- Liquidity conditions
- Regulatory pressure
- Exit liquidity for late entrants

Don't marry your bags. Take profits.
```

---

### Example 2: Legal Research

**Command:**
```bash
sovereign-yltra legal "What are the easement rights on Morgan Ridge?"
```

**What happens:**
1. Loads Legal Counselor Godhead (precise, citation-heavy)
2. Searches 15,596 legal documents for "easement Morgan Ridge"
3. Returns response with specific document citations

**Expected response:**
```
Based on the legal documents:

[Source: #127 Knight's Trial Exhibits.pdf]
The easement on Morgan Ridge includes:
1. A 10' width easement along the Blue Ridge Scenic Railway right-of-way
2. Foot-use only for owners, agents, invitees, and guests
3. Branches off onto Lot 9 at the nearest pathway point

[Source: GaryKnight_14.pdf - Deposition Transcript]
The easement runs parallel to the Toccoa River between the railway and river.

⚠️ This is informational only. Consult an attorney for legal decisions.
```

---

### Example 3: CROG Operations

**Command:**
```bash
sovereign-deepseek crog "What properties need turnover this week?"
```

**What happens:**
1. Loads CROG Controller Godhead (operations-focused)
2. Searches Oracle + emails for turnover/cleaning/maintenance
3. Returns operational briefing

**Expected response:**
```
Based on recent communications and operational data:

Properties requiring turnover:
- Check reservation calendar in Streamline VRS
- Search recent emails for guest checkout notifications
- Review maintenance logs for pending turnovers

Recommendation: Run the following to get current data:
./bin/sovereign email "turnover cleaning" --division REAL_ESTATE
```

---

### Example 4: Multi-Step Research

**Use Case:** Deep dive on Toccoa Heights property

**Command:**
```bash
sovereign-yltra legal "Search for all documents about Toccoa Heights easements, surveys, and legal disputes"
```

**What happens:**
1. Legal Counselor persona loads
2. Searches legal_library (15.6K vectors) for all Toccoa references
3. Returns comprehensive legal brief with citations

**Then follow up:**
```bash
sovereign-yltra "Now search the general archives for construction documents"
```

---

## 🔧 Advanced Usage

### Custom Persona Script

Create your own wrapper for specific use cases:

```bash
#!/bin/bash
# crypto-morning-briefing.sh

echo "📊 Crypto Morning Briefing with Jordi Visser"
echo ""

sovereign-deepseek jordi "Give me a quick morning briefing on Bitcoin, Ethereum, and any significant moves in crypto. Focus on risk factors."
```

---

### Integration with Existing Scripts

**Your `deepseek_max_launch.sh`:**

**Before:**
```bash
ollama run deepseek-r1:70b "$@"
```

**After (with Sovereign):**
```bash
# Check if query relates to crypto/market
if [[ "$*" =~ (bitcoin|crypto|market|trading) ]]; then
    sovereign-deepseek jordi "$@"
else
    ollama run deepseek-r1:70b "$@"
fi
```

---

### Batch Processing

**Search multiple knowledge bases:**
```bash
#!/bin/bash
# research-toccoa.sh

echo "Searching Legal Library..."
sovereign-yltra legal "Toccoa Heights easements" > toccoa-legal.txt

echo "Searching General Archives..."
./bin/sovereign oracle "Toccoa Heights construction survey" > toccoa-archive.txt

echo "Research complete!"
```

---

## 📊 Available Commands

### sovereign-yltra

**Usage:**
```bash
sovereign-yltra [persona] <query>
```

**Personas:**
- `jordi` - Jordi Visser (crypto/market analysis)
- `legal` - Legal Counselor (15.6K legal docs)
- `crog` - CROG Controller (property operations)
- `comp` - Comptroller (financial oversight)

**Examples:**
```bash
sovereign-yltra jordi "Bitcoin analysis"
sovereign-yltra legal "easement law"
sovereign-yltra crog "property turnover"
sovereign-yltra "general query"  # defaults to jordi
```

---

### sovereign-deepseek

**Usage:**
```bash
sovereign-deepseek [persona] <query>
```

**Same personas as above, uses DeepSeek-R1:70b directly**

**Examples:**
```bash
sovereign-deepseek jordi "What's your take on Ethereum?"
sovereign-deepseek legal "Summarize the 7IL lawsuit"
sovereign-deepseek "Market analysis"  # defaults to jordi
```

---

### Original sovereign CLI

**Still available for direct queries:**
```bash
./bin/sovereign stats              # System health
./bin/sovereign oracle "query"     # Search 224K vectors
./bin/sovereign legal "query"      # Search 15.6K legal docs
./bin/sovereign email "query"      # Search 56K emails
./bin/sovereign collections        # List all collections
./bin/sovereign prompt jordi       # Get raw Godhead
```

---

## 🎯 Real-World Workflow Example

**Scenario:** You're researching a property dispute

### Step 1: Legal Research
```bash
sovereign-yltra legal "Search for all easement disputes involving Blue Ridge Scenic Railway and Toccoa River access"
```

**Result:** Get legal brief with citations from 15.6K legal documents

### Step 2: Historical Context
```bash
./bin/sovereign oracle "Blue Ridge Scenic Railway Toccoa"
```

**Result:** Find 10+ historical documents, surveys, correspondence

### Step 3: Communication History
```bash
./bin/sovereign email "railway access dispute" --division LEGAL_ADMIN
```

**Result:** Find relevant email threads

### Step 4: Synthesize with Jordi (if financial implications)
```bash
sovereign-deepseek jordi "If we have to pay $X for an easement dispute settlement, how does this impact our cash position and property valuations?"
```

**Result:** Jordi's risk analysis from financial perspective

---

## 🚀 Power User Tips

### 1. **Pipe to File for Later**
```bash
sovereign-deepseek legal "Full analysis of Morgan Ridge easements" > morgan-ridge-analysis.txt
```

### 2. **Chain Commands**
```bash
# Get context, then analyze
CONTEXT=$(./bin/sovereign legal "easement")
echo "Context: $CONTEXT" | sovereign-deepseek legal "Analyze this for risk factors"
```

### 3. **Environment Variables**
```bash
# Set default persona
export SOVEREIGN_DEFAULT_PERSONA="legal"
sovereign-yltra "easement law"  # Uses legal automatically
```

### 4. **Interactive Mode**
```bash
# Start an interactive session
./bin/sovereign
# Then use: legal, oracle, email, stats, etc.
```

---

## 🎉 What You Now Have

### Before Integration
- Separate tools: yltra, deepseek, knowledge bases
- Manual context gathering
- No consistent persona
- Copy-paste between interfaces

### After Integration
- ✅ **Unified Intelligence**: One command accesses everything
- ✅ **Consistent Personas**: Jordi, Legal, CROG, Comp always available
- ✅ **Auto Context**: Knowledge base searched automatically
- ✅ **1.57M Vectors**: All accessible via natural language
- ✅ **CLI First**: Works immediately, no Cursor needed

---

## 📁 Files Created

**Integration Scripts:**
- `/home/admin/Fortress-Prime/bin/sovereign-yltra` - Yltra wrapper
- `/home/admin/Fortress-Prime/bin/sovereign-deepseek` - DeepSeek wrapper
- `/home/admin/Fortress-Prime/bin/sovereign` - Direct CLI (already existed)

**Documentation:**
- `INTEGRATION_EXAMPLES.md` - This file
- `CURSOR_TESTING_CHECKLIST.md` - Cursor testing guide
- `MCP_INTEGRATION_GUIDE.md` - Full integration patterns

---

## 🔧 Troubleshooting

### "command not found: yltra"
**Solution:** The wrapper will try ultra or ollama as fallback

### "Failed to load Godhead"
**Solution:** Check sovereign CLI works:
```bash
./bin/sovereign prompt jordi
```

### "No context found"
**Solution:** Normal for some queries. The system proceeds with persona only

### "DeepSeek not responding"
**Solution:** Check Ollama:
```bash
ollama list  # Verify deepseek-r1:70b is installed
ollama ps    # Check if running
```

---

## 🎯 Test It Now!

Try these commands right now:

```bash
# Test 1: Jordi personality
sovereign-deepseek jordi "What's your take on Bitcoin?"

# Test 2: Legal search
sovereign-deepseek legal "Summarize easement law"

# Test 3: Direct CLI
./bin/sovereign oracle "Toccoa"

# Test 4: System health
./bin/sovereign stats
```

---

**The Hive Mind is now integrated with your existing tools!** 🐝

No Cursor required - everything works via CLI immediately.
