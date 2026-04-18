#!/usr/bin/env python3
"""
Fortress Prime — Nightly Fine-Tuning Job
==========================================
Distils frontier-model interactions captured in distillation_queue into
the local Llama-3.3-70B model via QLoRA (LoRA + 4-bit NF4 quantization).

Execution order
---------------
1. Export today's data from distillation_queue → JSONL  (calls backend worker)
2. Load all JSONL from the rolling 30-day window
3. Validate: skip run if < MIN_EXAMPLES examples
4. Stop vllm-70b-captain Docker container (free ~60 GB)
5. QLoRA fine-tune Llama-3.3-70B-Instruct
6. Save LoRA adapter to NAS
7. Optionally merge + push to Ollama
8. Restart vllm-70b-captain

Usage
-----
    python3 /home/admin/Fortress-Prime/src/nightly_finetune.py [--dry-run] [--skip-export]

Environment variables (loaded from .env / .env.dgx by run-fortress-nightly-finetune.sh)
    INTERACTION_LOG_DIR     default: /mnt/ai_bulk/training_logs
    FINETUNE_BASE_MODEL_DIR default: /mnt/ai_bulk/models/huggingface/Llama-3.3-70B-Instruct-FP4
    FINETUNE_ADAPTER_DIR    default: /mnt/fortress_nas/finetune-artifacts
    FINETUNE_ROLLING_DAYS   default: 30
    FINETUNE_MIN_EXAMPLES   default: 20
    FINETUNE_LORA_RANK      default: 16
    FINETUNE_BATCH_SIZE     default: 1
    FINETUNE_GRAD_ACCUM     default: 8
    FINETUNE_MAX_SEQ_LEN    default: 4096
    FINETUNE_EPOCHS         default: 1
    FINETUNE_LR             default: 2e-4
    FINETUNE_PUSH_OLLAMA    default: false
    VLLM_CONTAINER_NAME     default: vllm-70b-captain
    DATABASE_URL            required for exporter
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging (structlog-style JSON to stdout so journald picks it up cleanly)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"nightly_finetune"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("finetune")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INTERACTION_LOG_DIR  = Path(os.getenv("INTERACTION_LOG_DIR",  "/mnt/ai_bulk/training_logs"))
BASE_MODEL_DIR       = Path(os.getenv("FINETUNE_BASE_MODEL_DIR", "/mnt/ai_bulk/models/huggingface/Llama-3.3-70B-Instruct-FP4"))
ADAPTER_DIR          = Path(os.getenv("FINETUNE_ADAPTER_DIR", "/mnt/fortress_nas/finetune-artifacts"))
ROLLING_DAYS         = int(os.getenv("FINETUNE_ROLLING_DAYS",  "30"))
MIN_EXAMPLES         = int(os.getenv("FINETUNE_MIN_EXAMPLES",  "20"))
LORA_RANK            = int(os.getenv("FINETUNE_LORA_RANK",     "16"))
BATCH_SIZE           = int(os.getenv("FINETUNE_BATCH_SIZE",    "1"))
GRAD_ACCUM           = int(os.getenv("FINETUNE_GRAD_ACCUM",    "8"))
MAX_SEQ_LEN          = int(os.getenv("FINETUNE_MAX_SEQ_LEN",   "4096"))
NUM_EPOCHS           = int(os.getenv("FINETUNE_EPOCHS",        "1"))
LEARNING_RATE        = float(os.getenv("FINETUNE_LR",          "2e-4"))
PUSH_OLLAMA          = os.getenv("FINETUNE_PUSH_OLLAMA",       "false").lower() == "true"
VLLM_CONTAINER       = os.getenv("VLLM_CONTAINER_NAME",        "vllm-70b-captain")
MIN_DATE             = date.fromisoformat(os.getenv("FINETUNE_MIN_DATE", "2026-04-18"))

# LoRA target modules for Llama architecture
LORA_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]


# ---------------------------------------------------------------------------
# Dependency check + install
# ---------------------------------------------------------------------------
def _ensure_training_deps() -> None:
    """Install peft, trl, bitsandbytes into the active Python env if missing."""
    required = {
        "peft": "peft>=0.14",
        "trl": "trl>=0.12",
        "bitsandbytes": "bitsandbytes>=0.45",
    }
    missing = []
    for pkg, spec in required.items():
        try:
            __import__(pkg)
        except ImportError:
            missing.append(spec)

    if not missing:
        return

    log.info("Installing missing training deps: %s", missing)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *missing],
        timeout=300,
    )
    log.info("Training deps installed.")


# ---------------------------------------------------------------------------
# Docker container management
# ---------------------------------------------------------------------------
def _docker_running(container: str) -> bool:
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            stderr=subprocess.DEVNULL, timeout=10,
        )
        return out.strip() == b"true"
    except subprocess.CalledProcessError:
        return False


def _stop_vllm(container: str) -> bool:
    if not _docker_running(container):
        log.info("vLLM container %s not running, skip stop.", container)
        return False
    log.info("Stopping vLLM container %s to free GPU memory …", container)
    subprocess.run(["docker", "stop", "-t", "30", container], check=True, timeout=60)
    time.sleep(5)
    log.info("vLLM container stopped.")
    return True


def _start_vllm(container: str) -> None:
    log.info("Restarting vLLM container %s …", container)
    subprocess.run(["docker", "start", container], check=True, timeout=30)
    log.info("vLLM container restarted.")


# ---------------------------------------------------------------------------
# Step 1: Export from DB
# ---------------------------------------------------------------------------
def run_export() -> None:
    """Call the backend exporter as a subprocess (uses .uv-venv with asyncpg)."""
    app_dir = Path(__file__).resolve().parents[1] / "fortress-guest-platform"
    venv_python = app_dir / ".uv-venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = app_dir / "venv" / "bin" / "python"

    exporter = app_dir / "backend" / "workers" / "nightly_distillation_exporter.py"
    log.info("Running distillation exporter …")
    result = subprocess.run(
        [str(venv_python), str(exporter)],
        cwd=str(app_dir),
        timeout=300,
    )
    if result.returncode != 0:
        log.warning("Exporter exited with code %d — continuing with existing JSONL.", result.returncode)


# ---------------------------------------------------------------------------
# Step 2: Load rolling JSONL window
# ---------------------------------------------------------------------------
def load_training_data(rolling_days: int) -> list[dict]:
    today = date.today()
    records: list[dict] = []
    for offset in range(rolling_days):
        day_date = today - timedelta(days=offset)
        if day_date < MIN_DATE:
            continue  # never consume pre-filter data
        day = day_date.isoformat()
        path = INTERACTION_LOG_DIR / f"{day}.jsonl"
        if not path.exists():
            continue
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
    log.info("Loaded %d training examples from last %d days.", len(records), rolling_days)
    return records


# ---------------------------------------------------------------------------
# Step 3: QLoRA training
# ---------------------------------------------------------------------------
def run_qlora_training(records: list[dict], adapter_out: Path) -> None:
    # Import here — deps may have been freshly installed
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTConfig, SFTTrainer

    log.info("Base model: %s", BASE_MODEL_DIR)
    log.info("Adapter output: %s", adapter_out)
    log.info("Training examples: %d", len(records))
    log.info("LoRA rank: %d, epochs: %d, lr: %g", LORA_RANK, NUM_EPOCHS, LEARNING_RATE)

    # --- Tokenizer ---
    tokenizer = AutoTokenizer.from_pretrained(
        str(BASE_MODEL_DIR),
        use_fast=True,
        trust_remote_code=False,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # --- 4-bit NF4 quantization config ---
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    # --- Load base model ---
    log.info("Loading base model in 4-bit NF4 …")
    model = AutoModelForCausalLM.from_pretrained(
        str(BASE_MODEL_DIR),
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=False,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    # --- LoRA config ---
    lora_config = LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_RANK * 2,
        target_modules=LORA_TARGET_MODULES,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # --- Dataset: apply chat template ---
    def _apply_template(example: dict) -> dict:
        text = tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )
        return {"text": text}

    raw_ds = Dataset.from_list([{"messages": r["messages"]} for r in records])
    dataset = raw_ds.map(_apply_template, remove_columns=["messages"])

    # --- Training arguments ---
    adapter_out.mkdir(parents=True, exist_ok=True)
    training_args = SFTConfig(
        output_dir=str(adapter_out),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        fp16=False,
        bf16=True,
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        max_seq_length=MAX_SEQ_LEN,
        dataset_text_field="text",
        packing=True,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    log.info("Training started …")
    train_result = trainer.train()
    log.info("Training complete. metrics=%s", train_result.metrics)

    log.info("Saving LoRA adapter to %s …", adapter_out)
    trainer.save_model(str(adapter_out))
    tokenizer.save_pretrained(str(adapter_out))
    log.info("Adapter saved.")

    # Capture loss curve from trainer log history
    loss_history = [
        {"step": e["step"], "loss": round(e["loss"], 6)}
        for e in trainer.state.log_history
        if "loss" in e
    ]
    final_loss = loss_history[-1]["loss"] if loss_history else None

    # Git SHA of trainer code at run time
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_sha = "unknown"

    # Write full metadata manifest
    manifest = {
        "base_model": str(BASE_MODEL_DIR),
        "adapter_path": str(adapter_out),
        "training_date": date.today().isoformat(),
        "dataset_size": len(records),
        "lora_config": {
            "r": LORA_RANK,
            "lora_alpha": LORA_RANK * 2,
            "target_modules": LORA_TARGET_MODULES,
            "lora_dropout": 0.05,
            "task_type": "CAUSAL_LM",
        },
        "training_args": {
            "epochs": NUM_EPOCHS,
            "learning_rate": LEARNING_RATE,
            "batch_size": BATCH_SIZE,
            "grad_accum": GRAD_ACCUM,
            "max_seq_len": MAX_SEQ_LEN,
        },
        "final_loss": final_loss,
        "loss_curve": loss_history,
        "trainer_git_sha": git_sha,
    }
    (adapter_out / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )
    log.info("Manifest written. final_loss=%s git_sha=%s", final_loss, git_sha)


# ---------------------------------------------------------------------------
# Step 4: Ollama hot-swap (optional)
# ---------------------------------------------------------------------------
def push_to_ollama(adapter_path: Path) -> None:
    """Merge LoRA adapter + create an Ollama model named crog-llama-70b."""
    import torch
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    merged_dir = adapter_path.parent / (adapter_path.name + "-merged")
    log.info("Merging LoRA adapter → %s …", merged_dir)

    model = AutoPeftModelForCausalLM.from_pretrained(
        str(adapter_path),
        device_map="cpu",
        torch_dtype=torch.bfloat16,
    )
    model = model.merge_and_unload()
    model.save_pretrained(str(merged_dir))

    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(merged_dir))
    log.info("Merge complete.")

    # Write Ollama Modelfile
    modelfile = merged_dir / "Modelfile"
    modelfile.write_text(
        f"FROM {merged_dir}\n"
        "PARAMETER temperature 0.7\n"
        "PARAMETER top_p 0.9\n"
        'SYSTEM "You are CROG-AI, a sovereign AI assistant for Cabin Rentals of Georgia. You have been fine-tuned on real operational data from legal, booking, and market intelligence domains."\n'
    )

    log.info("Creating Ollama model crog-llama-70b …")
    subprocess.run(
        ["ollama", "create", "crog-llama-70b", "-f", str(modelfile)],
        check=True,
        timeout=600,
    )
    log.info("Ollama model crog-llama-70b created.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(dry_run: bool = False, skip_export: bool = False) -> int:
    log.info("=" * 60)
    log.info("Fortress Prime — Nightly Fine-Tune Job starting")
    log.info("Date: %s  dry_run=%s", date.today().isoformat(), dry_run)
    log.info("=" * 60)

    today_tag = date.today().isoformat()
    adapter_out = ADAPTER_DIR / f"llama-3.3-70b-crog-{today_tag}"

    # --- Step 1: Export ---
    if not skip_export:
        run_export()
    else:
        log.info("Skipping export (--skip-export)")

    # --- Step 2: Load data ---
    records = load_training_data(ROLLING_DAYS)

    _HARD_MIN = 5  # absolute floor — never train on fewer than this regardless of env
    if len(records) < _HARD_MIN:
        log.warning(
            "Only %d training examples (hard minimum %d). Skipping.",
            len(records), _HARD_MIN,
        )
        return 0

    # Dry-run check comes before env-minimum so config can be validated even when
    # the rolling dataset is below the production threshold.
    if dry_run:
        log.info(
            "[DRY RUN] base_model=%s output=%s examples=%d min_required=%d. Exiting without training.",
            BASE_MODEL_DIR.name, adapter_out, len(records), MIN_EXAMPLES,
        )
        return 0

    if len(records) < MIN_EXAMPLES:
        log.warning(
            "Only %d training examples (env minimum %d). Skipping training run.",
            len(records), MIN_EXAMPLES,
        )
        return 0

    # --- Step 3: Install deps ---
    _ensure_training_deps()

    # --- Step 4: Stop vLLM ---
    vllm_was_running = _stop_vllm(VLLM_CONTAINER)

    exit_code = 0
    try:
        # --- Step 5: Train ---
        run_qlora_training(records, adapter_out)

        # --- Step 6: Optional Ollama push ---
        if PUSH_OLLAMA:
            push_to_ollama(adapter_out)

    except Exception as exc:
        import traceback as _tb
        log.error("Training failed: %s", exc, exc_info=True)
        exit_code = 1
        try:
            adapter_out.mkdir(parents=True, exist_ok=True)
            (adapter_out / "training.error").write_text(
                f"{type(exc).__name__}: {exc}\n\n{_tb.format_exc()}"
            )
            log.info("Failure reason written to %s/training.error", adapter_out)
        except Exception:
            pass
    finally:
        # Always restart vLLM even if training failed
        if vllm_was_running:
            _start_vllm(VLLM_CONTAINER)

    log.info("Nightly fine-tune job complete. exit_code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fortress Prime nightly fine-tune job")
    parser.add_argument("--dry-run",     action="store_true", help="Export + count examples, skip training")
    parser.add_argument("--skip-export", action="store_true", help="Skip DB export, use existing JSONL only")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run, skip_export=args.skip_export))
