"""Counsel signoff decision workflow artifact store.

This workflow adds explicit decision controls for the limited signoff
candidate packet. It does not infer signoff, read document bodies, inspect
locked content, mutate schema/RLS, create vectors, or authorize external use.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_counsel_workbench import AUDIT_DIR
from backend.services.legal_limited_signoff_candidate_packet import load_latest_limited_signoff_candidate

DECISION_PREFIX = "fortress-signoff-decision-"

ALLOWED_DECISION_TYPES = {
    "operator_review_acknowledgment",
    "counsel_review_acknowledgment",
    "counsel_approved_for_internal_review_use",
    "counsel_approved_limited_subset_for_review_use",
    "counsel_approved_specific_sections_for_review_use",
    "counsel_rejected_packet",
    "counsel_requested_revisions",
    "counsel_returned_items_to_source_remediation",
    "signoff_deferred",
    "decision_recorded_no_signoff",
}

SIGNOFF_DECISION_TYPES = {
    "counsel_approved_for_internal_review_use",
    "counsel_approved_limited_subset_for_review_use",
    "counsel_approved_specific_sections_for_review_use",
}

FORBIDDEN_DECISION_TYPES = {
    "final_legal_conclusion",
    "authorized_for_filing",
    "authorized_for_service",
    "authorized_for_external_submission",
    "unrestricted_production_legal_approval",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    candidate = packet.get("limited_signoff_candidate_packet", {})
    rollback = packet.get("rollback", {})
    return {
        "packet_execution_id": packet.get("execution_id"),
        "packet_version": int(packet.get("packet_version") or 1),
        "packet_hash": packet.get("manifest_checksum") or packet.get("packet_checksum"),
        "included_verified_subset": candidate.get("included_item_count", 0),
        "excluded_unresolved_items": candidate.get("excluded_item_count", 0),
        "source_verified_subset_count": packet.get("verified_subset_used", {}).get("item_count", 0),
        "unresolved_source_issue_count": packet.get("signoff_readiness_addendum", {}).get("remaining_unresolved", 0),
        "locked_restricted_count": packet.get("tier_summary", {}).get("locked_privilege_limited", 0),
        "rollback_packet_item_ids": rollback.get("limited_signoff_item_ids", []),
        "rollback_excluded_register_ids": rollback.get("excluded_register_ids", []),
        "manifest_path": packet.get("manifest_path"),
    }


def create_decision_workflow_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("decision_workflow_scope_refused")
    packet = load_latest_limited_signoff_candidate(case_slug)
    if packet is None:
        raise FileNotFoundError("limited_signoff_candidate_missing")

    packet_summary = _packet_summary(packet)
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "decision_store": "file_manifest",
        "status": "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
        "counsel_status": "COUNSEL_SIGNOFF_PENDING",
        "product_status": "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
        "packet": packet_summary,
        "decision_readiness": {
            "decision_panel_visible": True,
            "packet_checksum_required": True,
            "explicit_scope_confirmation_required": True,
            "unresolved_exclusions_acknowledgment_required": True,
            "privilege_handling_acknowledgment_required": True,
            "no_external_submission_authority_acknowledgment_required": True,
            "auto_signoff_prevented": True,
            "external_submission_authority_available": False,
            "final_legal_conclusion_available": False,
        },
        "decision_paths": [
            {
                "decision_type": "operator_review_acknowledgment",
                "label": "Operator acknowledgment only",
                "records_counsel_signoff": False,
                "resulting_counsel_status": "COUNSEL_SIGNOFF_PENDING",
            },
            {
                "decision_type": "counsel_approved_for_internal_review_use",
                "label": "Counsel approves limited packet for internal review use",
                "records_counsel_signoff": True,
                "resulting_counsel_status": "COUNSEL_SIGNOFF_RECORDED_FOR_APPROVED_REVIEW_SCOPE",
            },
            {
                "decision_type": "counsel_approved_specific_sections_for_review_use",
                "label": "Counsel approves selected sections/items only",
                "records_counsel_signoff": True,
                "resulting_counsel_status": "PARTIAL_COUNSEL_SIGNOFF_RECORDED_REMAINDER_PENDING",
            },
            {
                "decision_type": "counsel_rejected_packet",
                "label": "Counsel rejects packet",
                "records_counsel_signoff": False,
                "resulting_counsel_status": "COUNSEL_REVIEW_IN_PROGRESS",
            },
            {
                "decision_type": "counsel_requested_revisions",
                "label": "Counsel requests revisions",
                "records_counsel_signoff": False,
                "resulting_counsel_status": "COUNSEL_REVIEW_IN_PROGRESS",
            },
            {
                "decision_type": "counsel_returned_items_to_source_remediation",
                "label": "Return items to source remediation",
                "records_counsel_signoff": False,
                "resulting_counsel_status": "COUNSEL_SIGNOFF_PENDING",
            },
            {
                "decision_type": "signoff_deferred",
                "label": "Defer signoff",
                "records_counsel_signoff": False,
                "resulting_counsel_status": "COUNSEL_SIGNOFF_PENDING",
            },
        ],
        "explicit_confirmation_checklist": [
            "I confirm I am deciding only for the selected approved review scope.",
            "I understand unresolved items remain excluded.",
            "I understand locked/restricted documents remain metadata-only.",
            "I understand this does not authorize filing, service, sending, or external submission.",
            "I understand this does not create unrestricted legal production approval.",
        ],
        "decision_records": [],
        "revision_requests": [],
        "source_remediation_returns": [],
        "audit_history": [
            {
                "audit_id": str(uuid4()),
                "action": "decision_workflow_initialized",
                "created_at": now_iso(),
                "reviewer_identity_safe_label": "system:signoff-decision-workflow",
                "reviewer_role": "system",
            }
        ],
        "rollback": {
            "delete_manifest_path": str(decision_manifest_path(execution_id)),
            "decision_record_ids": [],
            "revision_request_ids": [],
            "source_remediation_return_ids": [],
            "raw_documents_touched": False,
            "qdrant_vectors_touched": False,
            "schema_changed": False,
            "rls_policy_changed": False,
            "signoff_auto_created": False,
        },
        "mutation_invariants": {
            "new_raw_document_upload": False,
            "new_ingest": False,
            "new_document_rows": False,
            "new_qdrant_document_vectors": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
            "signoff_auto_created": False,
            "explicit_signoff_recorded": False,
            "external_submission_authorized": False,
            "final_legal_conclusions_created": False,
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_decision_workflow_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = decision_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _decision_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{DECISION_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_decision_workflow(case_slug: str) -> dict[str, Any] | None:
    for path in _decision_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None


def _require_confirmations(
    *,
    decision_type: str,
    explicit_scope_confirmed: bool,
    unresolved_exclusions_acknowledged: bool,
    privilege_handling_acknowledged: bool,
    no_external_submission_authority_acknowledged: bool,
) -> None:
    if decision_type not in SIGNOFF_DECISION_TYPES:
        return
    if not explicit_scope_confirmed:
        raise ValueError("explicit_scope_confirmation_required")
    if not unresolved_exclusions_acknowledged:
        raise ValueError("unresolved_exclusions_acknowledgment_required")
    if not privilege_handling_acknowledged:
        raise ValueError("privilege_handling_acknowledgment_required")
    if not no_external_submission_authority_acknowledged:
        raise ValueError("no_external_submission_authority_acknowledgment_required")


def _status_after(decision_type: str) -> tuple[str, str, str]:
    if decision_type == "operator_review_acknowledgment":
        return (
            "OPERATOR_ACKNOWLEDGED_COUNSEL_SIGNOFF_PENDING",
            "OPERATOR_ACKNOWLEDGED_PACKET_READY_FOR_COUNSEL",
            "COUNSEL_SIGNOFF_PENDING",
        )
    if decision_type == "counsel_approved_for_internal_review_use":
        return (
            "COUNSEL_SIGNOFF_RECORDED_FOR_LIMITED_REVIEW_USE",
            "LIMITED_PACKET_SIGNED_OFF_FOR_APPROVED_REVIEW_SCOPE",
            "COUNSEL_SIGNOFF_RECORDED_FOR_APPROVED_REVIEW_SCOPE",
        )
    if decision_type == "counsel_approved_limited_subset_for_review_use":
        return (
            "COUNSEL_SIGNOFF_RECORDED_FOR_LIMITED_REVIEW_USE",
            "LIMITED_PACKET_SIGNED_OFF_FOR_APPROVED_REVIEW_SCOPE",
            "COUNSEL_SIGNOFF_RECORDED_FOR_APPROVED_REVIEW_SCOPE",
        )
    if decision_type == "counsel_approved_specific_sections_for_review_use":
        return (
            "PARTIAL_COUNSEL_SIGNOFF_RECORDED",
            "PARTIAL_LIMITED_PACKET_SIGNOFF_RECORDED_REMAINDER_PENDING",
            "PARTIAL_COUNSEL_SIGNOFF_RECORDED_REMAINDER_PENDING",
        )
    if decision_type == "counsel_rejected_packet":
        return ("COUNSEL_REJECTED_PACKET_REVISIONS_REQUIRED", "LIMITED_PACKET_REJECTED_REVISIONS_REQUIRED", "COUNSEL_REVIEW_IN_PROGRESS")
    if decision_type == "counsel_requested_revisions":
        return ("COUNSEL_REVISIONS_REQUESTED", "SIGNOFF_PACKET_REVISIONS_REQUESTED", "COUNSEL_REVIEW_IN_PROGRESS")
    if decision_type == "counsel_returned_items_to_source_remediation":
        return ("RETURNED_TO_SOURCE_REMEDIATION", "SOURCE_REMEDIATION_REQUIRED_FOR_RETURNED_ITEMS", "COUNSEL_SIGNOFF_PENDING")
    return ("COUNSEL_SIGNOFF_DEFERRED", "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY", "COUNSEL_SIGNOFF_PENDING")


def record_decision(
    case_slug: str,
    *,
    decision_type: str,
    decision_scope: str,
    item_ids_or_section_ids: list[str],
    signer_safe_label: str,
    signer_role: str,
    signer_affiliation: str | None,
    explicit_scope_confirmed: bool,
    unresolved_exclusions_acknowledged: bool,
    privilege_handling_acknowledged: bool,
    no_external_submission_authority_acknowledged: bool,
    decision_notes: str | None,
    revision_requests: list[str],
    source_remediation_returns: list[str],
) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("decision_scope_refused")
    if decision_type in FORBIDDEN_DECISION_TYPES or decision_type not in ALLOWED_DECISION_TYPES:
        raise ValueError("decision_type_not_allowed")
    _require_confirmations(
        decision_type=decision_type,
        explicit_scope_confirmed=explicit_scope_confirmed,
        unresolved_exclusions_acknowledged=unresolved_exclusions_acknowledged,
        privilege_handling_acknowledged=privilege_handling_acknowledged,
        no_external_submission_authority_acknowledged=no_external_submission_authority_acknowledged,
    )
    payload = load_latest_decision_workflow(case_slug)
    if payload is None:
        raise FileNotFoundError("decision_workflow_missing")

    status_before = payload.get("status")
    status_after, product_status, counsel_status = _status_after(decision_type)
    decision_id = str(uuid4())
    record = {
        "decision_id": decision_id,
        "decision_execution_id": payload["execution_id"],
        "matter_slug": case_slug,
        "packet_execution_id": payload["packet"]["packet_execution_id"],
        "packet_version": payload["packet"]["packet_version"],
        "packet_hash": payload["packet"]["packet_hash"],
        "decision_type": decision_type,
        "decision_scope": decision_scope,
        "item_ids_or_section_ids": item_ids_or_section_ids,
        "signer_safe_label": signer_safe_label,
        "signer_role": signer_role,
        "signer_affiliation": signer_affiliation,
        "signed_or_decided_at": now_iso(),
        "explicit_scope_confirmed": explicit_scope_confirmed,
        "unresolved_exclusions_acknowledged": unresolved_exclusions_acknowledged,
        "privilege_handling_acknowledged": privilege_handling_acknowledged,
        "no_external_submission_authority_acknowledged": no_external_submission_authority_acknowledged,
        "counsel_review_required": True,
        "decision_notes": decision_notes,
        "revision_requests": revision_requests,
        "source_remediation_returns": source_remediation_returns,
        "status_before": status_before,
        "status_after": status_after,
        "supersedes_decision_id": None,
        "rollback_ref": f"{payload['execution_id']}:{decision_id}",
        "external_submission_authorized": False,
        "final_legal_conclusion_created": False,
    }
    record["audit_hash"] = _json_hash(record)
    payload.setdefault("decision_records", []).append(record)
    payload["status"] = status_after
    payload["product_status"] = product_status
    payload["counsel_status"] = counsel_status
    payload["rollback"]["decision_record_ids"].append(decision_id)
    if revision_requests:
        request_id = str(uuid4())
        payload.setdefault("revision_requests", []).append(
            {"revision_request_id": request_id, "decision_id": decision_id, "items": revision_requests}
        )
        payload["rollback"]["revision_request_ids"].append(request_id)
    if source_remediation_returns:
        return_id = str(uuid4())
        payload.setdefault("source_remediation_returns", []).append(
            {"source_remediation_return_id": return_id, "decision_id": decision_id, "items": source_remediation_returns}
        )
        payload["rollback"]["source_remediation_return_ids"].append(return_id)
    payload.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": f"decision_recorded:{decision_type}",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": signer_safe_label,
            "reviewer_role": signer_role,
            "decision_id": decision_id,
            "audit_hash": _json_hash({"decision_id": decision_id, "decision_type": decision_type}),
        }
    )
    payload["mutation_invariants"]["explicit_signoff_recorded"] = decision_type in SIGNOFF_DECISION_TYPES
    payload["manifest_checksum"] = _json_hash({k: v for k, v in payload.items() if k != "manifest_checksum"})
    write_decision_workflow_manifest(payload)
    payload["latest_decision"] = record
    return payload
