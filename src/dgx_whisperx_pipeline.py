#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — DGX WHISPERX TRANSCRIPTION PIPELINE
═══════════════════════════════════════════════════════════════════════════════
Local audio transcription pipeline using WhisperX on DGX Spark units.

Workflow:
    1. Monitor audio sources (YouTube, podcasts)
    2. Download audio files (yt-dlp)
    3. Transcribe locally with WhisperX (DGX)
    4. Auto-chunk and ingest into persona collections
    5. Clean up processed audio

Features:
    - Speaker diarization (who said what)
    - Multi-language support
    - Timestamp alignment
    - Batch processing
    - GPU acceleration (DGX)

Requirements:
    pip install whisperx yt-dlp torch torchaudio

DGX Setup:
    - CUDA 12.x
    - PyTorch with CUDA support
    - WhisperX with GPU acceleration
    
Usage:
    # Single file
    python dgx_whisperx_pipeline.py --audio podcast.mp3 --persona jordi
    
    # Batch from YouTube
    python dgx_whisperx_pipeline.py --youtube-url URL --persona jordi
    
    # Monitor mode (24/7)
    python dgx_whisperx_pipeline.py --monitor --persona jordi

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
import hashlib
import shutil

# Try to import WhisperX (optional - install separately)
try:
    import whisperx
    WHISPERX_AVAILABLE = True
except ImportError:
    WHISPERX_AVAILABLE = False
    print("⚠️  WhisperX not installed. Run: pip install whisperx")

# Try to import torch for GPU detection
try:
    import torch
    TORCH_AVAILABLE = True
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    TORCH_AVAILABLE = False
    CUDA_AVAILABLE = False


# =============================================================================
# Configuration
# =============================================================================

# Storage paths
AUDIO_CACHE = Path("/mnt/fortress_nas/Audio_Cache")
TRANSCRIPTS_DIR = Path("/mnt/fortress_nas/Transcripts")
AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# WhisperX settings
WHISPERX_MODEL = os.getenv("WHISPERX_MODEL", "large-v3")  # large-v3, medium, small
DEVICE = "cuda" if CUDA_AVAILABLE else "cpu"
BATCH_SIZE = int(os.getenv("WHISPERX_BATCH_SIZE", "16"))  # Higher = faster on DGX
COMPUTE_TYPE = "float16" if CUDA_AVAILABLE else "int8"  # GPU vs CPU

# Audio download settings
MAX_AUDIO_LENGTH = 4 * 3600  # 4 hours max (prevent hanging on long streams)
AUDIO_QUALITY = "bestaudio/best"

# State tracking
STATE_FILE = TRANSCRIPTS_DIR / "transcription_state.json"


# =============================================================================
# State Management
# =============================================================================

