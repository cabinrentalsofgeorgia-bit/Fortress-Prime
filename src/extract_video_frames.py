"""
FORTRESS PRIME — Video Frame Extractor (Division 6 — The Eye)
===============================================================
Extracts keyframes from property walkthrough videos, security footage,
and archive reels. Feeds frames into the vision pipeline for AI analysis.

Uses OpenCV (no ffmpeg dependency) to:
1. Walk video directories on the NAS
2. Extract keyframes at configurable intervals (default: 1 per 10 seconds)
3. Save frames as JPGs to a staging directory
4. Optionally feed directly into ingest_vision.py

Architecture:
    NAS Videos → OpenCV keyframe extraction → JPG staging dir
    → ingest_vision.py → llava:v1.6 → PostgreSQL + ChromaDB

Usage:
    # Extract frames from all videos (default: Vol1 Video Library)
    python3 src/extract_video_frames.py

    # Custom source and output
    python3 src/extract_video_frames.py --source /mnt/vol1_source/Personal/Video_Library --output /mnt/ai_fast/video_frames

    # Extract 1 frame per 30 seconds (fewer frames, faster)
    python3 src/extract_video_frames.py --interval 30

    # Limit to first 10 videos (testing)
    python3 src/extract_video_frames.py --limit 10

    # Extract AND immediately feed to The Eye
    python3 src/extract_video_frames.py --ingest
"""

import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

import cv2

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_VIDEO_DIRS = [
    "/mnt/vol1_source/Personal/Video_Library",
    "/mnt/fortress_nas/raw_images",  # May contain .mov files
]

DEFAULT_OUTPUT_DIR = "/mnt/ai_fast/video_frames"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv",
                    ".flv", ".webm", ".mpg", ".mpeg", ".3gp"}

# Keyframe extraction interval (seconds between frames)
DEFAULT_INTERVAL = 10

# Skip videos shorter than this (seconds)
MIN_VIDEO_DURATION = 5

# Max frames per video (safety limit)
MAX_FRAMES_PER_VIDEO = 100

# Skip directories
SKIP_DIRS = {"#recycle", "@eaDir", ".Trash-1000", "@tmp"}


# =============================================================================
# VIDEO DISCOVERY
# =============================================================================

def discover_videos(source_dirs: list) -> list:
    """Walk source directories and find all video files."""
    videos = []
    for source in source_dirs:
        if not os.path.exists(source):
            print(f"  SKIP: {source} does not exist")
            continue

        for root, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in VIDEO_EXTENSIONS:
                    videos.append(os.path.join(root, f))

    return sorted(videos)


# =============================================================================
# KEYFRAME EXTRACTION
# =============================================================================

def extract_keyframes(video_path: str, output_dir: str,
                      interval_sec: int = DEFAULT_INTERVAL) -> dict:
    """
    Extract keyframes from a video file using OpenCV.

    Returns:
        dict with: frames_extracted, duration, fps, resolution, output_files
    """
    result = {
        "video": video_path,
        "frames_extracted": 0,
        "duration_sec": 0,
        "fps": 0,
        "resolution": "",
        "output_files": [],
        "error": None,
    }

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            result["error"] = "Cannot open video"
            return result

        # Video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if fps <= 0 or total_frames <= 0:
            result["error"] = "Invalid video metadata"
            cap.release()
            return result

        duration = total_frames / fps
        result["duration_sec"] = round(duration, 1)
        result["fps"] = round(fps, 1)
        result["resolution"] = f"{width}x{height}"

        if duration < MIN_VIDEO_DURATION:
            result["error"] = f"Too short ({duration:.1f}s)"
            cap.release()
            return result

        # Calculate frame positions
        frame_interval = int(fps * interval_sec)
        frame_positions = list(range(0, total_frames, frame_interval))

        # Safety limit
        if len(frame_positions) > MAX_FRAMES_PER_VIDEO:
            frame_positions = frame_positions[:MAX_FRAMES_PER_VIDEO]

        # Build output subdirectory from video name
        video_name = Path(video_path).stem
        # Sanitize for filesystem
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in video_name)
        video_out_dir = os.path.join(output_dir, safe_name)
        os.makedirs(video_out_dir, exist_ok=True)

        # Extract frames
        for i, frame_pos in enumerate(frame_positions):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if not ret:
                continue

            timestamp_sec = frame_pos / fps
            frame_filename = f"{safe_name}_frame_{i:04d}_{timestamp_sec:.0f}s.jpg"
            frame_path = os.path.join(video_out_dir, frame_filename)

            # Save with reasonable quality
            cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            result["output_files"].append(frame_path)
            result["frames_extracted"] += 1

        cap.release()

    except Exception as e:
        result["error"] = str(e)

    return result


