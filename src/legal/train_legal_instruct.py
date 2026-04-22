#!/usr/bin/env python3
"""
train_legal_instruct.py — QLoRA fine-tune on Phase 4d legal instruction pairs.

Base model: Qwen2.5-7B-Instruct (HF-format safetensors on NAS).
Data:       {instruction, output} JSONL — also accepts {messages:[...]} format.
LoRA:       r=16, alpha=32, all 7 projection modules.

Usage:
  # Smoke test (4 steps, confirms config/data/GPU before full run)
  python -m src.legal.train_legal_instruct \\
      --train /mnt/fortress_nas/legal-corpus/training-pairs/train.jsonl \\
      --val   /mnt/fortress_nas/legal-corpus/training-pairs/val.jsonl \\
      --output-dir /mnt/fortress_nas/models/legal-instruct-$(date +%Y%m%d) \\
      --max-steps 4

  # Full run
  python -m src.legal.train_legal_instruct \\
      --train /mnt/fortress_nas/legal-corpus/training-pairs/train.jsonl \\
      --val   /mnt/fortress_nas/legal-corpus/training-pairs/val.jsonl \\
      --output-dir /mnt/fortress_nas/models/legal-instruct-$(date +%Y%m%d)

Environment:
  LEGAL_LORA_RANK        LoRA r             (default: 16)
  LEGAL_LORA_ALPHA       LoRA alpha         (default: 32)
  LEGAL_MAX_SEQ_LEN      max token length   (default: 4096)
  LEGAL_EPOCHS           training epochs    (default: 3)
  LEGAL_LR               learning rate      (default: 2e-4)
  LEGAL_BATCH_SIZE       per-device batch   (default: 1)
  LEGAL_GRAD_ACCUM       grad accum steps   (default: 8)
  LEGAL_EVAL_STEPS       eval every N steps (default: 50)
  LEGAL_MIN_EXAMPLES     minimum train rows (default: 50)
  LEGAL_BASE_MODEL       model name         (default: qwen2.5:7b)
  HF_HOME                HF cache dir       (default: /mnt/ai_bulk/huggingface_cache)
  NTFY_TOPIC             ntfy.sh topic for completion ping (optional)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"train_legal"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("train_legal_instruct")

# ---------------------------------------------------------------------------
# Config (all overridable via env)
# ---------------------------------------------------------------------------
HF_HOME       = Path(os.getenv("HF_HOME", "/mnt/ai_bulk/huggingface_cache"))
BASE_MODEL    = os.getenv("LEGAL_BASE_MODEL", "qwen2.5:7b")
LORA_RANK     = int(os.getenv("LEGAL_LORA_RANK",    "16"))
LORA_ALPHA    = int(os.getenv("LEGAL_LORA_ALPHA",   "32"))
MAX_SEQ_LEN   = int(os.getenv("LEGAL_MAX_SEQ_LEN",  "4096"))
NUM_EPOCHS    = int(os.getenv("LEGAL_EPOCHS",        "3"))
LEARNING_RATE = float(os.getenv("LEGAL_LR",         "2e-4"))
BATCH_SIZE    = int(os.getenv("LEGAL_BATCH_SIZE",   "1"))
GRAD_ACCUM    = int(os.getenv("LEGAL_GRAD_ACCUM",   "8"))
EVAL_STEPS    = int(os.getenv("LEGAL_EVAL_STEPS",   "50"))
MIN_EXAMPLES  = int(os.getenv("LEGAL_MIN_EXAMPLES", "50"))
TRAINING_SEED = int(os.getenv("LEGAL_SEED",         "42"))
NTFY_TOPIC    = os.getenv("NTFY_TOPIC", "")

# Default target modules for Qwen/Mistral dense models.
# Override via LEGAL_LORA_TARGET_MODULES (comma-separated) for other architectures.
# Phi-3: "qkv_proj,o_proj,gate_up_proj,down_proj"
_default_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"]
_modules_env = os.getenv("LEGAL_LORA_TARGET_MODULES", "")
LORA_TARGET_MODULES = [m.strip() for m in _modules_env.split(",") if m.strip()] \
                      if _modules_env else _default_modules

# Prompt template — mirrors the chat template the model was trained on
_SYSTEM = (
    "You are a Georgia insurance defense legal analyst. "
    "Provide precise, well-reasoned analysis grounded in Georgia appellate precedent."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parents[2]),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _ntfy(message: str) -> None:
    if not NTFY_TOPIC:
        return
    try:
        subprocess.run(
            ["curl", "-s", "-d", message, f"https://ntfy.sh/{NTFY_TOPIC}"],
            timeout=10, capture_output=True,
        )
    except Exception:
        pass


def _disk_free_gb(path: Path) -> float:
    import shutil
    return shutil.disk_usage(path).free / (1024 ** 3)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Load JSONL supporting both {instruction,output} and {messages:[...]} formats."""
    records = []
    skipped = 0
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "messages" in obj:
                    records.append(obj)
                elif "instruction" in obj and "output" in obj:
                    records.append({"messages": [
                        {"role": "system",    "content": _SYSTEM},
                        {"role": "user",      "content": obj["instruction"]},
                        {"role": "assistant", "content": obj["output"]},
                    ]})
                else:
                    skipped += 1
            except json.JSONDecodeError:
                skipped += 1
    if skipped:
        log.warning("load_jsonl: skipped %d malformed lines in %s", skipped, path)
    return records


