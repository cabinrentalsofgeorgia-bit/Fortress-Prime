#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — DGX WHISPERX 24/7 MONITOR DAEMON
═══════════════════════════════════════════════════════════════════════════════
Autonomous monitoring daemon that hunts audio → transcribes → ingests 24/7.

Workflow:
    1. Monitor persona data sources (YouTube, podcasts, etc.)
    2. Download new audio files
    3. Transcribe with WhisperX (DGX)
    4. Auto-ingest transcripts to vector DB
    5. Repeat every N hours

Runs as:
    - Foreground: Interactive mode with status updates
    - Background: systemd service for 24/7 operation
    - Cron: Scheduled runs (e.g., every 6 hours)

Usage:
    # Single persona, one run
    python dgx_whisperx_monitor.py --persona jordi --once
    
    # Multiple personas, continuous
    python dgx_whisperx_monitor.py --personas jordi,raoul,lyn --interval 6
    
    # All personas, daemon mode
    python dgx_whisperx_monitor.py --all --daemon

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# =============================================================================
# Configuration
# =============================================================================

WORKSPACE = Path("/home/admin/Fortress-Prime")
MONITOR_STATE_FILE = WORKSPACE / "dgx_monitor_state.json"

# Default monitoring interval (hours)
DEFAULT_INTERVAL = 6

# Persona data sources (YouTube channels, podcast RSS, etc.)
PERSONA_SOURCES = {
    "jordi": {
        "youtube_channels": [
            "UC8H8L0KVl2AKI0dERXKAUuQ",  # The Pomp Podcast
        ],
        "podcast_rss": [
            "https://feeds.megaphone.fm/WWO3519750118",  # The Pomp Podcast
        ],
        "substack": "visserlabs.substack.com",
    },
    "raoul": {
        "youtube_channels": [
            "UCskaAm0ra016pMqGSa5x4gw",  # Real Vision
        ],
        "substack": "raoulpal.substack.com",
    },
    "lyn": {
        "substack": "lyn.substack.com",
    },
    "vol_trader": {
        "youtube_search": "SpotGamma volatility analysis",
    },
    "fed_watcher": {
        "youtube_search": "Zoltan Pozsar Fed analysis",
    },
    "sound_money": {
        "substack": "goldfixsubstack.com",
        "youtube_search": "Luke Gromen FFTT",
    },
    "real_estate": {
        # Internal CROG data - no external sources
    },
    "permabear": {
        "youtube_search": "John Hussman market valuation",
    },
    "black_swan": {
        "youtube_search": "Nassim Taleb tail risk",
    },
}


# =============================================================================
# State Management
# =============================================================================

def load_monitor_state() -> Dict:
    """Load monitor state (last run times, etc.)."""
    if MONITOR_STATE_FILE.exists():
        with open(MONITOR_STATE_FILE, 'r') as f:
            return json.load(f)
    return {"last_runs": {}, "total_transcribed": 0}


def save_monitor_state(state: Dict):
    """Save monitor state."""
    with open(MONITOR_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def update_last_run(persona: str, state: Dict):
    """Update last run timestamp for persona."""
    state["last_runs"][persona] = datetime.now().isoformat()
    save_monitor_state(state)


# =============================================================================
# Audio Hunting
# =============================================================================

def hunt_audio_for_persona(persona: str) -> List[str]:
    """
    Hunt for new audio sources for a persona.
    
    Args:
        persona: Persona slug
    
    Returns:
        List of YouTube URLs found
    """
    print(f"🔍 Hunting audio for {persona}...")
    
    sources = PERSONA_SOURCES.get(persona, {})
    urls = []
    
    # YouTube channels
    for channel_id in sources.get("youtube_channels", []):
        # Use yt-dlp to get latest videos
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--print", "url",
            "--playlist-end", "5",  # Latest 5 videos
            f"https://www.youtube.com/channel/{channel_id}/videos",
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                video_urls = result.stdout.strip().split('\n')
                urls.extend(video_urls)
                print(f"  Found {len(video_urls)} videos from YouTube channel")
        except Exception as e:
            print(f"  ⚠️  YouTube hunt failed: {e}")
    
    # YouTube search queries
    search_query = sources.get("youtube_search")
    if search_query:
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--print", "url",
            "--playlist-end", "3",  # Top 3 results
            f"ytsearch3:{search_query}",
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                video_urls = result.stdout.strip().split('\n')
                urls.extend(video_urls)
                print(f"  Found {len(video_urls)} videos from search")
        except Exception as e:
            print(f"  ⚠️  YouTube search failed: {e}")
    
    # Podcast RSS (handled by intelligence hunter)
    # Substack (handled by intelligence hunter)
    
    return [url for url in urls if url.startswith('http')]


# =============================================================================
# Pipeline Orchestration
# =============================================================================

def process_persona(persona: str) -> Dict[str, int]:
    """
    Full pipeline for one persona: hunt → transcribe → ingest.
    
    Args:
        persona: Persona slug
    
    Returns:
        Stats dict
    """
    print(f"\n{'='*70}")
    print(f"🎯 PROCESSING PERSONA: {persona}")
    print(f"{'='*70}\n")
    
    stats = {
        "audio_found": 0,
        "audio_downloaded": 0,
        "transcribed": 0,
        "ingested": 0,
    }
    
    # 1. Hunt for audio
    urls = hunt_audio_for_persona(persona)
    stats["audio_found"] = len(urls)
    
    if not urls:
        print(f"  No new audio found for {persona}")
        return stats
    
    print(f"  Found {len(urls)} audio sources")
    
    # 2. Transcribe each URL
    transcribed = 0
    for url in urls:
        print(f"\n📹 Processing: {url}")
        
        # Call dgx_whisperx_pipeline.py
        cmd = [
            "python3",
            str(WORKSPACE / "src/dgx_whisperx_pipeline.py"),
            "--youtube", url,
            "--persona", persona,
        ]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(WORKSPACE),
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min timeout per video
            )
            
            if result.returncode == 0:
                transcribed += 1
                print(f"  ✅ Transcribed successfully")
            else:
                print(f"  ❌ Transcription failed")
                if result.stderr:
                    print(f"     Error: {result.stderr[:200]}")
        
        except subprocess.TimeoutExpired:
            print(f"  ❌ Transcription timeout (>30 min)")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    stats["transcribed"] = transcribed
    
    # 3. Auto-ingest transcripts
    if transcribed > 0:
        print(f"\n📥 Auto-ingesting transcripts for {persona}...")
        
        cmd = [
            "python3",
            str(WORKSPACE / "src/auto_ingest_transcripts.py"),
            "--persona", persona,
        ]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(WORKSPACE),
                capture_output=True,
                text=True,
                timeout=600,
            )
            
            if result.returncode == 0:
                # Parse output for ingested count
                output = result.stdout
                if "Ingested:" in output:
                    try:
                        count_str = output.split("Ingested:")[1].split("files")[0].strip()
                        stats["ingested"] = int(count_str)
                    except:
                        pass
                print(f"  ✅ Ingestion complete")
            else:
                print(f"  ⚠️  Ingestion had warnings")
        
        except Exception as e:
            print(f"  ❌ Ingestion error: {e}")
    
    return stats


