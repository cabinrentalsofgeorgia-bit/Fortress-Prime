"""Counsel validation workflow artifact store.

Validation state is file-backed to avoid schema/RLS changes. The store tracks
human review status, source-check state, notes, and audit history for derived
workbench items only. It never reads raw document bodies or locked content.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_workbench import AUDIT_DIR, load_latest_workbench

VALIDATION_PREFIX = "fortress-validation-"
TARGET_SLUG = "fortress-legal-production-review"
SOURCE_WORKBENCH_EXECUTION_ID = "fortress-counsel-review-20260506-073330"

VALIDATION_STATUSES = {
    "unreviewed",
    "accepted_for_review_use",
    "rejected",
    "corrected",
    "needs_source_check",
    "needs_counsel_review",
    "needs_more_evidence",
    "privileged_locked_metadata_only",
    "duplicate_or_superseded",
    "unresolved",
    "final_counsel_signoff_pending",
}
SOURCE_CHECK_STATUSES = {
    "not_checked",
    "verified",
    "incomplete",
    "wrong_source",
    "needs_page_chunk_verification",
    "unsupported",
}
FORBIDDEN_STATUSES = {"final_legal_conclusion", "filed", "served", "counsel_signed_off"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validation_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        safe = {
            key: item.get(key)
            for key in (
                "document_id",
                "file_name",
                "processing_status",
                "locked_restricted",
                "event_id",
                "event_date",
                "event_type",
                "source_ref",
                "contradiction_id",
                "alert_type",
                "status",
            )
            if key in item
        }
        if safe:
            refs.append(safe)
    return refs


def _record(
    *,
    validation_execution_id: str,
    workbench_execution_id: str,
    matter_slug: str,
    item_type: str,
    item_id: str,
    item_title: str,
    source_refs: list[dict[str, Any]] | None = None,
    confidence: float | None = None,
    materiality: float | None = None,
    locked: bool = False,
    initial_status: str = "needs_counsel_review",
) -> dict[str, Any]:
    if locked:
        initial_status = "privileged_locked_metadata_only"
    if initial_status in FORBIDDEN_STATUSES or initial_status not in VALIDATION_STATUSES:
        raise ValueError(f"invalid_validation_status:{initial_status}")
    refs = source_refs or []
    source_check_status = "not_checked" if refs else "needs_page_chunk_verification"
    if locked:
        source_check_status = "not_checked"
    payload = {
        "validation_id": str(uuid4()),
        "source_execution_id": workbench_execution_id,
        "validation_execution_id": validation_execution_id,
        "matter_slug": matter_slug,
        "item_type": item_type,
        "item_id": item_id,
        "item_title": item_title,
        "current_status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "proposed_status": None,
        "validation_status": initial_status,
        "source_check_status": source_check_status,
        "reviewer_type": None,
        "reviewer_identity_safe_label": None,
        "reviewer_role": None,
        "reviewed_at": None,
        "confidence_before": confidence,
        "confidence_after": None,
        "materiality": materiality,
        "correction_summary": None,
        "note": None,
        "source_refs": refs,
        "locked_restricted_related": locked,
        "counsel_review_required": True,
        "version": 1,
        "supersedes_validation_id": None,
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _records_from_workbench(workbench: dict[str, Any], validation_execution_id: str) -> list[dict[str, Any]]:
    workbench_execution_id = str(workbench.get("execution_id") or SOURCE_WORKBENCH_EXECUTION_ID)
    slug = str(workbench.get("case_slug") or TARGET_SLUG)
    records: list[dict[str, Any]] = []

    for issue in workbench.get("issue_matrix") or []:
        if not isinstance(issue, dict):
            continue
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="issue_matrix",
                item_id=str(issue.get("id") or f"issue-{len(records) + 1}"),
                item_title=str(issue.get("title") or "Issue matrix item"),
                source_refs=_source_refs(issue.get("supporting_documents")) + _source_refs(issue.get("relevant_timeline_events")),
                confidence=issue.get("confidence_score"),
                materiality=issue.get("materiality_score"),
                initial_status="needs_counsel_review",
            )
        )

    for binder in workbench.get("evidence_binders") or []:
        if not isinstance(binder, dict):
            continue
        title = str(binder.get("title") or "Evidence binder")
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="evidence_binder",
                item_id=str(binder.get("id") or f"binder-{len(records) + 1}"),
                item_title=title,
                confidence=None,
                materiality=None,
                locked=False,
                initial_status="needs_counsel_review",
            )
        )

    for item in workbench.get("contradiction_triage") or []:
        if not isinstance(item, dict):
            continue
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="contradiction_candidate",
                item_id=str(item.get("id") or item.get("contradiction_id") or f"contradiction-{len(records) + 1}"),
                item_title=str(item.get("conflict_type") or "Contradiction candidate"),
                source_refs=_source_refs(item.get("source_refs")),
                confidence=item.get("confidence_score"),
                materiality=item.get("materiality_score"),
                initial_status="needs_source_check",
            )
        )

    for entity in workbench.get("entity_dossier") or []:
        if not isinstance(entity, dict):
            continue
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="entity_dossier",
                item_id=str(entity.get("id") or f"entity-{len(records) + 1}"),
                item_title=str(entity.get("canonical_name") or "Entity dossier item"),
                source_refs=_source_refs(entity.get("linked_documents")),
                confidence=entity.get("confidence_score"),
                materiality=None,
                initial_status="needs_counsel_review",
            )
        )

    for packet_id, packet in (workbench.get("theory_packets") or {}).items():
        if not isinstance(packet, dict):
            continue
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="theory_packet",
                item_id=str(packet_id),
                item_title=str(packet.get("title") or str(packet_id).replace("_", " ").title()),
                source_refs=_source_refs(packet.get("source_refs")),
                confidence=None,
                materiality=None,
                initial_status="needs_counsel_review",
            )
        )

    for item_type, key in (("counsel_question", "counsel_questions"), ("action_item", "action_checklist")):
        for item in workbench.get(key) or []:
            if not isinstance(item, dict):
                continue
            records.append(
                _record(
                    validation_execution_id=validation_execution_id,
                    workbench_execution_id=workbench_execution_id,
                    matter_slug=slug,
                    item_type=item_type,
                    item_id=str(item.get("id") or f"{item_type}-{len(records) + 1}"),
                    item_title=str(item.get("title") or item_type.replace("_", " ").title()),
                    source_refs=_source_refs(item.get("source_refs")),
                    confidence=None,
                    materiality=None,
                    initial_status="needs_counsel_review",
                )
            )

    chronology = workbench.get("chronology_review_packet") or {}
    total_events = int(chronology.get("total_events") or workbench.get("baseline", {}).get("timeline_events") or 0)
    event_refs = chronology.get("events_requiring_counsel_review") or []
    if not isinstance(event_refs, list):
        event_refs = []
    for idx in range(total_events):
        event_ref = event_refs[idx] if idx < len(event_refs) and isinstance(event_refs[idx], dict) else {}
        title = event_ref.get("event_type") or f"Timeline event {idx + 1:03d}"
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="timeline_event",
                item_id=str(event_ref.get("event_id") or f"timeline-event-{idx + 1:03d}"),
                item_title=str(title),
                source_refs=_source_refs([event_ref]) if event_ref else [],
                confidence=None,
                materiality=None,
                initial_status="needs_source_check" if not event_ref else "needs_counsel_review",
            )
        )

    locked_count = int((workbench.get("privileged_locked_handling") or {}).get("locked_restricted_count") or 0)
    for idx in range(locked_count):
        records.append(
            _record(
                validation_execution_id=validation_execution_id,
                workbench_execution_id=workbench_execution_id,
                matter_slug=slug,
                item_type="locked_restricted_metadata",
                item_id=f"locked-restricted-{idx + 1:02d}",
                item_title=f"Locked/restricted metadata item {idx + 1}",
                locked=True,
            )
        )

    return records


def _queue_summary(records: list[dict[str, Any]], queue_id: str, title: str, predicate) -> dict[str, Any]:
    items = [record for record in records if predicate(record)]
    statuses = Counter(str(item.get("validation_status")) for item in items)
    return {
        "queue_id": queue_id,
        "title": title,
        "item_count": len(items),
        "unreviewed_count": statuses.get("unreviewed", 0),
        "accepted_count": statuses.get("accepted_for_review_use", 0),
        "rejected_count": statuses.get("rejected", 0),
        "corrected_count": statuses.get("corrected", 0),
        "needs_source_check_count": statuses.get("needs_source_check", 0),
        "needs_counsel_review_count": statuses.get("needs_counsel_review", 0),
        "high_priority_count": sum(1 for item in items if (item.get("materiality") or 0) >= 0.75),
    }


def build_queues(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _queue_summary(records, "issue-matrix-validation", "Issue Matrix Validation", lambda r: r["item_type"] == "issue_matrix"),
        _queue_summary(records, "chronology-event-validation", "Chronology Event Validation", lambda r: r["item_type"] == "timeline_event"),
        _queue_summary(records, "contradiction-candidate-validation", "Contradiction Candidate Validation", lambda r: r["item_type"] == "contradiction_candidate"),
        _queue_summary(records, "evidence-binder-validation", "Evidence Binder Validation", lambda r: r["item_type"] == "evidence_binder"),
        _queue_summary(records, "entity-dossier-validation", "Entity Dossier Validation", lambda r: r["item_type"] == "entity_dossier"),
        _queue_summary(records, "theory-counter-theory-validation", "Theory / Counter-Theory Validation", lambda r: r["item_type"] == "theory_packet"),
        _queue_summary(records, "counsel-questions-actions-validation", "Counsel Questions / Actions Validation", lambda r: r["item_type"] in {"counsel_question", "action_item"}),
        _queue_summary(records, "privilege-locked-metadata-review", "Privilege / Locked Metadata Review", lambda r: bool(r.get("locked_restricted_related"))),
        _queue_summary(records, "source-citation-check", "Source Citation Check", lambda r: True),
        _queue_summary(records, "high-materiality-priority-review", "High-Materiality Priority Review", lambda r: (r.get("materiality") or 0) >= 0.75 or r["item_type"] == "contradiction_candidate"),
    ]


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(item.get("validation_status")) for item in records)
    complete = statuses.get("accepted_for_review_use", 0) + statuses.get("rejected", 0) + statuses.get("corrected", 0)
    total = len(records)
    return {
        "total_workbench_items": total,
        "validation_complete_percent": round((complete / total) * 100, 2) if total else 0,
        "unreviewed_items": statuses.get("unreviewed", 0),
        "accepted_for_review_use": statuses.get("accepted_for_review_use", 0),
        "rejected": statuses.get("rejected", 0),
        "corrected": statuses.get("corrected", 0),
        "needs_source_check": statuses.get("needs_source_check", 0),
        "needs_counsel_review": statuses.get("needs_counsel_review", 0),
        "high_priority_unresolved": sum(
            1
            for item in records
            if (item.get("materiality") or 0) >= 0.75
            and item.get("validation_status") not in {"accepted_for_review_use", "rejected", "corrected"}
        ),
        "privileged_locked_metadata_only": statuses.get("privileged_locked_metadata_only", 0),
        "counsel_signoff_pending": True,
        "last_reviewer": None,
        "last_validation_timestamp": None,
        "progress_label": "VALIDATION_NOT_STARTED" if complete == 0 else "VALIDATION_IN_PROGRESS",
    }


def create_validation_manifest(case_slug: str, validation_execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("validation_workflow_scope_refused")
    workbench = load_latest_workbench(case_slug)
    if workbench is None:
        raise FileNotFoundError("counsel_workbench_manifest_missing")
    records = _records_from_workbench(workbench, validation_execution_id)
    queues = build_queues(records)
    payload = {
        "execution_id": validation_execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "source_workbench_execution_id": str(workbench.get("execution_id") or SOURCE_WORKBENCH_EXECUTION_ID),
        "source_intelligence_execution_id": str(workbench.get("source_intelligence_execution_id") or ""),
        "status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "validation_store": "file_manifest",
        "validation_status_policy": "accepted_for_review_use_not_final_legal_conclusion",
        "baseline": workbench.get("baseline") or {},
        "records": records,
        "queues": queues,
        "summary": build_summary(records),
        "audit_history": [
            {
                "audit_id": str(uuid4()),
                "action": "validation_initialized",
                "created_at": now_iso(),
                "reviewer_identity_safe_label": "system:validation-initializer",
                "reviewer_role": "system",
                "record_count": len(records),
                "audit_hash": _json_hash({"action": "validation_initialized", "record_count": len(records)}),
            }
        ],
        "rollback": {
            "delete_manifest_path": str(validation_manifest_path(validation_execution_id)),
            "derived_record_ids": [record["validation_id"] for record in records],
            "raw_documents_touched": False,
            "qdrant_vectors_touched": False,
            "schema_changed": False,
            "rls_policy_changed": False,
        },
        "mutation_invariants": {
            "new_raw_document_upload": False,
            "new_ingest": False,
            "new_document_rows": False,
            "new_qdrant_document_vectors": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
        },
    }
    payload["manifest_hash"] = _json_hash(payload)
    return payload


def write_validation_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = validation_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{VALIDATION_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_validation(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None


def apply_validation_action(
    case_slug: str,
    *,
    item_id: str,
    action: str,
    reviewer_identity_safe_label: str,
    reviewer_role: str,
    validation_status: str | None = None,
    source_check_status: str | None = None,
    note: str | None = None,
    correction_summary: str | None = None,
) -> dict[str, Any]:
    payload = load_latest_validation(case_slug)
    if payload is None:
        raise FileNotFoundError("validation_manifest_missing")
    if validation_status and (validation_status in FORBIDDEN_STATUSES or validation_status not in VALIDATION_STATUSES):
        raise ValueError("invalid_validation_status")
    if source_check_status and source_check_status not in SOURCE_CHECK_STATUSES:
        raise ValueError("invalid_source_check_status")

    records = payload.get("records") or []
    target = next((record for record in records if record.get("item_id") == item_id), None)
    if target is None:
        raise KeyError("validation_item_not_found")
    previous = {
        "validation_status": target.get("validation_status"),
        "source_check_status": target.get("source_check_status"),
        "version": target.get("version"),
    }

    action_map = {
        "accept": "accepted_for_review_use",
        "reject": "rejected",
        "correct": "corrected",
        "needs_source_check": "needs_source_check",
        "needs_more_evidence": "needs_more_evidence",
        "needs_counsel_review": "needs_counsel_review",
        "reopen": "unreviewed",
    }
    next_status = validation_status or action_map.get(action)
    if next_status is None or next_status in FORBIDDEN_STATUSES or next_status not in VALIDATION_STATUSES:
        raise ValueError("invalid_validation_action")

    if target.get("locked_restricted_related") and next_status == "accepted_for_review_use":
        next_status = "privileged_locked_metadata_only"

    target["validation_status"] = next_status
    if source_check_status:
        target["source_check_status"] = source_check_status
    if note:
        target["note"] = note[:1200]
    if correction_summary:
        target["correction_summary"] = correction_summary[:1200]
    target["reviewer_type"] = "staff"
    target["reviewer_identity_safe_label"] = reviewer_identity_safe_label
    target["reviewer_role"] = reviewer_role
    target["reviewed_at"] = now_iso()
    target["version"] = int(target.get("version") or 1) + (1 if action == "correct" or correction_summary else 0)
    target["confidence_after"] = target.get("confidence_after")
    target["audit_hash"] = _json_hash(target)

    audit = {
        "audit_id": str(uuid4()),
        "action": action,
        "created_at": now_iso(),
        "item_id": item_id,
        "previous_state": previous,
        "new_state": {
            "validation_status": target.get("validation_status"),
            "source_check_status": target.get("source_check_status"),
            "version": target.get("version"),
        },
        "reviewer_identity_safe_label": reviewer_identity_safe_label,
        "reviewer_role": reviewer_role,
        "audit_hash": _json_hash({"item_id": item_id, "previous": previous, "new": target}),
    }
    payload.setdefault("audit_history", []).append(audit)
    payload["queues"] = build_queues(records)
    payload["summary"] = build_summary(records)
    payload["summary"]["last_reviewer"] = reviewer_identity_safe_label
    payload["summary"]["last_validation_timestamp"] = audit["created_at"]
    payload["manifest_hash"] = _json_hash({k: v for k, v in payload.items() if k != "manifest_hash"})
    write_validation_manifest(payload)
    payload["updated_record"] = target
    return payload
