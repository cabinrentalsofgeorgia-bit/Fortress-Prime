"""
Privilege filter for training capture routing.

Invoked at every capture write site to classify content by sensitivity.
Routes to one of: llm_training_captures (training set),
restricted_captures (retained but excluded from training), or BLOCK.

Phase 2 of Iron Dome architecture. Must ship before
nightly_distillation_exporter is enabled, otherwise privileged legal
content accumulates in training set.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CaptureRoute(str, Enum):
    """Where to route a capture."""
    ALLOW = "allow"
    RESTRICTED = "restricted"
    BLOCK = "block"


@dataclass(frozen=True)
class CaptureDecision:
    """Filter decision with audit trail."""
    route: CaptureRoute
    reason: str
    matched_patterns: tuple[str, ...] = ()


LEGAL_PERSONAS: frozenset[str] = frozenset({
    "senior_litigator",
    "contract_auditor",
    "statutory_scholar",
    "ediscovery_forensic",
    "devils_advocate",
    "compliance_officer",
    "local_counsel",
    "risk_assessor",
    "chief_justice",
})

PRIVILEGED_MODULES: frozenset[str] = frozenset({
    "legal_council",
    "ediscovery_agent",
    "legal_email_intake",
    "legal_intake",
})

PRIVILEGE_MARKERS: tuple[str, ...] = (
    "[PRIVILEGED]",
    "[ATTORNEY-CLIENT]",
    "[WORK PRODUCT]",
    "ATTORNEY-CLIENT PRIVILEGED",
    "ATTORNEY WORK PRODUCT",
)

BLOCK_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("bank_routing", re.compile(r"\b\d{9}\b(?=.*(?:routing|aba))", re.IGNORECASE)),
)


def classify_for_capture(
    prompt: str,
    response: str,
    source_persona: str | None = None,
    source_module: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CaptureDecision:
    """
    Classify a capture for routing.

    Called at every write site to llm_training_captures. Defaults to
    RESTRICTED on any signal of privilege — training set is conservative.
    """
    metadata = metadata or {}

    override = metadata.get("restriction_override")
    if override in {CaptureRoute.ALLOW.value, CaptureRoute.RESTRICTED.value, CaptureRoute.BLOCK.value}:
        logger.warning(
            "privilege_filter.override route=%s persona=%s module=%s",
            override, source_persona, source_module,
        )
        return CaptureDecision(
            route=CaptureRoute(override),
            reason="admin_override",
        )

    block_matches: list[str] = []
    combined_text = f"{prompt}\n{response}"
    for pattern_name, pattern in BLOCK_PATTERNS:
        if pattern.search(combined_text):
            block_matches.append(pattern_name)

    if block_matches:
        logger.info(
            "privilege_filter.block patterns=%s persona=%s module=%s",
            block_matches, source_persona, source_module,
        )
        return CaptureDecision(
            route=CaptureRoute.BLOCK,
            reason="pii_pattern_matched",
            matched_patterns=tuple(block_matches),
        )

    restrict_reasons: list[str] = []

    if source_persona and source_persona in LEGAL_PERSONAS:
        restrict_reasons.append(f"legal_persona:{source_persona}")

    if source_module and source_module in PRIVILEGED_MODULES:
        restrict_reasons.append(f"privileged_module:{source_module}")

    if metadata.get("privilege_marker"):
        restrict_reasons.append("metadata_privilege_marker")

    for marker in PRIVILEGE_MARKERS:
        if marker in prompt or marker in response:
            restrict_reasons.append(f"text_marker:{marker}")
            break

    if restrict_reasons:
        return CaptureDecision(
            route=CaptureRoute.RESTRICTED,
            reason="|".join(restrict_reasons),
            matched_patterns=tuple(restrict_reasons),
        )

    return CaptureDecision(
        route=CaptureRoute.ALLOW,
        reason="no_privilege_signal",
    )


# ---------------------------------------------------------------------------
# Training contamination detection
# ---------------------------------------------------------------------------

# Matches the Feb 2026 concierge ASSESSMENT block separator pattern:
#   \n---\n\n**ASSESSMENT**
_ASSESSMENT_BLOCK_RE: re.Pattern = re.compile(
    r"\n---\n\n\*\*ASSESSMENT\*\*",
    re.IGNORECASE,
)

# Individual internal metadata markers from the same prompt era.
# Checked as a fallback if the full separator pattern is absent.
_INTERNAL_METADATA_MARKERS: tuple[str, ...] = (
    "**ASSESSMENT**",
    "**Risk Level:**",
    "**Strategy Type:**",
    "**Citations Used:**",
)


def check_training_contamination(prompt: str, response: str) -> tuple[bool, str]:
    """
    Detect internal metadata leaked into a stored LLM response.

    Returns (is_contaminated, reason). Never raises.

    Defense-in-depth against the Feb 2026 vrs_concierge defect: the system
    prompt asked the model to produce a guest-facing response followed by a
    '---' separator and an internal **ASSESSMENT** block (Risk Level /
    Strategy Type / Citations Used). The prompt was fixed in Iron Dome
    (2026-03-01). This check catches recurrence or similar patterns.

    The `prompt` argument is accepted for API symmetry with classify_for_capture
    but is not currently inspected — contamination lives in the response.
    """
    try:
        if _ASSESSMENT_BLOCK_RE.search(response):
            return True, "assessment_block_separator"
        for marker in _INTERNAL_METADATA_MARKERS:
            if marker in response:
                tag = marker.strip("*").strip().lower().replace(" ", "_").rstrip(":")
                return True, f"internal_metadata_marker:{tag}"
    except Exception:
        pass
    return False, ""
