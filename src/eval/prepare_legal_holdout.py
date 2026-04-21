"""
prepare_legal_holdout.py — convert legal-corpus holdout.jsonl to run_eval.py format.

The legal training holdout uses {instruction, output, pattern, metadata} keys.
run_eval.py expects {user_prompt, teacher_response, domain} inside a records array.

Usage:
  python -m src.eval.prepare_legal_holdout \
      --input  /mnt/fortress_nas/legal-corpus/training-pairs/holdout.jsonl \
      --output /mnt/fortress_nas/legal-corpus/training-pairs/holdout-eval.json

Output is a JSON file compatible with run_eval.py --holdout-path.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"prepare_holdout"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("prepare_holdout")

DEFAULT_INPUT  = Path("/mnt/fortress_nas/legal-corpus/training-pairs/holdout.jsonl")
DEFAULT_OUTPUT = Path("/mnt/fortress_nas/legal-corpus/training-pairs/holdout-eval.json")


def convert(input_path: Path, output_path: Path) -> None:
    records = []
    with input_path.open() as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            records.append({
                "id":               raw.get("source_cluster", str(i)),
                "domain":           f"legal/{raw.get('pattern', 'unknown')}",
                "source_module":    "legal_corpus",
                "model_used":       raw.get("metadata", {}).get("model", "unknown"),
                "user_prompt":      raw["instruction"],
                "teacher_response": raw["output"],
                "created_at":       raw.get("metadata", {}).get("date", ""),
            })

    domain_counts = dict(Counter(r["domain"] for r in records))
    holdout = {
        "holdout_date":       datetime.now(tz=timezone.utc).date().isoformat(),
        "built_at":           datetime.now(tz=timezone.utc).isoformat(),
        "source":             str(input_path),
        "total_holdout":      len(records),
        "domain_counts":      domain_counts,
        "records":            records,
    }
    output_path.write_text(json.dumps(holdout, indent=2))
    log.info("Wrote %d records to %s", len(records), output_path)
    log.info("domain_counts %s", json.dumps(domain_counts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    convert(args.input, args.output)
