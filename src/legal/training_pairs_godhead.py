#!/usr/bin/env python3
"""
training_pairs_godhead.py — Phase 4d Part 2, Pattern E: Godhead-generated pairs.

Filters the corpus for high-value insurance defense cases and sends them to
Claude (via LiteLLM gateway) for diverse instruction-tuning pair generation.

Usage:
  python -m src.legal.training_pairs_godhead --dry-run
  python -m src.legal.training_pairs_godhead --limit 150 --model claude-haiku-4-5
  python -m src.legal.training_pairs_godhead --limit 150 --model claude-opus-4-6

Environment:
  LITELLM_MASTER_KEY         API key for the LiteLLM gateway
  LITELLM_BASE_URL           LiteLLM proxy base URL (default: http://127.0.0.1:8002/v1)
  LEGAL_GODHEAD_BUDGET_USD   Hard cost cap (default: 200.0)
  LEGAL_CORPUS_ROOT          NAS corpus root

Output:
  /mnt/fortress_nas/legal-corpus/training-pairs/godhead.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("training_pairs_godhead")

CORPUS_ROOT = Path(os.getenv("LEGAL_CORPUS_ROOT", "/mnt/fortress_nas/legal-corpus"))
FULLTEXT_PATH = CORPUS_ROOT / "courtlistener" / "opinions-full.jsonl"
OUT_PATH = CORPUS_ROOT / "training-pairs" / "godhead.jsonl"

LITELLM_BASE = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:8002/v1")
BUDGET_USD = float(os.getenv("LEGAL_GODHEAD_BUDGET_USD", "200.0"))

# Pricing per 1M tokens (haiku-4-5 is cheapest, opus-4-6 highest quality)
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5":  {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
}
DEFAULT_MODEL = "claude-haiku-4-5"

# ---------------------------------------------------------------------------
# Hard-case filter (Option 4 criteria)
# ---------------------------------------------------------------------------

_FILTER_KEYWORDS = [
    "bad faith", "duty to defend", "coverage exclusion", "reservation of rights",
    "stacking", "uim", "uninsured motorist", "underinsured motorist",
    "first-party", "third-party", "subrogation waiver", "independent counsel",
    "excess verdict", "settlement demand", "policy limits", "liability coverage",
    "coverage denial", "insurer's duty",
]

MIN_CHARS = 8000


def _matches_filter(rec: dict) -> bool:
    text = (rec.get("plain_text") or "").lower()
    if len(text) < MIN_CHARS:
        return False
    return any(kw in text for kw in _FILTER_KEYWORDS)


def filter_cases(records: list[dict], limit: int) -> list[dict]:
    """Return the top `limit` high-value insurance defense opinions."""
    matched = [r for r in records if _matches_filter(r)]
    # Sort by text length descending (longer = denser reasoning)
    matched.sort(key=lambda r: len(r.get("plain_text") or ""), reverse=True)
    selected = matched[:limit]
    log.info("filter: %d matched, selecting top %d by length", len(matched), len(selected))
    return selected


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """You are generating training examples for a Georgia insurance defense AI judge model. Given this appellate opinion, produce 5 diverse instruction-tuning pairs. Each pair must have:
1. "instruction": A realistic query an attorney might ask (vary style: plain English, formal analysis, client communication)
2. "output": The correct analytical response grounded in the opinion's specific reasoning and citations

Return ONLY a JSON array of 5 objects, each with "instruction" and "output" keys. No other text.

