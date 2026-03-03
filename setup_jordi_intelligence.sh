#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Jordi Visser Intelligence Pipeline - Setup & Testing
# ═══════════════════════════════════════════════════════════════════════════

set -e

WORKSPACE="/home/admin/Fortress-Prime"
cd "$WORKSPACE"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 JORDI VISSER INTELLIGENCE PIPELINE SETUP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Install Dependencies
# ═══════════════════════════════════════════════════════════════════════════

echo "📦 Step 1: Installing dependencies..."
echo ""

if ! command -v yt-dlp &> /dev/null; then
    echo "  Installing yt-dlp..."
    pip install --break-system-packages yt-dlp
else
    echo "  ✅ yt-dlp already installed"
fi

if ! python3 -c "import bs4" 2>/dev/null; then
    echo "  Installing BeautifulSoup4..."
    pip install --break-system-packages beautifulsoup4 lxml
else
    echo "  ✅ BeautifulSoup4 already installed"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Check API Keys
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔑 Step 2: API Key Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

XAI_CONFIGURED=false
YOUTUBE_CONFIGURED=false

if [[ -n "$XAI_API_KEY" ]]; then
    echo "✅ XAI_API_KEY configured (${#XAI_API_KEY} chars)"
    XAI_CONFIGURED=true
else
    echo "⚠️  XAI_API_KEY not set"
    echo ""
    echo "   To enable X/Twitter monitoring via Grok:"
    echo "   1. Visit: https://console.x.ai/"
    echo "   2. Create API key"
    echo "   3. Export: export XAI_API_KEY='your_key_here'"
    echo "   4. Add to ~/.bashrc for persistence"
    echo ""
fi

if [[ -n "$YOUTUBE_API_KEY" ]]; then
    echo "✅ YOUTUBE_API_KEY configured (${#YOUTUBE_API_KEY} chars)"
    YOUTUBE_CONFIGURED=true
else
    echo "⚠️  YOUTUBE_API_KEY not set"
    echo ""
    echo "   To enable YouTube monitoring:"
    echo "   1. Visit: https://console.cloud.google.com/apis/credentials"
    echo "   2. Create project + enable YouTube Data API v3"
    echo "   3. Create API key"
    echo "   4. Export: export YOUTUBE_API_KEY='your_key_here'"
    echo "   5. Add to ~/.bashrc for persistence"
    echo ""
fi

# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Test API Connections
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 Step 3: Testing API Connections"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ "$XAI_CONFIGURED" == true ]]; then
    echo "Testing xAI (Grok) API..."
    XAI_TEST=$(curl -s -X POST https://api.x.ai/v1/chat/completions \
      -H "Authorization: Bearer $XAI_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "grok-beta",
        "messages": [{"role": "user", "content": "Reply with OK"}],
        "max_tokens": 10
      }' | grep -o '"content":"[^"]*"' | head -1)
    
    if [[ -n "$XAI_TEST" ]]; then
        echo "  ✅ xAI API working"
    else
        echo "  ❌ xAI API failed - check key"
    fi
else
    echo "  ⏭️  Skipping xAI test (no key configured)"
fi

echo ""

if [[ "$YOUTUBE_CONFIGURED" == true ]]; then
    echo "Testing YouTube API..."
    YT_TEST=$(curl -s "https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&type=video&maxResults=1&key=$YOUTUBE_API_KEY" | grep -o '"kind":"youtube#searchResult"')
    
    if [[ -n "$YT_TEST" ]]; then
        echo "  ✅ YouTube API working"
    else
        echo "  ❌ YouTube API failed - check key"
    fi
else
    echo "  ⏭️  Skipping YouTube test (no key configured)"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Verify Storage
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💾 Step 4: Verifying Storage"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

INTEL_DIR="/mnt/fortress_nas/Intelligence/Jordi_Visser"

if [[ -d "$INTEL_DIR" ]]; then
    echo "✅ Intelligence directory exists: $INTEL_DIR"
    
    # Count existing files
    TWITTER_COUNT=$(find "$INTEL_DIR/twitter_feed" -type f 2>/dev/null | wc -l)
    YOUTUBE_COUNT=$(find "$INTEL_DIR/youtube_transcripts" -type f 2>/dev/null | wc -l)
    PODCAST_COUNT=$(find "$INTEL_DIR/podcast_transcripts" -type f 2>/dev/null | wc -l)
    SUBSTACK_COUNT=$(find "$INTEL_DIR/substack_articles" -type f 2>/dev/null | wc -l)
    
    echo ""
    echo "   Current inventory:"
    echo "   - Twitter posts: $TWITTER_COUNT"
    echo "   - YouTube transcripts: $YOUTUBE_COUNT"
    echo "   - Podcast episodes: $PODCAST_COUNT"
    echo "   - Substack articles: $SUBSTACK_COUNT"
else
    echo "⚠️  Intelligence directory not found"
    echo "   It will be created on first run"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 5: Interactive Setup
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Setup Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo ""

if [[ "$XAI_CONFIGURED" == false || "$YOUTUBE_CONFIGURED" == false ]]; then
    echo "1️⃣  Configure missing API keys (see instructions above)"
    echo ""
fi

echo "2️⃣  Run your first hunt:"
echo "    ./bin/hunt-jordi --once"
echo ""
echo "3️⃣  Check results:"
echo "    ls -lh $INTEL_DIR/*/\"
echo ""
echo "4️⃣  Query the Jordi Hive Mind:"
echo "    ./bin/sovereign jordi \"Bitcoin thesis\""
echo ""
echo "5️⃣  Set up automated monitoring:"
echo "    nohup ./bin/hunt-jordi &"
echo "    # Or add to crontab for every 6 hours:"
echo "    0 */6 * * * cd /home/admin/Fortress-Prime && /home/admin/Fortress-Prime/bin/hunt-jordi --once"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📚 Documentation:"
echo "   Setup Guide: docs/JORDI_INTELLIGENCE_SETUP.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Optional: Offer to run first hunt
read -p "Run a test hunt now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🎯 Launching test hunt..."
    ./bin/hunt-jordi --once
fi
