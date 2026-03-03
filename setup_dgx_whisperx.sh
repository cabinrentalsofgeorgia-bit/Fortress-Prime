#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# DGX WhisperX Pipeline Setup
# ═══════════════════════════════════════════════════════════════════════════
# Sets up WhisperX transcription system on NVIDIA DGX Spark units.
#
# Prerequisites:
#   - NVIDIA DGX with CUDA 12.x
#   - Python 3.10+
#   - Internet connection (for model downloads)
#
# Usage:
#   bash setup_dgx_whisperx.sh
#
# Author: Fortress Prime Architect
# ═══════════════════════════════════════════════════════════════════════════

set -e

WORKSPACE="/home/admin/Fortress-Prime"
cd "$WORKSPACE"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 DGX WHISPERX PIPELINE SETUP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Check CUDA
# ═══════════════════════════════════════════════════════════════════════════

echo "Step 1: Checking CUDA availability..."
echo ""

if command -v nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA GPU detected:"
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1
    CUDA_AVAILABLE=true
else
    echo "⚠️  NVIDIA GPU not detected"
    echo "   WhisperX will run on CPU (very slow)"
    CUDA_AVAILABLE=false
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Install PyTorch with CUDA
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Installing PyTorch with CUDA support..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if $CUDA_AVAILABLE; then
    echo "Installing PyTorch with CUDA 12.1..."
    pip install --break-system-packages torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
else
    echo "Installing PyTorch (CPU only)..."
    pip install --break-system-packages torch torchvision torchaudio
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Install WhisperX
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Installing WhisperX..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

pip install --break-system-packages whisperx

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Install Audio Tools
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4: Installing audio download tools..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if ! command -v yt-dlp &> /dev/null; then
    echo "Installing yt-dlp..."
    pip install --break-system-packages yt-dlp
else
    echo "✅ yt-dlp already installed"
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg
else
    echo "✅ ffmpeg already installed"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 5: Download WhisperX Models
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 5: Downloading WhisperX models (this may take a while)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Downloading large-v3 model (best quality)..."
python3 -c "
import whisperx
print('Loading model...')
model = whisperx.load_model('large-v3', device='cpu', compute_type='int8')
print('✅ Model downloaded successfully')
" 2>&1 | grep -E "✅|Loading|Downloading"

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 6: Test Installation
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 6: Testing installation..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 -c "
import sys
import torch
import whisperx

print('Python version:', sys.version)
print('PyTorch version:', torch.__version__)
print('CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('CUDA version:', torch.version.cuda)
    print('GPU:', torch.cuda.get_device_name(0))
    print('GPU memory:', f'{torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
print('WhisperX installed: ✅')
"

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 7: Create Storage Directories
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 7: Creating storage directories..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

mkdir -p /mnt/fortress_nas/Audio_Cache
mkdir -p /mnt/fortress_nas/Transcripts/{jordi,raoul,lyn,vol_trader,fed_watcher,sound_money,real_estate,permabear,black_swan}

echo "✅ Directories created:"
echo "   /mnt/fortress_nas/Audio_Cache (temp audio storage)"
echo "   /mnt/fortress_nas/Transcripts/* (persona transcripts)"

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Step 8: Optional - HuggingFace Token for Diarization
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 8: Speaker Diarization Setup (Optional)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -z "$HF_TOKEN" ]; then
    echo "⚠️  HF_TOKEN not set - speaker diarization will be skipped"
    echo ""
    echo "   To enable speaker diarization:"
    echo "   1. Get token at: https://huggingface.co/settings/tokens"
    echo "   2. Accept terms: https://huggingface.co/pyannote/speaker-diarization"
    echo "   3. Export: export HF_TOKEN='your_token_here'"
    echo "   4. Add to ~/.bashrc for persistence"
else
    echo "✅ HF_TOKEN configured - speaker diarization enabled"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Setup Complete
# ═══════════════════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ SETUP COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo ""
echo "1️⃣  Test with a sample audio file:"
echo "    python src/dgx_whisperx_pipeline.py --audio sample.mp3 --persona jordi"
echo ""
echo "2️⃣  Transcribe from YouTube:"
echo "    python src/dgx_whisperx_pipeline.py --youtube 'https://youtube.com/watch?v=xxx' --persona raoul"
echo ""
echo "3️⃣  Batch process directory:"
echo "    python src/dgx_whisperx_pipeline.py --batch /path/to/audio/ --persona lyn"
echo ""
echo "4️⃣  Set up automated monitoring (coming soon):"
echo "    python src/dgx_whisperx_monitor.py --personas jordi,raoul,lyn"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📚 Documentation:"
echo "   Setup Guide: docs/DGX_WHISPERX_GUIDE.md"
echo "   Pipeline Code: src/dgx_whisperx_pipeline.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