# ---------------------------------------------------------------------------
# Token length histogram (pre-flight diagnostic)
# ---------------------------------------------------------------------------

def token_length_histogram(records: list[dict], tokenizer) -> dict:
    """Tokenize the dataset and return length stats. Logs a histogram."""
    lengths = []
    for r in records:
        text = tokenizer.apply_chat_template(
            r["messages"], tokenize=False, add_generation_prompt=False)
        lengths.append(len(tokenizer.encode(text)))
    lengths.sort()
    n = len(lengths)
    stats = {
        "count": n,
        "min": lengths[0],
        "p50": lengths[n // 2],
        "p90": lengths[int(n * 0.9)],
        "p95": lengths[int(n * 0.95)],
        "p99": lengths[int(n * 0.99)],
        "max": lengths[-1],
    }
    truncated = sum(1 for l in lengths if l > MAX_SEQ_LEN)
    stats["truncated_pct"] = round(100 * truncated / n, 1)
    log.info("Token length histogram: %s", json.dumps(stats))
    if stats["truncated_pct"] > 10:
        log.warning(
            "%.1f%% of training pairs exceed MAX_SEQ_LEN=%d. "
            "Consider raising LEGAL_MAX_SEQ_LEN or set --max-seq-len.",
            stats["truncated_pct"], MAX_SEQ_LEN,
        )
    return stats


# ---------------------------------------------------------------------------
# Checkpoint manifest callback
# ---------------------------------------------------------------------------

def _write_manifest(output_dir: Path, checkpoint_dir: Path | None, state,
                    train_records: int, val_records: int, args_ns) -> None:
    loss_history = [{"step": e["step"], "loss": round(e["loss"], 6)}
                    for e in state.log_history if "loss" in e]
    eval_history = [{"step": e["step"], "eval_loss": round(e["eval_loss"], 6)}
                    for e in state.log_history if "eval_loss" in e]
    manifest = {
        "base_model":       BASE_MODEL,
        "adapter_path":     str(checkpoint_dir or output_dir),
        "training_date":    datetime.utcnow().isoformat() + "Z",
        "train_pairs":      train_records,
        "val_pairs":        val_records,
        "lora_config":      {"r": LORA_RANK, "lora_alpha": LORA_ALPHA,
                             "target_modules": LORA_TARGET_MODULES},
        "training_args":    {"epochs": NUM_EPOCHS, "lr": LEARNING_RATE,
                             "batch_size": BATCH_SIZE, "grad_accum": GRAD_ACCUM,
                             "max_seq_len": MAX_SEQ_LEN,
                             "max_steps": getattr(args_ns, "max_steps", -1)},
        "final_train_loss": loss_history[-1]["loss"] if loss_history else None,
        "final_eval_loss":  eval_history[-1]["eval_loss"] if eval_history else None,
        "loss_curve":       loss_history,
        "eval_curve":       eval_history,
        "trainer_git_sha":  _git_sha(),
    }
    dest = (checkpoint_dir or output_dir) / "training_manifest.json"
    dest.write_text(json.dumps(manifest, indent=2))
    log.info("Manifest written to %s", dest)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace) -> int:
    from src.judge.base_model_locator import find_base_model

    # --- Pre-flight ---
    nas_free = _disk_free_gb(args.output_dir.parent
                              if not args.output_dir.exists()
                              else args.output_dir)
    log.info("NAS free disk: %.1f GB", nas_free)
    if nas_free < 20:
        log.error("Less than 20 GB free on NAS (%s). Aborting.", nas_free)
        _ntfy(f"[legal-instruct] ABORTED: only {nas_free:.1f} GB free on NAS")
        return 1

    log.info("Loading train data from %s", args.train)
    train_records = load_jsonl(args.train)
    log.info("Loading val data from %s", args.val)
    val_records   = load_jsonl(args.val)

    log.info("train=%d val=%d", len(train_records), len(val_records))
    if len(train_records) < MIN_EXAMPLES:
        log.error("Only %d train examples, minimum is %d", len(train_records), MIN_EXAMPLES)
        return 1

    base_model_path = find_base_model(BASE_MODEL)
    if base_model_path is None:
        log.error("Base model not found. Stage HF weights to NAS first.")
        _ntfy(f"[legal-instruct] ABORTED: base model {BASE_MODEL} not found on disk")
        return 1
    log.info("Base model resolved: %s", base_model_path)

    if args.dry_run:
        log.info("[DRY RUN] Pre-flight OK. train=%d val=%d base=%s",
                 len(train_records), len(val_records), base_model_path)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainerCallback
        from trl import SFTConfig, SFTTrainer

        os.environ["HF_HOME"] = str(HF_HOME)

        log.info("Loading tokenizer from %s", base_model_path)
        tokenizer = AutoTokenizer.from_pretrained(
            str(base_model_path), use_fast=True, trust_remote_code=False)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"

        # Token length histogram before training
        log.info("Running token length histogram on train split...")
        hist = token_length_histogram(train_records, tokenizer)
        (args.output_dir / "token_histogram.json").write_text(json.dumps(hist, indent=2))

        # GB10 unified memory (130 GB): 7B model in bf16 = ~14 GB — no quantization needed.
        # bitsandbytes 4-bit reports cuda_specs=None on this unified-memory platform.
        # Training in native bf16 avoids quantization artifacts and is fine at this scale.
        log.info("Loading %s in bf16 (unified memory — no quantization needed)", BASE_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            str(base_model_path),
            device_map="auto", torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        model.enable_input_require_grads()
        model = get_peft_model(model, LoraConfig(
            r=LORA_RANK, lora_alpha=LORA_ALPHA,
            target_modules=LORA_TARGET_MODULES,
            lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        ))
        model.print_trainable_parameters()

        def _fmt(ex: dict) -> dict:
            return {"text": tokenizer.apply_chat_template(
                ex["messages"], tokenize=False, add_generation_prompt=False)}

        train_ds = Dataset.from_list(train_records).map(_fmt, remove_columns=["messages"])
        val_ds   = Dataset.from_list(val_records).map(_fmt,   remove_columns=["messages"])

        # Callback: write manifest after every checkpoint save
        class _ManifestCallback(TrainerCallback):
            def on_save(self, cb_args, state, control, **kwargs):
                ckpt = Path(cb_args.output_dir) / f"checkpoint-{state.global_step}"
                _write_manifest(args.output_dir, ckpt if ckpt.exists() else None,
                                state, len(train_records), len(val_records), args)

        # transformers 5.3.0 no longer auto-prints eval metrics to stdout
        class _EvalLogCallback(TrainerCallback):
            def on_evaluate(self, cb_args, state, control, metrics=None, **kwargs):
                if metrics:
                    log.info("eval_metrics %s", json.dumps({k: round(v, 6) for k, v in metrics.items() if isinstance(v, float)}))

        sft = SFTConfig(
            output_dir=str(args.output_dir),
            num_train_epochs=NUM_EPOCHS,
            max_steps=args.max_steps,          # -1 = train to completion; >0 = smoke test
            per_device_train_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRAD_ACCUM,
            learning_rate=LEARNING_RATE,
            lr_scheduler_type="cosine", warmup_ratio=0.05,
            bf16=True,
            logging_steps=5,
            eval_strategy="steps", eval_steps=EVAL_STEPS,
            save_strategy="epoch", save_total_limit=2,
            load_best_model_at_end=False,     # adapter only — no full reload
            optim="adamw_torch_fused",        # no bitsandbytes needed on unified memory
            max_length=MAX_SEQ_LEN, dataset_text_field="text",
            packing=True, report_to="none",
            seed=TRAINING_SEED, data_seed=TRAINING_SEED,
        )
        trainer = SFTTrainer(
            model=model, args=sft,
            train_dataset=train_ds, eval_dataset=val_ds,
            processing_class=tokenizer,       # trl 1.1.0: tokenizer → processing_class
            callbacks=[_ManifestCallback(), _EvalLogCallback()],
        )

        log.info("Training started (max_steps=%s, epochs=%d)", args.max_steps, NUM_EPOCHS)
        _ntfy(f"[legal-instruct] Training started — {len(train_records)} pairs, {BASE_MODEL}")
        train_result = trainer.train()
        log.info("Training complete: %s", train_result.metrics)

        trainer.save_model(str(args.output_dir))
        tokenizer.save_pretrained(str(args.output_dir))
        _write_manifest(args.output_dir, None,
                        trainer.state, len(train_records), len(val_records), args)

        final_loss = train_result.metrics.get("train_loss", "?")
        _ntfy(f"[legal-instruct] DONE — loss={final_loss} adapter={args.output_dir}")
        return 0

    except Exception as exc:
        tb = traceback.format_exc()
        log.error("Training failed: %s\n%s", exc, tb)
        (args.output_dir / "training.error").write_text(
            f"{type(exc).__name__}: {exc}\n\n{tb}")
        _ntfy(f"[legal-instruct] FAILED: {type(exc).__name__}: {exc}"[:500])
        return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="QLoRA fine-tune on Phase 4d legal instruction pairs")
    parser.add_argument("--train",      required=True, type=Path)
    parser.add_argument("--val",        required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--max-steps",  type=int, default=-1,
                        help="Override steps (-1 = full run, 4 = smoke test)")
    parser.add_argument("--max-seq-len", type=int, default=MAX_SEQ_LEN)
    parser.add_argument("--dry-run",    action="store_true",
                        help="Pre-flight only — no GPU, no training")
    args = parser.parse_args()

    # Allow CLI overrides to propagate into module-level constants
    # (used by train() and _write_manifest which read these directly)
    import src.legal.train_legal_instruct as _self
    _self.BASE_MODEL  = args.base_model
    _self.MAX_SEQ_LEN = args.max_seq_len

    # Validate paths before touching GPU
    for path, label in [(args.train, "--train"), (args.val, "--val")]:
        if not path.exists():
            log.error("%s not found: %s", label, path)
            return 1

    return train(args)  # type: ignore[return-value]


if __name__ == "__main__":
    sys.exit(main())
