"""
run_eval.py — run the newly-trained LoRA adapter against the holdout set.

Loads adapter via peft + transformers (4-bit NF4, same config as training),
runs each holdout prompt through it, computes three metrics:

  response_similarity  cosine similarity (MiniLM-L6-v2) vs teacher output
  response_validity    non-empty, not gibberish, length in [1x, 10x] teacher
  regressions          prompts where new model FAILS and teacher was valid

Writes metrics.json alongside the adapter.

Usage:
  python run_eval.py --adapter-path /mnt/fortress_nas/finetune-artifacts/.../
                     --holdout-path /mnt/fortress_nas/finetune-artifacts/holdouts/holdout-<date>.json
                     [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"run_eval"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("run_eval")

_eval_base_env = os.getenv("FINETUNE_BASE_MODEL_DIR")
if not _eval_base_env:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from judge.base_model_locator import find_base_model as _find_base_model
        _found = _find_base_model("qwen2.5:7b")
        _eval_base_env = str(_found) if _found else "/mnt/fortress_nas/models/Qwen2.5-7B-Instruct"
    except Exception:
        _eval_base_env = "/mnt/fortress_nas/models/Qwen2.5-7B-Instruct"
BASE_MODEL_DIR = Path(_eval_base_env)
EMBEDDING_MODEL = os.getenv("EVAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
MAX_NEW_TOKENS  = int(os.getenv("EVAL_MAX_NEW_TOKENS", "512"))

# ---------------------------------------------------------------------------
# Validity checks
# ---------------------------------------------------------------------------
_REPEATED_TOKEN_RE = re.compile(r"(.{2,}?)\1{10,}")


def _is_valid_response(text: str, teacher_text: str) -> bool:
    if not text or not text.strip():
        return False
    t_len = max(len(teacher_text), 1)
    r_len = len(text)
    if r_len < t_len * 0.1 or r_len > t_len * 10:
        return False
    special = sum(1 for c in text if not c.isalnum() and not c.isspace())
    if special / max(len(text), 1) > 0.5:
        return False
    if _REPEATED_TOKEN_RE.search(text):
        return False
    return True


# ---------------------------------------------------------------------------
# Eval core
# ---------------------------------------------------------------------------
def run_eval(adapter_path: Path, holdout_path: Path, dry_run: bool) -> dict:
    log.info("Loading holdout manifest from %s", holdout_path)
    manifest = json.loads(holdout_path.read_text())
    records = manifest["records"]
    log.info("Holdout: %d records across domains %s",
             len(records), list(manifest["domain_counts"].keys()))

    if dry_run:
        log.info("[DRY RUN] Would load adapter from %s", adapter_path)
        log.info("[DRY RUN] Would evaluate %d prompts", len(records))
        log.info("[DRY RUN] Embedding model: %s", EMBEDDING_MODEL)
        return {"dry_run": True, "records": len(records)}

    if not records:
        log.warning("No holdout records — nothing to eval")
        return {"similarity_mean": None, "validity_rate": None,
                "regression_count": 0, "domain_regressions": {}, "n_evaluated": 0}

    # --- Load embedding model (CPU, small) ---
    log.info("Loading embedding model %s …", EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")

    # --- Load LoRA adapter ---
    # DGX Spark (GB10) unified memory: skip 4-bit quantization, load bf16 directly
    # (matches training config; bitsandbytes CUDA ops unavailable in this env)
    log.info("Loading base model %s in bf16 …", BASE_MODEL_DIR)
    import torch
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path), use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoPeftModelForCausalLM.from_pretrained(
        str(adapter_path),
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.eval()
    log.info("Adapter loaded.")

    # --- Run prompts ---
    similarities: list[float] = []
    validity_flags: list[bool] = []
    regressions: dict[str, int] = {}  # domain → count

    for i, rec in enumerate(records):
        prompt = rec["user_prompt"]
        teacher = rec["teacher_response"]
        domain = rec["domain"]

        # Build input using chat template
        messages = [{"role": "user", "content": prompt}]
        try:
            input_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            input_text = prompt

        inputs = tokenizer(input_text, return_tensors="pt",
                           max_length=2048, truncation=True).to(model.device)

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        # Decode only the new tokens
        new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
        student_output = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

        # Validity
        valid = _is_valid_response(student_output, teacher)
        teacher_valid = _is_valid_response(teacher, teacher)
        validity_flags.append(valid)

        # Regression: student fails but teacher was valid
        if not valid and teacher_valid:
            regressions[domain] = regressions.get(domain, 0) + 1

        # Similarity
        embs = embedder.encode([student_output, teacher], convert_to_numpy=True)
        from sklearn.metrics.pairwise import cosine_similarity
        sim = float(cosine_similarity(embs[0:1], embs[1:2])[0][0])
        similarities.append(sim)

        if (i + 1) % 10 == 0:
            log.info("Progress: %d/%d evaluated", i + 1, len(records))

    # --- Aggregate ---
    n = len(records)
    metrics = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "adapter_path": str(adapter_path),
        "holdout_path": str(holdout_path),
        "n_evaluated": n,
        "similarity_mean": round(sum(similarities) / n, 4) if similarities else None,
        "similarity_by_domain": {},
        "validity_rate": round(sum(validity_flags) / n, 4) if validity_flags else None,
        "regression_count": sum(regressions.values()),
        "domain_regressions": regressions,
        "domain_counts": manifest["domain_counts"],
    }

    # Per-domain similarity breakdown
    by_domain: dict[str, list[float]] = {}
    for rec, sim in zip(records, similarities):
        by_domain.setdefault(rec["domain"], []).append(sim)
    for d, sims in by_domain.items():
        metrics["similarity_by_domain"][d] = round(sum(sims) / len(sims), 4)

    metrics_path = adapter_path / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    log.info("Metrics written to %s", metrics_path)
    log.info("similarity_mean=%.4f validity_rate=%.4f regressions=%d",
             metrics["similarity_mean"] or 0,
             metrics["validity_rate"] or 0,
             metrics["regression_count"])

    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run eval against holdout set")
    parser.add_argument("--adapter-path", required=True,
                        help="Path to the trained LoRA adapter directory")
    parser.add_argument("--holdout-path", required=True,
                        help="Path to holdout manifest JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate imports and config without running inference")
    args = parser.parse_args()

    adapter_path = Path(args.adapter_path)
    holdout_path = Path(args.holdout_path)

    if not adapter_path.exists():
        log.error("Adapter path does not exist: %s", adapter_path)
        return 1
    if not holdout_path.exists():
        log.error("Holdout path does not exist: %s", holdout_path)
        return 1

    result = run_eval(adapter_path, holdout_path, args.dry_run)
    if args.dry_run:
        log.info("[DRY RUN] Validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
