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
    VLLM_DEPLOYMENT         default: nim-sovereign (k8s deployment name)
    VLLM_NAMESPACE          default: default
    VLLM_HEALTH_URL         default: http://10.43.38.88:8000/v1/models (ClusterIP)
    VLLM_STOP_TIMEOUT             default: 120  (seconds to wait for pod to terminate)
    VLLM_START_TIMEOUT            default: 300  (seconds for NIM model load + health)
    NIM_TERMINATION_DWELL_SECONDS default: 30   (fixed sleep after pod gone on unified-memory GPUs)
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
VLLM_DEPLOYMENT              = os.getenv("VLLM_DEPLOYMENT",            "nim-sovereign")
VLLM_NAMESPACE               = os.getenv("VLLM_NAMESPACE",             "default")
VLLM_HEALTH_URL              = os.getenv("VLLM_HEALTH_URL",            "http://10.43.38.88:8000/v1/models")
VLLM_STOP_TIMEOUT            = int(os.getenv("VLLM_STOP_TIMEOUT",      "120"))
VLLM_START_TIMEOUT           = int(os.getenv("VLLM_START_TIMEOUT",     "300"))
NIM_TERMINATION_DWELL_SECONDS = int(os.getenv("NIM_TERMINATION_DWELL_SECONDS", "30"))
_NIM_GPU_RELEASE_TIMEOUT     = 120  # hard ceiling; not configurable
MIN_DATE             = date.fromisoformat(os.getenv("FINETUNE_MIN_DATE", "2026-04-18"))
HOLDOUT_DIR          = Path(os.getenv("HOLDOUT_DIR",
                         "/mnt/fortress_nas/finetune-artifacts/holdouts"))

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
# NIM / vLLM k8s pod management
# vLLM runs as NVIDIA NIM (nim-sovereign deployment) inside k3s, NOT as a
# native systemd process or Docker container. GPU is freed only when the
# k8s pod terminates. We use kubectl scale to control replica count.
# ---------------------------------------------------------------------------
def _nim_pod_running() -> bool:
    """True if at least one nim-sovereign pod is in Running state."""
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", VLLM_NAMESPACE,
         "-l", "app=nim-engine", "--no-headers"],
        capture_output=True, text=True, timeout=15,
    )
    return "Running" in result.stdout


def _nim_any_pod_exists() -> bool:
    """True if any nim-engine pod exists in any state (Running, Terminating, etc.)."""
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", VLLM_NAMESPACE,
         "-l", "app=nim-engine", "--no-headers"],
        capture_output=True, text=True, timeout=15,
    )
    return bool(result.stdout.strip())


