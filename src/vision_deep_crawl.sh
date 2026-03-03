#!/bin/bash
# ==============================================================================
# FORTRESS PRIME — The Deep Crawl (Vision Daemon)
# ==============================================================================
# Processes all cabin listing photos in priority order.
# Designed to run in a screen/tmux session and survive logout.
#
# Usage:
#   screen -dmS vision_crawler bash src/vision_deep_crawl.sh
#   screen -r vision_crawler   # to reattach
#
# The ingestion script is fully resumable — it skips already-processed images.
# ==============================================================================

set -e
cd /home/admin/Fortress-Prime

echo "=========================================="
echo "  THE DEEP CRAWL — Vision Daemon"
echo "  Started: $(date)"
echo "=========================================="

# --- PRIORITY 1: Raw listing photos (2,642 images — property hero shots) ---
echo ""
echo "[PRIORITY 1] Raw listing photos (raw_images)..."
python3 -u src/ingest_vision.py --node captain --path "/mnt/fortress_nas/raw_images" --timeout 180

# --- PRIORITY 2: Individual cabin folders (high-value) ---
for cabin in \
    "RiversEdge" \
    "Serendipity" \
    "Aska Escape Lodge" \
    "Buckhorn Lodge" \
    "Riverview lodge" \
    "Above The Pines" \
    "Fallen Timber" \
    "Rolling River" \
    "A Rolling River" \
    "A Rivers Bend" \
    "Celtic Clouds" \
    "Cloud 9" \
    "Cloud 10" \
    "Cadence Ridge" \
    "Durango Ridge" \
    "Eagles Landing" \
    "Echos By The Lake" \
    "Heavens Gate" \
    "Hickory Lodge" \
    "Majestic Lake" \
    "morningstar Vista" \
    "Outlaw Ridge" \
    "Paradise Found" \
    "Point of View" \
    "Royal Mountain Lodge" \
    "Rustic Retreat" \
    "Sanctuary" \
    "Sweet Surrender" \
    "Time Flies" \
    "Trappers Lodge" \
    "Urban Retreat" \
    "CABIN RENTALS OF GA" \
    "CRG WEBSITE"
do
    target="/mnt/vol1_source/Personal/Photos/$cabin"
    if [ -d "$target" ]; then
        echo ""
        echo "[PRIORITY 2] Processing: $cabin..."
        python3 -u src/ingest_vision.py --node captain --path "$target" --timeout 180
    fi
done

# --- PRIORITY 3: Full Vol1 Photos sweep (catch anything missed) ---
echo ""
echo "[PRIORITY 3] Full Vol1 Photos sweep..."
python3 -u src/ingest_vision.py --node captain --path "/mnt/vol1_source/Personal/Photos" --timeout 180

echo ""
echo "=========================================="
echo "  THE DEEP CRAWL — COMPLETE"
echo "  Finished: $(date)"
echo "=========================================="
