"""
citations.py — Citation extraction and matching for GA legal text.

Handles:
  OCGA § formats:  "O.C.G.A. § 9-11-12(b)(6)", "OCGA § 9-11-12", "§ 9-11-12"
  GA case cites:   "Smith v. Jones, 123 Ga. App. 456, 789 S.E.2d 123 (2020)"
                   "Smith v. Jones, 123 Ga. 456 (2020)"
  GA court rules:  "USCR 6.2", "Uniform Superior Court Rule 6.2",
                   "GA Supreme Court Rule 4", "Court of Appeals Rule 12"
  Federal rules:   NOT extracted (out of scope for GA primary jurisdiction)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _norm_section(raw: str) -> str:
    """Normalise OCGA section number: strip spaces, collapse § variants."""
    s = raw.replace("O.C.G.A.", "OCGA").replace("Ga. Code Ann.", "OCGA")
    s = re.sub(r"\s*§\s*", "§", s)
    s = re.sub(r"\s+", "", s)
    return s.upper()


def _norm_case(name: str) -> str:
    """Lowercase + collapse whitespace for case name matching."""
    return re.sub(r"\s+", " ", name.lower().strip())


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# OCGA section references — captures the section number
_OCGA_RE = re.compile(
    r"(?:O\.C\.G\.A\.|OCGA|Ga\.\s*Code\s*Ann\.)\s*§\s*([\d\-]+(?:\([a-z0-9]+\))*)"
    r"|§\s*([\d\-]+(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)

# GA case citations — "Name v. Name, [digits] Ga. [App.] [digits] ([year])"
_CASE_RE = re.compile(
    r"([A-Z][A-Za-z &',\.]+)\s+v\.\s+([A-Z][A-Za-z &',\.]+)"
    r",?\s+(\d{1,3})\s+Ga\.(?:\s+App\.)?\s+(\d+)[^\(]{0,30}\((\d{4})\)",
    re.IGNORECASE,
)

# GA court rule references
_RULE_RE = re.compile(
    r"(?:Uniform\s+Superior\s+Court\s+Rules?|USCR)\s+([\d\.]+)"
    r"|(?:GA\s+)?Supreme\s+Court\s+Rules?\s+([\d\.]+)"
    r"|Court\s+of\s+Appeals\s+Rules?\s+([\d\.]+)"
    r"|(?:Uniform\s+)?(?:Magistrate|State|Probate)\s+Court\s+Rules?\s+([\d\.]+)",
    re.IGNORECASE,
)


@dataclass
class Citation:
    type: str               # "ocga" | "case" | "rule"
    raw: str                # original text span
    normalized: str         # canonical form for matching

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Citation):
            return False
        return self.type == other.type and self.normalized == other.normalized

    def __hash__(self) -> int:
        return hash((self.type, self.normalized))


def extract_citations(text: str) -> list[Citation]:
    """Return all citations found in text, deduped."""
    results: list[Citation] = []
    seen: set[str] = set()

    def _add(cit: Citation) -> None:
        key = f"{cit.type}:{cit.normalized}"
        if key not in seen:
            seen.add(key)
            results.append(cit)

    # OCGA
    for m in _OCGA_RE.finditer(text):
        sec = (m.group(1) or m.group(2) or "").strip()
        if not sec or len(sec) < 3:
            continue
        norm = _norm_section(f"OCGA§{sec}")
        _add(Citation("ocga", m.group(0), norm))

    # Case citations
    for m in _CASE_RE.finditer(text):
        p1, p2, vol, pg, yr = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        norm = f"{_norm_case(p1)}v{_norm_case(p2)}{vol}ga{pg}{yr}"
        _add(Citation("case", m.group(0), norm))

    # Court rules
    for m in _RULE_RE.finditer(text):
        num = next(g for g in m.groups() if g is not None)
        raw = _norm_ws(m.group(0))
        # Determine rule set
        rl = raw.lower()
        if "superior" in rl or "uscr" in rl:
            rtype = "uscr"
        elif "supreme" in rl:
            rtype = "gasupreme"
        elif "appeals" in rl:
            rtype = "gaappeals"
        else:
            rtype = "garule"
        norm = f"{rtype}:{num.strip()}"
        _add(Citation("rule", raw, norm))

    return results


def citation_f1(output: str, gold: str) -> dict[str, float]:
    """
    Compute citation precision, recall, F1.
    Matching is on normalised citation strings.
    Returns dict with keys: precision, recall, f1, n_output, n_gold, n_match.
    """
    pred_set = set(c.normalized for c in extract_citations(output))
    gold_set = set(c.normalized for c in extract_citations(gold))

    if not gold_set and not pred_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0,
                "n_output": 0, "n_gold": 0, "n_match": 0}

    if not gold_set:
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0,
                "n_output": len(pred_set), "n_gold": 0, "n_match": 0}

    if not pred_set:
        return {"precision": 1.0, "recall": 0.0, "f1": 0.0,
                "n_output": 0, "n_gold": len(gold_set), "n_match": 0}

    matches = pred_set & gold_set
    p = len(matches) / len(pred_set)
    r = len(matches) / len(gold_set)
    f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f, 4),
        "n_output": len(pred_set),
        "n_gold": len(gold_set),
        "n_match": len(matches),
    }


def hallucination_rate(output: str) -> float:
    """
    Fraction of citations in output that are structurally invalid for GA law.
    Heuristic: a citation is suspect if it looks like a citation (has § or v.)
    but doesn't match any of our known patterns.
    Returns 0.0 if no citation-like text found.
    """
    # Quick scan for citation-like tokens
    citation_like = re.findall(
        r"(?:§\s*[\d\-]+|v\.\s+[A-Z][a-z]+|Rule\s+[\d\.]+)", output
    )
    if not citation_like:
        return 0.0

    extracted = extract_citations(output)
    # If we find citation-like tokens but can't parse them as valid citations
    n_like = len(citation_like)
    n_parsed = len(extracted)
    unparsed = max(0, n_like - n_parsed)
    return round(unparsed / n_like, 4) if n_like > 0 else 0.0
