"""
Fortress Prime — Enterprise Prompt Management System
=====================================================
Version-controlled, decoupled prompt templates for the sovereign AI stack.

Usage:
    from prompts.loader import load_prompt

    # Load a template
    template = load_prompt("ledger_classifier")

    # Render with variables
    prompt = template.render(filename="invoice.pdf", document_text="...")

    # Access metadata
    print(template.model_config)   # {"recommended": "deepseek-r1:8b", ...}
    print(template.version)        # "v1"
    print(template.division)       # "finance"

    # List all available templates
    from prompts.loader import list_prompts
    print(list_prompts())          # ["ledger_classifier", "thunderdome_pitbull", ...]
"""

from prompts.loader import (
    load_prompt,
    list_prompts,
    log_prompt_execution,
    get_prompt_logs,
    get_prompt_stats,
)
from prompts.tone_detector import detect_tone, detect_tone_modifier
from prompts.topic_classifier import classify_topic, classify_topic_tag
from prompts.judge_parser import parse_verdict
from prompts.starred_db import (
    star_response,
    load_dynamic_examples,
    get_examples_for_topic,
)
from prompts.context_slicer import (
    slice_context,
    slice_context_text,
    load_cabin,
    list_cabins,
)

__all__ = [
    "load_prompt",
    "list_prompts",
    "log_prompt_execution",
    "get_prompt_logs",
    "get_prompt_stats",
    "detect_tone",
    "detect_tone_modifier",
    "classify_topic",
    "classify_topic_tag",
    "parse_verdict",
    "star_response",
    "load_dynamic_examples",
    "get_examples_for_topic",
    "slice_context",
    "slice_context_text",
    "load_cabin",
    "list_cabins",
]
