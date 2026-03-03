"""
FORTRESS PROTOCOL: RAG Context Compressor
==========================================
Token optimization utility for the DGX inference pipeline.

Strips redundant whitespace, known legal boilerplate, and near-duplicate
sentences before context reaches the LLM. Reduces VRAM pressure and
improves response latency across SWARM, HYDRA, and TITAN modes.

Usage:
    from src.context_compressor import compress_rag_context

    raw_context = "\\n---\\n".join(chunks)
    optimized = compress_rag_context(raw_context, max_tokens=8000)
"""

import re
from typing import List

BOILERPLATE_PATTERNS = [
    r"IN WITNESS WHEREOF,?\s+the parties hereto have executed.*?(?:\.|$)",
    r"Page\s+\d+\s+of\s+\d+",
    r"All rights reserved\.?",
    r"This document is confidential and proprietary\.?",
    r"_{10,}",
    r"-{10,}",
    r"={10,}",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]


def compress_rag_context(raw_text: str, max_tokens: int = 8000) -> str:
    """Compress RAG context to reduce token waste before LLM inference.

    Pipeline:
        1. Collapse redundant whitespace (multi-newlines, tabs, trailing spaces)
        2. Strip known boilerplate patterns (legal footers, page numbers, etc.)
        3. Deduplicate exact-match sentences (common with overlapping chunks)
        4. Enforce a hard character cap derived from max_tokens

    Args:
        raw_text:   Raw concatenated context from Qdrant retrieval.
        max_tokens: Approximate upper bound on output tokens (~4 chars/token).

    Returns:
        Compressed context string.
    """
    if not raw_text:
        return ""

    compressed = re.sub(r'[ \t]+', ' ', raw_text)
    compressed = re.sub(r'\n{3,}', '\n\n', compressed)

    for pattern in _COMPILED_PATTERNS:
        compressed = pattern.sub('', compressed)

    sentences = compressed.split('. ')
    seen = set()
    deduped: List[str] = []
    for s in sentences:
        normalized = s.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(s.strip())

    final_text = '. '.join(deduped).strip()

    char_limit = max_tokens * 4
    if len(final_text) > char_limit:
        final_text = final_text[:char_limit] + "\n... [TRUNCATED FOR TOKEN LIMIT]"

    return final_text