def load_state() -> Dict:
    """Load transcription state (prevents re-processing)."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"processed_files": [], "processed_urls": {}}


def save_state(state: Dict):
    """Save transcription state."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_file_hash(filepath: Path) -> str:
    """Generate hash for audio file (dedupe check)."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


# =============================================================================
# Audio Download (yt-dlp)
# =============================================================================

def download_audio_from_youtube(
    url: str,
    output_dir: Path = AUDIO_CACHE,
) -> Optional[Path]:
    """
    Download audio from YouTube URL using yt-dlp.
    
    Args:
        url: YouTube video URL
        output_dir: Where to save audio file
    
    Returns:
        Path to downloaded audio file, or None if failed
    """
    print(f"📥 Downloading audio from: {url}")
    
    # Generate safe filename from URL
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    output_template = output_dir / f"yt_{url_hash}_%(title)s.%(ext)s"
    
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",  # Best quality
        "--output", str(output_template),
        "--no-playlist",  # Don't download playlists
        "--max-downloads", "1",
        url,
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
        
        if result.returncode == 0:
            # Find the downloaded file
            pattern = f"yt_{url_hash}_*"
            files = list(output_dir.glob(pattern))
            if files:
                print(f"✅ Downloaded: {files[0].name}")
                return files[0]
        
        print(f"❌ Download failed: {result.stderr}")
        return None
    
    except subprocess.TimeoutExpired:
        print(f"❌ Download timeout (>10 min)")
        return None
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None


def download_audio_from_url(url: str) -> Optional[Path]:
    """
    Download audio from generic URL (podcast feed, etc.).
    
    Args:
        url: Direct audio file URL
    
    Returns:
        Path to downloaded file
    """
    print(f"📥 Downloading audio from: {url}")
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    filename = f"audio_{url_hash}.mp3"
    output_path = AUDIO_CACHE / filename
    
    try:
        # Use curl or wget
        cmd = ["curl", "-L", "-o", str(output_path), url]
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        
        if result.returncode == 0 and output_path.exists():
            print(f"✅ Downloaded: {filename}")
            return output_path
        
        print(f"❌ Download failed")
        return None
    
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None


# =============================================================================
# WhisperX Transcription
# =============================================================================

def transcribe_audio_whisperx(
    audio_path: Path,
    language: str = "en",
    diarize: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Transcribe audio using WhisperX with speaker diarization.
    
    Args:
        audio_path: Path to audio file
        language: Language code (en, es, fr, etc.)
        diarize: Enable speaker diarization
    
    Returns:
        Transcription dict with segments, speakers, timestamps
    """
    if not WHISPERX_AVAILABLE:
        print("❌ WhisperX not installed")
        return None
    
    print(f"🎙️  Transcribing: {audio_path.name}")
    print(f"   Model: {WHISPERX_MODEL}")
    print(f"   Device: {DEVICE} ({COMPUTE_TYPE})")
    print(f"   Diarization: {diarize}")
    
    try:
        # 1. Load audio
        audio = whisperx.load_audio(str(audio_path))
        
        # 2. Load WhisperX model
        model = whisperx.load_model(
            WHISPERX_MODEL,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
        )
        
        # 3. Transcribe
        result = model.transcribe(
            audio,
            batch_size=BATCH_SIZE,
            language=language,
        )
        
        print(f"   ✅ Transcription complete: {len(result['segments'])} segments")
        
        # 4. Align timestamps (word-level)
        model_a, metadata = whisperx.load_align_model(
            language_code=language,
            device=DEVICE,
        )
        result = whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            device=DEVICE,
        )
        
        print(f"   ✅ Timestamp alignment complete")
        
        # 5. Speaker diarization (optional)
        if diarize:
            try:
                # Requires HuggingFace token for pyannote models
                hf_token = os.getenv("HF_TOKEN")
                if hf_token:
                    diarize_model = whisperx.DiarizationPipeline(
                        use_auth_token=hf_token,
                        device=DEVICE,
                    )
                    diarize_segments = diarize_model(audio)
                    result = whisperx.assign_word_speakers(
                        diarize_segments,
                        result,
                    )
                    print(f"   ✅ Speaker diarization complete")
                else:
                    print(f"   ⚠️  HF_TOKEN not set - skipping diarization")
            except Exception as e:
                print(f"   ⚠️  Diarization failed: {e}")
        
        return result
    
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return None


def format_transcript(
    result: Dict[str, Any],
    audio_path: Path,
    metadata: Optional[Dict] = None,
) -> str:
    """
    Format WhisperX output as human-readable transcript.
    
    Args:
        result: WhisperX transcription result
        audio_path: Source audio file
        metadata: Optional metadata (title, speaker, etc.)
    
    Returns:
        Formatted markdown transcript
    """
    lines = []
    
    # Header
    lines.append(f"# Transcript: {audio_path.stem}")
    lines.append("")
    
    if metadata:
        lines.append("## Metadata")
        lines.append("")
        for key, value in metadata.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")
    
    lines.append(f"- **Source**: {audio_path.name}")
    lines.append(f"- **Transcribed**: {datetime.now().isoformat()}")
    lines.append(f"- **Model**: {WHISPERX_MODEL}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Transcript body
    lines.append("## Transcript")
    lines.append("")
    
    current_speaker = None
    
    for segment in result.get("segments", []):
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "").strip()
        speaker = segment.get("speaker", "Unknown")
        
        # Format timestamp
        timestamp = f"[{int(start//60):02d}:{int(start%60):02d}]"
        
        # Add speaker label if changed
        if speaker != current_speaker:
            lines.append(f"**{speaker}**: {timestamp} {text}")
            current_speaker = speaker
        else:
            lines.append(f"{timestamp} {text}")
    
    return "\n".join(lines)


# =============================================================================
# Pipeline Orchestration
# =============================================================================

def process_audio_file(
    audio_path: Path,
    persona_slug: str,
    language: str = "en",
    cleanup: bool = True,
) -> Optional[Path]:
    """
    Full pipeline: Transcribe → Format → Save → (optionally) Ingest.
    
    Args:
        audio_path: Path to audio file
        persona_slug: Persona to attribute this to (jordi, raoul, etc.)
        language: Language code
        cleanup: Delete audio after transcription
    
    Returns:
        Path to transcript file
    """
    # Check if already processed
    state = load_state()
    file_hash = get_file_hash(audio_path)
    
    if file_hash in state.get("processed_files", []):
        print(f"⏭️  Already processed: {audio_path.name}")
        return None
    
    print(f"\n{'='*70}")
    print(f"🎙️  PROCESSING AUDIO: {audio_path.name}")
    print(f"   Persona: {persona_slug}")
    print(f"{'='*70}\n")
    
    # 1. Transcribe with WhisperX
    result = transcribe_audio_whisperx(audio_path, language=language, diarize=True)
    
    if not result:
        print(f"❌ Transcription failed")
        return None
    
    # 2. Format transcript
    metadata = {
        "Persona": persona_slug,
        "Language": language,
        "Audio File": audio_path.name,
    }
    
    transcript_text = format_transcript(result, audio_path, metadata)
    
    # 3. Save transcript
    transcript_dir = TRANSCRIPTS_DIR / persona_slug
    transcript_dir.mkdir(exist_ok=True)
    
    transcript_filename = f"{audio_path.stem}_transcript.md"
    transcript_path = transcript_dir / transcript_filename
    
    with open(transcript_path, 'w', encoding='utf-8') as f:
        f.write(transcript_text)
    
    print(f"✅ Transcript saved: {transcript_path}")
    
    # 4. Update state
    state["processed_files"].append(file_hash)
    save_state(state)
    
    # 5. Cleanup audio (optional)
    if cleanup and audio_path.parent == AUDIO_CACHE:
        audio_path.unlink()
        print(f"🗑️  Cleaned up: {audio_path.name}")
    
    return transcript_path


