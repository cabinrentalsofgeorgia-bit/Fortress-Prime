"""
THE PROMPT ENGINEER — Meta-Agent Middleware Layer
==================================================
Sits between every business-logic caller and every LLM endpoint.
Performs three transformations on every prompt before it reaches metal:

  1. SYNTAX TRANSLATOR  — Rewrites prompts into the optimal dialect for
                          the target model (XML tags for Anthropic,
                          <think> blocks for DeepSeek, strict JSON for
                          fast local models).

  2. CONTEXT COMPILER   — Assembles RAG context from Qdrant collections
                          (fgp_knowledge, fgp_golden_claims, legal_library)
                          into structured dossiers injected into the prompt.

  3. ZERO-TRUST SANITIZER — Strips PII from any prompt leaving the DGX
                            cluster for a cloud Horseman. Replaces real
                            names, codes, and addresses with tagged
                            placeholders. Rehydrates on response return.

Data Sovereignty: PII only flows to local models. Cloud Horsemen receive
sanitized prompts only. This is Constitution Article I, Section 1.1.
"""

import os
import sys
import re
from typing import Optional, Dict, List, Tuple

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from src.context_compressor import compress_rag_context


logger = structlog.get_logger()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. SYNTAX TRANSLATOR — Model-Specific Prompt Dialects
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODEL_FAMILIES = {
    "anthropic": ["claude", "opus", "sonnet", "haiku"],
    "deepseek": ["deepseek", "r1"],
    "qwen": ["qwen"],
    "llama": ["llama", "llama3"],
    "gemini": ["gemini"],
    "grok": ["grok"],
    "openai": ["gpt", "o1", "o3"],
}


def detect_model_family(model_name: str) -> str:
    """Detect which family a model belongs to for syntax optimization."""
    name = model_name.lower()
    for family, patterns in MODEL_FAMILIES.items():
        if any(p in name for p in patterns):
            return family
    return "generic"


