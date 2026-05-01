"""Wave 5 evaluator — scores a candidate legal brief against a baseline.

Per brief §9.3. The judge is `legal-reasoning` (extended-reasoning Super-120B
via LiteLLM), not `legal-moderation`. Output is structured JSON; pass/fail is
gated by `rubric.pass_threshold` and `rubric.per_dimension_minimum`.

Usage:
    python score.py \
      --baseline /path/to/baseline.md \
      --candidate /path/to/candidate.md \
      --config /path/to/config.yml \
      --output /path/to/score.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

DIMENSIONS = (
    "citation_density",
    "citation_precision",
    "structural_completeness",
    "doctrinal_soundness",
    "internal_consistency",
)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _extract_json(text: str) -> dict[str, Any]:
    """Find the first {...} JSON object in `text` and parse it.

    The judge model sometimes wraps the JSON in code fences or commentary;
    a permissive scan is more robust than json.loads(text) directly.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object found in judge response (first 300 chars): {text[:300]!r}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"unterminated JSON in judge response: {text[start:start+300]!r}")


def score(baseline_path: str, candidate_path: str, config_path: str, output_path: str | None) -> dict[str, Any]:
    config = yaml.safe_load(_read(config_path))
    judge = config["judge"]
    rubric = config["rubric"]

    api_key = os.environ.get(judge.get("api_key_env", "OPENAI_API_KEY"), "")
    if not api_key:
        raise RuntimeError(f"missing API key in env var {judge.get('api_key_env')}")

    baseline_text = _read(baseline_path)
    candidate_text = _read(candidate_path)

    prompt = (
        judge["prompt_template"]
        .replace("{baseline_text}", baseline_text)
        .replace("{candidate_text}", candidate_text)
    )

    t0 = time.time()
    r = requests.post(
        f"{judge['endpoint']}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": judge["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": judge.get("max_tokens", 4096),
            "temperature": judge.get("temperature", 0.2),
        },
        timeout=judge.get("timeout_s", 300),
    )
    elapsed = time.time() - t0
    r.raise_for_status()

    judge_resp = r.json()["choices"][0]["message"]["content"]
    parsed = _extract_json(judge_resp)

    # Validate dimensions
    missing = [d for d in DIMENSIONS if d not in parsed]
    if missing:
        raise ValueError(f"judge response missing dimensions: {missing}; got keys: {list(parsed.keys())}")

    overall = float(parsed.get("overall", sum(parsed[d] for d in DIMENSIONS) / len(DIMENSIONS)))
    per_dim_min = min(float(parsed[d]) for d in DIMENSIONS)
    pass_overall = overall >= float(rubric["pass_threshold"])
    pass_per_dim = per_dim_min >= float(rubric["per_dimension_minimum"])

    summary = {
        "baseline": baseline_path,
        "candidate": candidate_path,
        "judge_model": judge["model"],
        "elapsed_s": round(elapsed, 2),
        "scores": {d: parsed[d] for d in DIMENSIONS},
        "overall": overall,
        "rationale": parsed.get("rationale", ""),
        "rubric": {
            "pass_threshold": rubric["pass_threshold"],
            "per_dimension_minimum": rubric["per_dimension_minimum"],
        },
        "result": {
            "pass_overall": pass_overall,
            "pass_per_dim": pass_per_dim,
            "candidate_passes_baseline": pass_overall and pass_per_dim,
        },
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(summary, indent=2))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    summary = score(args.baseline, args.candidate, args.config, args.output)
    print(json.dumps(summary, indent=2))
    return 0 if summary["result"]["candidate_passes_baseline"] else 1


if __name__ == "__main__":
    sys.exit(main())