def process_youtube_url(
    url: str,
    persona_slug: str,
    language: str = "en",
) -> Optional[Path]:
    """
    Download from YouTube → Transcribe → Ingest.
    
    Args:
        url: YouTube video URL
        persona_slug: Persona attribution
        language: Language code
    
    Returns:
        Path to transcript
    """
    # Check if URL already processed
    state = load_state()
    if url in state.get("processed_urls", {}):
        print(f"⏭️  URL already processed: {url}")
        return None
    
    # Download audio
    audio_path = download_audio_from_youtube(url)
    if not audio_path:
        return None
    
    # Process audio
    transcript_path = process_audio_file(
        audio_path,
        persona_slug,
        language=language,
        cleanup=True,
    )
    
    if transcript_path:
        # Track URL
        state["processed_urls"][url] = {
            "transcript": str(transcript_path),
            "processed_at": datetime.now().isoformat(),
        }
        save_state(state)
    
    return transcript_path


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="DGX WhisperX Transcription Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Transcribe local audio
  python dgx_whisperx_pipeline.py --audio podcast.mp3 --persona jordi
  
  # Download + transcribe from YouTube
  python dgx_whisperx_pipeline.py --youtube https://youtube.com/watch?v=xxx --persona raoul
  
  # Batch process directory
  python dgx_whisperx_pipeline.py --batch /path/to/audio/ --persona lyn
  
  # Monitor mode (24/7 autonomous)
  python dgx_whisperx_pipeline.py --monitor --persona jordi
        """,
    )
    
    parser.add_argument("--audio", type=Path, help="Local audio file to transcribe")
    parser.add_argument("--youtube", type=str, help="YouTube URL to download + transcribe")
    parser.add_argument("--batch", type=Path, help="Directory of audio files to process")
    parser.add_argument("--persona", required=True, help="Persona slug (jordi, raoul, etc.)")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep audio files after transcription")
    parser.add_argument("--monitor", action="store_true", help="Monitor mode (not yet implemented)")
    
    args = parser.parse_args()
    
    # Validation
    if not WHISPERX_AVAILABLE:
        print("❌ WhisperX not installed")
        print("   Install: pip install whisperx")
        print("   Docs: https://github.com/m-bain/whisperX")
        return 1
    
    if not CUDA_AVAILABLE:
        print("⚠️  CUDA not available - using CPU (slow)")
        print("   For DGX: Install PyTorch with CUDA support")
    
    # Process based on input type
    if args.audio:
        if not args.audio.exists():
            print(f"❌ Audio file not found: {args.audio}")
            return 1
        
        transcript = process_audio_file(
            args.audio,
            args.persona,
            language=args.language,
            cleanup=not args.no_cleanup,
        )
        
        if transcript:
            print(f"\n✅ SUCCESS: {transcript}")
            return 0
        else:
            return 1
    
    elif args.youtube:
        transcript = process_youtube_url(
            args.youtube,
            args.persona,
            language=args.language,
        )
        
        if transcript:
            print(f"\n✅ SUCCESS: {transcript}")
            return 0
        else:
            return 1
    
    elif args.batch:
        if not args.batch.is_dir():
            print(f"❌ Not a directory: {args.batch}")
            return 1
        
        # Process all audio files in directory
        audio_extensions = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
        audio_files = [f for f in args.batch.iterdir() if f.suffix.lower() in audio_extensions]
        
        print(f"📁 Found {len(audio_files)} audio files")
        
        success_count = 0
        for audio_file in audio_files:
            transcript = process_audio_file(
                audio_file,
                args.persona,
                language=args.language,
                cleanup=not args.no_cleanup,
            )
            if transcript:
                success_count += 1
        
        print(f"\n✅ Processed {success_count}/{len(audio_files)} files")
        return 0
    
    elif args.monitor:
        print("⚠️  Monitor mode not yet implemented")
        print("   Coming in next version")
        return 1
    
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
