# Jordi Visser Intelligence Pipeline
## Autonomous Multi-Source Monitoring & Ingestion

This system monitors Jordi Visser's digital footprint across 4 platforms and auto-ingests everything into your Sovereign MCP `jordi_intel` collection.

---

## 🎯 Target Intelligence Sources

| Source | Handle/URL | Content Type | API Required |
|--------|-----------|--------------|--------------|
| **X/Twitter** | `@jvisserlabs` | Posts, threads, commentary | xAI (Grok) |
| **YouTube** | Multiple channels | Podcast appearances, interviews | YouTube Data API v3 |
| **Podcasts** | The Pomp Podcast | Audio transcripts | RSS (free) |
| **Substack** | visserlabs.substack.com | Long-form articles | RSS (free) |

---

## 🔧 Setup Instructions

### 1. Install Dependencies

```bash
# YouTube transcript downloader
pip install --break-system-packages yt-dlp

# Optional: HTML parsing for Substack
pip install --break-system-packages beautifulsoup4 lxml
```

### 2. Get API Keys

#### xAI API Key (for X/Twitter monitoring)
1. Visit: https://console.x.ai/
2. Create account / sign in
3. Generate API key
4. Export: `export XAI_API_KEY='your_key_here'`

**Why xAI?** Grok has native X/Twitter access. No scraping, no rate limits.

#### YouTube API Key (for video discovery)
1. Visit: https://console.cloud.google.com/apis/credentials
2. Create new project: "Fortress Intelligence"
3. Enable "YouTube Data API v3"
4. Create credentials → API Key
5. Export: `export YOUTUBE_API_KEY='your_key_here'`

**Free Tier**: 10,000 requests/day (plenty for monitoring)

### 3. Configure Storage

The hunter automatically creates this structure:

```
/mnt/fortress_nas/Intelligence/Jordi_Visser/
├── twitter_feed/           # X posts
├── youtube_transcripts/    # Video transcripts
├── podcast_transcripts/    # Audio transcripts
├── substack_articles/      # Long-form articles
└── intelligence_state.json # Tracking (prevents duplicates)
```

### 4. Set Environment Variables

Add to your `~/.bashrc` or `~/.profile`:

```bash
# Jordi Intelligence Pipeline
export XAI_API_KEY='xai-xxxxxxxxxxxxxxxxxxxxxxxx'
export YOUTUBE_API_KEY='AIzaSyxxxxxxxxxxxxxxxxxxxxxxxx'
```

Then reload: `source ~/.bashrc`

---

## 🚀 Usage

### Manual Hunt (Run Once)

```bash
python3 src/jordi_intelligence_hunter.py
```

**What it does:**
1. Checks X/Twitter for posts in last 7 days
2. Searches YouTube for recent appearances
3. Scans The Pomp Podcast RSS for new episodes
4. Monitors VisserLabs Substack for articles
5. Downloads transcripts/content
6. Auto-ingests into `jordi_intel` Qdrant collection

### Automated Monitoring (Cron Job)

Run every 6 hours:

```bash
# Add to crontab
crontab -e

# Add this line:
0 */6 * * * cd /home/admin/Fortress-Prime && /usr/bin/python3 src/jordi_intelligence_hunter.py >> /var/log/jordi_hunt.log 2>&1
```

Or use the wrapper script (see below).

---

## 🤖 Autonomous Monitoring Wrapper

Create `/home/admin/Fortress-Prime/bin/hunt-jordi`:

```bash
#!/bin/bash
# Autonomous Jordi Visser Intelligence Hunter
# Runs in background, monitors continuously

set -e

WORKSPACE="/home/admin/Fortress-Prime"
LOG_FILE="/var/log/jordi_hunt.log"
INTERVAL_HOURS=6

cd "$WORKSPACE"

echo "🎯 Starting Jordi Intelligence Hunter (every ${INTERVAL_HOURS}h)" | tee -a "$LOG_FILE"

while true; do
    echo "" | tee -a "$LOG_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    echo "🔍 Hunt started: $(date)" | tee -a "$LOG_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    
    python3 src/jordi_intelligence_hunter.py 2>&1 | tee -a "$LOG_FILE"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    echo "✅ Hunt complete. Next run in ${INTERVAL_HOURS}h" | tee -a "$LOG_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    
    sleep $((INTERVAL_HOURS * 3600))
done
```

Make executable and run:

```bash
chmod +x bin/hunt-jordi
nohup bin/hunt-jordi &
```

---

## 🧪 Testing the Pipeline

### 1. Test xAI Connection

