"""
task_types.py — v5 task taxonomy constants.

Used by task_classifier.py, labeling_pipeline.py, and the judge tier.
Every valid task_type string must be in _TASK_TYPES.
Changes to this file require an architectural decision logged in
docs/IRON_DOME_ARCHITECTURE.md.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Valid task type labels (v5 Godhead spec)
# ---------------------------------------------------------------------------
_TASK_TYPES: frozenset[str] = frozenset({
    # Legal
    "legal_reasoning",
    "brief_drafting",
    "legal_citations",
    "contract_analysis",
    # Code
    "code_generation",
    "code_refactoring",
    "code_debugging",
    # Vision
    "vision_damage",
    "vision_photo",
    "ocr",
    # Real-time
    "real_time",
    "current_market",
    # Math / logic
    "math_reasoning",
    "complex_logic",
    # Summarization
    "summarization_long",
    "summarization_news",
    # VRS / CROG
    "vrs_concierge",
    "vrs_ota_response",
    # Business intelligence
    "competitive_intel",
    "pricing_math",
    "acquisitions_analysis",
    "market_research",
    # Fallback
    "generic",
})

# ---------------------------------------------------------------------------
# Tier 1: source_module → task_type (deterministic, highest confidence)
# ---------------------------------------------------------------------------
_MODULE_TO_TASK: dict[str, str] = {
    # Legal modules
    "legal_council":               "legal_reasoning",
    "ediscovery_agent":            "legal_citations",
    "legal_email_intake":          "legal_reasoning",
    "legal_intake":                "legal_reasoning",
    "legal_agent_orchestrator":    "legal_reasoning",
    "legal_case_graph":            "legal_reasoning",
    "legal_chronology":            "legal_reasoning",
    "legal_deposition_prep":       "brief_drafting",
    "legal_discovery_engine":      "legal_citations",
    # VRS / CROG
    "vrs_agent_dispatcher":        "vrs_concierge",
    "concierge_worker":            "vrs_concierge",
    "reactivation_hunter":         "vrs_concierge",
    "damage_claim_workflow":       "vrs_concierge",
    # Pricing
    "quote_engine":                "pricing_math",
    # Vision
    "ota_vision_recon":            "vision_photo",
    "listing_qc_worker":           "vision_photo",
    # Market intelligence
    "macro_treasury":              "market_research",
    "research_scout":              "market_research",
    # Acquisitions
    "acquisitions_analyzer":       "acquisitions_analysis",
}

# ---------------------------------------------------------------------------
# Tier 2: keyword patterns → task_type (ordered, first match wins)
# Case-insensitive — applied to lowercased combined prompt+response.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Content-signal patterns for Tier 1 override logic
# These are separate from _KEYWORD_PATTERNS (which are classification rules).
# Used by _detect_content_mismatch in task_classifier.py to catch modules
# whose source_module → task_type mapping is ambiguous (e.g. quote_engine
# sometimes produces property descriptions instead of pricing calculations).
# ---------------------------------------------------------------------------

# Patterns that indicate the prompt is requesting a pricing calculation.
# Must be present for a quote_engine capture to stay classified as pricing_math.
_PRICING_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bnightly rate\b|\bprice per night\b|\brate per night\b",  re.IGNORECASE),
    re.compile(r"\bhow much\b.{0,40}\b(?:night|stay|week|total)\b",         re.IGNORECASE),
    re.compile(r"\bprice this\b|\bprice for\b|\brate for\b|\bquote for\b",  re.IGNORECASE),
    re.compile(r"\brate.*(?:strategy|multiplier|extraction|adjustment)\b",   re.IGNORECASE),
    re.compile(r"\bstrike.*(?:type|price|rate)\b|\brate.*strike\b",         re.IGNORECASE),
    re.compile(r"\$\s*\d+",                                                  re.IGNORECASE),
    re.compile(r"\btotal cost\b|\bbooking cost\b|\bfee schedule\b",         re.IGNORECASE),
    re.compile(r"\bcompetitor.*(?:rate|price|nightly)\b",                   re.IGNORECASE),
]

# Patterns that indicate the prompt is requesting a property description,
# marketing copy, or factual property information — not a price calculation.
_DESCRIPTIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"what does .{1,60} look like",                                              re.IGNORECASE),
    re.compile(r"\bdescribe (?:the |this |that |\w+ )?(?:property|cabin|lodge|deck|exterior|interior|room|view|amenit)", re.IGNORECASE),
    re.compile(r"\bmarketing copy\b|\blisting (?:description|copy)\b|\bproperty description\b", re.IGNORECASE),
    re.compile(r"\btell me about\b|\bdetails about\b|\binfo(?:rmation)? about\b",          re.IGNORECASE),
    re.compile(r"\bamenities of\b|\bfeatures of\b",                                        re.IGNORECASE),
    re.compile(r"\b(?:deck|exterior|interior|views?|outdoor|indoor)\b.{0,40}\b(?:look|appear|feature|material|condition|built|made)\b", re.IGNORECASE),
    re.compile(r"\bluxury (?:retreat|escape|sanctuary|experience)\b",                      re.IGNORECASE),
    re.compile(r"\bself[- ]check.?in\b|\bsmart home\b|\bpanoram\w*\b",                    re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Tier 2: keyword patterns → task_type (ordered, first match wins)
# Case-insensitive — applied to lowercased combined prompt+response.
# ---------------------------------------------------------------------------
_KEYWORD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"draft (?:a |the )?brief|opening statement|closing argument"), "brief_drafting"),
    (re.compile(r"analyze|review (?:this |the )contract"), "contract_analysis"),
    (re.compile(r"cite (?:.*?)?(?:case|statute|authority)|legal citation"), "legal_citations"),
    (re.compile(r"deponent|deposition|depose|cross.examn"), "brief_drafting"),
    (re.compile(r"price this|nightly rate|pricing strategy|rate for"), "pricing_math"),
    (re.compile(r"refactor|optimize this code|clean up the code"), "code_refactoring"),
    (re.compile(r"debug|fix this error|why is this failing|traceback"), "code_debugging"),
    (re.compile(r"write (?:a |the )?function|implement|generate code|def "), "code_generation"),
    (re.compile(r"damage (?:assessment|claim|to|in)"), "vision_damage"),
    (re.compile(r"describe (?:this |the )(?:image|photo)|what do you see|identify.*photo"), "vision_photo"),
    (re.compile(r"latest news|current (?:status|rate|price)|today.s|right now"), "real_time"),
    (re.compile(r"market (?:condition|trend|report)|comp(?:etitor)?(?:s)? (?:analysis|intel)"), "competitive_intel"),
    (re.compile(r"summarize (?:this |the )(?:article|report|paper|document)"), "market_research"),
    (re.compile(r"respond to (?:this |the )?(?:guest|booking|inquiry)|guest message"), "vrs_ota_response"),
    (re.compile(r"acquisition|due diligence|parcel|property purchase"), "acquisitions_analysis"),
    (re.compile(r"calculate|solve|proof|theorem|equation"), "math_reasoning"),
]
