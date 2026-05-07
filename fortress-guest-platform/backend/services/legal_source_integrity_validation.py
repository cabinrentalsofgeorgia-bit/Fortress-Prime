"""Source integrity validation artifact store.

This layer classifies source support for signoff-packet material items without
schema changes, document ingestion, vector writes, or locked-content access.
It records whether source refs are review-use ready, incomplete, missing, or
privilege-limited so counsel can safely decide what remains blocked.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_signoff_packet import (
    load_latest_signoff_packet,
    write_signoff_packet_manifest,
)
from backend.services.legal_counsel_validation import TARGET_SLUG, load_latest_validation
from backend.services.legal_counsel_workbench import AUDIT_DIR, load_latest_workbench

SOURCE_INTEGRITY_PREFIX = "fortress-source-integrity-"
SOURCE_SUPPORT_STATUSES = {
    "source_verified_for_review_use",
    "partially_supported",
    "unsupported",
    "conflicting_sources",
    "wrong_source",
    "source_missing",
    "needs_page_or_chunk_review",
    "needs_more_evidence",
    "locked_or_privilege_limited",
    "duplicate_or_superseded",
    "not_applicable",
    "needs_counsel_review",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_integrity_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_source_refs(refs: Any) -> list[dict[str, Any]]:
    if not isinstance(refs, list):
        return []
    safe_refs: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        safe_refs.append(
            {
                key: ref.get(key)
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
                if key in ref
            }
        )
    return [ref for ref in safe_refs if ref]


def _packet_section_for(item_type: str) -> str:
    return {
        "issue_matrix": "reviewed-issue-matrix",
        "timeline_event": "reviewed-master-chronology",
        "contradiction_candidate": "contradiction-triage-packet",
        "evidence_binder": "evidence-binder-index",
        "entity_dossier": "entity-actor-dossier",
        "theory_packet": "case-theory-packet",
        "counsel_question": "counsel-questions-actions",
        "action_item": "counsel-questions-actions",
    }.get(item_type, "source-integrity-matrix")


def _classify(record: dict[str, Any]) -> tuple[str, str, str, bool, str]:
    refs = _safe_source_refs(record.get("source_refs"))
    locked_involved = bool(record.get("locked_restricted_related")) or any(ref.get("locked_restricted") for ref in refs)
    if locked_involved:
        return (
            "locked_or_privilege_limited",
            "locked_or_privilege_limited",
            "locked_only_or_privilege_limited",
            True,
            "Source validation would require locked/restricted material or locked-only support.",
        )
    if not refs:
        return (
            "source_missing",
            "source_missing",
            "none",
            True,
            "No safe source reference is attached; item cannot be verified without citation repair.",
        )
    if record.get("source_check_status") == "verified":
        return (
            "source_verified_for_review_use",
            "checked",
            "moderate",
            False,
            "Source references are present and previously marked verified for review use.",
        )
    return (
        "needs_page_or_chunk_review",
        "needs_page_or_chunk_review",
        "plausible_but_unverified",
        True,
        "Source reference exists but page/chunk or content-level support still requires review.",
    )


def _source_validation_record(
    *,
    record: dict[str, Any],
    execution_id: str,
    signoff_packet_execution_id: str,
    validation_execution_id: str,
    workbench_execution_id: str,
) -> dict[str, Any]:
    support_status, check_status, strength, blocker, note = _classify(record)
    refs = _safe_source_refs(record.get("source_refs"))
    payload = {
        "source_validation_id": str(uuid4()),
        "source_validation_execution_id": execution_id,
        "signoff_packet_execution_id": signoff_packet_execution_id,
        "validation_execution_id": validation_execution_id,
        "workbench_execution_id": workbench_execution_id,
        "matter_slug": TARGET_SLUG,
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "item_title": record.get("item_title"),
        "packet_section": _packet_section_for(str(record.get("item_type"))),
        "materiality": record.get("materiality"),
        "confidence": record.get("confidence_before"),
        "source_refs_claimed": refs,
        "source_refs_checked": refs if support_status == "source_verified_for_review_use" else [],
        "source_documents_checked": [
            {"document_id": ref.get("document_id"), "file_name": ref.get("file_name")}
            for ref in refs
            if ref.get("document_id") or ref.get("file_name")
        ],
        "locked_restricted_involved": support_status == "locked_or_privilege_limited",
        "source_support_status": support_status,
        "source_check_status": check_status,
        "support_strength": strength,
        "verification_method": "metadata_and_existing_source_ref_classification_no_locked_content",
        "verified_at": now_iso(),
        "reviewer_safe_label": "system:source-integrity-validator",
        "source_notes": note,
        "correction_needed": blocker,
        "correction_summary": "Repair source citation or route to counsel review." if blocker else None,
        "unresolved_reason": note if blocker else None,
        "counsel_review_required": True,
        "signoff_blocker": blocker,
        "version": 1,
        "supersedes_source_validation_id": None,
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _batch_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("item_type"))].append(record)
    batches: list[dict[str, Any]] = []
    for item_type, items in sorted(grouped.items()):
        counts = Counter(item["source_support_status"] for item in items)
        batches.append(
            {
                "item_type": item_type,
                "items_total": len(items),
                "checked": len(items),
                "verified": counts.get("source_verified_for_review_use", 0),
                "partial": counts.get("partially_supported", 0),
                "unsupported": counts.get("unsupported", 0) + counts.get("source_missing", 0),
                "conflicting": counts.get("conflicting_sources", 0),
                "locked_or_privilege_limited": counts.get("locked_or_privilege_limited", 0),
                "needs_page_or_chunk_review": counts.get("needs_page_or_chunk_review", 0),
                "needs_counsel_review": counts.get("needs_counsel_review", 0),
                "signoff_blockers": sum(1 for item in items if item.get("signoff_blocker")),
            }
        )
    return batches


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(record["source_support_status"] for record in records)
    total = len(records)
    blockers = sum(1 for record in records if record.get("signoff_blocker"))
    verified = counts.get("source_verified_for_review_use", 0)
    recommendation = (
        "READY_FOR_COUNSEL_SOURCE_REVIEW"
        if blockers
        else "READY_FOR_LIMITED_SIGNOFF_SUBSET"
    )
    return {
        "total_material_items": total,
        "checked": total,
        "source_verified_for_review_use": verified,
        "partially_supported": counts.get("partially_supported", 0),
        "unsupported": counts.get("unsupported", 0),
        "conflicting_sources": counts.get("conflicting_sources", 0),
        "wrong_source": counts.get("wrong_source", 0),
        "source_missing": counts.get("source_missing", 0),
        "needs_page_or_chunk_review": counts.get("needs_page_or_chunk_review", 0),
        "locked_or_privilege_limited": counts.get("locked_or_privilege_limited", 0),
        "needs_counsel_review": counts.get("needs_counsel_review", 0),
        "signoff_blockers": blockers,
        "source_validation_complete_percent": round((total / total) * 100, 2) if total else 0,
        "verified_subset_count": verified,
        "signoff_readiness_recommendation": recommendation,
        "counsel_signoff_pending": True,
    }


def _correction_queue(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    priority_rank = {
        "source_missing": "high",
        "unsupported": "high",
        "conflicting_sources": "high",
        "locked_or_privilege_limited": "high",
        "needs_page_or_chunk_review": "medium",
    }
    for record in records:
        if record["source_support_status"] == "source_verified_for_review_use":
            continue
        status = record["source_support_status"]
        queue.append(
            {
                "queue_id": str(uuid4()),
                "source_validation_id": record["source_validation_id"],
                "item_id": record["item_id"],
                "item_type": record["item_type"],
                "issue_category": record["packet_section"],
                "source_support_status": status,
                "reason": record["source_notes"],
                "suggested_correction": record["correction_summary"],
                "required_next_action": "Add or verify page/chunk source support before signoff.",
                "priority": priority_rank.get(status, "medium"),
                "signoff_blocker": record["signoff_blocker"],
                "counsel_review_required": True,
                "linked_source_refs": record["source_refs_claimed"],
                "locked_restricted_flag": record["locked_restricted_involved"],
            }
        )
    return queue


def create_source_integrity_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("source_integrity_scope_refused")
    signoff = load_latest_signoff_packet(case_slug)
    validation = load_latest_validation(case_slug)
    workbench = load_latest_workbench(case_slug)
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    if validation is None:
        raise FileNotFoundError("validation_manifest_missing")
    if workbench is None:
        raise FileNotFoundError("workbench_manifest_missing")
    material_records = [
        record for record in validation.get("records", []) if record.get("item_type") != "locked_restricted_metadata"
    ]
    source_records = [
        _source_validation_record(
            record=record,
            execution_id=execution_id,
            signoff_packet_execution_id=str(signoff.get("execution_id")),
            validation_execution_id=str(validation.get("execution_id")),
            workbench_execution_id=str(workbench.get("execution_id")),
        )
        for record in material_records
    ]
    summary = _summary(source_records)
    queue = _correction_queue(source_records)
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "signoff_packet_execution_id": signoff.get("execution_id"),
        "validation_execution_id": validation.get("execution_id"),
        "workbench_execution_id": workbench.get("execution_id"),
        "status": "SOURCE_INTEGRITY_VALIDATION_COMPLETE_WITH_UNRESOLVED_ITEMS"
        if summary["signoff_blockers"]
        else "SOURCE_INTEGRITY_VALIDATION_COMPLETE",
        "source_validation_store": "file_manifest",
        "records": source_records,
        "batch_results": _batch_summary(source_records),
        "source_integrity_summary": summary,
        "correction_queue": queue,
        "signoff_blockers": [record for record in source_records if record.get("signoff_blocker")],
        "verified_subset": [
            record for record in source_records if record["source_support_status"] == "source_verified_for_review_use"
        ],
        "signoff_packet_readiness_update": {
            "previous_readiness_status": signoff.get("readiness_status"),
            "new_readiness_status": "SOURCE_INTEGRITY_VALIDATION_COMPLETE_WITH_UNRESOLVED_ITEMS"
            if summary["signoff_blockers"]
            else "SOURCE_INTEGRITY_VALIDATION_COMPLETE",
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "audit_history": [
            {
                "audit_id": str(uuid4()),
                "action": "source_integrity_validation_created",
                "created_at": now_iso(),
                "reviewer_identity_safe_label": "system:source-integrity-validator",
                "reviewer_role": "system",
                "audit_hash": _json_hash({"execution_id": execution_id, "records": len(source_records)}),
            }
        ],
        "rollback": {
            "delete_manifest_path": str(source_integrity_manifest_path(execution_id)),
            "source_validation_record_ids": [record["source_validation_id"] for record in source_records],
            "signoff_packet_addendum_target": signoff.get("execution_id"),
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
            "duplicate_signoff_packet_records": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
            "signoff_auto_created": False,
            "explicit_signoff_recorded": False,
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_source_integrity_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = source_integrity_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_source_integrity_addendum(payload: dict[str, Any]) -> dict[str, Any]:
    signoff = load_latest_signoff_packet(str(payload["case_slug"]))
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    signoff["source_integrity_addendum"] = {
        "source_validation_execution_id": payload["execution_id"],
        "status": payload["status"],
        "source_integrity_summary": payload["source_integrity_summary"],
        "correction_queue_count": len(payload["correction_queue"]),
        "signoff_blockers_count": len(payload["signoff_blockers"]),
        "verified_subset_count": len(payload["verified_subset"]),
        "manifest_path": str(source_integrity_manifest_path(str(payload["execution_id"]))),
        "updated_at": now_iso(),
    }
    signoff["readiness_status"] = payload["signoff_packet_readiness_update"]["new_readiness_status"]
    signoff["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    signoff.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "source_integrity_addendum_attached",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": "system:source-integrity-validator",
            "reviewer_role": "system",
            "source_validation_execution_id": payload["execution_id"],
            "audit_hash": _json_hash({"action": "source_integrity_addendum_attached", "execution_id": payload["execution_id"]}),
        }
    )
    signoff["packet_checksum"] = _json_hash({k: v for k, v in signoff.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(signoff)
    return signoff


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{SOURCE_INTEGRITY_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_source_integrity(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
