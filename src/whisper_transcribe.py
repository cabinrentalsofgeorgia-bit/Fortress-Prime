#!/usr/bin/env python3
"""
Whisper Transcription Wrapper
Uses OpenAI Whisper for audio transcription (WhisperX alternative for ARM64)
"""

import sys
import os
import argparse
import json
from pathlib import Path
import subprocess

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def download_audio(youtube_url: str, output_path: str) -> bool:
    """Download audio from YouTube using yt-dlp"""
    print(f"📥 Downloading audio from: {youtube_url}")
    
    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--audio-quality", "0",  # Best quality
        "-o", output_path,
        youtube_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ Audio downloaded to: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Download failed: {e.stderr}")
        return False

def transcribe_audio(audio_path: str, model_name: str = "base") -> dict:
    """Transcribe audio using OpenAI Whisper"""
    import whisper
    
    print(f"🎤 Transcribing audio with model: {model_name}")
    print(f"   Audio file: {audio_path}")
    
    # Load model
    print(f"📦 Loading Whisper model: {model_name}")
    model = whisper.load_model(model_name)
    
    # Transcribe
    print(f"⚙️  Transcribing... (this may take a while)")
    result = model.transcribe(audio_path, verbose=True)
    
    print(f"✅ Transcription complete!")
    print(f"   Language detected: {result['language']}")
    print(f"   Segments: {len(result['segments'])}")
    
    return result

def save_transcript(result: dict, output_path: str):
    """Save transcript to file"""
    # Save full JSON
    json_path = output_path + ".json"
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"✅ Full transcript saved: {json_path}")
    
    # Save text only
    txt_path = output_path + ".txt"
    with open(txt_path, 'w') as f:
        f.write(result['text'])
    print(f"✅ Text transcript saved: {txt_path}")
    
    # Save with timestamps
    srt_path = output_path + ".srt"
    with open(srt_path, 'w') as f:
        for i, segment in enumerate(result['segments'], 1):
            start = format_timestamp(segment['start'])
            end = format_timestamp(segment['end'])
            text = segment['text'].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    print(f"✅ SRT subtitles saved: {srt_path}")

def format_timestamp(seconds: float) -> str:
    """Format seconds to SRT timestamp format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def main():
    parser = argparse.ArgumentParser(description="Whisper Audio Transcription")
    parser.add_argument("--youtube", help="YouTube URL to transcribe")
    parser.add_argument("--audio", help="Local audio file to transcribe")
    parser.add_argument("--model", default="base", 
                       choices=["tiny", "base", "small", "medium", "large"],
                       help="Whisper model size (default: base)")
    parser.add_argument("--output", help="Output directory for transcripts",
                       default="data/transcripts")
    parser.add_argument("--persona", help="Persona name (for organizing outputs)")
    
    args = parser.parse_args()
    
    if not args.youtube and not args.audio:
        parser.error("Either --youtube or --audio must be provided")
    
    # Create output directory
    output_dir = Path(args.output)
    if args.persona:
        output_dir = output_dir / args.persona
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Download audio if YouTube URL provided
    if args.youtube:
        import hashlib
        video_id = args.youtube.split('v=')[-1].split('&')[0]
        audio_path = str(output_dir / f"{video_id}.mp3")
        
        if not Path(audio_path).exists():
            success = download_audio(args.youtube, audio_path)
            if not success:
                return 1
        else:
            print(f"✅ Audio already downloaded: {audio_path}")
    else:
        audio_path = args.audio
    
    # Transcribe
    result = transcribe_audio(audio_path, args.model)
    
    # Save results
    output_base = str(output_dir / Path(audio_path).stem)
    save_transcript(result, output_base)
    
    print("\n" + "="*70)
    print("📊 TRANSCRIPTION SUMMARY")
    print("="*70)
    print(f"Audio file: {audio_path}")
    print(f"Model: {args.model}")
    print(f"Language: {result['language']}")
    print(f"Duration: {result['segments'][-1]['end']:.1f}s")
    print(f"Segments: {len(result['segments'])}")
    print(f"Output: {output_base}.*")
    print("="*70)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
