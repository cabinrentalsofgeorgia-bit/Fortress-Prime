"""Read-only operational memory registry loader.

Operational memory is metadata-only. It is not legal authority, does not record
counsel signoff, and must not contain document body text, secrets, or locked
content.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED_MATTER_SLUG = "fortress-legal-production-review"

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "operational-memory" / "registries"

REGISTRY_FILES = {
    "operational_state": "operational-state.json",
    "capabilities": "capability-registry.json",
    "governance": "governance-registry.json",
    "evidence": "evidence-registry.json",
    "remediation": "remediation-registry.json",
    "reviewer_feedback_ledger": "reviewer-feedback-ledger.json",
    "wiki_knowledge_index": "wiki-knowledge-index.json",
    "validation_report": "validation-report.json",
}


def _load_json(filename: str) -> dict[str, Any]:
    path = REGISTRY_DIR / filename
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"registry_not_object:{filename}")
    return payload


def load_operational_memory(slug: str) -> dict[str, Any] | None:
    if slug != SUPPORTED_MATTER_SLUG:
        raise ValueError("operational_memory_scope_refused")
    if not REGISTRY_DIR.exists():
        return None

    registries = {name: _load_json(filename) for name, filename in REGISTRY_FILES.items()}
    state = registries["operational_state"]
    capabilities = registries["capabilities"].get("capabilities", [])
    evidence_dirs = registries["evidence"].get("evidenceDirectories", [])
    wiki_entries = registries["wiki_knowledge_index"].get("entries", [])
    ledger_entries = registries["reviewer_feedback_ledger"].get("entries", [])

    return {
        "schemaVersion": "1.0.0",
        "matterSlug": slug,
        "status": "OPERATIONAL_MEMORY_VISIBLE_READ_ONLY",
        "standingLabels": state.get("standingLabels", {}),
        "governanceBoundaries": state.get("governanceBoundaries", []),
        "validationStatus": {
            **state.get("validationStatus", {}),
            "operationalMemory": "VISIBLE_READ_ONLY",
            "registryValidation": registries["validation_report"].get("ok", False),
        },
        "summary": {
            "capabilityCount": len(capabilities),
            "evidenceDirectoryCount": len(evidence_dirs),
            "wikiKnowledgeEntries": len(wiki_entries),
            "reviewerFeedbackEntries": len(ledger_entries),
            "unresolvedSourceIssues": registries["remediation"].get("unresolvedSourceIssues"),
            "reviewerLedgerMode": registries["reviewer_feedback_ledger"].get("validationStatus", {}).get("status"),
        },
        "registries": registries,
        "negativeControls": {
            "noSecrets": all(registry.get("noSecrets") is True for registry in registries.values()),
            "noConfidentialText": all(registry.get("noConfidentialText") is True for registry in registries.values()),
            "noCounselSignoffAuthority": True,
            "noFinalLegalConclusionAuthority": True,
            "noExternalSubmissionAuthority": True,
            "noSourcePromotion": True,
            "noSchemaRlsPolicyMutation": True,
            "readOnly": True,
        },
    }
