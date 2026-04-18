"""
promotion_gate.py — apply the promotion gate to a metrics.json.

Reads metrics.json from the adapter directory, applies conservative
thresholds, and writes either:
  promotion_candidate.json  — all gates passed
  promotion_rejected.json   — one or more gates failed (with reason)

Also writes a PROMOTED_CANDIDATE sentinel file at ARTIFACTS_ROOT if
the candidate passes — this is a flag only. Phase 4c handles actual routing.

Usage:
  python promotion_gate.py --adapter-path /mnt/fortress_nas/finetune-artifacts/.../
                           [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"promotion_gate"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("promotion_gate")

# ---------------------------------------------------------------------------
# Thresholds (all env-var overridable)
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD    = float(os.getenv("EVAL_SIMILARITY_THRESHOLD",   "0.85"))
VALIDITY_THRESHOLD      = float(os.getenv("EVAL_VALIDITY_THRESHOLD",     "0.95"))
MIN_PROMPTS_PER_DOMAIN  = int(os.getenv("EVAL_MIN_PROMPTS_PER_DOMAIN",   "30"))
BLOCKER_DOMAINS         = set(os.getenv("EVAL_BLOCKER_DOMAINS",
                              "legal,vrs").split(","))

ARTIFACTS_ROOT = Path(os.getenv("FINETUNE_ADAPTER_DIR",
                      "/mnt/fortress_nas/finetune-artifacts"))


def apply_gate(adapter_path: Path, dry_run: bool) -> bool:
    metrics_path = adapter_path / "metrics.json"
    if not metrics_path.exists():
        log.error("metrics.json not found at %s — eval must run first", metrics_path)
        return False

    metrics = json.loads(metrics_path.read_text())
    log.info("Loaded metrics: n=%d sim=%.4f validity=%.4f regressions=%d",
             metrics.get("n_evaluated", 0),
             metrics.get("similarity_mean") or 0,
             metrics.get("validity_rate") or 0,
             metrics.get("regression_count", 0))

    failures: list[dict] = []

    # Gate 1: similarity
    sim = metrics.get("similarity_mean")
    if sim is None:
        failures.append({"gate": "similarity", "reason": "no similarity data"})
    elif sim < SIMILARITY_THRESHOLD:
        failures.append({
            "gate": "similarity",
            "actual": sim,
            "threshold": SIMILARITY_THRESHOLD,
            "reason": f"similarity_mean {sim:.4f} < {SIMILARITY_THRESHOLD}",
        })

    # Gate 2: validity
    val = metrics.get("validity_rate")
    if val is None:
        failures.append({"gate": "validity", "reason": "no validity data"})
    elif val < VALIDITY_THRESHOLD:
        failures.append({
            "gate": "validity",
            "actual": val,
            "threshold": VALIDITY_THRESHOLD,
            "reason": f"validity_rate {val:.4f} < {VALIDITY_THRESHOLD}",
        })

    # Gate 3: regressions in blocker domains
    domain_regressions = metrics.get("domain_regressions", {})
    for domain in BLOCKER_DOMAINS:
        count = domain_regressions.get(domain, 0)
        if count > 0:
            failures.append({
                "gate": "regressions",
                "domain": domain,
                "regression_count": count,
                "reason": f"{count} regression(s) in blocker domain '{domain}'",
            })

    # Gate 4: minimum prompts per domain (warn only, not a hard block)
    domain_counts = metrics.get("domain_counts", {})
    for domain in BLOCKER_DOMAINS:
        n = domain_counts.get(domain, 0)
        if 0 < n < MIN_PROMPTS_PER_DOMAIN:
            log.warning(
                "Domain '%s' has only %d holdout prompts (min=%d) — "
                "regression gate has limited power for this domain",
                domain, n, MIN_PROMPTS_PER_DOMAIN,
            )

    passed = len(failures) == 0
    result = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "adapter_path": str(adapter_path),
        "passed": passed,
        "thresholds": {
            "similarity": SIMILARITY_THRESHOLD,
            "validity": VALIDITY_THRESHOLD,
            "min_prompts_per_domain": MIN_PROMPTS_PER_DOMAIN,
            "blocker_domains": list(BLOCKER_DOMAINS),
        },
        "metrics_summary": {
            "similarity_mean": metrics.get("similarity_mean"),
            "validity_rate": metrics.get("validity_rate"),
            "regression_count": metrics.get("regression_count"),
            "domain_regressions": domain_regressions,
            "n_evaluated": metrics.get("n_evaluated"),
        },
        "failures": failures,
    }

    if dry_run:
        log.info("[DRY RUN] gate_result=passed=%s failures=%s", passed, failures)
        return passed

    if passed:
        out_path = adapter_path / "promotion_candidate.json"
        out_path.write_text(json.dumps(result, indent=2))
        log.info("PROMOTED CANDIDATE — all gates passed. Written to %s", out_path)

        # Write sentinel at artifacts root — Phase 4c reads this
        sentinel = ARTIFACTS_ROOT / "PROMOTED_CANDIDATE"
        sentinel.write_text(json.dumps({
            "adapter_path": str(adapter_path),
            "promoted_at": result["evaluated_at"],
        }, indent=2))
        log.info("Sentinel written to %s", sentinel)
    else:
        out_path = adapter_path / "promotion_rejected.json"
        out_path.write_text(json.dumps(result, indent=2))
        log.warning("PROMOTION REJECTED — %d gate(s) failed:", len(failures))
        for f in failures:
            log.warning("  ✗ %s", f["reason"])

    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply promotion gate to eval metrics")
    parser.add_argument("--adapter-path", required=True,
                        help="Path to the trained LoRA adapter directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate gate logic without writing output files")
    args = parser.parse_args()

    adapter_path = Path(args.adapter_path)
    if not (adapter_path / "metrics.json").exists():
        log.error("metrics.json not found at %s", adapter_path)
        return 1

    passed = apply_gate(adapter_path, args.dry_run)
    return 0 if passed else 2  # exit 2 = rejected (not an error, just not promoted)


if __name__ == "__main__":
    sys.exit(main())
