#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — AUTO-INGEST TRANSCRIPTS TO VECTOR DB
═══════════════════════════════════════════════════════════════════════════════
Monitors transcript directories and auto-ingests into persona vector collections.

Workflow:
    1. Watch /mnt/fortress_nas/Transcripts/{persona}/ for new files
    2. Parse transcript markdown
    3. Extract metadata (date, speaker, timestamps)
    4. Chunk text intelligently
    5. Embed with nomic-embed-text
    6. Upload to Qdrant persona collection
    7. Mark as processed

Usage:
    # Single persona
    python auto_ingest_transcripts.py --persona jordi
    
    # All personas
    python auto_ingest_transcripts.py --all
    
    # Watch mode (continuous)
    python auto_ingest_transcripts.py --watch --persona jordi

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import argparse
import uuid
import hashlib
import re
import requests
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# =============================================================================
# Configuration
# =============================================================================

TRANSCRIPTS_DIR = Path("/mnt/fortress_nas/Transcripts")
INGEST_STATE_FILE = TRANSCRIPTS_DIR / "ingest_state.json"

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# Chunking parameters
CHUNK_SIZE = 1000  # characters
CHUNK_OVERLAP = 200


# =============================================================================
# State Management
# =============================================================================

def load_ingest_state() -> Dict:
    """Load ingestion state."""
    if INGEST_STATE_FILE.exists():
        import json
        with open(INGEST_STATE_FILE, 'r') as f:
            return json.load(f)
    return {"ingested_files": []}


