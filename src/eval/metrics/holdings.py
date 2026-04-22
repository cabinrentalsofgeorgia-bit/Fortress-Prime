"""
holdings.py — Holding extraction and overlap for legal/A.

Pattern A gold answers are paragraphs with the court's holding + reasoning.
Metrics:
  - holding_present: does the output contain an affirmance/reversal signal?
  - holding_term_overlap: key legal term Jaccard overlap (output vs gold)
  - rouge_l: ROUGE-L sentence-level recall
"""
from __future__ import annotations

import re


_HOLDING_MARKERS = re.compile(
    r"\b(we\s+hold|we\s+affirm|we\s+reverse|we\s+conclude|affirmed|reversed|"
    r"judgment\s+affirmed|judgment\s+reversed|we\s+find|we\s+determine)\b",
    re.IGNORECASE,
)

_LEGAL_TERMS = re.compile(
    r"\b(summary\s+judgment|motion\s+to\s+dismiss|breach|coverage|"
    r"exclusion|duty\s+to\s+defend|subrogation|negligence|damages|"
    r"indemnif|insurer|insured|policyholder|bad\s+faith|statutory|"
    r"O\.C\.G\.A|OCGA|affirm|revers|summary\s+judgment|directed\s+verdict|"
    r"genuine\s+issue|material\s+fact)\b",
    re.IGNORECASE,
)


def _extract_terms(text: str) -> set[str]:
    return {m.group(0).lower().replace(" ", "_") for m in _LEGAL_TERMS.finditer(text)}


def _rouge_l(hypothesis: str, reference: str) -> float:
    """LCS-based ROUGE-L at word level."""
    h = hypothesis.lower().split()
    r = reference.lower().split()
    if not h or not r:
        return 0.0
    # LCS via DP
    m, n = len(r), len(h)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if r[i - 1] == h[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    precision = lcs / n if n > 0 else 0.0
    recall = lcs / m if m > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def holding_metrics(output: str, gold: str) -> dict:
    """
    Compute holding-related metrics for Pattern A.
    Returns: holding_present, holding_term_overlap, rouge_l.
    """
    holding_present = bool(_HOLDING_MARKERS.search(output))

    output_terms = _extract_terms(output)
    gold_terms = _extract_terms(gold)
    if not gold_terms:
        term_overlap = 1.0
    else:
        shared = output_terms & gold_terms
        union = output_terms | gold_terms
        term_overlap = round(len(shared) / len(union), 4) if union else 1.0

    rl = _rouge_l(output, gold)

    return {
        "holding_present": holding_present,
        "holding_term_overlap": term_overlap,
        "rouge_l": rl,
    }
