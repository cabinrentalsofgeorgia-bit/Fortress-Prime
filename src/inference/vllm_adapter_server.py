#!/usr/bin/env python3
"""
vllm_adapter_server.py — Starts a vLLM OpenAI-compat server
for the promoted LoRA adapter.

Phase 4c coexistence model: Model B (on-demand).
This process is NOT started automatically. It is started manually
or by fortress-vllm-adapter.service ONLY when:
  1. PROMOTED_CANDIDATE sentinel file exists at ADAPTER_DIR
  2. Sufficient memory is available (NIM was stopped first)

The server serves the fine-tuned Llama-3.3-70B-Instruct-FP4 model
with the promoted LoRA adapter via OpenAI-compatible HTTP API.

Memory model:
  NIM (nim-sovereign): ~61GB when running
  This server (70B FP4 + 4-bit): ~35-40GB
  Total GB10 memory: 121GB
  These CANNOT coexist — NIM must be scaled to 0 before starting this.

Usage:
  python vllm_adapter_server.py [--port 8100] [--dry-run]

  --dry-run: validate config and print resolved paths without starting server

Environment:
  FINETUNE_ADAPTER_DIR    default: /mnt/fortress_nas/finetune-artifacts
  FINETUNE_BASE_MODEL_DIR default: /mnt/ai_bulk/models/huggingface/Llama-3.3-70B-Instruct-FP4
  ADAPTER_SERVER_PORT     default: 8100
  ADAPTER_SERVER_HOST     default: 127.0.0.1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("vllm_adapter_server")

ADAPTER_DIR     = Path(os.getenv("FINETUNE_ADAPTER_DIR",    "/mnt/fortress_nas/finetune-artifacts"))
BASE_MODEL_DIR  = Path(os.getenv("FINETUNE_BASE_MODEL_DIR", "/mnt/ai_bulk/models/huggingface/Llama-3.3-70B-Instruct-FP4"))
SERVER_PORT     = int(os.getenv("ADAPTER_SERVER_PORT",      "8100"))
SERVER_HOST     = os.getenv("ADAPTER_SERVER_HOST",          "127.0.0.1")

SENTINEL        = ADAPTER_DIR / "PROMOTED_CANDIDATE"


def resolve_adapter_path() -> Path | None:
    """Read PROMOTED_CANDIDATE sentinel and return the adapter path."""
    if not SENTINEL.exists():
        log.error("No PROMOTED_CANDIDATE sentinel at %s — nothing to serve", SENTINEL)
        return None
    try:
        data = json.loads(SENTINEL.read_text())
        adapter_path = Path(data["adapter_path"])
        if not adapter_path.exists():
            log.error("Adapter path from sentinel does not exist: %s", adapter_path)
            return None
        return adapter_path
    except Exception as exc:
        log.error("Cannot read PROMOTED_CANDIDATE: %s", exc)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Start vLLM adapter server")
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate config without starting server")
    args = parser.parse_args()

    adapter_path = resolve_adapter_path()
    if adapter_path is None:
        return 1

    log.info("Adapter path: %s", adapter_path)
    log.info("Base model:   %s", BASE_MODEL_DIR)
    log.info("Serving at:   %s:%d", SERVER_HOST, args.port)

    if not BASE_MODEL_DIR.exists():
        log.error("Base model directory not found: %s", BASE_MODEL_DIR)
        return 1

    if args.dry_run:
        log.info("[DRY RUN] Config valid. Would start vLLM on %s:%d", SERVER_HOST, args.port)
        log.info("[DRY RUN] vllm serve %s --enable-lora --lora-modules crog=%s ...",
                 BASE_MODEL_DIR, adapter_path)
        return 0

    # Find vLLM binary
    vllm_bin = subprocess.run(["which", "vllm"], capture_output=True, text=True).stdout.strip()
    if not vllm_bin:
        # Try venv
        vllm_bin = str(Path(sys.executable).parent / "vllm")

    cmd = [
        vllm_bin, "serve", str(BASE_MODEL_DIR),
        "--enable-lora",
        "--lora-modules", f"crog-distilled={adapter_path}",
        "--host", SERVER_HOST,
        "--port", str(args.port),
        "--quantization", "bitsandbytes",
        "--load-format", "bitsandbytes",
        "--max-lora-rank", "64",
        "--gpu-memory-utilization", "0.90",
        "--max-model-len", "4096",
        "--tensor-parallel-size", "1",
        "--served-model-name", "crog-distilled",
    ]

    log.info("Starting vLLM: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except KeyboardInterrupt:
        log.info("vLLM adapter server stopped.")
        return 0
    except FileNotFoundError:
        log.error("vLLM binary not found at %s — install with: pip install vllm", vllm_bin)
        return 1


if __name__ == "__main__":
    sys.exit(main())
