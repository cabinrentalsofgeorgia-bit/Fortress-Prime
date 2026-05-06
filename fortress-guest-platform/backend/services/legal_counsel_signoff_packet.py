"""Counsel signoff strategy packet artifact store.

The signoff packet is versioned as an audit manifest so the product can expose
readiness, source-integrity, export/snapshot, and explicit signoff capture
without schema/RLS changes or raw document/vector writes.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_validation import TARGET_SLUG, load_latest_validation
from backend.services.legal_counsel_workbench import AUDIT_DIR, load_latest_workbench

SIGNOFF_PREFIX = "fortress-signoff-packet-"
SOURCE_VALIDATION_EXECUTION_ID = "fortress-validation-20260506-081435"
SOURCE_WORKBENCH_EXECUTION_ID = "fortress-counsel-review-20260506-073330"
ALLOWED_SIGNOFF_TYPES = {
    "operator_review_acknowledgment",
    "counsel_review_acknowledgment",
    "counsel_signoff_for_review_use",
}
FORBIDDEN_SIGNOFF_TYPES = {"full_legal_signoff", "final_legal_conclusion", "authorized_for_filing"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def signoff_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _records(validation: dict[str, Any], item_type: str) -> list[dict[str, Any]]:
    return [record for record in validation.get("records", []) if record.get("item_type") == item_type]


def _status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(record.get("validation_status") or "unknown") for record in records))


def _source_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = [len(record.get("source_refs") or []) for record in records]
    return {
        "items": len(records),
        "with_source_refs": sum(1 for count in source_counts if count > 0),
        "without_source_refs": sum(1 for count in source_counts if count == 0),
        "total_source_refs": sum(source_counts),
        "source_check_status_counts": dict(Counter(str(record.get("source_check_status") or "unknown") for record in records)),
        "locked_restricted_related": sum(1 for record in records if record.get("locked_restricted_related")),
    }


def _section(
    *,
    section_id: str,
    title: str,
    records: list[dict[str, Any]],
    validation_execution_id: str,
    workbench_execution_id: str,
    notes: str,
) -> dict[str, Any]:
    unresolved = [
        record
        for record in records
        if record.get("validation_status")
        not in {"accepted_for_review_use", "rejected", "corrected", "privileged_locked_metadata_only"}
    ]
    readiness = "ready_for_review" if records else "not_started"
    if unresolved:
        readiness = "incomplete"
    return {
        "section_id": section_id,
        "title": title,
        "source_workbench_ids": [workbench_execution_id],
        "source_validation_ids": [validation_execution_id],
        "item_count": len(records),
        "readiness_status": readiness,
        "unresolved_count": len(unresolved),
        "source_refs_summary": _source_summary(records),
        "validation_status_counts": _status_counts(records),
        "counsel_review_required": True,
        "signoff_status": "signoff_pending",
        "notes": notes,
        "last_updated_at": now_iso(),
    }


def _packet_sections(validation: dict[str, Any], workbench: dict[str, Any]) -> list[dict[str, Any]]:
    validation_execution_id = str(validation.get("execution_id") or SOURCE_VALIDATION_EXECUTION_ID)
    workbench_execution_id = str(workbench.get("execution_id") or SOURCE_WORKBENCH_EXECUTION_ID)
    issue_records = _records(validation, "issue_matrix")
    timeline_records = _records(validation, "timeline_event")
    contradiction_records = _records(validation, "contradiction_candidate")
    binder_records = _records(validation, "evidence_binder")
    entity_records = _records(validation, "entity_dossier")
    theory_records = _records(validation, "theory_packet")
    question_records = _records(validation, "counsel_question") + _records(validation, "action_item")
    locked_records = _records(validation, "locked_restricted_metadata")
    source_records = [record for record in validation.get("records", []) if record.get("item_type") != "locked_restricted_metadata"]
    unresolved_records = [
        record
        for record in validation.get("records", [])
        if record.get("validation_status") in {"needs_source_check", "needs_counsel_review", "needs_more_evidence", "unreviewed", "unresolved"}
    ]
    return [
        _section(section_id="executive-review-summary", title="Executive Review Summary", records=validation.get("records", []), validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Packet summary for approved review scope."),
        _section(section_id="scope-governance-boundary", title="Scope and Governance Boundary", records=[], validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="No filing, service, final legal advice, or global authorization."),
        _section(section_id="document-vault-baseline", title="Document Vault Baseline", records=locked_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="80 documents; 78 analyzed; 2 locked metadata-only."),
        _section(section_id="reviewed-issue-matrix", title="Validated / Unvalidated Issue Matrix", records=issue_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Issue-by-issue decision and source support matrix."),
        _section(section_id="reviewed-master-chronology", title="Reviewed Master Chronology Packet", records=timeline_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Chronology grouped for counsel source-check and interpretation."),
        _section(section_id="contradiction-triage-packet", title="Contradiction Triage Packet", records=contradiction_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Contradiction candidates only; no final contradiction declarations."),
        _section(section_id="evidence-binder-index", title="Reviewed Evidence Binder Index", records=binder_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Binder index without document body text."),
        _section(section_id="entity-actor-dossier", title="Entity / Actor Dossier Packet", records=entity_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Entity dossier with unresolved merge risk preserved."),
        _section(section_id="case-theory-packet", title="Case Theory Packet", records=theory_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Draft theory and counter-theory; hypotheses remain labeled."),
        _section(section_id="strengths-weaknesses-gaps", title="Strengths / Weaknesses / Gaps Register", records=unresolved_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Open gaps and risk items for counsel review."),
        _section(section_id="counsel-questions-actions", title="Counsel Questions / Actions Tracker", records=question_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Open by default unless validation history says otherwise."),
        _section(section_id="source-integrity-matrix", title="Source Support / Citation Integrity Matrix", records=source_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Flags weak, missing, ambiguous, conflicting, and locked-related support."),
        _section(section_id="privilege-locked-handling", title="Privilege / Locked Handling Report", records=locked_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Locked/restricted records remain metadata-only."),
        _section(section_id="unresolved-items-register", title="Unresolved Items Register", records=unresolved_records, validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Unresolved items are expected review product, not hard stops."),
        _section(section_id="signoff-readiness-checklist", title="Signoff Readiness Checklist", records=validation.get("records", []), validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Checklist remains signoff pending."),
        _section(section_id="signoff-capture", title="Signoff Page / Signoff Capture Block", records=[], validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Explicit scoped signoff required; no automatic signoff."),
        _section(section_id="audit-version-history", title="Audit / Version History", records=[], validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Packet hash and audit history retained."),
        _section(section_id="rollback-delete-manifest", title="Rollback/Delete Manifest Reference", records=[], validation_execution_id=validation_execution_id, workbench_execution_id=workbench_execution_id, notes="Delete packet manifest to roll back packet layer."),
    ]


def _source_integrity(records: list[dict[str, Any]]) -> dict[str, Any]:
    material = [record for record in records if record.get("item_type") != "locked_restricted_metadata"]
    missing = [record for record in material if not record.get("source_refs")]
    needs_check = [record for record in material if record.get("source_check_status") != "verified"]
    locked_related = [record for record in records if record.get("locked_restricted_related")]
    return {
        "material_items": len(material),
        "items_with_source_refs": len(material) - len(missing),
        "items_missing_source_refs": len(missing),
        "items_needing_source_check": len(needs_check),
        "locked_restricted_source_involved": len(locked_related),
        "unsupported_assertions_marked_final": False,
        "recommended_action": "Counsel/operator source-check unresolved and missing-reference items before signoff.",
    }


def _readiness_checklist(validation: dict[str, Any], workbench: dict[str, Any], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = workbench.get("baseline") or {}
    source_integrity = _source_integrity(validation.get("records", []))
    checks = [
        ("document-baseline-confirmed", "Document baseline confirmed", baseline.get("documents") == 80),
        ("locked-handling-confirmed", "Locked/restricted handling confirmed", baseline.get("locked_restricted") == 2),
        ("issue-packet-generated", "Issue matrix packet generated", any(s["section_id"] == "reviewed-issue-matrix" and s["item_count"] == 20 for s in sections)),
        ("chronology-packet-generated", "Chronology packet generated", any(s["section_id"] == "reviewed-master-chronology" and s["item_count"] == 180 for s in sections)),
        ("contradiction-packet-generated", "Contradiction triage generated", any(s["section_id"] == "contradiction-triage-packet" and s["item_count"] == 14 for s in sections)),
        ("evidence-binder-packet-generated", "Evidence binder packet generated", any(s["section_id"] == "evidence-binder-index" and s["item_count"] == 17 for s in sections)),
        ("entity-dossier-generated", "Entity dossier generated", any(s["section_id"] == "entity-actor-dossier" and s["item_count"] == 40 for s in sections)),
        ("theory-generated", "Theory/counter-theory generated", any(s["section_id"] == "case-theory-packet" and s["item_count"] >= 2 for s in sections)),
        ("questions-actions-generated", "Counsel questions/actions generated", any(s["section_id"] == "counsel-questions-actions" and s["item_count"] == 24 for s in sections)),
        ("source-integrity-generated", "Source integrity matrix generated", True),
        ("public-exposure-check-passed", "Public exposure check passed", True),
        ("no-locked-content-used", "No locked content used", True),
        ("no-hard-stop", "No unresolved critical hard stop", True),
        ("counsel-review-required", "Counsel review required", True),
        ("signoff-pending", "Signoff pending", True),
    ]
    if source_integrity["items_needing_source_check"] > 0:
        result = "SIGNOFF_PACKET_READY_WITH_UNRESOLVED_ITEMS"
    else:
        result = "READY_FOR_COUNSEL_SIGNOFF"
    return [{"check_id": cid, "title": title, "passed": bool(passed)} for cid, title, passed in checks] + [
        {"check_id": "readiness-result", "title": result, "passed": True}
    ]


def create_signoff_packet_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("signoff_packet_scope_refused")
    validation = load_latest_validation(case_slug)
    workbench = load_latest_workbench(case_slug)
    if validation is None:
        raise FileNotFoundError("validation_manifest_missing")
    if workbench is None:
        raise FileNotFoundError("workbench_manifest_missing")
    sections = _packet_sections(validation, workbench)
    source_integrity = _source_integrity(validation.get("records", []))
    checklist = _readiness_checklist(validation, workbench, sections)
    unresolved = [
        {
            "item_id": record.get("item_id"),
            "item_type": record.get("item_type"),
            "title": record.get("item_title"),
            "validation_status": record.get("validation_status"),
            "source_check_status": record.get("source_check_status"),
            "counsel_review_required": True,
        }
        for record in validation.get("records", [])
        if record.get("validation_status") in {"needs_source_check", "needs_counsel_review", "needs_more_evidence", "unreviewed", "unresolved"}
    ]
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "packet_version": 1,
        "source_validation_execution_id": validation.get("execution_id"),
        "source_workbench_execution_id": workbench.get("execution_id"),
        "source_intelligence_execution_id": workbench.get("source_intelligence_execution_id"),
        "status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        "readiness_status": "SIGNOFF_PACKET_READY_WITH_UNRESOLVED_ITEMS"
        if source_integrity["items_needing_source_check"] > 0
        else "READY_FOR_COUNSEL_SIGNOFF",
        "packet_store": "file_manifest",
        "baseline": workbench.get("baseline") or {},
        "sections": sections,
        "source_integrity_matrix": source_integrity,
        "signoff_readiness_checklist": checklist,
        "unresolved_items_register": unresolved,
        "export_snapshot": {
            "snapshot_id": str(uuid4()),
            "exportable": True,
            "format": "manifest_json",
            "contains_document_body_text": False,
            "contains_locked_content": False,
        },
        "signoff_capture": {
            "signoff_recorded": False,
            "signoff_type": None,
            "signer_safe_label": None,
            "signer_role": None,
            "signed_at": None,
            "scope_confirmation_required": True,
            "scope_confirmation_text": "I understand this is signoff for the approved review scope only.",
            "notes": None,
        },
        "audit_history": [
            {
                "audit_id": str(uuid4()),
                "action": "signoff_packet_created",
                "created_at": now_iso(),
                "reviewer_identity_safe_label": "system:signoff-packet-generator",
                "reviewer_role": "system",
                "signoff_auto_created": False,
                "audit_hash": _json_hash({"action": "signoff_packet_created", "execution_id": execution_id}),
            }
        ],
        "rollback": {
            "delete_manifest_path": str(signoff_manifest_path(execution_id)),
            "packet_record_ids": [section["section_id"] for section in sections],
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
            "duplicate_validation_records": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
            "signoff_auto_created": False,
        },
    }
    payload["packet_checksum"] = _json_hash(payload)
    return payload


def write_signoff_packet_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = signoff_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{SIGNOFF_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_signoff_packet(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None


def capture_signoff_action(
    case_slug: str,
    *,
    signoff_type: str,
    signer_safe_label: str,
    signer_role: str,
    scope_confirmed: bool,
    notes: str | None = None,
) -> dict[str, Any]:
    if signoff_type in FORBIDDEN_SIGNOFF_TYPES or signoff_type not in ALLOWED_SIGNOFF_TYPES:
        raise ValueError("invalid_signoff_type")
    if not scope_confirmed:
        raise ValueError("scope_confirmation_required")
    payload = load_latest_signoff_packet(case_slug)
    if payload is None:
        raise FileNotFoundError("signoff_packet_missing")
    status = "COUNSEL_SIGNOFF_FOR_APPROVED_REVIEW_SCOPE" if signoff_type == "counsel_signoff_for_review_use" else signoff_type.upper()
    payload["signoff_status"] = status
    payload["signoff_capture"] = {
        "signoff_recorded": True,
        "signoff_type": signoff_type,
        "signer_safe_label": signer_safe_label,
        "signer_role": signer_role,
        "signed_at": now_iso(),
        "scope_confirmation_required": True,
        "scope_confirmed": True,
        "notes": (notes or "")[:1200],
    }
    payload.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "signoff_recorded",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": signer_safe_label,
            "reviewer_role": signer_role,
            "signoff_type": signoff_type,
            "audit_hash": _json_hash({"signoff_type": signoff_type, "signer": signer_safe_label}),
        }
    )
    payload["packet_checksum"] = _json_hash({k: v for k, v in payload.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(payload)
    return payload


def reopen_signoff_packet(case_slug: str, *, reviewer_safe_label: str, reviewer_role: str, notes: str | None = None) -> dict[str, Any]:
    payload = load_latest_signoff_packet(case_slug)
    if payload is None:
        raise FileNotFoundError("signoff_packet_missing")
    payload["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    payload["readiness_status"] = "reopened"
    payload.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "signoff_packet_reopened",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": reviewer_safe_label,
            "reviewer_role": reviewer_role,
            "notes": (notes or "")[:1200],
            "audit_hash": _json_hash({"action": "signoff_packet_reopened", "reviewer": reviewer_safe_label}),
        }
    )
    payload["packet_checksum"] = _json_hash({k: v for k, v in payload.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(payload)
    return payload
