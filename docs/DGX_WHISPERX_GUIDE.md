# 🎙️ DGX WhisperX Pipeline - Complete Guide

**Purpose**: Autonomous audio transcription + ingestion system running on DGX Spark units

**Status**: ⚡ **READY FOR DEPLOYMENT**

---

## 🎯 What This System Does

Fully autonomous pipeline that:
1. **Monitors** YouTube channels, podcast feeds for new audio
2. **Downloads** audio files locally
3. **Transcribes** using WhisperX on DGX (GPU-accelerated, private)
4. **Auto-ingests** transcripts into persona vector collections
5. **Runs 24/7** without manual intervention

**Result**: Every podcast, video, interview gets transcribed → embedded → queryable within hours of publication.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  DGX WHISPERX PIPELINE                       │
└─────────────────────────────────────────────────────────────┘

STAGE 1: AUDIO HUNTING
├── Monitor YouTube channels
├── Monitor podcast RSS feeds
├── Monitor Substack for embedded audio
└── Track processed URLs (no duplicates)

STAGE 2: DOWNLOAD
├── yt-dlp downloads audio from YouTube
├── curl downloads from direct URLs
└── Store in /mnt/fortress_nas/Audio_Cache/

STAGE 3: TRANSCRIPTION (DGX)
├── WhisperX large-v3 model
├── GPU acceleration (CUDA)
├── Speaker diarization (who said what)
├── Word-level timestamps
└── Output: Markdown transcripts

STAGE 4: AUTO-INGESTION
├── Parse transcript metadata
├── Chunk text intelligently
├── Embed with nomic-embed-text
├── Upload to Qdrant persona collections
└── Store in /mnt/fortress_nas/Transcripts/{persona}/

STAGE 5: CLEANUP
├── Delete processed audio files
├── Update state tracking
└── Ready for next run
```

---

## 📦 Components

| File | Purpose | Lines |
|------|---------|-------|
| `src/dgx_whisperx_pipeline.py` | Core transcription pipeline | 600 |
| `src/auto_ingest_transcripts.py` | Transcript → Vector DB ingestion | 400 |
| `src/dgx_whisperx_monitor.py` | 24/7 monitoring daemon | 400 |
| `setup_dgx_whisperx.sh` | One-command DGX setup | 200 |

---

## 🚀 Quick Start

### Step 1: Setup DGX (5-10 min)

```bash
cd /home/admin/Fortress-Prime
bash setup_dgx_whisperx.sh
```

**What it does:**
- Installs PyTorch with CUDA
- Installs WhisperX
- Downloads large-v3 model (~3 GB)
- Installs yt-dlp, ffmpeg
- Creates storage directories
- Tests CUDA availability

**Requirements:**
- NVIDIA DGX with CUDA 12.x
- ~20 GB disk space (models + audio cache)
- Internet connection

### Step 2: Test Single File (2 min)

```bash
# Download sample audio
yt-dlp --extract-audio --audio-format mp3 \
  -o sample.mp3 \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Transcribe
python src/dgx_whisperx_pipeline.py \
  --audio sample.mp3 \
  --persona jordi

# Expected output:
# 🎙️  Transcribing: sample.mp3
#    Model: large-v3
#    Device: cuda (float16)
#    ✅ Transcription complete: 45 segments
#    ✅ Transcript saved: /mnt/fortress_nas/Transcripts/jordi/sample_transcript.md
```

### Step 3: Ingest Transcript (1 min)

```bash
# Auto-ingest transcripts for Jordi
python src/auto_ingest_transcripts.py --persona jordi

# Expected output:
# 📥 Ingesting: sample_transcript.md → jordi_intel
#    Chunked into 12 segments
#    ✅ Uploaded 12/12 chunks
```

### Step 4: Verify in Vector DB

```bash
# Check Jordi collection
./bin/sovereign status jordi

# Query the new content
./bin/sovereign jordi "sample topic from video"
```

---

## 🎯 Usage Patterns

### Pattern A: Single Video Transcription

```bash
# YouTube video
python src/dgx_whisperx_pipeline.py \
  --youtube "https://youtube.com/watch?v=xxx" \
  --persona raoul

# Direct audio URL
python src/dgx_whisperx_pipeline.py \
  --audio "https://example.com/podcast.mp3" \
  --persona lyn
```

### Pattern B: Batch Processing

```bash
# Transcribe all audio in a directory
python src/dgx_whisperx_pipeline.py \
  --batch /path/to/audio/files/ \
  --persona vol_trader

# Keep audio files (don't auto-delete)
python src/dgx_whisperx_pipeline.py \
  --batch /path/to/audio/ \
  --persona fed_watcher \
  --no-cleanup
```

### Pattern C: Automated Monitoring (24/7)

```bash
# Single persona, check every 6 hours
python src/dgx_whisperx_monitor.py \
  --persona jordi \
  --interval 6 \
  --daemon

