#!/usr/bin/env python3
"""
Jordi Visser Intelligence Hunter
=================================
Autonomous agent that monitors and ingests Jordi Visser's content:
1. X/Twitter via xAI API (@jvisserlabs)
2. YouTube podcast appearances
3. Podcast transcripts from The Pomp Podcast
4. Substack articles (VisserLabs)

Feeds everything into the Sovereign MCP jordi_intel collection.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import subprocess
import re

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

JORDI_TWITTER = "@jvisserlabs"
JORDI_YOUTUBE_CHANNELS = [
    "UC8H8L0KVl2AKI0dERXKAUuQ",  # The Pomp Podcast
    "UCXvdmzjJbwSM0S6NNDQfsBg",  # The Milk Road Show
]
JORDI_SUBSTACK = "visserlabs.substack.com"
JORDI_SEARCH_QUERIES = [
    "Jordi Visser Bitcoin",
    "Jordi Visser AI",
    "Jordi Visser macro",
    "Jordi Visser interview",
]

# Storage paths
INTEL_DIR = Path("/mnt/fortress_nas/Intelligence/Jordi_Visser")
INTEL_DIR.mkdir(parents=True, exist_ok=True)

TWITTER_DIR = INTEL_DIR / "twitter_feed"
YOUTUBE_DIR = INTEL_DIR / "youtube_transcripts"
PODCAST_DIR = INTEL_DIR / "podcast_transcripts"
SUBSTACK_DIR = INTEL_DIR / "substack_articles"

for d in [TWITTER_DIR, YOUTUBE_DIR, PODCAST_DIR, SUBSTACK_DIR]:
    d.mkdir(exist_ok=True)

# State tracking
STATE_FILE = INTEL_DIR / "intelligence_state.json"

# API Keys
XAI_API_KEY = os.getenv("XAI_API_KEY", "")  # For X/Twitter monitoring
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")  # For YouTube Data API v3

# Ollama for local transcription summarization
OLLAMA_BASE = "http://localhost:11434"


# ═══════════════════════════════════════════════════════════════════════════
# State Management
# ═══════════════════════════════════════════════════════════════════════════

def load_state() -> Dict:
    """Load last run state to avoid duplicate downloads."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "last_twitter_id": None,
        "last_youtube_check": None,
        "last_substack_check": None,
        "processed_videos": [],
        "processed_tweets": [],
        "processed_articles": [],
    }


def save_state(state: Dict):
    """Persist state for incremental updates."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# 1. X/Twitter Intelligence (via xAI API)
# ═══════════════════════════════════════════════════════════════════════════

def hunt_twitter_intel(state: Dict) -> List[str]:
    """
    Monitor @jvisserlabs Twitter feed via xAI API.
    xAI has direct X/Twitter access (Grok).
    
    Returns list of newly created transcript files.
    """
    if not XAI_API_KEY:
        print("⚠️  XAI_API_KEY not set. Skipping Twitter monitoring.")
        print("   Set via: export XAI_API_KEY='your_key_here'")
        return []
    
    print(f"🔍 Monitoring X/Twitter: {JORDI_TWITTER}")
    
    # Use xAI's Grok model to fetch recent tweets
    # xAI API endpoint: https://api.x.ai/v1/chat/completions
    
    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # Construct a query to get recent tweets
    since_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    prompt = f"""Search X/Twitter for recent posts from {JORDI_TWITTER} since {since_date}.
    
Return ONLY a JSON array of tweets with this structure:
[
  {{
    "id": "tweet_id",
    "created_at": "ISO_timestamp",
    "text": "full tweet text",
    "url": "https://twitter.com/..."
  }}
]