# =============================================================================
# MAIN
# =============================================================================

def run_extraction(source_dirs: list, output_dir: str, interval: int,
                   limit: int = 0, run_ingest: bool = False):
    """Main extraction pipeline."""
    print("=" * 72)
    print("  FORTRESS PRIME — VIDEO FRAME EXTRACTOR")
    print("=" * 72)
    print(f"  Sources:       {source_dirs}")
    print(f"  Output:        {output_dir}")
    print(f"  Interval:      1 frame per {interval}s")
    if limit:
        print(f"  Limit:         {limit} videos")
    print()

    # Discover videos
    print("  Discovering videos...", end="", flush=True)
    videos = discover_videos(source_dirs)
    print(f" found {len(videos):,}")

    if not videos:
        print("  No videos found. Nothing to do.")
        return

    if limit:
        videos = videos[:limit]
        print(f"  Limited to first {limit} videos.")

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Extract
    total_frames = 0
    total_duration = 0
    processed = 0
    failed = 0
    start_time = time.time()

    for i, video_path in enumerate(videos):
        fname = os.path.basename(video_path)
        fsize_mb = os.path.getsize(video_path) / (1024 * 1024)

        sys.stdout.write(f"  [{i+1}/{len(videos)}] {fname[:50]:<50} ({fsize_mb:.0f}MB)...")
        sys.stdout.flush()

        result = extract_keyframes(video_path, output_dir, interval)

        if result["error"]:
            print(f" FAIL ({result['error'][:40]})")
            failed += 1
        else:
            frames = result["frames_extracted"]
            dur = result["duration_sec"]
            total_frames += frames
            total_duration += dur
            processed += 1
            print(f" OK ({frames} frames, {dur:.0f}s, {result['resolution']})")

        # Progress every 10 videos
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            print(f"\n  --- {processed}/{len(videos)} done, "
                  f"{total_frames} frames extracted, "
                  f"{elapsed/60:.1f}min elapsed ---\n")

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 72)
    print("  VIDEO FRAME EXTRACTION COMPLETE")
    print("=" * 72)
    print(f"  Videos processed:  {processed:,}")
    print(f"  Videos failed:     {failed:,}")
    print(f"  Frames extracted:  {total_frames:,}")
    print(f"  Total video time:  {total_duration/60:.1f} minutes")
    print(f"  Output directory:  {output_dir}")
    print(f"  Elapsed:           {elapsed/60:.1f} minutes")

    if total_frames > 0:
        print(f"\n  Frames are ready for The Eye:")
        print(f"    python3 -u src/ingest_vision.py --node captain --path \"{output_dir}\"")

    # Auto-ingest if requested
    if run_ingest and total_frames > 0:
        print(f"\n  Auto-ingesting {total_frames} frames into The Eye...")
        os.system(
            f"python3 -u src/ingest_vision.py --node captain "
            f"--path \"{output_dir}\" --timeout 180"
        )

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Video Frame Extractor"
    )
    parser.add_argument("--source", nargs="+", default=DEFAULT_VIDEO_DIRS,
                        help="Video source directories")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory for frames (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Seconds between keyframes (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max videos to process (0=all)")
    parser.add_argument("--ingest", action="store_true",
                        help="Auto-feed extracted frames to The Eye")
    args = parser.parse_args()

    run_extraction(
        source_dirs=args.source,
        output_dir=args.output,
        interval=args.interval,
        limit=args.limit,
        run_ingest=args.ingest,
    )


if __name__ == "__main__":
    main()