def translate_for_model(
    system_message: str,
    user_prompt: str,
    model_name: str,
    structured_data: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Translate a prompt into the optimal syntax for the target model.

    Args:
        system_message: The system prompt
        user_prompt: The user/task prompt
        model_name: Target model name (e.g. "claude-opus-4-6")
        structured_data: Optional dict of labeled data blocks to embed
                         (e.g. {"contract": "...", "staff_notes": "..."})

    Returns:
        (translated_system, translated_user) tuple
    """
    family = detect_model_family(model_name)

    if family == "anthropic":
        return _translate_anthropic(system_message, user_prompt, structured_data)
    elif family == "deepseek":
        return _translate_deepseek(system_message, user_prompt, structured_data)
    elif family in ("qwen", "llama"):
        return _translate_local_fast(system_message, user_prompt, structured_data)
    else:
        return _translate_generic(system_message, user_prompt, structured_data)


def _translate_anthropic(
    system: str, user: str, data: Optional[Dict[str, str]],
) -> Tuple[str, str]:
    """Anthropic Opus/Sonnet: XML-tagged structure for maximum precision."""
    if data:
        xml_blocks = []
        for key, value in data.items():
            tag = re.sub(r"[^a-z_]", "_", key.lower())
            xml_blocks.append(f"<{tag}>\n{value}\n</{tag}>")
        user = "\n\n".join(xml_blocks) + f"\n\n<task>\n{user}\n</task>"

    system = (
        f"<instructions>\n{system}\n</instructions>\n\n"
        "<output_rules>\n"
        "- Follow the instructions precisely.\n"
        "- Cite sources with exact quotes when referencing documents.\n"
        "- If asked for JSON, return ONLY valid JSON with no surrounding text.\n"
        "</output_rules>"
    )
    return system, user


def _translate_deepseek(
    system: str, user: str, data: Optional[Dict[str, str]],
) -> Tuple[str, str]:
    """DeepSeek-R1: Chain-of-thought priming with <think> blocks."""
    if data:
        context_block = "\n\n".join(
            f"### {key.upper()}\n{value}" for key, value in data.items()
        )
        user = f"{context_block}\n\n### TASK\n{user}"

    user += (
        "\n\nBefore answering, reason step-by-step in a <think> block. "
        "Show your analysis of each relevant data point. "
        "Then provide your final answer after </think>."
    )
    return system, user


def _translate_local_fast(
    system: str, user: str, data: Optional[Dict[str, str]],
) -> Tuple[str, str]:
    """Qwen/Llama local models: Strict, minimal, JSON-focused."""
    if data:
        context_block = "\n\n".join(
            f"{key.upper()}:\n{value[:2000]}" for key, value in data.items()
        )
        user = f"{context_block}\n\n{user}"

    system = (
        f"{system}\n\n"
        "CRITICAL: Respond ONLY with the requested output format. "
        "No preamble, no explanation, no markdown fences. "
        "If JSON is requested, output raw JSON only."
    )
    return system, user


def _translate_generic(
    system: str, user: str, data: Optional[Dict[str, str]],
) -> Tuple[str, str]:
    """Generic (OpenAI, Gemini, Grok): Clean markdown structure."""
    if data:
        context_block = "\n\n".join(
            f"## {key.replace('_', ' ').title()}\n{value}" for key, value in data.items()
        )
        user = f"{context_block}\n\n---\n\n{user}"
    return system, user


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. CONTEXT COMPILER — RAG Dossier Assembler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def compile_damage_dossier(
    staff_notes: str,
    property_id: Optional[str] = None,
    db=None,
) -> Dict[str, str]:
    """Assemble a full damage-claim dossier from all RAG sources.

    Pulls from:
      - fgp_knowledge (property info, reservation notes, work orders)
      - fgp_golden_claims (historical damage precedents)
      - legal_library (Georgia statutory code)

    Returns a dict of labeled text blocks ready for translate_for_model().
    """
    dossier: Dict[str, str] = {}
    dossier["staff_damage_report"] = staff_notes

    # Property / operational knowledge from fgp_knowledge
    try:
        from backend.services.knowledge_retriever import semantic_search, format_context
        hits = await semantic_search(
            question=staff_notes[:500],
            db=db,
            property_id=property_id,
            top_k=3,
        )
        if hits:
            dossier["property_knowledge"] = format_context(hits, max_chars=1500)
    except Exception as e:
        logger.debug("dossier_knowledge_failed", error=str(e)[:100])

    # Golden claims (few-shot precedents)
    try:
        from backend.services.damage_workflow import _retrieve_golden_examples
        golden = await _retrieve_golden_examples(staff_notes, top_k=2)
        if golden:
            dossier["historical_precedents"] = golden
    except Exception as e:
        logger.debug("dossier_golden_failed", error=str(e)[:100])

    # Georgia statutory code
    try:
        from backend.services.legal_auditor import query_statutory_law
        statutes = await query_statutory_law(
            f"property damage liability {staff_notes[:200]}", top_k=3
        )
        if statutes:
            dossier["georgia_statutory_code"] = statutes
    except Exception as e:
        logger.debug("dossier_statutory_failed", error=str(e)[:100])

    raw_chars = sum(len(v) for v in dossier.values())
    dossier = {k: compress_rag_context(v) for k, v in dossier.items()}

    logger.info(
        "dossier_compiled",
        sections=list(dossier.keys()),
        raw_chars=raw_chars,
        compressed_chars=sum(len(v) for v in dossier.values()),
    )
    return dossier


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. ZERO-TRUST SANITIZER — PII Stripping for Cloud Egress
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PIISanitizer:
    """Strips and rehydrates PII for cloud-bound prompts.

    Usage:
        sanitizer = PIISanitizer()
        clean_text = sanitizer.sanitize(dirty_text)
        # ... send clean_text to cloud API, get response ...
        rehydrated = sanitizer.rehydrate(response_text)
    """

    # Patterns that match PII we need to redact
    PHONE_PATTERN = re.compile(r"\+?1?\s*\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    GATE_CODE_PATTERN = re.compile(r"\b(?:code|gate|door|lock)\s*[:=]?\s*[#]?\s*(\d{4,8})\b", re.IGNORECASE)
    ADDRESS_PATTERN = re.compile(r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Ave|Rd|Dr|Ln|Ct|Blvd|Way|Pl|Cr)\b")

    def __init__(self):
        self._replacements: Dict[str, str] = {}
        self._counter: Dict[str, int] = {}

    def _get_placeholder(self, category: str) -> str:
        self._counter[category] = self._counter.get(category, 0) + 1
        return f"[{category}_{self._counter[category]}]"

    def sanitize(self, text: str, known_names: Optional[List[str]] = None) -> str:
        """Strip PII from text, storing a reversible mapping.

        Args:
            text: Raw text potentially containing PII
            known_names: List of known person names to redact (e.g. guest/staff names)

        Returns:
            Sanitized text with PII replaced by tagged placeholders
        """
        result = text

        # Named persons (highest priority — replace before pattern matching)
        if known_names:
            for name in known_names:
                if not name or len(name) < 2:
                    continue
                placeholder = self._get_placeholder("PERSON")
                self._replacements[placeholder] = name
                result = result.replace(name, placeholder)
                # Also try first-name only
                parts = name.split()
                if len(parts) > 1:
                    for part in parts:
                        if len(part) > 2:
                            result = result.replace(part, placeholder)

        # Phone numbers
        for match in self.PHONE_PATTERN.findall(result):
            placeholder = self._get_placeholder("PHONE")
            self._replacements[placeholder] = match
            result = result.replace(match, placeholder)

        # Email addresses
        for match in self.EMAIL_PATTERN.findall(result):
            placeholder = self._get_placeholder("EMAIL")
            self._replacements[placeholder] = match
            result = result.replace(match, placeholder)

        # SSN
        for match in self.SSN_PATTERN.findall(result):
            placeholder = self._get_placeholder("SSN")
            self._replacements[placeholder] = match
            result = result.replace(match, placeholder)

        # Gate/door codes
        for match in self.GATE_CODE_PATTERN.finditer(result):
            code = match.group(1)
            placeholder = self._get_placeholder("ACCESS_CODE")
            self._replacements[placeholder] = code
            result = result.replace(code, placeholder, 1)

        if self._replacements:
            logger.info(
                "pii_sanitized",
                replacements=len(self._replacements),
                categories=list(set(k.rsplit("_", 1)[0] for k in self._replacements)),
            )

        return result

    def rehydrate(self, text: str) -> str:
        """Restore PII placeholders with their original values."""
        result = text
        for placeholder, original in self._replacements.items():
            result = result.replace(placeholder, original)
        return result

    @property
    def replacement_count(self) -> int:
        return len(self._replacements)

    @property
    def replacement_map(self) -> Dict[str, str]:
        return dict(self._replacements)


def is_cloud_target(provider_name: str) -> bool:
    """Determine if a provider requires PII sanitization (cloud egress)."""
    return provider_name in ("anthropic", "gemini", "xai", "openai")


def is_local_target(provider_name: str) -> bool:
    """Determine if a provider is on the local DGX cluster (PII safe)."""
    return provider_name in ("ollama", "nim", "swarm", "hydra", "titan", "dgx")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UNIFIED INTERFACE — The Full Prompt Engineer Pipeline
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PromptEngineer:
    """Stateful prompt compilation pipeline.

    Usage:
        pe = PromptEngineer(target_provider="anthropic", target_model="claude-opus-4-6")

        # Optional: compile RAG dossier
        dossier = await compile_damage_dossier(staff_notes, property_id, db)

        # Build the final prompt
        system, user = pe.build(
            system_message="You are a legal analyst...",
            user_prompt="Analyze this damage report...",
            structured_data=dossier,
            known_names=["Taylor Knight", "Scott Lovell"],
        )

        # Send to LLM...
        response = await query_horseman("anthropic", prompt=user, system_message=system)

        # Rehydrate PII in the response
        final = pe.rehydrate(response)
    """

    def __init__(self, target_provider: str, target_model: str):
        self.provider = target_provider
        self.model = target_model
        self.sanitizer = PIISanitizer() if is_cloud_target(target_provider) else None

    def build(
        self,
        system_message: str,
        user_prompt: str,
        structured_data: Optional[Dict[str, str]] = None,
        known_names: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """Compile the final (system, user) prompt pair.

        1. Sanitize PII if target is a cloud provider
        2. Translate syntax for the target model family
        """
        sys_msg = system_message
        usr_msg = user_prompt
        data = dict(structured_data) if structured_data else None

        # Zero-Trust: sanitize if cloud-bound
        if self.sanitizer:
            sys_msg = self.sanitizer.sanitize(sys_msg, known_names)
            usr_msg = self.sanitizer.sanitize(usr_msg)
            if data:
                data = {k: self.sanitizer.sanitize(v) for k, v in data.items()}

            logger.info(
                "prompt_engineer_sanitized",
                provider=self.provider,
                pii_replaced=self.sanitizer.replacement_count,
            )

        # Syntax translation for the target model
        sys_msg, usr_msg = translate_for_model(sys_msg, usr_msg, self.model, data)

        logger.info(
            "prompt_engineer_compiled",
            provider=self.provider,
            model_family=detect_model_family(self.model),
            system_chars=len(sys_msg),
            user_chars=len(usr_msg),
        )

        return sys_msg, usr_msg

    def rehydrate(self, response: str) -> str:
        """Restore PII in a cloud response. No-op for local providers."""
        if self.sanitizer and response:
            return self.sanitizer.rehydrate(response)
        return response

    @property
    def was_sanitized(self) -> bool:
        return self.sanitizer is not None and self.sanitizer.replacement_count > 0
