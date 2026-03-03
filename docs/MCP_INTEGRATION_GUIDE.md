# Sovereign MCP Integration Guide

**How to connect the Hive Mind to all your existing tools**

## Architecture Diagram

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                   SOVEREIGN CONTEXT PROTOCOL (MCP)                    ┃
┃                         The Hive Mind / Godhead                       ┃
┃  ┌────────────────────────────────────────────────────────────────┐  ┃
┃  │ Resources (Godhead Prompts)  │  Tools (Vector Search)          │  ┃
┃  │ - sovereign://godhead/jordi  │  - search_jordi_knowledge()     │  ┃
┃  │ - sovereign://godhead/legal  │  - search_fortress_legal()      │  ┃
┃  │ - sovereign://godhead/crog   │  - search_oracle()              │  ┃
┃  │ - sovereign://godhead/comp   │  - search_email_intel()         │  ┃
┃  │ - sovereign://atlas          │  - get_fortress_stats()         │  ┃
┃  └────────────────────────────────────────────────────────────────┘  ┃
┗━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                       │
      ┌────────────────┼────────────────┬────────────────┐
      │                │                │                │
┌─────▼─────┐    ┌─────▼─────┐    ┌────▼────┐    ┌─────▼─────┐
│  Cursor   │    │    CLI    │    │  yltra  │    │  Web UI   │
│  @jordi   │    │ sovereign │    │  ultra  │    │ Open WebUI│
│  @legal   │    │  command  │    │deepseek │    │  (future) │
└───────────┘    └───────────┘    └─────────┘    └───────────┘
      │                │                │                │
      └────────────────┼────────────────┴────────────────┘
                       │
      ┌────────────────┼────────────────┬────────────────┐
      │                │                │                │
┌─────▼─────┐    ┌─────▼─────┐    ┌────▼────┐    ┌─────▼─────┐
│  Qdrant   │    │ ChromaDB  │    │Postgres │    │   NAS     │
│ 2,455 vec │    │ 224K vec  │    │fortress │    │ Transcripts│
│legal_lib  │    │  Oracle   │    │   _db   │    │ Documents │
└───────────┘    └───────────┘    └─────────┘    └───────────┘

DATA FLOW:
1. User asks question in any interface (Cursor, CLI, Web)
2. Interface calls MCP server tool (search_jordi_knowledge, etc.)
3. MCP server fetches Godhead prompt (persona context)
4. MCP server queries vector DB (Qdrant/ChromaDB)
5. Results + Godhead prompt returned to interface
6. Interface forwards to LLM (DeepSeek-R1, Claude, etc.)
7. LLM answers with full persona + knowledge context
```

## Integration Patterns

### 1. Cursor Integration (Native MCP)

**Configuration:** `.cursor/mcp_config.json` (already created)

**Usage in Cursor:**
```
@fortress-prime-sovereign search_fortress_legal("easement rights")
@fortress-prime-sovereign search_oracle("Toccoa survey")
@fortress-prime-sovereign get_fortress_stats()
```

**Use Cases:**
- Deep code assistance with legal context
- Architecture decisions informed by past projects (Oracle search)
- Financial queries with Comptroller persona

---

### 2. CLI Tools Integration

#### Option A: Direct Python Import

For scripts that already use Python, import the MCP tools directly:

```python
#!/usr/bin/env python3
from src.sovereign_mcp_server import (
    search_jordi_knowledge,
    search_fortress_legal,
    search_oracle,
    get_jordi_prompt,
)

# Get Jordi's personality
godhead = get_jordi_prompt()

# Search Jordi's knowledge
context = search_jordi_knowledge("Bitcoin outlook", top_k=5)

# Now send to your LLM
# ... your LLM call here with godhead + context ...
```

#### Option B: CLI Wrapper

Use the `sovereign` command:

```bash
#!/bin/bash
# Example: Integrate with your existing deepseek_max_launch.sh

# Get Jordi context
JORDI_CONTEXT=$(./bin/sovereign jordi "Bitcoin outlook")

# Send to DeepSeek with context
python3 - <<EOF
import json
import requests

context = '''$JORDI_CONTEXT'''