def _gpu_free_mib() -> "int | None":
    """Return free GPU MiB, or None if the card reports [N/A] (GB10 unified memory)."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            timeout=10, text=True,
        ).strip()
        first = out.splitlines()[0].strip() if out else ""
        return None if not first or "[N/A]" in first else int(first)
    except Exception:
        return None


def _wait_for_gpu_released() -> None:
    """
    After kubectl scale-to-zero, block until VRAM is confirmed free.

    Phase 1 — pod termination: poll until no nim-engine pods exist in any
    state (Running or Terminating). _stop_vllm's loop only checks "Running";
    a pod stuck in Terminating still holds the CUDA context.

    Phase 2 — VRAM release:
    - Unified-memory / GB10: nvidia-smi reports [N/A] for memory metrics.
      Sleep NIM_TERMINATION_DWELL_SECONDS (default 30 s) as a fixed dwell.
    - Discrete GPU: poll nvidia-smi memory.free until it jumps by >1 GiB,
      indicating the CUDA context was released.

    Hard ceiling: _NIM_GPU_RELEASE_TIMEOUT (120 s). Raises RuntimeError on
    timeout so the caller can write a .error file instead of OOMing mid-load.
    """
    deadline = time.time() + _NIM_GPU_RELEASE_TIMEOUT

    # Phase 1: wait for pod to vanish entirely (no Terminating stragglers)
    while time.time() < deadline:
        if not _nim_any_pod_exists():
            log.info("NIM pod fully terminated (no pods in any state).")
            break
        log.info("NIM pod still exists (may be Terminating) — waiting for full teardown …")
        time.sleep(3)
    else:
        raise RuntimeError(
            f"NIM pod ({VLLM_NAMESPACE}/{VLLM_DEPLOYMENT}) still present "
            f"{_NIM_GPU_RELEASE_TIMEOUT}s after scale-to-zero. "
            "GPU memory not confirmed free — aborting training to avoid OOM. "
            f"Check: kubectl get pods -n {VLLM_NAMESPACE} -l app=nim-engine"
        )

    # Phase 2: confirm VRAM released
    free_mib = _gpu_free_mib()
    if free_mib is None:
        # GB10 / unified-memory: nvidia-smi can't report discrete VRAM
        dwell = NIM_TERMINATION_DWELL_SECONDS
        log.info(
            "Unified-memory GPU detected (nvidia-smi N/A) — "
            "sleeping %ds for CUDA context teardown (NIM_TERMINATION_DWELL_SECONDS).", dwell,
        )
        time.sleep(dwell)
        log.info("GPU dwell complete — proceeding with model load.")
    else:
        # Discrete GPU: poll until free memory jumps (NIM CUDA context released)
        log.info("GPU free before dwell: %d MiB — polling for release …", free_mib)
        prev = free_mib
        while time.time() < deadline:
            time.sleep(5)
            curr = _gpu_free_mib()
            if curr is None:
                log.info("GPU switched to N/A reporting — assuming released.")
                return
            if curr >= prev + 1024:
                log.info("GPU memory released: %d MiB → %d MiB — proceeding.", prev, curr)
                return
            prev = curr
        log.warning(
            "GPU memory polling reached %ds ceiling (%d MiB free) — proceeding anyway.",
            _NIM_GPU_RELEASE_TIMEOUT, prev,
        )


def _stop_vllm() -> bool:
    """
    Scale nim-sovereign to 0 replicas, freeing GPU memory for training.

    k8s gracefully terminates the pod (SIGTERM then SIGKILL), releasing
    all GPU allocations. We poll until the pod disappears or raise
    RuntimeError if it doesn't terminate within VLLM_STOP_TIMEOUT.

    Returns True if NIM was running and was stopped, False if already gone.
    """
    if not _nim_pod_running():
        log.info("NIM pod not running — GPU already free.")
        return False

    log.info("Scaling %s/%s to 0 replicas to free GPU …", VLLM_NAMESPACE, VLLM_DEPLOYMENT)
    subprocess.run(
        ["kubectl", "scale", "deployment", VLLM_DEPLOYMENT,
         "-n", VLLM_NAMESPACE, "--replicas=0"],
        check=True, timeout=30,
    )

    deadline = time.time() + VLLM_STOP_TIMEOUT
    while time.time() < deadline:
        if not _nim_pod_running():
            log.info("NIM pod no longer Running — waiting for full teardown and GPU release …")
            _wait_for_gpu_released()
            log.info("GPU memory confirmed free — proceeding with training.")
            return True
        time.sleep(5)

    raise RuntimeError(
        f"NIM pod ({VLLM_NAMESPACE}/{VLLM_DEPLOYMENT}) did not leave Running state "
        f"within {VLLM_STOP_TIMEOUT}s after scale-to-zero. "
        "GPU memory not freed — aborting training to avoid OOM. "
        f"Check: kubectl get pods -n {VLLM_NAMESPACE} -l app=nim-engine"
    )


def _start_vllm() -> None:
    """
    Scale nim-sovereign back to 1 replica and wait for the OpenAI-compat
    health endpoint to respond. NIM model load takes 3-5 minutes for 8B,
    so VLLM_START_TIMEOUT defaults to 300s.

    Raises RuntimeError if health check times out — caller writes error file.
    """
    import urllib.request

    log.info("Scaling %s/%s to 1 replica …", VLLM_NAMESPACE, VLLM_DEPLOYMENT)
    subprocess.run(
        ["kubectl", "scale", "deployment", VLLM_DEPLOYMENT,
         "-n", VLLM_NAMESPACE, "--replicas=1"],
        check=True, timeout=30,
    )

    log.info("Waiting for NIM health at %s (timeout=%ds) …", VLLM_HEALTH_URL, VLLM_START_TIMEOUT)
    deadline = time.time() + VLLM_START_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(VLLM_HEALTH_URL, timeout=10) as resp:
                if resp.status == 200:
                    log.info("NIM healthy — pod Running and API responding.")
                    return
        except Exception:
            pass
        time.sleep(10)

    raise RuntimeError(
        f"NIM pod did not become healthy at {VLLM_HEALTH_URL} within "
        f"{VLLM_START_TIMEOUT}s after scale-up. "
        "Check: kubectl logs -n default -l app=nim-engine"
    )


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
# Phase 4b: Eval pipeline
# ---------------------------------------------------------------------------
def _run_eval_pipeline(adapter_out: Path) -> None:
    """
    Run the Phase 4b eval harness after training.

    Finds today's holdout manifest, runs run_eval.py against the adapter,
    then applies the promotion gate. Errors are logged but never raise —
    a failed eval doesn't roll back the training artifact.
    """
    today_tag = date.today().isoformat()
    holdout_path = HOLDOUT_DIR / f"holdout-{today_tag}.json"

    if not holdout_path.exists():
        log.warning("No holdout manifest at %s — skipping eval. "
                    "Run build_holdout.py to create one.", holdout_path)
        return

    eval_script = Path(__file__).parent / "eval" / "run_eval.py"
    gate_script  = Path(__file__).parent / "eval" / "promotion_gate.py"

    try:
        log.info("Running eval harness …")
        result = subprocess.run(
            [sys.executable, str(eval_script),
             "--adapter-path", str(adapter_out),
             "--holdout-path", str(holdout_path)],
            timeout=3600,
        )
        if result.returncode != 0:
            log.warning("Eval script exited %d — check adapter metrics", result.returncode)
            return

        log.info("Running promotion gate …")
        gate_result = subprocess.run(
            [sys.executable, str(gate_script),
             "--adapter-path", str(adapter_out)],
            timeout=60,
        )
        if gate_result.returncode == 0:
            log.info("Promotion gate PASSED — promotion_candidate.json written")
        elif gate_result.returncode == 2:
            log.warning("Promotion gate REJECTED — see promotion_rejected.json")
        else:
            log.error("Promotion gate failed unexpectedly (exit %d)", gate_result.returncode)

    except Exception as exc:
        log.error("Eval pipeline error (non-fatal): %s", exc)


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

    # --- Step 4: Stop vLLM to free GPU memory ---
    vllm_was_running = False
    try:
        vllm_was_running = _stop_vllm()
    except RuntimeError as exc:
        # GPU not freed — abort cleanly rather than OOM during training
        log.error("Cannot free GPU memory for training: %s", exc)
        adapter_out.mkdir(parents=True, exist_ok=True)
        (adapter_out / "training.error").write_text(
            f"vLLM stop failed — training aborted to avoid OOM.\n{exc}"
        )
        return 1

    exit_code = 0
    try:
        # --- Step 5: Train ---
        run_qlora_training(records, adapter_out)

        # --- Step 6: Phase 4b eval pipeline (runs while GPU is still free) ---
        _run_eval_pipeline(adapter_out)

        # --- Step 7: Optional Ollama push ---
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
        # Always attempt to restart vLLM even if training failed
        if vllm_was_running:
            try:
                _start_vllm()
            except RuntimeError as exc:
                import traceback as _tb
                log.error("vLLM failed to restart after training: %s", exc)
                try:
                    adapter_out.mkdir(parents=True, exist_ok=True)
                    (adapter_out / "vllm_restart.error").write_text(
                        f"vLLM restart failed after training.\n{exc}\n\n{_tb.format_exc()}"
                    )
                except Exception:
                    pass
                exit_code = max(exit_code, 1)

    log.info("Nightly fine-tune job complete. exit_code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fortress Prime nightly fine-tune job")
    parser.add_argument("--dry-run",     action="store_true", help="Export + count examples, skip training")
    parser.add_argument("--skip-export", action="store_true", help="Skip DB export, use existing JSONL only")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run, skip_export=args.skip_export))