# =============================================================================
# Monitor Loop
# =============================================================================

def monitor_personas(
    personas: List[str],
    interval_hours: int = DEFAULT_INTERVAL,
    once: bool = False,
):
    """
    Monitor loop: process personas continuously.
    
    Args:
        personas: List of persona slugs
        interval_hours: Hours between runs
        once: Run once and exit (no loop)
    """
    print(f"{'='*70}")
    print(f"🏛️  DGX WHISPERX MONITOR DAEMON")
    print(f"{'='*70}")
    print(f"Personas: {', '.join(personas)}")
    print(f"Interval: {interval_hours} hours")
    print(f"Mode: {'One-time run' if once else 'Continuous daemon'}")
    print(f"{'='*70}\n")
    
    state = load_monitor_state()
    
    run_count = 0
    
    while True:
        run_count += 1
        start_time = datetime.now()
        
        print(f"\n🔄 RUN #{run_count} - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        total_stats = {
            "audio_found": 0,
            "transcribed": 0,
            "ingested": 0,
        }
        
        # Process each persona
        for persona in personas:
            stats = process_persona(persona)
            
            # Aggregate stats
            for key in total_stats:
                total_stats[key] += stats.get(key, 0)
            
            # Update state
            update_last_run(persona, state)
            state["total_transcribed"] += stats.get("transcribed", 0)
            save_monitor_state(state)
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n{'='*70}")
        print(f"✅ RUN #{run_count} COMPLETE")
        print(f"{'='*70}")
        print(f"Duration: {duration:.0f} seconds")
        print(f"Audio found: {total_stats['audio_found']}")
        print(f"Transcribed: {total_stats['transcribed']}")
        print(f"Ingested: {total_stats['ingested']}")
        print(f"Total transcribed (lifetime): {state['total_transcribed']}")
        print(f"{'='*70}\n")
        
        # Exit if one-time run
        if once:
            break
        
        # Sleep until next run
        next_run = datetime.now().timestamp() + (interval_hours * 3600)
        next_run_str = datetime.fromtimestamp(next_run).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"💤 Sleeping until next run: {next_run_str}")
        print(f"   Press Ctrl+C to stop\n")
        
        try:
            time.sleep(interval_hours * 3600)
        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user")
            break


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="DGX WhisperX 24/7 Monitor Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single persona, one run
  python dgx_whisperx_monitor.py --persona jordi --once
  
  # Multiple personas, every 6 hours
  python dgx_whisperx_monitor.py --personas jordi,raoul,lyn --interval 6
  
  # All personas, daemon mode
  python dgx_whisperx_monitor.py --all --daemon
        """,
    )
    
    parser.add_argument("--persona", help="Single persona to monitor")
    parser.add_argument("--personas", help="Comma-separated personas (jordi,raoul,lyn)")
    parser.add_argument("--all", action="store_true", help="Monitor all personas")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Hours between runs (default: 6)")
    parser.add_argument("--once", action="store_true", help="Run once and exit (no loop)")
    parser.add_argument("--daemon", action="store_true", help="Daemon mode (continuous loop)")
    
    args = parser.parse_args()
    
    # Determine personas list
    if args.all:
        personas = list(PERSONA_SOURCES.keys())
    elif args.personas:
        personas = [p.strip() for p in args.personas.split(',')]
    elif args.persona:
        personas = [args.persona]
    else:
        print("❌ Must specify --persona, --personas, or --all")
        parser.print_help()
        return 1
    
    # Validate personas
    for persona in personas:
        if persona not in PERSONA_SOURCES:
            print(f"⚠️  Unknown persona: {persona}")
            print(f"   Known personas: {', '.join(PERSONA_SOURCES.keys())}")
    
    # Run monitor
    try:
        monitor_personas(
            personas=personas,
            interval_hours=args.interval,
            once=args.once or not args.daemon,
        )
        return 0
    
    except KeyboardInterrupt:
        print("\n🛑 Monitor stopped by user")
        return 0
    except Exception as e:
        print(f"\n❌ Monitor error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