# Send to DeepSeek with Jordi persona
response = requests.post("http://localhost:11434/api/chat", json={
    "model": "deepseek-r1:70b",
    "messages": [
        {"role": "system", "content": "You are Jordi Visser..."},
        {"role": "user", "content": f"Context: {context}\n\nQuestion: What is your Bitcoin outlook?"}
    ]
})
print(response.json()['message']['content'])
EOF
```

---

### 3. yltra/ultra Integration

Your `yltra` and `ultra` CLI tools can access the Hive Mind:

**Method 1: Wrapper Script**

Create `bin/yltra_sovereign`:

```bash
#!/bin/bash
# Yltra with Sovereign Context

PERSONA=${1:-jordi}  # Default to Jordi
QUERY=${2:-"$@"}

# Get Godhead prompt
GODHEAD=$(./bin/sovereign prompt $PERSONA)

# Get knowledge context
CONTEXT=$(./bin/sovereign $PERSONA "$QUERY")

# Call yltra with full context
yltra --system "$GODHEAD" --context "$CONTEXT" "$QUERY"
```

**Method 2: Environment Variable**

Set the Godhead as an environment variable:

```bash
#!/bin/bash
# In your deepseek_max_launch.sh

export JORDI_GODHEAD=$(./bin/sovereign prompt jordi)

# Now when you call yltra/ultra, inject $JORDI_GODHEAD as system prompt
yltra --system "$JORDI_GODHEAD" "What is your Bitcoin outlook?"
```

---

### 4. OpenWebUI Integration (Future)

To connect OpenWebUI to the Hive Mind:

**Step 1: Create HTTP Proxy**

```python
# src/sovereign_http_proxy.py
from fastapi import FastAPI
from src.sovereign_mcp_server import *

app = FastAPI()

@app.post("/v1/search/jordi")
async def search_jordi(query: str, top_k: int = 5):
    return search_jordi_knowledge(query, top_k)

@app.post("/v1/search/legal")
async def search_legal(query: str, top_k: int = 6):
    return search_fortress_legal(query, top_k)

# ... etc
```

**Step 2: Configure OpenWebUI**

In OpenWebUI settings:
- Add custom tool: "Jordi Knowledge Search"
- Endpoint: `http://localhost:8000/v1/search/jordi`
- Auth: None (local only)

---

### 5. DeepSeek R1 Integration

Your `deepseek_max_launch.sh` can inject Sovereign context:

```bash
#!/bin/bash
# Enhanced deepseek_max_launch.sh with Sovereign integration

PERSONA=${PERSONA:-jordi}
QUERY="$@"

# Get Godhead and context
GODHEAD=$(./bin/sovereign prompt $PERSONA 2>/dev/null)
CONTEXT=$(./bin/sovereign $PERSONA "$QUERY" 2>/dev/null)

# Build system prompt
SYSTEM_PROMPT="$GODHEAD

CONTEXT FROM KNOWLEDGE BASE:
$CONTEXT

Now answer the user's question using this context."

# Call DeepSeek R1
curl http://localhost:11434/api/chat -d '{
  "model": "deepseek-r1:70b",
  "messages": [
    {"role": "system", "content": "'"$SYSTEM_PROMPT"'"},
    {"role": "user", "content": "'"$QUERY"'"}
  ],
  "stream": false,
  "options": {
    "temperature": 0.2,
    "num_predict": 4096
  }
}' | jq -r '.message.content' | sed 's/<think>.*<\/think>//g'
```

---

## Replicating for Other People

### Example: Raoul Pal (Real Vision)

**1. Create the Godhead Prompt**

Add to `src/sovereign_mcp_server.py`:

