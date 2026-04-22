"""
run_eval_v2.py — Hardened eval harness with task-specific metrics.

Extends run_eval.py with:
  - Citation extraction accuracy (legal/C primary): precision/recall/F1
  - Topic recall/precision/F1 (legal/B primary): semantic matching of section headers
  - Holding term overlap + ROUGE-L (legal/A)
  - Format compliance per domain
  - Hallucination rate (proxy: unparseable citation-like tokens)
  - Per-sample output storage (--save-outputs flag, required for failure mode analysis)

All legacy metrics (similarity_mean, validity_rate, regression_count) still computed.
New metrics stored in metrics_v2.json alongside legacy metrics.json.

Usage:
  python -m src.eval.run_eval_v2 \
      --adapter-path /mnt/fortress_nas/models/... \
      --holdout-path /mnt/fortress_nas/legal-corpus/training-pairs/holdout-eval-expanded-v2.json \
      [--save-outputs] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"run_eval_v2"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("run_eval_v2")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval.metrics.citations import citation_f1, hallucination_rate
from src.eval.metrics.holdings import holding_metrics
from src.eval.metrics.topics import topic_f1


# ---------------------------------------------------------------------------
# Validity check (unchanged from run_eval.py)
# ---------------------------------------------------------------------------
import re as _re

_REPEATED_TOKEN_RE = _re.compile(r"(.{2,}?)\1{10,}")
_EVAL_BASE_ENV = os.getenv("FINETUNE_BASE_MODEL_DIR",
                           "/mnt/fortress_nas/models/Qwen2.5-7B-Instruct")
EMBEDDING_MODEL = os.getenv("EVAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
# 256 ≈ 190 words — sufficient for all gold responses (max 362w teacher).
# Prevents 4-5min/record stall when model generates maximum-length outputs.
MAX_NEW_TOKENS = int(os.getenv("EVAL_MAX_NEW_TOKENS", "256"))


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
# Format compliance checks
# ---------------------------------------------------------------------------

_NUMBERED_LIST_RE = _re.compile(r"^\s*\d+[\.\)]\s+", _re.MULTILINE)
_UNDER_CITE_RE = _re.compile(r"^Under\s+.{3,}:", _re.IGNORECASE)


def _format_ok(output: str, domain: str) -> bool:
    """Check domain-specific output format."""
    if domain == "legal/B":
        return bool(_NUMBERED_LIST_RE.search(output))
    if domain == "legal/C":
        return bool(_UNDER_CITE_RE.match(output.strip()))
    # A, D, E: should be prose (not starting with a numbered list at position 0)
    if domain in ("legal/A", "legal/D"):
        return not bool(_re.match(r"^\s*1[\.\)]\s+", output))
    return True


# ---------------------------------------------------------------------------
# Core eval
# ---------------------------------------------------------------------------

def run_eval_v2(
    adapter_path: Path,
    holdout_path: Path,
    dry_run: bool = False,
    save_outputs: bool = False,
) -> dict:
    log.info("Loading holdout manifest from %s", holdout_path)
    manifest = json.loads(holdout_path.read_text())
    records = manifest["records"]
    log.info("Holdout: %d records across domains %s",
             len(records), list(manifest.get("domain_counts", {}).keys()))

    if dry_run:
        log.info("[DRY RUN] Would evaluate %d prompts with hardened metrics", len(records))
        log.info("[DRY RUN] Embedding model: %s", EMBEDDING_MODEL)
        log.info("[DRY RUN] Citation parser, topic matcher, holding overlap all active")
        return {"dry_run": True, "records": len(records)}

    # Load embedding model
    log.info("Loading embedding model %s …", EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")

    # Load adapter
    log.info("Loading adapter from %s in bf16 …", adapter_path)
    import torch
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer
    from sklearn.metrics.pairwise import cosine_similarity

    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path), use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoPeftModelForCausalLM.from_pretrained(
        str(adapter_path), device_map="auto", torch_dtype=torch.bfloat16)
    model.eval()
    log.info("Adapter loaded.")

    # Per-record accumulators
    per_domain: dict[str, list] = defaultdict(list)
    all_outputs: list[dict] = []

    # Legacy accumulators
    similarities: list[float] = []
    validity_flags: list[bool] = []
    regressions: dict[str, int] = {}

    for i, rec in enumerate(records):
        prompt = rec["user_prompt"]
        teacher = rec["teacher_response"]
        domain = rec["domain"]

        # Generate
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
                **inputs, max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False, pad_token_id=tokenizer.eos_token_id)
        new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
        student_output = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

        # --- Legacy metrics ---
        valid = _is_valid_response(student_output, teacher)
        teacher_valid = _is_valid_response(teacher, teacher)
        validity_flags.append(valid)
        if not valid and teacher_valid:
            regressions[domain] = regressions.get(domain, 0) + 1

        embs = embedder.encode([student_output, teacher], convert_to_numpy=True)
        sim = float(cosine_similarity(embs[0:1], embs[1:2])[0][0])
        similarities.append(sim)

        # --- Task-specific metrics ---
        sample_metrics: dict = {
            "record_id": rec.get("id", str(i)),
            "domain": domain,
            "similarity": round(sim, 4),
            "valid": valid,
            "format_ok": _format_ok(student_output, domain),
            "hallucination_rate": hallucination_rate(student_output),
        }

        if domain == "legal/B":
            tf = topic_f1(student_output, teacher, embedder=embedder)
            sample_metrics.update(tf)

        elif domain == "legal/C":
            cf = citation_f1(student_output, teacher)
            sample_metrics.update(cf)
            # Format: starts with "Under [something]:"
            sample_metrics["citation_format_ok"] = _format_ok(student_output, "legal/C")

        elif domain == "legal/A":
            hm = holding_metrics(student_output, teacher)
            sample_metrics.update(hm)

        per_domain[domain].append(sample_metrics)

        if save_outputs:
            all_outputs.append({
                "record_id": rec.get("id", str(i)),
                "domain": domain,
                "prompt": prompt,
                "teacher": teacher,
                "output": student_output,
                "metrics": {k: v for k, v in sample_metrics.items()
                            if k not in ("record_id", "domain")},
            })

        if (i + 1) % 10 == 0:
            log.info("Progress: %d/%d evaluated", i + 1, len(records))

    # --- Aggregate ---
    n = len(records)

    # Legacy metrics (unchanged)
    legacy = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "adapter_path": str(adapter_path),
        "holdout_path": str(holdout_path),
        "n_evaluated": n,
        "similarity_mean": round(sum(similarities) / n, 4) if similarities else None,
        "similarity_by_domain": {},
        "validity_rate": round(sum(validity_flags) / n, 4) if validity_flags else None,
        "regression_count": sum(regressions.values()),
        "domain_regressions": regressions,
        "domain_counts": manifest.get("domain_counts", {}),
    }
    by_dom_sim: dict[str, list] = defaultdict(list)
    for rec2, sim in zip(records, similarities):
        by_dom_sim[rec2["domain"]].append(sim)
    for d, sims in by_dom_sim.items():
        legacy["similarity_by_domain"][d] = round(sum(sims) / len(sims), 4)

    # V2 aggregated metrics
    v2_domain: dict[str, dict] = {}

    for dom, samples in per_domain.items():
        agg: dict[str, float | int | bool] = {}
        # Always include: format_ok rate, hallucination_rate mean, similarity mean
        agg["n"] = len(samples)
        agg["similarity_mean"] = round(sum(s["similarity"] for s in samples) / len(samples), 4)
        agg["format_ok_rate"] = round(sum(1 for s in samples if s["format_ok"]) / len(samples), 4)
        agg["hallucination_rate"] = round(
            sum(s["hallucination_rate"] for s in samples) / len(samples), 4)

        if dom == "legal/B":
            for key in ("topic_recall", "topic_precision", "topic_f1"):
                vals = [s[key] for s in samples if key in s]
                if vals:
                    agg[key] = round(sum(vals) / len(vals), 4)
            agg["format_ok_rate"] = round(
                sum(1 for s in samples if s.get("format_ok", False)) / len(samples), 4)

        elif dom == "legal/C":
            for key in ("precision", "recall", "f1"):
                vals = [s[key] for s in samples if key in s]
                if vals:
                    agg[f"citation_{key}"] = round(sum(vals) / len(vals), 4)

        elif dom == "legal/A":
            agg["holding_present_rate"] = round(
                sum(1 for s in samples if s.get("holding_present", False)) / len(samples), 4)
            for key in ("holding_term_overlap", "rouge_l"):
                vals = [s[key] for s in samples if key in s]
                if vals:
                    agg[key] = round(sum(vals) / len(vals), 4)

        v2_domain[dom] = agg

    metrics_v2 = {
        "evaluated_at": legacy["evaluated_at"],
        "adapter_path": str(adapter_path),
        "holdout_path": str(holdout_path),
        "n_evaluated": n,
        "harness_version": "v2",
        "domain_metrics": v2_domain,
        # Roll up key cross-domain numbers
        "overall": {
            "similarity_mean": legacy["similarity_mean"],
            "validity_rate": legacy["validity_rate"],
            "regression_count": legacy["regression_count"],
            "topic_f1_B": v2_domain.get("legal/B", {}).get("topic_f1"),
            "citation_f1_C": v2_domain.get("legal/C", {}).get("citation_f1"),
            "rouge_l_A": v2_domain.get("legal/A", {}).get("rouge_l"),
        },
    }

    # Write outputs
    # Legacy metrics.json (unchanged path — backward compatible)
    legacy_path = adapter_path / "metrics.json"
    legacy_path.write_text(json.dumps(legacy, indent=2))

    # New metrics_v2.json
    v2_path = adapter_path / "metrics_v2.json"
    v2_path.write_text(json.dumps(metrics_v2, indent=2))
    log.info("metrics_v2.json written to %s", v2_path)

    if save_outputs:
        out_path = adapter_path / "outputs.jsonl"
        with out_path.open("w") as f:
            for rec3 in all_outputs:
                f.write(json.dumps(rec3, ensure_ascii=False) + "\n")
        log.info("Per-sample outputs written to %s (%d records)", out_path, len(all_outputs))

    log.info(
        "eval_v2 complete: sim=%.4f validity=%.4f regressions=%d topic_f1_B=%s citation_f1_C=%s",
        legacy["similarity_mean"] or 0,
        legacy["validity_rate"] or 0,
        legacy["regression_count"],
        v2_domain.get("legal/B", {}).get("topic_f1", "n/a"),
        v2_domain.get("legal/C", {}).get("citation_f1", "n/a"),
    )
    return metrics_v2


def main() -> int:
    p = argparse.ArgumentParser(description="Hardened eval harness v2")
    p.add_argument("--adapter-path", required=True)
    p.add_argument("--holdout-path", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--save-outputs", action="store_true",
                   help="Store per-sample outputs in outputs.jsonl (needed for Phase 2 diagnosis)")
    args = p.parse_args()

    adapter_path = Path(args.adapter_path)
    holdout_path = Path(args.holdout_path)
    if not adapter_path.exists():
        log.error("Adapter path does not exist: %s", adapter_path)
        return 1
    if not holdout_path.exists():
        log.error("Holdout path does not exist: %s", holdout_path)
        return 1

    run_eval_v2(adapter_path, holdout_path,
                dry_run=args.dry_run, save_outputs=args.save_outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