def save_ingest_state(state: Dict):
    """Save ingestion state."""
    import json
    with open(INGEST_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_file_hash(filepath: Path) -> str:
    """Generate hash for file (dedupe)."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()


# =============================================================================
# Embedding
# =============================================================================

def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding via Ollama."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if emb and len(emb) == EMBED_DIM:
            return emb
    except Exception as e:
        print(f"  [ERROR] Embedding failed: {e}")
    return None


# =============================================================================
# Transcript Parsing
# =============================================================================

def parse_transcript_markdown(filepath: Path) -> Dict:
    """
    Parse WhisperX-generated transcript markdown.
    
    Returns:
        Dict with metadata and text chunks
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract metadata section
    metadata = {}
    meta_match = re.search(r'## Metadata\n\n(.*?)\n\n', content, re.DOTALL)
    if meta_match:
        for line in meta_match.group(1).split('\n'):
            if '**' in line:
                key_val = line.split(':', 1)
                if len(key_val) == 2:
                    key = key_val[0].strip(' -**')
                    val = key_val[1].strip(' *')
                    metadata[key] = val
    
    # Extract source info
    source_match = re.search(r'- \*\*Source\*\*: (.+)', content)
    if source_match:
        metadata['source_file'] = source_match.group(1)
    
    # Extract transcript body
    transcript_match = re.search(r'## Transcript\n\n(.+)', content, re.DOTALL)
    if transcript_match:
        transcript_text = transcript_match.group(1)
    else:
        transcript_text = content  # Fallback: use entire content
    
    # Remove speaker labels and timestamps for chunking (keep raw text)
    # But preserve them in metadata
    clean_text = re.sub(r'\*\*\w+\*\*:\s*\[\d+:\d+\]\s*', '', transcript_text)
    clean_text = re.sub(r'\[\d+:\d+\]\s*', '', clean_text)
    
    return {
        "metadata": metadata,
        "text": clean_text.strip(),
        "filename": filepath.name,
    }


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Chunk text with overlap."""
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        
        # Try to break at sentence boundary
        if end < len(text):
            last_period = chunk.rfind('.')
            last_question = chunk.rfind('?')
            last_exclamation = chunk.rfind('!')
            break_point = max(last_period, last_question, last_exclamation)
            
            if break_point > chunk_size * 0.5:
                chunk = chunk[:break_point + 1]
                end = start + break_point + 1
        
        chunks.append(chunk.strip())
        start = end - overlap
    
    return chunks


# =============================================================================
# Qdrant Upload
# =============================================================================

def ingest_transcript_to_qdrant(
    filepath: Path,
    persona_slug: str,
) -> bool:
    """
    Ingest transcript into Qdrant persona collection.
    
    Args:
        filepath: Path to transcript markdown
        persona_slug: Persona collection (jordi, raoul, etc.)
    
    Returns:
        True if successful
    """
    collection = f"{persona_slug}_intel"
    
    print(f"📥 Ingesting: {filepath.name} → {collection}")
    
    # 1. Parse transcript
    parsed = parse_transcript_markdown(filepath)
    metadata = parsed["metadata"]
    text = parsed["text"]
    
    if len(text) < 100:
        print(f"  ⏭️  Skipped: Insufficient text ({len(text)} chars)")
        return False
    
    # 2. Chunk text
    chunks = chunk_text(text)
    print(f"  Chunked into {len(chunks)} segments")
    
    # 3. Create points (chunk + embed)
    points = []
    for i, chunk in enumerate(chunks):
        # Embed
        embedding = embed_text(chunk)
        if not embedding:
            continue
        
        # Generate UUID
        hash_hex = hashlib.sha256(f"{filepath}_{i}".encode()).hexdigest()[:32]
        point_id = str(uuid.UUID(hash_hex))
        
        # Build point
        point = {
            "id": point_id,
            "vector": embedding,
            "payload": {
                "text": chunk,
                "source_file": str(filepath),
                "file_name": filepath.name,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "persona": persona_slug,
                "ingested_at": datetime.now().isoformat(),
                **metadata,  # Include all parsed metadata
            }
        }
        
        points.append(point)
    
    if not points:
        print(f"  ❌ No valid embeddings generated")
        return False
    
    # 4. Batch upload to Qdrant
    batch_size = 100
    uploaded = 0
    
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        try:
            resp = requests.put(
                f"{QDRANT_URL}/collections/{collection}/points",
                headers=QDRANT_HEADERS,
                json={"points": batch},
                timeout=60,
            )
            
            if resp.status_code in (200, 201):
                uploaded += len(batch)
            else:
                print(f"  ❌ Batch upload failed: {resp.text}")
        
        except Exception as e:
            print(f"  ❌ Upload error: {e}")
    
    print(f"  ✅ Uploaded {uploaded}/{len(points)} chunks")
    return uploaded > 0


# =============================================================================
# Batch Processing
# =============================================================================

def ingest_persona_transcripts(persona_slug: str) -> int:
    """
    Ingest all new transcripts for a persona.
    
    Args:
        persona_slug: Persona slug (jordi, raoul, etc.)
    
    Returns:
        Number of files ingested
    """
    transcript_dir = TRANSCRIPTS_DIR / persona_slug
    
    if not transcript_dir.exists():
        print(f"⚠️  Directory not found: {transcript_dir}")
        return 0
    
    # Load state
    state = load_ingest_state()
    
    # Find new transcript files
    transcript_files = list(transcript_dir.glob("*_transcript.md"))
    
    if not transcript_files:
        print(f"⚠️  No transcript files found in {transcript_dir}")
        return 0
    
    # Filter out already ingested
    new_files = []
    for filepath in transcript_files:
        file_hash = get_file_hash(filepath)
        if file_hash not in state["ingested_files"]:
            new_files.append((filepath, file_hash))
    
    if not new_files:
        print(f"✅ All transcripts already ingested for {persona_slug}")
        return 0
    
    print(f"📁 Found {len(new_files)} new transcripts for {persona_slug}")
    
    # Ingest each file
    success_count = 0
    for filepath, file_hash in new_files:
        if ingest_transcript_to_qdrant(filepath, persona_slug):
            state["ingested_files"].append(file_hash)
            save_ingest_state(state)
            success_count += 1
    
    return success_count


# =============================================================================
# Watch Mode (Continuous)
# =============================================================================

class TranscriptHandler(FileSystemEventHandler):
    """Watch for new transcript files and auto-ingest."""
    
    def __init__(self, persona_slug: str):
        self.persona_slug = persona_slug
        self.processing = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        filepath = Path(event.src_path)
        
        # Only process transcript markdown files
        if not filepath.name.endswith('_transcript.md'):
            return
        
        # Avoid duplicate processing
        if str(filepath) in self.processing:
            return
        
        self.processing.add(str(filepath))
        
        print(f"\n🆕 New transcript detected: {filepath.name}")
        
        # Wait a bit to ensure file is fully written
        time.sleep(2)
        
        # Ingest
        try:
            if ingest_transcript_to_qdrant(filepath, self.persona_slug):
                # Update state
                state = load_ingest_state()
                file_hash = get_file_hash(filepath)
                if file_hash not in state["ingested_files"]:
                    state["ingested_files"].append(file_hash)
                    save_ingest_state(state)
        finally:
            self.processing.discard(str(filepath))


def watch_persona_transcripts(persona_slug: str):
    """
    Watch persona transcript directory and auto-ingest new files.
    
    Args:
        persona_slug: Persona to watch
    """
    transcript_dir = TRANSCRIPTS_DIR / persona_slug
    
    if not transcript_dir.exists():
        print(f"❌ Directory not found: {transcript_dir}")
        return
    
    print(f"👁️  Watching: {transcript_dir}")
    print(f"   Press Ctrl+C to stop")
    print()
    
    event_handler = TranscriptHandler(persona_slug)
    observer = Observer()
    observer.schedule(event_handler, str(transcript_dir), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n🛑 Stopping watcher...")
        observer.stop()
    
    observer.join()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Auto-ingest transcripts to vector DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ingest all new transcripts for Jordi
  python auto_ingest_transcripts.py --persona jordi
  
  # Ingest for all personas
  python auto_ingest_transcripts.py --all
  
  # Watch mode (continuous)
  python auto_ingest_transcripts.py --watch --persona jordi
        """,
    )
    
    parser.add_argument("--persona", help="Persona slug (jordi, raoul, etc.)")
    parser.add_argument("--all", action="store_true", help="Process all personas")
    parser.add_argument("--watch", action="store_true", help="Watch mode (continuous)")
    
    args = parser.parse_args()
    
    # Validation
    if not args.persona and not args.all:
        print("❌ Must specify --persona or --all")
        parser.print_help()
        return 1
    
    if args.watch and args.all:
        print("❌ Cannot use --watch with --all (too many directories)")
        return 1
    
    # Watch mode
    if args.watch:
        watch_persona_transcripts(args.persona)
        return 0
    
    # Batch mode
    if args.all:
        personas = [d.name for d in TRANSCRIPTS_DIR.iterdir() if d.is_dir()]
        print(f"📁 Processing {len(personas)} personas: {', '.join(personas)}")
        print()
        
        total = 0
        for persona in personas:
            count = ingest_persona_transcripts(persona)
            total += count
        
        print()
        print(f"✅ Total ingested: {total} files across {len(personas)} personas")
    else:
        count = ingest_persona_transcripts(args.persona)
        print()
        print(f"✅ Ingested: {count} files for {args.persona}")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(1)