```python
RAOUL_PAL_GODHEAD = """You are the Real Vision Intelligence Engine.

BACKGROUND: Raoul Pal is a macro investor, founder of Real Vision...

PERSONALITY TRAITS:
- Exponential thinking (tech adoption curves)
- Macro focus (liquidity, demographics)
- Optimistic on crypto
- Network effects obsessed

COMMUNICATION STYLE:
- Uses charts and visual metaphors
- "Banana Zone", "Everything is going to infinity"
- Cites on-chain metrics

CORE BELIEFS:
- Bitcoin + Ethereum = new financial base layer
- DeFi will replace TradFi
- Solana as "Mac to Ethereum's Linux"
"""

@mcp.resource("sovereign://godhead/raoul")
def get_raoul_prompt() -> str:
    return RAOUL_PAL_GODHEAD

@mcp.tool()
def search_raoul_knowledge(query: str, top_k: int = 5) -> str:
    """Search Raoul Pal's Real Vision content."""
    collection = "raoul_intel"
    # Same pattern as search_jordi_knowledge
    query_vec = embed_text(query)
    if not query_vec:
        return json.dumps({"error": "Embedding failed"})
    
    # Search Qdrant...
    # Format and return results...
```

**2. Create Ingestion Script**

```bash
cp src/ingest_jordi_knowledge.py src/ingest_raoul_knowledge.py
# Edit: Change COLLECTION_NAME to "raoul_intel"
# Edit: Change DEFAULT_SOURCE_PATH to "/mnt/fortress_nas/Intelligence/Raoul_Pal"
```

**3. Gather Source Material**

```bash
mkdir -p /mnt/fortress_nas/Intelligence/Raoul_Pal
# Download Real Vision episodes, newsletters, interviews
# Organize with naming: RealVision_2024-12-15_Episode_123.pdf
```

**4. Ingest**

```bash
python src/ingest_raoul_knowledge.py
```

**5. Update CLI**

Add to `bin/sovereign`:

```python
elif cmd == "raoul":
    if len(parts) < 2:
        print("  Usage: raoul <query>")
        continue
    query = parts[1]
    result = mcp.search_raoul_knowledge(query, top_k=5)
    pretty_print(result)
```

**6. Use**

```bash
# In CLI
./bin/sovereign raoul "banana zone"

# In Cursor
@fortress-prime-sovereign search_raoul_knowledge("Solana vs Ethereum")

# With yltra
RAOUL_GODHEAD=$(./bin/sovereign prompt raoul)
yltra --system "$RAOUL_GODHEAD" "What is the banana zone?"
```

---

## Advanced Patterns

### Multi-Persona Synthesis

Ask multiple personas the same question and compare:

```bash
#!/bin/bash
# compare_perspectives.sh

QUESTION="What is your Bitcoin outlook for 2024?"

echo "JORDI:"
./bin/sovereign jordi "$QUESTION"

echo -e "\nRAOUL:"
./bin/sovereign raoul "$QUESTION"

echo -e "\nLYN:"
./bin/sovereign lyn "$QUESTION"
```

Or in Python:

```python
from src.sovereign_mcp_server import (
    search_jordi_knowledge,
    search_raoul_knowledge,
    get_jordi_prompt,
    get_raoul_prompt,
)

question = "Bitcoin outlook 2024"

jordi_context = search_jordi_knowledge(question)
raoul_context = search_raoul_knowledge(question)

# Send both to LLM for synthesis
prompt = f"""
Compare these two perspectives on: {question}

JORDI VISSER (Contrarian, Risk-Focused):
{jordi_context}

RAOUL PAL (Exponential, Network-Effects):
{raoul_context}

Synthesize: What do they agree on? Where do they differ?
"""
```

### Time-Travel Queries

Filter by date to track opinion evolution:

```python
# How did Jordi's Bitcoin view change?
jan_2024 = search_jordi_knowledge("Bitcoin", date_filter="2024-01")
dec_2024 = search_jordi_knowledge("Bitcoin", date_filter="2024-12")

# Compare the two
```

### Disagreement Detection

Find conflicts between personas:

```python
from collections import defaultdict

def find_disagreements(topic: str, personas: list):
    """Find where personas disagree on a topic."""
    responses = {}
    for persona in personas:
        search_func = globals()[f"search_{persona}_knowledge"]
        responses[persona] = search_func(topic)
    
    # Analyze for conflicts...
    # (Look for opposing keywords: bullish/bearish, buy/sell, etc.)
```

---

## Production Hardening

### 1. Add Caching

Use Redis to cache frequent queries:

