"""
base_model_locator.py — Locate base model weights on disk without downloading.

Search order (no network calls):
  1. /mnt/fortress_nas/models/<model_name>  (NAS direct)
  2. /mnt/ai_bulk/huggingface_cache/hub/    (node-local HF cache on ai_bulk)
  3. ~/.cache/huggingface/hub/              (local HF cache)
  4. Ollama model store (for GGUF extraction hint only)

Returns the HuggingFace-format directory (containing config.json + safetensors)
or None if not found. Never downloads.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("base_model_locator")

_HF_CACHE_AI_BULK = Path("/mnt/ai_bulk/huggingface_cache/hub")
_HF_CACHE_LOCAL   = Path.home() / ".cache" / "huggingface" / "hub"
_NAS_MODELS       = Path("/mnt/fortress_nas/models")

# Maps friendly names → HuggingFace repo IDs for cache directory matching
_MODEL_ALIASES: dict[str, list[str]] = {
    "qwen2.5:7b":      ["Qwen--Qwen2.5-7B-Instruct", "Qwen--Qwen2.5-7B"],
    "qwen2.5:0.5b":    ["Qwen--Qwen2.5-0.5B-Instruct"],
    "qwen2.5:1.5b":    ["Qwen--Qwen2.5-1.5B-Instruct"],
    "qwen2.5:32b":     ["Qwen--Qwen2.5-32B-Instruct"],
    "deepseek-r1:70b": ["deepseek-ai--DeepSeek-R1-Distill-Llama-70B"],
}


def _hf_dir_for_model(model_name: str, cache_root: Path) -> Optional[Path]:
    """Find a model's HF cache directory under cache_root."""
    aliases = _MODEL_ALIASES.get(model_name, [])
    if not aliases:
        # Try direct name transform: Qwen/Qwen2.5-7B-Instruct → Qwen--Qwen2.5-7B-Instruct
        aliases = [model_name.replace("/", "--")]

    for alias in aliases:
        candidate = cache_root / f"models--{alias}"
        if candidate.exists():
            # Look for a snapshot with config.json
            snapshots = candidate / "snapshots"
            if snapshots.exists():
                for snap in sorted(snapshots.iterdir(), reverse=True):
                    if (snap / "config.json").exists():
                        log.info("Found %s at %s", model_name, snap)
                        return snap
            # Fallback: return the cache dir itself
            if (candidate / "config.json").exists():
                return candidate
    return None


def _ollama_model_path(model_name: str) -> Optional[Path]:
    """
    Check if model exists in Ollama (GGUF format).
    Returns None — Ollama GGUFs can't be directly used for HF-format training.
    But logs a hint if the model is available via Ollama.
    """
    try:
        result = subprocess.run(
            ["ollama", "show", model_name, "--modelfile"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and "FROM" in result.stdout:
            log.info(
                "Model %s found in Ollama (GGUF format). "
                "For HF-format training, stage safetensors to %s or use "
                "a conversion tool. Ollama modelfile:\n%s",
                model_name, _NAS_MODELS, result.stdout[:300],
            )
            return None  # Signal: Ollama has it but not in HF format
    except Exception:
        pass
    return None


def find_base_model(model_name: str) -> Optional[Path]:
    """
    Locate base model weights on disk. Returns HF-format directory or None.
    Never downloads from HuggingFace.

    If None is returned and Ollama has the model in GGUF format, a warning
    is logged with instructions for converting or staging the model.
    """
    log.info("Searching for base model: %s", model_name)

    # 1. NAS direct — look for model directory
    nas_direct = _NAS_MODELS / model_name.replace(":", "-").replace("/", "-")
    if nas_direct.exists() and (nas_direct / "config.json").exists():
        log.info("Found %s on NAS at %s", model_name, nas_direct)
        return nas_direct

    # 2. ai_bulk HF cache
    found = _hf_dir_for_model(model_name, _HF_CACHE_AI_BULK)
    if found:
        return found

    # 3. Local HF cache
    found = _hf_dir_for_model(model_name, _HF_CACHE_LOCAL)
    if found:
        return found

    # 4. Check Ollama (GGUF hint only, not usable for HF training)
    _ollama_model_path(model_name)

    log.warning(
        "Base model %s not found in HF format on disk. "
        "Options: (a) stage safetensors to %s/%s, "
        "(b) download via 'huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir %s', "
        "(c) convert Ollama GGUF with llama.cpp convert_hf_to_gguf.py (reverse not supported directly).",
        model_name, _NAS_MODELS, model_name.replace(":", "-"),
        _NAS_MODELS / "Qwen2.5-7B-Instruct",
    )
    return None


if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
    logging.basicConfig(level=logging.INFO)
    result = find_base_model(model)
    print(f"Result: {result}")
    sys.exit(0 if result else 1)
