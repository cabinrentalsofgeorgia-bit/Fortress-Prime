"""Source link repair artifact store.

This phase repairs source-link state using existing safe metadata only. It can
mark a limited subset as corrected_verified_for_review_use when a blocker has a
completed, non-locked source document link. It does not assert content-level
legal truth, read locked content, create vectors, change schema, or sign off.
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
from backend.services.legal_source_remediation import load_latest_source_remediation

SOURCE_LINK_REPAIR_PREFIX = "fortress-source-link-repair-"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_link_repair_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _eligible_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs = record.get("source_refs_after") or record.get("source_refs_before") or []
    if not isinstance(refs, list):
        return []
    eligible: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("locked_restricted") is True:
            continue
        if ref.get("processing_status") != "completed":
            continue
        if not ref.get("document_id") and not ref.get("file_name"):
            continue
        eligible.append(
            {
                key: ref.get(key)
                for key in ("document_id", "file_name", "processing_status", "locked_restricted")
                if key in ref
            }
        )
    return eligible


def _repair(record: dict[str, Any]) -> tuple[str, str, bool, str, str, list[dict[str, Any]]]:
    if record.get("locked_restricted_involved"):
        return (
            "locked_or_privilege_limited",
            "locked_or_privilege_limited",
            True,
            "Locked/restricted relationship remains metadata-only; no content repair attempted.",
            "Counsel-only privilege review.",
            [],
        )
    refs = _eligible_refs(record)
    if refs:
        return (
            "corrected_verified_for_review_use",
            "resolved_source_link_repaired",
            False,
            "Existing completed non-locked source document link verified for review-use citation routing; content-level legal support remains counsel-review required.",
            "Use only as limited source-link verified subset; counsel must verify substantive content before signoff.",
            refs,
        )
    original = str(record.get("support_status_after") or record.get("original_status") or "")
    if original == "needs_page_or_chunk_review":
        return (
            "needs_page_or_chunk_review",
            "unresolved_needs_page_or_chunk_review",
            True,
            "No eligible completed non-locked source link with sufficient page/chunk metadata was available.",
            "Add or verify page/chunk source reference.",
            [],
        )
    return (
        "unsupported",
        "unresolved_unsupported",
        True,
        "No eligible source link was available for repair.",
        "Attach source reference or exclude from limited subset.",
        [],
    )


def _record(record: dict[str, Any], execution_id: str) -> dict[str, Any]:
    final_state, outcome, blocker, note, next_action, refs = _repair(record)
    payload = {
        "source_link_repair_id": str(uuid4()),
        "source_link_repair_execution_id": execution_id,
        "source_remediation_id": record.get("remediation_id"),
        "source_validation_id": record.get("source_validation_id"),
        "matter_slug": TARGET_SLUG,
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "prior_remediation_outcome": record.get("remediation_outcome"),
        "final_remediation_state": final_state,
        "repair_outcome": outcome,
        "verified_for_review_use": final_state in {"verified_for_review_use", "corrected_verified_for_review_use"},
        "signoff_blocker_after": blocker,
        "corrected_claim_summary": "Source link only: completed non-locked document association verified for review routing; substantive claim not finally verified."
        if final_state == "corrected_verified_for_review_use"
        else None,
        "source_refs_before": record.get("source_refs_before") or [],
        "source_refs_after": refs,
        "verification_method": "existing_metadata_source_link_repair_no_content_excerpts",
        "locked_restricted_involved": bool(record.get("locked_restricted_involved")),
        "counsel_review_required": True,
        "source_notes_safe": note,
        "required_next_action": next_action,
        "reviewer_safe_label": "system:source-link-repair",
        "version": 1,
        "rollback_ref": record.get("remediation_id"),
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    states = Counter(record["final_remediation_state"] for record in records)
    return {
        "total_blockers_processed": len(records),
        "verified_for_review_use": states.get("verified_for_review_use", 0),
        "corrected_verified_for_review_use": states.get("corrected_verified_for_review_use", 0),
        "partially_supported": states.get("partially_supported", 0),
        "unsupported": states.get("unsupported", 0),
        "conflicting_sources": states.get("conflicting_sources", 0),
        "needs_page_or_chunk_review": states.get("needs_page_or_chunk_review", 0),
        "needs_more_evidence": states.get("needs_more_evidence", 0),
        "needs_counsel_review": states.get("needs_counsel_review", 0),
        "locked_or_privilege_limited": states.get("locked_or_privilege_limited", 0),
        "unable_to_check_safely": states.get("unable_to_check_safely", 0),
        "remaining_unresolved": sum(1 for record in records if record.get("signoff_blocker_after")),
        "verified_subset_count": sum(1 for record in records if record.get("verified_for_review_use")),
        "counsel_signoff_pending": True,
    }


def _group(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("item_type"))].append(record)
    return [
        {
            "item_type": item_type,
            "item_count": len(items),
            "verified_subset_count": sum(1 for item in items if item.get("verified_for_review_use")),
            "unresolved_count": sum(1 for item in items if item.get("signoff_blocker_after")),
        }
        for item_type, items in sorted(grouped.items())
    ]


def create_source_link_repair_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("source_link_repair_scope_refused")
    remediation = load_latest_source_remediation(case_slug)
    signoff = load_latest_signoff_packet(case_slug)
    if remediation is None:
        raise FileNotFoundError("source_remediation_manifest_missing")
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    records = [_record(record, execution_id) for record in remediation.get("records", [])]
    summary = _summary(records)
    verified = [record for record in records if record.get("verified_for_review_use")]
    unresolved = [record for record in records if record.get("signoff_blocker_after")]
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "source_remediation_execution_id": remediation.get("execution_id"),
        "source_integrity_execution_id": remediation.get("source_integrity_execution_id"),
        "signoff_packet_execution_id": signoff.get("execution_id"),
        "status": "SOURCE_LINK_REPAIR_COMPLETE_VERIFIED_SUBSET_READY" if verified else "SOURCE_LINK_REPAIR_COMPLETE_NO_VERIFIED_SUBSET",
        "source_link_repair_store": "file_manifest",
        "records": records,
        "repair_summary": summary,
        "packet_section_summary": _group(records),
        "verified_subset": {
            "verified_subset_id": str(uuid4()),
            "item_count": len(verified),
            "item_ids": [record["item_id"] for record in verified],
            "packet_sections_covered": sorted({str(record.get("item_type")) for record in verified}),
            "excluded_item_count": len(unresolved),
            "signoff_scope_recommendation": "LIMITED_SOURCE_LINK_SIGNOFF_REVIEW_SUBSET_AVAILABLE"
            if verified
            else "NO_VERIFIED_SUBSET_READY",
            "items": verified,
        },
        "refined_unresolved_register": unresolved,
        "signoff_readiness_addendum": {
            "source_link_repair_execution_id": execution_id,
            "readiness_recommendation": "VERIFIED_SUBSET_READY_FOR_COUNSEL_SIGNOFF_REVIEW"
            if verified
            else "FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_SOURCE_BLOCKERS",
            "full_packet_ready": False,
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "rollback": {
            "delete_manifest_path": str(source_link_repair_manifest_path(execution_id)),
            "source_link_repair_record_ids": [record["source_link_repair_id"] for record in records],
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
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
            "signoff_auto_created": False,
            "explicit_signoff_recorded": False,
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_source_link_repair_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = source_link_repair_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_source_link_repair_addendum(payload: dict[str, Any]) -> dict[str, Any]:
    signoff = load_latest_signoff_packet(str(payload["case_slug"]))
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    signoff["source_link_repair_addendum"] = {
        "source_link_repair_execution_id": payload["execution_id"],
        "status": payload["status"],
        "repair_summary": payload["repair_summary"],
        "verified_subset": {
            "verified_subset_id": payload["verified_subset"]["verified_subset_id"],
            "item_count": payload["verified_subset"]["item_count"],
            "excluded_item_count": payload["verified_subset"]["excluded_item_count"],
            "signoff_scope_recommendation": payload["verified_subset"]["signoff_scope_recommendation"],
        },
        "refined_unresolved_count": len(payload["refined_unresolved_register"]),
        "manifest_path": str(source_link_repair_manifest_path(str(payload["execution_id"]))),
        "updated_at": now_iso(),
    }
    signoff["readiness_status"] = payload["signoff_readiness_addendum"]["readiness_recommendation"]
    signoff["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    signoff.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "source_link_repair_addendum_attached",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": "system:source-link-repair",
            "reviewer_role": "system",
            "source_link_repair_execution_id": payload["execution_id"],
            "audit_hash": _json_hash({"action": "source_link_repair_addendum_attached", "execution_id": payload["execution_id"]}),
        }
    )
    signoff["packet_checksum"] = _json_hash({k: v for k, v in signoff.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(signoff)
    return signoff


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{SOURCE_LINK_REPAIR_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_source_link_repair(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
