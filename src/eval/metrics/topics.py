"""
topics.py — Topic recall/precision/F1 for legal/B (issue spotting).

Pattern B gold answers are numbered lists of section headers:
  "The following legal issues are presented:\n  1. Summary Judgment\n  2. Analysis"

Metric: for each gold topic, is there a semantically similar topic in the output?
Uses MiniLM embeddings + cosine similarity at threshold=0.7.
Falls back to token-overlap if embedder unavailable.
"""
from __future__ import annotations

import re
from typing import Optional


_ITEM_RE = re.compile(r"^\s*\d+[\.\)]\s*(.+)$", re.MULTILINE)
_HEADER_STRIP = re.compile(r"^The following\b.*?:\s*", re.IGNORECASE | re.DOTALL)


def parse_topics(text: str) -> list[str]:
    """Extract numbered list items from a Pattern B response."""
    # Strip preamble line
    cleaned = _HEADER_STRIP.sub("", text.strip(), count=1)
    items = [m.group(1).strip() for m in _ITEM_RE.finditer(cleaned)]
    # Filter very short or empty
    return [t for t in items if len(t) > 2]


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity on lowercased word tokens."""
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def topic_f1(
    output: str,
    gold: str,
    embedder=None,
    threshold: float = 0.70,
) -> dict[str, float]:
    """
    Compute topic precision, recall, F1 for Pattern B.

    For each gold topic, find the best-matching output topic (by semantic
    similarity if embedder provided, else token overlap). Mark as match if
    score >= threshold.

    Returns dict with: topic_recall, topic_precision, topic_f1,
                       n_output_topics, n_gold_topics, n_matched_gold,
                       format_ok (bool — output is a numbered list).
    """
    pred_topics = parse_topics(output)
    gold_topics = parse_topics(gold)

    format_ok = len(pred_topics) > 0  # has a numbered list

    if not gold_topics:
        # Nothing to match against — score undefined, return neutral
        return {
            "topic_recall": 1.0, "topic_precision": 1.0, "topic_f1": 1.0,
            "n_output_topics": len(pred_topics),
            "n_gold_topics": 0, "n_matched_gold": 0,
            "format_ok": format_ok,
        }

    if not pred_topics:
        return {
            "topic_recall": 0.0, "topic_precision": 0.0, "topic_f1": 0.0,
            "n_output_topics": 0,
            "n_gold_topics": len(gold_topics), "n_matched_gold": 0,
            "format_ok": False,
        }

    def _best_sim(query: str, candidates: list[str]) -> float:
        if embedder is not None:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity as _cos
            all_texts = [query] + candidates
            embs = embedder.encode(all_texts, convert_to_numpy=True)
            sims = _cos(embs[0:1], embs[1:])[0]
            return float(np.max(sims))
        else:
            return max(_token_overlap(query, c) for c in candidates)

    # Recall: fraction of gold topics matched in output
    matched_gold = sum(
        1 for g in gold_topics if _best_sim(g, pred_topics) >= threshold
    )
    recall = matched_gold / len(gold_topics)

    # Precision: fraction of output topics matched in gold
    matched_pred = sum(
        1 for p in pred_topics if _best_sim(p, gold_topics) >= threshold
    )
    precision = matched_pred / len(pred_topics)

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "topic_recall": round(recall, 4),
        "topic_precision": round(precision, 4),
        "topic_f1": round(f1, 4),
        "n_output_topics": len(pred_topics),
        "n_gold_topics": len(gold_topics),
        "n_matched_gold": matched_gold,
        "format_ok": format_ok,
    }