```bash
curl -X POST https://api.x.ai/v1/chat/completions \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-beta",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

**Expected**: JSON response with Grok's greeting.

### 2. Test YouTube API

```bash
curl "https://www.googleapis.com/youtube/v3/search?part=snippet&q=Jordi+Visser&type=video&maxResults=1&key=$YOUTUBE_API_KEY"
```

**Expected**: JSON with video results.

### 3. Run Hunter (Dry Run)

```bash
python3 src/jordi_intelligence_hunter.py
```

**Expected output:**
```
🎯 JORDI VISSER INTELLIGENCE HUNTER
================================================================================
Target: @jvisserlabs
Storage: /mnt/fortress_nas/Intelligence/Jordi_Visser
Started: 2026-02-15T...
================================================================================

🔍 Monitoring X/Twitter: @jvisserlabs
  ✅ Captured: tweet_12345_20260215.md
🔍 Hunting YouTube appearances...
  📹 Found: Why Bitcoin & AI Will EXPLODE Higher...
     ✅ Transcript saved
...
```

### 4. Verify Ingestion

```bash
./bin/sovereign status jordi
```

**Expected**: Vector count should increase after each hunt.

---

## 📊 Monitoring & Maintenance

### Check Hunt Status

```bash
tail -f /var/log/jordi_hunt.log
```

### View Intelligence Stats

```bash
./bin/sovereign status jordi
```

### Manual Re-Ingest (if needed)

```bash
python3 src/ingest_jordi_knowledge.py
```

### Clear State (force re-download)

```bash
rm /mnt/fortress_nas/Intelligence/Jordi_Visser/intelligence_state.json
```

---

## 🎯 Query Examples (After Ingestion)

```bash
# CLI
./bin/sovereign jordi "What is Jordi's thesis on Bitcoin and AI?"
./bin/sovereign jordi "scarcity trade"
./bin/sovereign jordi "robotics productivity boom"

# Cursor Chat
"@jordi_intel What does Jordi think about Bitcoin vs gold in 2026?"

# Python
from src.sovereign_mcp_server import search_jordi_knowledge
results = search_jordi_knowledge("AI deflation thesis", top_k=5)
```

---

## 🔥 Extending to Other Personas

Want to replicate this for **Raoul Pal**, **Lyn Alden**, or others?

1. Copy `src/jordi_intelligence_hunter.py` → `src/raoul_intelligence_hunter.py`
2. Update target handles:
   ```python
   TARGET_TWITTER = "@RaoulGMI"
   TARGET_SUBSTACK = "raoulpal.substack.com"
   INTEL_DIR = Path("/mnt/fortress_nas/Intelligence/Raoul_Pal")
   ```
3. Create new Qdrant collection: `raoul_intel`
4. Add to `fortress_atlas.yaml` as new persona
5. Update MCP server to expose `search_raoul_knowledge` tool

**Blueprint is universal** — just swap handles and storage paths.

---

## 🛠️ Troubleshooting

### "No module named 'yt-dlp'"
```bash
pip install --break-system-packages yt-dlp
```

### "xAI API error: 401 Unauthorized"
Check your API key:
```bash
echo $XAI_API_KEY  # Should print key starting with "xai-"
```

### "YouTube API quota exceeded"
Free tier = 10K requests/day. Each search = ~3 requests.
- Reduce `JORDI_SEARCH_QUERIES` list
- Increase cron interval to 12h

### "No transcripts found"
Some videos don't have auto-captions. Options:
1. Use Whisper (Ollama) to transcribe audio locally
2. Use paid service like AssemblyAI
3. Skip videos without transcripts

---

## 📈 Future Enhancements

- [ ] Whisper integration for videos without auto-captions
- [ ] Sentiment analysis on tweets (DeepSeek-R1 daily summary)
- [ ] Real-time X/Twitter streaming (websocket)
- [ ] Web UI dashboard showing recent captures
- [ ] Email alerts when Jordi posts major thesis
- [ ] Cross-reference with market data (Bitcoin price on post date)
- [ ] Multi-persona dashboard (Jordi + Raoul + Lyn + more)

---

## 🎯 Success Criteria

✅ **Setup Complete** when:
- Hunter runs without errors
- `intelligence_state.json` exists and updates
- Content appears in storage directories
- `./bin/sovereign status jordi` shows growing vector count

✅ **Production Ready** when:
- Cron job runs every 6h
- Logs show successful hunts
- Queries return relevant results
- No API rate limit errors

---

**Next Step**: Run your first hunt and watch the Jordi Hive Mind come alive! 🚀
