#!/usr/bin/env python3
"""
train_judge.py — QLoRA fine-tune a judge model on labeled sovereign responses.

Base model: qwen2.5:7b (Ollama-served, HF format required for training).
Judge output: JSON {"decision": "confident|uncertain|escalate", "reasoning": "..."}
LoRA: r=16, alpha=32 — judges need reasoning capacity, not just classification.

Usage:
  python -m src.judge.train_judge \\
      --judge-name vrs_concierge_judge \\
      --base-model qwen2.5:7b \\
      --training-data /mnt/fortress_nas/judge-training/<name>-<date>.jsonl \\
      --output-dir /mnt/fortress_nas/judge-artifacts/<name>-<date>/ \\
      [--dry-run]

Environment:
  HF_HOME               HuggingFace cache (default: /mnt/ai_bulk/huggingface_cache)
  JUDGE_MIN_EXAMPLES    minimum labeled examples required (default: 50)
  JUDGE_LORA_RANK       LoRA r (default: 16)
  JUDGE_LORA_ALPHA      LoRA alpha (default: 32)
  JUDGE_MAX_SEQ_LEN     max sequence length (default: 1024)
  JUDGE_EPOCHS          training epochs (default: 3)
  JUDGE_LR              learning rate (default: 2e-4)
  JUDGE_BATCH_SIZE      batch size per device (default: 2)
  JUDGE_GRAD_ACCUM      gradient accumulation steps (default: 4)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"train_judge"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("train_judge")

HF_HOME      = Path(os.getenv("HF_HOME", "/mnt/ai_bulk/huggingface_cache"))
MIN_EXAMPLES = int(os.getenv("JUDGE_MIN_EXAMPLES",  "50"))
LORA_RANK    = int(os.getenv("JUDGE_LORA_RANK",     "16"))
LORA_ALPHA   = int(os.getenv("JUDGE_LORA_ALPHA",    "32"))
MAX_SEQ_LEN  = int(os.getenv("JUDGE_MAX_SEQ_LEN",   "1024"))
NUM_EPOCHS   = int(os.getenv("JUDGE_EPOCHS",        "3"))
LEARNING_RATE= float(os.getenv("JUDGE_LR",          "2e-4"))
BATCH_SIZE   = int(os.getenv("JUDGE_BATCH_SIZE",    "2"))
GRAD_ACCUM   = int(os.getenv("JUDGE_GRAD_ACCUM",    "4"))

LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"]

_JUDGE_SYSTEM = (
    'You are a quality judge for {task_type} responses. '
    'Output JSON only: {"decision": "confident|uncertain|escalate", "reasoning": "<one sentence>"}'
)
_JUDGE_USER = "Prompt: {prompt}\n\nResponse: {sovereign_response}\n\nEvaluate quality."
_JUDGE_ASSISTANT = '{{"decision": "{decision}", "reasoning": "{reasoning}"}}'


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def load_training_data(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "messages" in obj:
                    records.append(obj)
            except json.JSONDecodeError:
                pass
    return records


def _find_base_model_path(model_name: str) -> Path:
    """Locate HF-format model on disk. Raises if not found."""
    from src.judge.base_model_locator import find_base_model
    result = find_base_model(model_name)
    if result is None:
        raise FileNotFoundError(
            f"Base model '{model_name}' not found in HF format on disk. "
            f"Stage safetensors to /mnt/fortress_nas/models/ before training. "
            f"See base_model_locator.py for search paths."
        )
    return result


def train_judge(
    judge_name: str,
    base_model: str,
    training_data_path: Path,
    output_dir: Path,
    dry_run: bool,
) -> int:
    log.info("train_judge start judge=%s base=%s data=%s dry_run=%s",
             judge_name, base_model, training_data_path, dry_run)

    if dry_run and not training_data_path.exists():
        log.info("[DRY RUN] Data file %s does not exist — reporting 0 examples", training_data_path)
        records = []
    else:
        records = load_training_data(training_data_path)
    log.info("Loaded %d training examples", len(records))

    if len(records) < MIN_EXAMPLES:
        msg = (
            f"Insufficient data: {len(records)} examples "
            f"(minimum {MIN_EXAMPLES}, need {MIN_EXAMPLES - len(records)} more). "
            f"Accumulate more labeled captures via labeling_pipeline before training."
        )
        log.warning(msg)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "training.error").write_text(msg)
        return 1

    # Locate base model (will raise if not on disk)
    try:
        base_model_path = _find_base_model_path(base_model)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "training.error").write_text(str(exc))
        return 1

    if dry_run:
        log.info("[DRY RUN] base=%s path=%s examples=%d output=%s",
                 base_model, base_model_path, len(records), output_dir)
        log.info("[DRY RUN] LoRA: r=%d alpha=%d epochs=%d lr=%g",
                 LORA_RANK, LORA_ALPHA, NUM_EPOCHS, LEARNING_RATE)
        log.info("[DRY RUN] Would train judge successfully.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer

        os.environ["HF_HOME"] = str(HF_HOME)
        log.info("Loading tokenizer from %s", base_model_path)
        tokenizer = AutoTokenizer.from_pretrained(
            str(base_model_path), use_fast=True, trust_remote_code=False)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"

        bnb = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
        )
        log.info("Loading %s in 4-bit NF4 from %s", base_model, base_model_path)
        model = AutoModelForCausalLM.from_pretrained(
            str(base_model_path), quantization_config=bnb,
            device_map="auto", torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        model = get_peft_model(model, LoraConfig(
            r=LORA_RANK, lora_alpha=LORA_ALPHA,
            target_modules=LORA_TARGET_MODULES,
            lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        ))
        model.print_trainable_parameters()

        def _apply_template(ex: dict) -> dict:
            return {"text": tokenizer.apply_chat_template(
                ex["messages"], tokenize=False, add_generation_prompt=False)}

        raw_ds  = Dataset.from_list([{"messages": r["messages"]} for r in records])
        dataset = raw_ds.map(_apply_template, remove_columns=["messages"])

        sft = SFTConfig(
            output_dir=str(output_dir),
            num_train_epochs=NUM_EPOCHS,
            per_device_train_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRAD_ACCUM,
            learning_rate=LEARNING_RATE,
            lr_scheduler_type="cosine", warmup_ratio=0.05,
            bf16=True, logging_steps=5,
            save_strategy="epoch", save_total_limit=2,
            optim="paged_adamw_8bit", gradient_checkpointing=True,
            max_seq_length=MAX_SEQ_LEN, dataset_text_field="text",
            packing=True, report_to="none",
        )
        trainer = SFTTrainer(model=model, args=sft,
                             train_dataset=dataset, tokenizer=tokenizer)

        log.info("Training started")
        train_result = trainer.train()
        log.info("Training complete metrics=%s", train_result.metrics)

        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))

        loss_history = [{"step": e["step"], "loss": round(e["loss"], 6)}
                        for e in trainer.state.log_history if "loss" in e]
        manifest = {
            "judge_name":           judge_name,
            "base_model":           base_model,
            "base_model_path":      str(base_model_path),
            "adapter_path":         str(output_dir),
            "training_date":        date.today().isoformat(),
            "training_data_path":   str(training_data_path),
            "dataset_size":         len(records),
            "lora_config":          {"r": LORA_RANK, "lora_alpha": LORA_ALPHA,
                                     "target_modules": LORA_TARGET_MODULES},
            "training_args":        {"epochs": NUM_EPOCHS, "lr": LEARNING_RATE,
                                     "batch_size": BATCH_SIZE, "grad_accum": GRAD_ACCUM,
                                     "max_seq_len": MAX_SEQ_LEN},
            "final_loss":           loss_history[-1]["loss"] if loss_history else None,
            "loss_curve":           loss_history,
            "trainer_git_sha":      _git_sha(),
            "serving_format":       "ollama-lora",
            "base_ollama_model":    base_model,
        }
        (output_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2))
        log.info("Manifest written. final_loss=%s", manifest["final_loss"])
        return 0

    except Exception as exc:
        log.error("Training failed: %s", exc, exc_info=True)
        (output_dir / "training.error").write_text(
            f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a judge model via QLoRA")
    parser.add_argument("--judge-name",     required=True)
    parser.add_argument("--base-model",     default="qwen2.5:7b")
    parser.add_argument("--training-data",  required=True, type=Path)
    parser.add_argument("--output-dir",     required=True, type=Path)
    parser.add_argument("--dry-run",        action="store_true")
    args = parser.parse_args()

    if not args.training_data.exists() and not args.dry_run:
        log.error("Training data not found: %s", args.training_data)
        return 1

    return train_judge(
        args.judge_name, args.base_model,
        args.training_data, args.output_dir,
        args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