Focus on substantive posts about Bitcoin, AI, macro economics, markets.
Skip pure retweets without commentary."""
    
    payload = {
        "model": "grok-beta",
        "messages": [
            {"role": "system", "content": "You are a precise data extraction agent. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
    }
    
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if resp.status_code != 200:
            print(f"❌ xAI API error: {resp.status_code}")
            print(f"   Response: {resp.text}")
            return []
        
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        
        # Extract JSON from response (might be wrapped in markdown)
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            print(f"⚠️  No JSON found in xAI response")
            return []
        
        tweets = json.loads(json_match.group(0))
        
        new_files = []
        for tweet in tweets:
            tweet_id = tweet["id"]
            
            if tweet_id in state["processed_tweets"]:
                continue
            
            # Save tweet as markdown
            filename = f"tweet_{tweet_id}_{datetime.now().strftime('%Y%m%d')}.md"
            filepath = TWITTER_DIR / filename
            
            with open(filepath, 'w') as f:
                f.write(f"# X Post by {JORDI_TWITTER}\n\n")
                f.write(f"**Date**: {tweet['created_at']}\n")
                f.write(f"**URL**: {tweet['url']}\n\n")
                f.write(f"---\n\n")
                f.write(tweet['text'])
            
            state["processed_tweets"].append(tweet_id)
            new_files.append(str(filepath))
            print(f"✅ Captured: {filename}")
        
        if new_files:
            save_state(state)
        
        return new_files
    
    except Exception as e:
        print(f"❌ Twitter hunt failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# 2. YouTube Intelligence (via YouTube Data API v3)
# ═══════════════════════════════════════════════════════════════════════════

def hunt_youtube_intel(state: Dict) -> List[str]:
    """
    Search YouTube for Jordi Visser appearances.
    Downloads transcripts using yt-dlp.
    
    Returns list of newly created transcript files.
    """
    if not YOUTUBE_API_KEY:
        print("⚠️  YOUTUBE_API_KEY not set. Skipping YouTube monitoring.")
        print("   Get one at: https://console.cloud.google.com/apis/credentials")
        return []
    
    print(f"🔍 Hunting YouTube appearances...")
    
    new_files = []
    
    for query in JORDI_SEARCH_QUERIES:
        # Search YouTube
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 5,
            "order": "date",
            "key": YOUTUBE_API_KEY,
        }
        
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params,
                timeout=10
            )
            
            if resp.status_code != 200:
                print(f"⚠️  YouTube API error for '{query}': {resp.status_code}")
                continue
            
            results = resp.json()
            
            for item in results.get("items", []):
                video_id = item["id"]["videoId"]
                
                if video_id in state["processed_videos"]:
                    continue
                
                video_title = item["snippet"]["title"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                print(f"  📹 Found: {video_title}")
                
                # Download transcript using yt-dlp
                transcript_file = download_youtube_transcript(video_id, video_title)
                
                if transcript_file:
                    state["processed_videos"].append(video_id)
                    new_files.append(transcript_file)
                    print(f"     ✅ Transcript saved")
        
        except Exception as e:
            print(f"❌ YouTube search failed for '{query}': {e}")
    
    if new_files:
        save_state(state)
    
    return new_files


def download_youtube_transcript(video_id: str, title: str) -> Optional[str]:
    """Use yt-dlp to download auto-generated transcript."""
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:100]
    filename = f"{safe_title}_{video_id}.txt"
    filepath = YOUTUBE_DIR / filename
    
    try:
        # yt-dlp command to get auto-generated subtitles
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--sub-format", "txt",
            "--output", str(filepath.with_suffix('')),
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        
        # yt-dlp creates filename.en.txt
        expected_file = filepath.with_suffix('.en.txt')
        if expected_file.exists():
            expected_file.rename(filepath)
            return str(filepath)
        
        # If no auto-subs, try to extract audio and transcribe locally
        print(f"     ⚠️  No auto-subs available for {video_id}")
        return None
    
    except Exception as e:
        print(f"     ❌ Transcript download failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. Podcast Intelligence (The Pomp Podcast)
# ═══════════════════════════════════════════════════════════════════════════

def hunt_podcast_intel(state: Dict) -> List[str]:
    """
    Search for Jordi's appearances on The Pomp Podcast.
    Uses podcast RSS feed + episode search.
    
    Returns list of newly created transcript files.
    """
    print(f"🔍 Monitoring The Pomp Podcast RSS...")
    
    POMP_RSS = "https://feeds.megaphone.fm/WWO3519750118"
    
    try:
        resp = requests.get(POMP_RSS, timeout=10)
        
        if resp.status_code != 200:
            print(f"❌ Failed to fetch RSS: {resp.status_code}")
            return []
        
        # Parse RSS (simple regex for now, could use feedparser)
        episodes = re.findall(
            r'<title>(.*?Jordi Visser.*?)</title>.*?<link>(.*?)</link>',
            resp.text,
            re.DOTALL | re.IGNORECASE
        )
        
        new_files = []
        
        for title, link in episodes[:5]:  # Check last 5 matches
            episode_id = re.search(r'id=(\d+)', link)
            if not episode_id:
                continue
            
            ep_id = episode_id.group(1)
            
            if ep_id in state.get("processed_podcasts", []):
                continue
            
            print(f"  🎙️  Found: {title}")
            
            # For now, save episode metadata
            # Future: Integrate with podcast transcript services
            filename = f"pomp_{ep_id}.md"
            filepath = PODCAST_DIR / filename
            
            with open(filepath, 'w') as f:
                f.write(f"# {title}\n\n")
                f.write(f"**Podcast**: The Pomp Podcast\n")
                f.write(f"**Guest**: Jordi Visser\n")
                f.write(f"**URL**: {link}\n")
                f.write(f"**Scraped**: {datetime.now().isoformat()}\n\n")
                f.write(f"---\n\n")
                f.write(f"[Transcript to be downloaded]\n")
            
            if "processed_podcasts" not in state:
                state["processed_podcasts"] = []
            state["processed_podcasts"].append(ep_id)
            
            new_files.append(str(filepath))
            print(f"     ✅ Metadata saved")
        
        if new_files:
            save_state(state)
        
        return new_files
    
    except Exception as e:
        print(f"❌ Podcast hunt failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# 4. Substack Intelligence
# ═══════════════════════════════════════════════════════════════════════════

def hunt_substack_intel(state: Dict) -> List[str]:
    """
    Monitor VisserLabs Substack for new articles.
    
    Returns list of newly created article files.
    """
    print(f"🔍 Monitoring {JORDI_SUBSTACK}...")
    
    # Substack RSS feed
    SUBSTACK_RSS = f"https://{JORDI_SUBSTACK}/feed"
    
    try:
        resp = requests.get(SUBSTACK_RSS, timeout=10)
        
        if resp.status_code != 200:
            print(f"❌ Failed to fetch Substack RSS: {resp.status_code}")
            return []
        
        # Parse RSS for articles
        articles = re.findall(
            r'<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>',
            resp.text,
            re.DOTALL
        )
        
        new_files = []
        
        for title, link, pub_date in articles[:10]:
            article_id = link.split('/')[-1] if '/' in link else link
            
            if article_id in state.get("processed_articles", []):
                continue
            
            print(f"  📄 Found: {title}")
            
            # Download full article content
            article_content = download_substack_article(link)
            
            if article_content:
                safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:100]
                filename = f"{safe_title}.md"
                filepath = SUBSTACK_DIR / filename
                
                with open(filepath, 'w') as f:
                    f.write(f"# {title}\n\n")
                    f.write(f"**Source**: VisserLabs Substack\n")
                    f.write(f"**Published**: {pub_date}\n")
                    f.write(f"**URL**: {link}\n\n")
                    f.write(f"---\n\n")
                    f.write(article_content)
                
                if "processed_articles" not in state:
                    state["processed_articles"] = []
                state["processed_articles"].append(article_id)
                
                new_files.append(str(filepath))
                print(f"     ✅ Article saved")
        
        if new_files:
            save_state(state)
        
        return new_files
    
    except Exception as e:
        print(f"❌ Substack hunt failed: {e}")
        return []


def download_substack_article(url: str) -> Optional[str]:
    """Extract article text from Substack page."""
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        
        # Extract article body (simplified - adjust selectors as needed)
        # This is a placeholder - you'd want to use BeautifulSoup for real parsing
        content = resp.text
        
        # Very basic extraction: grab text between <article> tags
        match = re.search(r'<article.*?>(.*?)</article>', content, re.DOTALL)
        if match:
            article_html = match.group(1)
            # Strip HTML tags (very basic)
            text = re.sub(r'<.*?>', '', article_html)
            return text.strip()
        
        return "[Article content extraction pending - needs BeautifulSoup]"
    
    except Exception as e:
        print(f"     ⚠️  Article download failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. Auto-Ingest into Sovereign MCP
# ═══════════════════════════════════════════════════════════════════════════

def auto_ingest_to_mcp(new_files: List[str]):
    """
    Automatically run the ingest script when new content is gathered.
    """
    if not new_files:
        print("\n📊 No new content to ingest.")
        return
    
    print(f"\n📥 Auto-ingesting {len(new_files)} new files into Sovereign MCP...")
    
    ingest_script = Path(__file__).parent / "ingest_jordi_knowledge.py"
    
    if not ingest_script.exists():
        print(f"❌ Ingest script not found: {ingest_script}")
        return
    
    try:
        result = subprocess.run(
            ["python3", str(ingest_script)],
            cwd=str(ingest_script.parent),
            capture_output=True,
            timeout=300
        )
        
        print(result.stdout.decode())
        
        if result.returncode == 0:
            print("✅ Ingestion complete!")
        else:
            print(f"⚠️  Ingestion had errors:")
            print(result.stderr.decode())
    
    except Exception as e:
        print(f"❌ Auto-ingest failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("="*80)
    print("🎯 JORDI VISSER INTELLIGENCE HUNTER")
    print("="*80)
    print(f"Target: {JORDI_TWITTER}")
    print(f"Storage: {INTEL_DIR}")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*80 + "\n")
    
    state = load_state()
    
    all_new_files = []
    
    # 1. Hunt Twitter/X
    twitter_files = hunt_twitter_intel(state)
    all_new_files.extend(twitter_files)
    
    # 2. Hunt YouTube
    youtube_files = hunt_youtube_intel(state)
    all_new_files.extend(youtube_files)
    
    # 3. Hunt Podcasts
    podcast_files = hunt_podcast_intel(state)
    all_new_files.extend(podcast_files)
    
    # 4. Hunt Substack
    substack_files = hunt_substack_intel(state)
    all_new_files.extend(substack_files)
    
    # 5. Auto-ingest everything
    auto_ingest_to_mcp(all_new_files)
    
    print("\n" + "="*80)
    print(f"🎯 HUNT COMPLETE: {len(all_new_files)} new files")
    print(f"   Twitter: {len(twitter_files)}")
    print(f"   YouTube: {len(youtube_files)}")
    print(f"   Podcasts: {len(podcast_files)}")
    print(f"   Substack: {len(substack_files)}")
    print("="*80)
    
    # Show summary
    print("\n📊 Intelligence Summary:")
    print(f"   Total tweets tracked: {len(state.get('processed_tweets', []))}")
    print(f"   Total videos tracked: {len(state.get('processed_videos', []))}")
    print(f"   Total podcasts tracked: {len(state.get('processed_podcasts', []))}")
    print(f"   Total articles tracked: {len(state.get('processed_articles', []))}")


if __name__ == "__main__":
    main()