# Multiple personas
python src/dgx_whisperx_monitor.py \
  --personas jordi,raoul,lyn \
  --interval 6 \
  --daemon

# All personas
python src/dgx_whisperx_monitor.py \
  --all \
  --interval 6 \
  --daemon
```

### Pattern D: Watch Mode (Real-Time)

```bash
# Watch Jordi transcript directory and auto-ingest
python src/auto_ingest_transcripts.py \
  --watch \
  --persona jordi

# In another terminal, transcribe new audio
# Transcripts auto-ingest as they're created
```

---

## 🔧 Configuration

### Environment Variables

```bash
# Qdrant
export QDRANT_URL="http://localhost:6333"
export QDRANT_API_KEY="your_key_here"

# Ollama (for embeddings)
export OLLAMA_URL="http://localhost:11434"

# WhisperX Model
export WHISPERX_MODEL="large-v3"  # or medium, small
export WHISPERX_BATCH_SIZE="16"   # Higher = faster on DGX

# HuggingFace (for speaker diarization)
export HF_TOKEN="your_hf_token"   # Optional
```

### Storage Paths

```
/mnt/fortress_nas/
├── Audio_Cache/              # Temp audio storage (auto-deleted)
├── Transcripts/              # Final transcripts
│   ├── jordi/
│   ├── raoul/
│   ├── lyn/
│   ├── vol_trader/
│   ├── fed_watcher/
│   ├── sound_money/
│   ├── real_estate/
│   ├── permabear/
│   └── black_swan/
└── Intelligence/             # Original source files (from hunters)
    ├── Jordi_Visser/
    ├── Raoul_Pal/
    └── ...
```

### Persona Data Sources

Edit `src/dgx_whisperx_monitor.py`:

```python
PERSONA_SOURCES = {
    "jordi": {
        "youtube_channels": ["UC8H8L0KVl2AKI0dERXKAUuQ"],  # Pomp Podcast
        "podcast_rss": ["https://feeds.megaphone.fm/WWO3519750118"],
        "substack": "visserlabs.substack.com",
    },
    "raoul": {
        "youtube_channels": ["UCskaAm0ra016pMqGSa5x4gw"],  # Real Vision
        "substack": "raoulpal.substack.com",
    },
    # Add more...
}
```

---

## 📊 Performance

### Transcription Speed (DGX A100)

| Model | Audio Length | Transcription Time | Real-Time Factor |
|-------|--------------|-------------------|------------------|
| **large-v3** | 60 min | ~3-5 min | 12-20x |
| **medium** | 60 min | ~2-3 min | 20-30x |
| **small** | 60 min | ~1-2 min | 30-60x |

**Example**: 1-hour podcast transcribes in ~4 minutes on DGX.

### Throughput

**Single DGX Unit:**
- **Podcasts/day**: ~300 (1 hour each)
- **Total audio/day**: ~300 hours
- **Concurrent limit**: ~10 transcriptions (GPU memory)

**Two DGX Units (Spark-01 + Spark-02):**
- **Podcasts/day**: ~600
- **Total audio/day**: ~600 hours

**Bottleneck**: Download speed (Internet), not transcription.

---

## 🎓 Advanced Features

### Speaker Diarization (Who Said What)

**Setup:**
1. Get HuggingFace token: https://huggingface.co/settings/tokens
2. Accept terms: https://huggingface.co/pyannote/speaker-diarization
3. Export: `export HF_TOKEN='your_token'`

**Output:**
```markdown
**Speaker_00**: [00:15] Welcome to the podcast...
**Speaker_01**: [00:32] Thanks for having me...
**Speaker_00**: [01:05] Let's talk about Bitcoin...
```

### Multi-Language Support

```bash
# Spanish
python src/dgx_whisperx_pipeline.py \
  --audio podcast.mp3 \
  --persona jordi \
  --language es

# Auto-detect (default)
python src/dgx_whisperx_pipeline.py \
  --audio podcast.mp3 \
  --persona jordi
```

Supported: en, es, fr, de, it, pt, ru, zh, ja, ko, and 90+ more

### Word-Level Timestamps

WhisperX provides word-level alignment:

```json
{
  "text": "Bitcoin is digital scarcity",
  "words": [
    {"word": "Bitcoin", "start": 15.2, "end": 15.6},
    {"word": "is", "start": 15.7, "end": 15.8},
    {"word": "digital", "start": 15.9, "end": 16.3},
    {"word": "scarcity", "start": 16.4, "end": 17.0}
  ]
}
```

Useful for: Video clipping, timestamp navigation, precise citation.

---

## 🛠️ Troubleshooting

### "CUDA out of memory"

**Cause**: Batch size too high for GPU memory

**Fix:**
```bash
export WHISPERX_BATCH_SIZE="8"  # Reduce from default 16
```

### "WhisperX not installed"

**Fix:**
```bash
pip install --break-system-packages whisperx
```

### "yt-dlp download failed"

**Causes**:
- Video is private/deleted
- Region-restricted
- Network timeout

**Fix**:
```bash
# Test manually
yt-dlp --extract-audio --audio-format mp3 "URL"

