#!/usr/bin/env bash
# bakeoff_train.sh — Train one bake-off candidate adapter with locked hyperparams.
#
# Usage:
#   CANDIDATE=c1_qwen14b bash src/legal/bakeoff_train.sh
#   CANDIDATE=c2_mistral7b bash src/legal/bakeoff_train.sh
#   CANDIDATE=c3_phi3medium bash src/legal/bakeoff_train.sh
#
# All hyperparams locked; only BASE_MODEL, OUTPUT_DIR, and LORA_TARGET_MODULES differ.

set -euo pipefail

CANDIDATE="${CANDIDATE:?must set CANDIDATE (c0_qwen7b|c1_qwen14b|c2_mistral7b|c3_phi3medium)}"
PYTHON="/home/admin/Fortress-Prime/fortress-guest-platform/.uv-venv/bin/python3"
TRAIN_DATA="/mnt/fortress_nas/legal-corpus/training-pairs/train.jsonl"
VAL_DATA="/mnt/fortress_nas/legal-corpus/training-pairs/val.jsonl"
BAKEOFF_DIR="/mnt/fortress_nas/models/bakeoff_20260422"
LOG_DIR="/home/admin/Fortress-Prime/logs"
DATE=$(date +%Y%m%d)

# ── Locked hyperparams (identical for all candidates) ─────────────────────────
export LEGAL_LORA_RANK=16
export LEGAL_LORA_ALPHA=32
export LEGAL_MAX_SEQ_LEN=4096
export LEGAL_EPOCHS=3
export LEGAL_LR=2e-4
export LEGAL_BATCH_SIZE=1
export LEGAL_GRAD_ACCUM=8
export LEGAL_EVAL_STEPS=50
export LEGAL_SEED=42
export PYTHONPATH=/home/admin/Fortress-Prime

# ── Per-candidate config ───────────────────────────────────────────────────────
case "$CANDIDATE" in
  c0_qwen7b)
    export LEGAL_BASE_MODEL="qwen2.5:7b"
    export LEGAL_LORA_TARGET_MODULES="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
    ;;
  c1_qwen14b)
    export LEGAL_BASE_MODEL="qwen2.5:14b"
    export LEGAL_LORA_TARGET_MODULES="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
    ;;
  c2_mistral7b)
    export LEGAL_BASE_MODEL="mistral:7b-v0.3"
    export LEGAL_LORA_TARGET_MODULES="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
    ;;
  c3_phi3medium)
    export LEGAL_BASE_MODEL="phi3:medium"
    export LEGAL_LORA_TARGET_MODULES="qkv_proj,o_proj,gate_up_proj,down_proj"
    ;;
  *)
    echo "Unknown candidate: $CANDIDATE" >&2; exit 1 ;;
esac

OUTPUT_DIR="${BAKEOFF_DIR}/${CANDIDATE}"
LOG_FILE="${LOG_DIR}/bakeoff_${CANDIDATE}_${DATE}.log"

mkdir -p "$OUTPUT_DIR"
echo "[$(date -Iseconds)] Starting bakeoff train: CANDIDATE=$CANDIDATE BASE=$LEGAL_BASE_MODEL" | tee -a "$LOG_FILE"

"$PYTHON" -m src.legal.train_legal_instruct \
  --train  "$TRAIN_DATA" \
  --val    "$VAL_DATA" \
  --output-dir "$OUTPUT_DIR" \
  2>&1 | tee -a "$LOG_FILE"

echo "[$(date -Iseconds)] DONE: $CANDIDATE" | tee -a "$LOG_FILE"