```python
import redis
import hashlib

cache = redis.Redis(host='localhost', port=6379, db=0)

def search_with_cache(query: str, search_func, ttl: int = 3600):
    """Cache search results for 1 hour."""
    cache_key = f"sovereign:{search_func.__name__}:{hashlib.md5(query.encode()).hexdigest()}"
    
    # Check cache
    cached = cache.get(cache_key)
    if cached:
        return cached.decode()
    
    # Execute search
    result = search_func(query)
    
    # Cache result
    cache.setex(cache_key, ttl, result)
    
    return result
```

### 2. Add Query Logging

Track all queries to PostgreSQL:

```python
import psycopg2
from datetime import datetime

def log_query(persona: str, query: str, results_count: int):
    """Log all Sovereign queries to audit table."""
    conn = psycopg2.connect(
        host="localhost",
        database="fortress_db",
        user="miner_bot",
    )
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sovereign_query_log 
        (persona, query, results_count, timestamp)
        VALUES (%s, %s, %s, %s)
    """, (persona, query, results_count, datetime.now()))
    conn.commit()
    conn.close()
```

### 3. Add Rate Limiting

Prevent abuse:

```python
from time import time
from collections import defaultdict

class RateLimiter:
    def __init__(self, max_requests: int = 100, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)
    
    def check(self, user_id: str) -> bool:
        """Check if user is within rate limit."""
        now = time()
        # Clean old requests
        self.requests[user_id] = [
            t for t in self.requests[user_id] 
            if now - t < self.window
        ]
        
        # Check limit
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True

rate_limiter = RateLimiter()

@mcp.tool()
def search_with_rate_limit(query: str, user_id: str = "default"):
    if not rate_limiter.check(user_id):
        return json.dumps({"error": "Rate limit exceeded"})
    
    # ... execute search ...
```

---

## Migration Path

### Phase 1: Core Setup (Week 1)
- [x] Install MCP server
- [x] Connect Cursor
- [x] Test with existing legal/Oracle databases
- [ ] Integrate with 1-2 CLI scripts

### Phase 2: Jordi Visser (Week 2-3)
- [ ] Gather Jordi transcripts (20+ hours)
- [ ] Run ingestion
- [ ] Test search quality
- [ ] Refine Godhead prompt
- [ ] Integrate with yltra/ultra

### Phase 3: Additional Personas (Month 2)
- [ ] Raoul Pal (Real Vision)
- [ ] Lyn Alden (Macro + Bitcoin)
- [ ] Balaji Srinivasan (Tech + Crypto)

### Phase 4: Production Features (Month 3)
- [ ] HTTP API for web UIs
- [ ] Redis caching
- [ ] PostgreSQL query logging
- [ ] Rate limiting
- [ ] Multi-user access control

---

## Troubleshooting

### "MCP server not responding"

```bash
# Check if process is running
ps aux | grep sovereign_mcp_server

# Kill zombie processes
pkill -f sovereign_mcp_server

# Restart Cursor
```

### "Search returns no results"

```bash
# Check collection exists and has data
python src/test_mcp_server.py list-collections

# Check embedding service
curl http://localhost:11434/api/embeddings \
  -d '{"model":"nomic-embed-text","prompt":"test"}'

# Re-ingest data
python src/ingest_jordi_knowledge.py --force-recreate
```

### "Cursor MCP connection refused"

```bash
# Check config exists
cat .cursor/mcp_config.json

# Verify paths are absolute
# Make sure Python path is correct: `which python3`

# Check Cursor logs
# Help > Toggle Developer Tools > Console
```

---

## Support

For integration issues:
1. Check documentation: `docs/SOVEREIGN_CONTEXT_PROTOCOL.md`
2. Run diagnostics: `python src/test_mcp_server.py`
3. Check system status: `./bin/sovereign stats`
4. Review Constitution: `.cursor/rules/002-sovereign-constitution.mdc`

---

**Next Steps:**
1. Run setup: `bash setup_sovereign_mcp.sh`
2. Test integration: `./bin/sovereign stats`
3. Connect your first tool (Cursor, yltra, or CLI script)
4. Start gathering Jordi transcripts
5. Replicate for other personas

Welcome to Level 3 Intelligence — Unified, Sovereign, Local.