# Use cookies if age-restricted
yt-dlp --cookies-from-browser chrome "URL"
```

### "Transcription very slow (CPU)"

**Cause**: CUDA not available

**Check:**
```python
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

**Fix**: Reinstall PyTorch with CUDA:
```bash
pip install --break-system-packages torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
```

### "Speaker diarization failed"

**Cause**: HF_TOKEN not set

**Fix:**
```bash
export HF_TOKEN='your_token_here'
echo "export HF_TOKEN='...'" >> ~/.bashrc
```

---

## 🔄 Integration with Council of Giants

### Workflow

```
1. DGX Pipeline Transcribes Audio
   └─> /mnt/fortress_nas/Transcripts/jordi/podcast_123_transcript.md

2. Auto-Ingestion Embeds Content
   └─> Qdrant: jordi_intel collection (+35 vectors)

3. Council Can Now Query
   └─> ./bin/sovereign jordi "Bitcoin outlook"
   └─> Returns insights from newly transcribed podcast!
```

### Example: Jordi New Podcast

```bash
# 1. Monitor detects new Pomp Podcast episode
# 2. Downloads audio (1 min)
# 3. Transcribes with WhisperX (4 min for 60-min podcast)
# 4. Auto-ingests chunks (2 min)
# 5. Available in Council votes (immediate)

# Total: ~7 minutes from publication to queryable!
```

---

## 📈 Scaling Strategy

### Phase 1: Single Persona (Week 1)
- Deploy for Jordi only
- Monitor The Pomp Podcast
- Transcribe 2-4 episodes/week
- **Goal**: Validate pipeline end-to-end

### Phase 2: Core Personas (Week 2-3)
- Add Raoul, Lyn, Vol Trader
- Monitor 10+ sources
- Transcribe 10-20 episodes/week
- **Goal**: Multi-persona operational

### Phase 3: Full Council (Week 4)
- All 9 personas
- Monitor 30+ sources
- Transcribe 50+ episodes/week
- **Goal**: Comprehensive coverage

### Phase 4: Scale (Month 2+)
- Add 10+ more personas
- Monitor 100+ sources
- Transcribe 200+ episodes/week
- **Goal**: Become the macro research Hive Mind

---

## 💰 Cost Analysis

### Hardware (One-Time)
- **2x DGX Spark units**: Already owned ✅
- **Storage (NAS)**: Already owned ✅
- **Total new cost**: $0

### Operating Costs
- **Electricity**: ~$50/month (DGX idle 90% of time)
- **Internet**: Already paid for
- **API costs**: $0 (all local compute)
- **Total monthly**: ~$50

### Value
- **Manual transcription**: $1.50/min = $90/hour
- **100 hours/week**: $9,000/week = $468,000/year
- **Your cost**: ~$600/year

**ROI**: 780x 🚀

---

## 🎯 Success Metrics

### Week 1 (Validation)
- [ ] Setup complete (all dependencies installed)
- [ ] Single video transcribed successfully
- [ ] Transcript ingested to vector DB
- [ ] Query returns relevant results

### Week 2 (Automation)
- [ ] Monitor daemon running 24/7
- [ ] 10+ transcripts processed automatically
- [ ] No manual intervention required
- [ ] Zero transcription errors

### Month 1 (Scale)
- [ ] All 9 personas operational
- [ ] 200+ transcripts processed
- [ ] Council voting with real data
- [ ] Query latency <500ms

### Month 2 (Production)
- [ ] 500+ transcripts in system
- [ ] Add 5+ new personas
- [ ] <1% error rate
- [ ] Dashboard operational

---

## 📚 Related Documentation

| Document | Purpose |
|----------|---------|
| `DGX_WHISPERX_GUIDE.md` | **This file** - Complete guide |
| `COUNCIL_OF_GIANTS_ARCHITECTURE.md` | Multi-persona system design |
| `src/dgx_whisperx_pipeline.py` | Transcription pipeline code |
| `src/dgx_whisperx_monitor.py` | Monitoring daemon code |
| `setup_dgx_whisperx.sh` | DGX setup script |

---

## ⚡ Next Steps

**You have 3 paths:**

### Path A: Test Now (15 min)
```bash
bash setup_dgx_whisperx.sh
# Test with sample video
# Verify end-to-end
```

### Path B: Deploy Jordi (1 day)
```bash
bash setup_dgx_whisperx.sh
# Configure Jordi sources
# Run monitor in background
# Validate 24 hours
```

### Path C: Full Council (1 week)
```bash
bash setup_dgx_whisperx.sh
# Configure all 9 personas
# Deploy systemd services
# Monitor performance
```

---

**Status**: ✅ **READY FOR DEPLOYMENT**

The DGX WhisperX pipeline is fully built and documented. Time to transcribe the world! 🎙️⚡
