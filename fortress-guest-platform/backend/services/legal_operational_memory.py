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
GRAPH_DIR = ROOT / "operational-memory" / "graph"
QUERY_DIR = ROOT / "operational-memory" / "queries"
AGENT_CONTEXT_DIR = ROOT / "operational-memory" / "agent-context"
CONTEXT_PACK_DIR = ROOT / "operational-memory" / "context-packs"

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


def _load_graph_json(filename: str) -> dict[str, Any] | None:
    path = GRAPH_DIR / filename
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"graph_not_object:{filename}")
    return payload


def _load_optional_json(directory: Path, filename: str) -> dict[str, Any] | None:
    path = directory / filename
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"optional_json_not_object:{filename}")
    return payload


def load_operational_memory(slug: str) -> dict[str, Any] | None:
    if slug != SUPPORTED_MATTER_SLUG:
        raise ValueError("operational_memory_scope_refused")
    if not REGISTRY_DIR.exists():
        return None

    registries = {name: _load_json(filename) for name, filename in REGISTRY_FILES.items()}
    graph = _load_graph_json("graph.json")
    graph_validation = _load_graph_json("graph-validation-report.json")
    wiki_graph = _load_graph_json("wiki-graph-index.json")
    evidence_graph = _load_graph_json("evidence-graph-index.json")
    query_taxonomy = _load_optional_json(QUERY_DIR, "query-taxonomy.json")
    agent_context = _load_optional_json(AGENT_CONTEXT_DIR, "current-agent-context.json")
    context_pack_files = sorted(CONTEXT_PACK_DIR.glob("*.json")) if CONTEXT_PACK_DIR.exists() else []
    context_packs = []
    for path in context_pack_files:
        payload = _load_optional_json(CONTEXT_PACK_DIR, path.name)
        if payload:
            context_packs.append(
                {
                    "contextPackType": payload.get("contextPackType"),
                    "standingLabels": payload.get("standingLabels", {}),
                    "readFirst": payload.get("readFirst", [])[:8],
                    "safeNextActions": payload.get("safeNextActions", [])[:5],
                    "forbiddenActionCount": len(payload.get("forbiddenActions", [])),
                    "noSecrets": payload.get("noSecrets") is True,
                    "noConfidentialText": payload.get("noConfidentialText") is True,
                }
            )
    state = registries["operational_state"]
    capabilities = registries["capabilities"].get("capabilities", [])
    evidence_dirs = registries["evidence"].get("evidenceDirectories", [])
    wiki_entries = registries["wiki_knowledge_index"].get("entries", [])
    ledger_entries = registries["reviewer_feedback_ledger"].get("entries", [])
    graph_nodes = graph.get("nodes", []) if graph else []
    graph_edges = graph.get("edges", []) if graph else []

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
            "graphNodeCount": len(graph_nodes),
            "graphEdgeCount": len(graph_edges),
            "graphValidationOk": graph_validation.get("ok", False) if graph_validation else False,
            "governanceQueryCount": len(query_taxonomy.get("queries", [])) if query_taxonomy else 0,
            "contextPackCount": len(context_packs),
        },
        "registries": registries,
        "graph": {
            "status": "OPERATIONAL_GRAPH_VISIBLE_READ_ONLY" if graph else "OPERATIONAL_GRAPH_NOT_AVAILABLE",
            "summary": {
                "nodeCount": len(graph_nodes),
                "edgeCount": len(graph_edges),
                "governanceNodes": len([node for node in graph_nodes if node.get("type") == "governance_boundary"]),
                "remediationNodes": len(
                    [
                        node
                        for node in graph_nodes
                        if node.get("type") in {"remediation_issue", "contradiction_cluster", "review_queue"}
                    ]
                ),
                "evidenceNodes": len([node for node in graph_nodes if node.get("type") == "evidence_bundle"]),
                "deploymentNodes": len(
                    [node for node in graph_nodes if node.get("type") in {"deployment", "rollback_event"}]
                ),
                "wikiGraphNodes": len(wiki_graph.get("nodes", [])) if wiki_graph else 0,
                "evidenceGraphNodes": len(evidence_graph.get("nodes", [])) if evidence_graph else 0,
            },
            "nodes": graph_nodes[:20],
            "edges": graph_edges[:30],
            "validation": graph_validation,
            "wikiGraphIndex": wiki_graph,
            "evidenceGraphIndex": evidence_graph,
        },
        "governanceQueryEngine": {
            "status": "GOVERNANCE_QUERY_ENGINE_VISIBLE_READ_ONLY" if query_taxonomy else "GOVERNANCE_QUERY_ENGINE_NOT_AVAILABLE",
            "queryCount": len(query_taxonomy.get("queries", [])) if query_taxonomy else 0,
            "queries": query_taxonomy.get("queries", []) if query_taxonomy else [],
            "safeNextActions": (
                agent_context.get("safeNextActions", [])[:5]
                if agent_context
                else [
                    {
                        "action": "Review operational graph and query engine evidence",
                        "humanReviewRequired": True,
                    }
                ]
            ),
            "forbiddenOperations": governance.get("forbiddenOperations", []),
            "signoffBlockers": [
                "COUNSEL_SIGNOFF_PENDING",
                "232_unresolved_source_issues_excluded",
                "human_review_required",
            ],
            "launchBlockers": [
                "NOT_AUTHORIZED",
                "public_launch_forbidden",
                "external_legal_operations_forbidden",
            ],
            "agentContext": agent_context,
            "contextPacks": context_packs,
        },
        "negativeControls": {
            "noSecrets": all(registry.get("noSecrets") is True for registry in registries.values()),
            "noConfidentialText": all(registry.get("noConfidentialText") is True for registry in registries.values()),
            "noCounselSignoffAuthority": True,
            "noFinalLegalConclusionAuthority": True,
            "noExternalSubmissionAuthority": True,
            "noSourcePromotion": True,
            "noSchemaRlsPolicyMutation": True,
            "noGraphLegalAuthority": True,
            "noQueryEngineLegalAuthority": True,
            "readOnly": True,
        },
    }
