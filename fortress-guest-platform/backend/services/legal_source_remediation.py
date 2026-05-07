"""Source blocker remediation artifact store.

This layer converts source-integrity blockers into precise remediation
outcomes and a verified-subset register without reading locked content,
creating vectors, changing schema/RLS, or recording counsel signoff.
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
from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_counsel_workbench import AUDIT_DIR
from backend.services.legal_source_integrity_validation import load_latest_source_integrity

SOURCE_REMEDIATION_PREFIX = "fortress-source-remediation-"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_remediation_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _blocker_type(record: dict[str, Any]) -> str:
    status = str(record.get("source_support_status") or "")
    if record.get("locked_restricted_involved") or status == "locked_or_privilege_limited":
        return "locked_or_privilege_limited"
    if status == "source_missing":
        return "missing_source_ref"
    if status == "needs_page_or_chunk_review":
        return "incomplete_page_or_chunk_ref"
    if status == "wrong_source":
        return "wrong_source_ref"
    if status == "conflicting_sources":
        return "conflicting_sources"
    if status == "partially_supported":
        return "partially_supported_assertion"
    if status == "unsupported":
        return "unsupported_assertion"
    if status == "needs_more_evidence":
        return "needs_more_evidence"
    if status == "duplicate_or_superseded":
        return "duplicate_or_superseded"
    if status == "needs_counsel_review":
        return "legal_interpretation_required"
    return "source_ref_format_problem"


def _remediation_outcome(record: dict[str, Any]) -> tuple[str, str, str, bool, bool, str, str]:
    status = str(record.get("source_support_status") or "")
    blocker = _blocker_type(record)
    refs = record.get("source_refs_claimed") or []
    if blocker == "locked_or_privilege_limited":
        return (
            "unresolved_locked_or_privilege_limited",
            "locked_or_privilege_limited",
            "locked_or_privilege_limited",
            True,
            True,
            "Counsel-only metadata review required; locked/restricted content was not read.",
            "Counsel privilege review of metadata-only item.",
        )
    if status == "source_verified_for_review_use":
        return (
            "resolved_source_verified",
            "source_verified_for_review_use",
            "source_verified_for_review_use",
            False,
            False,
            "Existing source-integrity record was already verified for review use.",
            "No remediation required beyond counsel review.",
        )
    if status == "duplicate_or_superseded":
        return (
            "resolved_duplicate_or_superseded",
            "duplicate_or_superseded",
            "duplicate_or_superseded",
            False,
            False,
            "Item is marked duplicate or superseded; canonical verification remains controlling.",
            "Review canonical item before any signoff reliance.",
        )
    if status == "partially_supported":
        return (
            "unresolved_partially_supported",
            "partially_supported",
            "partially_supported",
            True,
            True,
            "Existing support covers only part of the material item.",
            "Narrow claim or add source support.",
        )
    if status == "conflicting_sources":
        return (
            "unresolved_conflicting_sources",
            "conflicting_sources",
            "conflicting_sources",
            True,
            True,
            "Source support is materially conflicting and requires counsel triage.",
            "Resolve conflict or scope out of signoff subset.",
        )
    if status == "wrong_source":
        return (
            "unresolved_wrong_source",
            "wrong_source",
            "wrong_source",
            True,
            True,
            "Claimed source does not support the item and no safe replacement was found in metadata.",
            "Attach correct source reference.",
        )
    if not refs:
        return (
            "unresolved_unsupported",
            "unsupported",
            "source_missing",
            True,
            True,
            "No claimed source reference is available for automated source remediation.",
            "Add source reference or mark item out of signoff subset.",
        )
    return (
        "unresolved_needs_page_or_chunk_review",
        "needs_page_or_chunk_review",
        "needs_page_or_chunk_review",
        True,
        True,
        "Source reference exists but page/chunk support is still too vague for review-use verification.",
        "Verify page/chunk citation or narrow the item.",
    )


def _record(source_record: dict[str, Any], execution_id: str) -> dict[str, Any]:
    outcome, remediated_status, support_status, blocker_after, correction_needed, note, next_action = _remediation_outcome(source_record)
    payload = {
        "remediation_id": str(uuid4()),
        "source_remediation_execution_id": execution_id,
        "source_validation_id": source_record.get("source_validation_id"),
        "matter_slug": TARGET_SLUG,
        "item_id": source_record.get("item_id"),
        "item_type": source_record.get("item_type"),
        "blocker_type": _blocker_type(source_record),
        "original_status": source_record.get("source_support_status"),
        "remediation_outcome": outcome,
        "remediated_status": remediated_status,
        "support_status_after": support_status,
        "signoff_blocker_after": blocker_after,
        "correction_needed": correction_needed,
        "corrected_claim_summary": None,
        "source_refs_before": source_record.get("source_refs_claimed") or [],
        "source_refs_after": source_record.get("source_refs_claimed") or [],
        "verification_method": "metadata_only_source_blocker_remediation_no_locked_content",
        "locked_restricted_involved": bool(source_record.get("locked_restricted_involved")),
        "counsel_review_required": True,
        "source_notes_safe": note,
        "required_next_action": next_action,
        "reviewer_safe_label": "system:source-remediation",
        "version": 1,
        "supersedes_record_id": None,
        "rollback_ref": source_record.get("source_validation_id"),
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(record["remediation_outcome"] for record in records)
    blockers = sum(1 for record in records if record.get("signoff_blocker_after"))
    verified = outcomes.get("resolved_source_verified", 0) + outcomes.get("resolved_corrected_for_review_use", 0)
    return {
        "total_blockers_processed": len(records),
        "resolved_source_verified": outcomes.get("resolved_source_verified", 0),
        "resolved_corrected_for_review_use": outcomes.get("resolved_corrected_for_review_use", 0),
        "resolved_duplicate_or_superseded": outcomes.get("resolved_duplicate_or_superseded", 0),
        "unresolved_partially_supported": outcomes.get("unresolved_partially_supported", 0),
        "unresolved_unsupported": outcomes.get("unresolved_unsupported", 0),
        "unresolved_conflicting_sources": outcomes.get("unresolved_conflicting_sources", 0),
        "unresolved_needs_page_or_chunk_review": outcomes.get("unresolved_needs_page_or_chunk_review", 0),
        "unresolved_needs_more_evidence": outcomes.get("unresolved_needs_more_evidence", 0),
        "unresolved_needs_counsel_review": outcomes.get("unresolved_needs_counsel_review", 0),
        "unresolved_locked_or_privilege_limited": outcomes.get("unresolved_locked_or_privilege_limited", 0),
        "unresolved_wrong_source": outcomes.get("unresolved_wrong_source", 0),
        "unable_to_check_safely": outcomes.get("unable_to_check_safely", 0),
        "remaining_blockers": blockers,
        "verified_subset_count": verified,
        "limited_signoff_subset_available": verified > 0,
        "counsel_signoff_pending": True,
    }


def _category_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["blocker_type"]].append(record)
    return [
        {
            "blocker_type": blocker_type,
            "item_count": len(items),
            "high_materiality_count": sum(1 for item in items if (item.get("materiality") or 0) >= 0.75),
            "automated_remediation_safe": blocker_type not in {"locked_or_privilege_limited", "legal_interpretation_required"},
            "counsel_review_required": True,
            "blocks_signoff": any(item.get("signoff_blocker_after") for item in items),
            "remediation_strategy": _strategy_for(blocker_type),
        }
        for blocker_type, items in sorted(grouped.items())
    ]


def _strategy_for(blocker_type: str) -> str:
    return {
        "missing_source_ref": "Attach source reference or classify as unsupported/out of subset.",
        "incomplete_page_or_chunk_ref": "Verify page/chunk support before signoff reliance.",
        "locked_or_privilege_limited": "Counsel-only metadata review; locked content remains inaccessible.",
        "wrong_source_ref": "Replace with correct source or keep as blocker.",
    }.get(blocker_type, "Route to counsel/source review with safe metadata only.")


def create_source_remediation_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("source_remediation_scope_refused")
    source_integrity = load_latest_source_integrity(case_slug)
    signoff = load_latest_signoff_packet(case_slug)
    if source_integrity is None:
        raise FileNotFoundError("source_integrity_manifest_missing")
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    blockers = [record for record in source_integrity.get("records", []) if record.get("signoff_blocker")]
    records = [_record(record, execution_id) for record in blockers]
    summary = _summary(records)
    verified_subset = [record for record in records if not record.get("signoff_blocker_after")]
    unresolved = [record for record in records if record.get("signoff_blocker_after")]
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "source_integrity_execution_id": source_integrity.get("execution_id"),
        "signoff_packet_execution_id": signoff.get("execution_id"),
        "status": "SOURCE_REMEDIATION_COMPLETE_NO_SIGNOFF_SUBSET_READY"
        if not verified_subset
        else "SOURCE_REMEDIATION_COMPLETE_VERIFIED_SUBSET_READY",
        "source_remediation_store": "file_manifest",
        "records": records,
        "remediation_category_summary": _category_summary(records),
        "remediation_summary": summary,
        "verified_subset": {
            "verified_subset_id": str(uuid4()),
            "item_count": len(verified_subset),
            "item_ids": [record["item_id"] for record in verified_subset],
            "packet_sections_covered": sorted({str(record.get("item_type")) for record in verified_subset}),
            "excluded_item_count": len(unresolved),
            "signoff_scope_recommendation": "NO_LIMITED_SIGNOFF_SUBSET_READY"
            if not verified_subset
            else "LIMITED_SIGNOFF_SUBSET_AVAILABLE",
            "items": verified_subset,
        },
        "refined_blocker_register": unresolved,
        "signoff_readiness_addendum": {
            "source_remediation_execution_id": execution_id,
            "readiness_recommendation": "FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_BLOCKERS",
            "verified_subset_status": "NO_VERIFIED_SUBSET_READY" if not verified_subset else "LIMITED_SIGNOFF_SUBSET_AVAILABLE",
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "rollback": {
            "delete_manifest_path": str(source_remediation_manifest_path(execution_id)),
            "source_remediation_record_ids": [record["remediation_id"] for record in records],
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
            "duplicate_source_validation_records": False,
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


def write_source_remediation_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = source_remediation_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_source_remediation_addendum(payload: dict[str, Any]) -> dict[str, Any]:
    signoff = load_latest_signoff_packet(str(payload["case_slug"]))
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    signoff["source_remediation_addendum"] = {
        "source_remediation_execution_id": payload["execution_id"],
        "status": payload["status"],
        "remediation_summary": payload["remediation_summary"],
        "verified_subset": {
            "verified_subset_id": payload["verified_subset"]["verified_subset_id"],
            "item_count": payload["verified_subset"]["item_count"],
            "excluded_item_count": payload["verified_subset"]["excluded_item_count"],
            "signoff_scope_recommendation": payload["verified_subset"]["signoff_scope_recommendation"],
        },
        "refined_blocker_count": len(payload["refined_blocker_register"]),
        "manifest_path": str(source_remediation_manifest_path(str(payload["execution_id"]))),
        "updated_at": now_iso(),
    }
    signoff["readiness_status"] = "FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_BLOCKERS"
    signoff["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    signoff.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "source_remediation_addendum_attached",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": "system:source-remediation",
            "reviewer_role": "system",
            "source_remediation_execution_id": payload["execution_id"],
            "audit_hash": _json_hash({"action": "source_remediation_addendum_attached", "execution_id": payload["execution_id"]}),
        }
    )
    signoff["packet_checksum"] = _json_hash({k: v for k, v in signoff.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(signoff)
    return signoff


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{SOURCE_REMEDIATION_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_source_remediation(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