Opinion ({chars} chars):
{text}"""

_AVG_OUTPUT_TOKENS = 1800  # ~5 pairs × ~360 tokens each


def estimate_cost(model: str, n_cases: int, avg_chars: int) -> float:
    pricing = _PRICING.get(model, _PRICING[DEFAULT_MODEL])
    avg_input_tokens = avg_chars // 4 + 300  # prompt overhead
    total_input_tokens = avg_input_tokens * n_cases
    total_output_tokens = _AVG_OUTPUT_TOKENS * n_cases
    cost = (
        total_input_tokens / 1_000_000 * pricing["input"]
        + total_output_tokens / 1_000_000 * pricing["output"]
    )
    return cost


# ---------------------------------------------------------------------------
# Godhead API call
# ---------------------------------------------------------------------------

def _call_godhead(text: str, model: str, api_key: str, base_url: str) -> tuple[list[dict], int, int]:
    """Call LiteLLM gateway. Returns (pairs, input_tokens, output_tokens)."""
    import urllib.request
    truncated = text[:12000]  # stay within context window
    prompt = _PROMPT_TEMPLATE.format(chars=len(truncated), text=truncated)

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2200,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    input_tok = usage.get("prompt_tokens", len(prompt) // 4)
    output_tok = usage.get("completion_tokens", len(content) // 4)

    # Parse JSON array from response
    # Handle potential markdown wrapping
    json_match = re.search(r'\[[\s\S]*\]', content)
    if not json_match:
        raise ValueError(f"No JSON array in response: {content[:200]}")
    pairs = json.loads(json_match.group())
    if not isinstance(pairs, list):
        raise ValueError(f"Expected list, got {type(pairs)}")
    return pairs, input_tok, output_tok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    if not FULLTEXT_PATH.exists():
        log.error("Corpus not found: %s", FULLTEXT_PATH)
        return 1

    records = [json.loads(l) for l in FULLTEXT_PATH.open() if l.strip()]
    log.info("loaded %d opinions", len(records))

    selected = filter_cases(records, args.limit)
    avg_chars = sum(len(r.get("plain_text") or "") for r in selected) // max(len(selected), 1)
    est_cost = estimate_cost(args.model, len(selected), avg_chars)

    print(f"\nGodhead filter results:")
    print(f"  Opinions matching filter:  {len([r for r in records if _matches_filter(r)])}")
    print(f"  Selected (top by length):  {len(selected)}")
    print(f"  Avg opinion length:        {avg_chars:,} chars")
    print(f"  Model:                     {args.model}")
    print(f"  Estimated cost:            ${est_cost:.2f}")
    print(f"  Budget cap:                ${BUDGET_USD:.2f}")

    if args.dry_run:
        print("\n[DRY RUN] Top 10 selected cases:")
        for r in selected[:10]:
            kws_found = [kw for kw in _FILTER_KEYWORDS if kw in (r.get("plain_text") or "").lower()]
            print(f"  [{r.get('date_filed','?')[:4]}] {r.get('case_name','?')[:70]}")
            print(f"         chars={len(r.get('plain_text','') or ''):,}  keywords={kws_found[:3]}")
        print(f"\n  ...and {max(0, len(selected)-10)} more")
        print(f"\nRun without --dry-run to generate pairs (est. ${est_cost:.2f})")
        return 0

    if est_cost > BUDGET_USD:
        log.error(
            "Estimated cost $%.2f exceeds budget $%.2f — reduce --limit or change --model",
            est_cost, BUDGET_USD,
        )
        return 1

    api_key = os.getenv("LITELLM_MASTER_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""
    if not api_key:
        log.error("No API key. Set LITELLM_MASTER_KEY or ANTHROPIC_API_KEY")
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total_pairs = 0
    total_cost = 0.0
    failed = 0
    pricing = _PRICING.get(args.model, _PRICING[DEFAULT_MODEL])

    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(selected):
            if total_cost >= BUDGET_USD:
                log.warning("BUDGET EXHAUSTED at $%.2f — stopping at %d/%d opinions",
                            total_cost, i, len(selected))
                break

            cluster_id = rec.get("cluster_id", "?")
            log.info("generating pairs %d/%d cluster=%s", i + 1, len(selected), cluster_id)

            try:
                pairs, in_tok, out_tok = _call_godhead(
                    rec.get("plain_text", ""), args.model, api_key, LITELLM_BASE
                )
                call_cost = (in_tok / 1_000_000 * pricing["input"]
                             + out_tok / 1_000_000 * pricing["output"])
                total_cost += call_cost

                for p in pairs:
                    if not isinstance(p, dict) or not p.get("instruction") or not p.get("output"):
                        continue
                    record = {
                        "pattern": "E",
                        "source_cluster": cluster_id,
                        "instruction": p["instruction"],
                        "output": p["output"],
                        "metadata": {
                            "case": rec.get("case_name"),
                            "date": rec.get("date_filed"),
                            "model": args.model,
                        },
                    }
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_pairs += 1

                log.info("  pairs=%d cost=$%.4f cumulative=$%.2f", len(pairs), call_cost, total_cost)

            except Exception as exc:
                log.error("godhead_failed cluster=%s error=%s", cluster_id, exc)
                failed += 1

            time.sleep(0.3)  # polite rate limiting

    log.info(
        "godhead_complete total_pairs=%d failed=%d total_cost=$%.2f out=%s",
        total_pairs, failed, total_cost, OUT_PATH,
    )
    print(f"\nGodhead pairs written: {total_pairs:,}")
    print(f"Failed opinions: {failed}")
    print(f"Actual cost: ${total_cost:.2f}")
    print(f"Output: {OUT_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.legal.training_pairs_godhead",
        description="Pattern E: Godhead-generated training pairs for hard insurance defense cases",
    )
    parser.add_argument("--limit", type=int, default=150,
                        help="Max opinions to send to Godhead (default: 150)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        choices=list(_PRICING.keys()),
                        help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show selected cases + cost estimate without calling API")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
