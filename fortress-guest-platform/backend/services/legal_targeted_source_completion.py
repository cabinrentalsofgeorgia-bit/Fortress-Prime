"""Targeted source completion artifact store.

This phase starts from the latest source-link repair manifest and resolves
remaining page/chunk blockers where existing completed, non-locked document
metadata can repair the source link. It does not read document body text,
create vectors, mutate schema/RLS, inspect locked content, or record signoff.
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
from backend.services.legal_source_link_repair import load_latest_source_link_repair

TARGETED_SOURCE_COMPLETION_PREFIX = "fortress-targeted-source-completion-"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def targeted_source_completion_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_doc_ref(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ref.get(key)
        for key in ("document_id", "file_name", "processing_status", "locked_restricted")
        if key in ref
    }


def _document_catalog(source_link: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for record in source_link.get("records", []):
        for field in ("source_refs_before", "source_refs_after"):
            refs = record.get(field) or []
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                file_name = ref.get("file_name")
                if not file_name:
                    continue
                if ref.get("locked_restricted") is True:
                    continue
                if ref.get("processing_status") != "completed":
                    continue
                catalog[str(file_name)] = _safe_doc_ref(ref)
    return catalog


def _matched_refs(record: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    refs = record.get("source_refs_before") or []
    if not isinstance(refs, list):
        return matched
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        name = ref.get("source_ref") or ref.get("file_name")
        if not name:
            continue
        doc_ref = catalog.get(str(name))
        if not doc_ref:
            continue
        repaired = dict(doc_ref)
        repaired["source_ref"] = name
        if ref.get("event_id"):
            repaired["event_id"] = ref.get("event_id")
        if ref.get("event_date"):
            repaired["event_date"] = ref.get("event_date")
        if ref.get("event_type"):
            repaired["event_type"] = ref.get("event_type")
        repaired["source_link_repair"] = "filename_matched_existing_completed_non_locked_document"
        repaired["page_chunk_status"] = "existing_source_ref_repaired_for_review_use_routing"
        matched.append(repaired)
    return matched


def _track(record: dict[str, Any]) -> str:
    state = str(record.get("final_remediation_state") or "")
    if state == "needs_page_or_chunk_review":
        return "track_a_page_chunk_review"
    if state == "unsupported":
        return "track_b_unsupported_recheck"
    if state == "locked_or_privilege_limited" or record.get("locked_restricted_involved"):
        return "track_c_locked_privilege_limited"
    return "track_b_unsupported_recheck"


def _completion_record(record: dict[str, Any], execution_id: str, catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    track = _track(record)
    prior_state = str(record.get("final_remediation_state") or "")
    matched_refs = _matched_refs(record, catalog)
    locked = bool(record.get("locked_restricted_involved")) or prior_state == "locked_or_privilege_limited"

    if locked:
        final_state = "locked_or_privilege_limited"
        outcome = "preserved_locked_privilege_metadata_only"
        blocker = True
        note = "Locked/restricted item preserved as metadata-only; no content review attempted."
        next_action = "Counsel-only privilege/source review."
        corrected = None
        refs_after: list[dict[str, Any]] = []
    elif track == "track_a_page_chunk_review" and matched_refs:
        final_state = "corrected_verified_for_review_use"
        outcome = "resolved_existing_page_chunk_source_link"
        blocker = False
        note = "Existing filename source reference matched to completed non-locked document metadata; verified for review-use source routing without content excerpts."
        next_action = "Route limited corrected item to counsel source review; counsel interpretation remains required."
        corrected = "Corrected source link: existing completed non-locked document metadata supports review-use citation routing; no final legal conclusion."
        refs_after = matched_refs
    elif track == "track_a_page_chunk_review":
        final_state = "needs_page_or_chunk_review"
        outcome = "unresolved_page_chunk_reference_not_repairable"
        blocker = True
        note = "Existing page/chunk source reference could not be matched to completed non-locked document metadata."
        next_action = "Manual page/chunk citation repair required."
        corrected = None
        refs_after = []
    else:
        final_state = "unsupported"
        outcome = "unresolved_no_existing_source_link"
        blocker = True
        note = "No existing safe source reference or linked completed document metadata was available for targeted completion."
        next_action = "Attach eligible source reference, narrow claim, or exclude from limited subset."
        corrected = None
        refs_after = []

    payload = {
        "targeted_source_completion_id": str(uuid4()),
        "targeted_source_completion_execution_id": execution_id,
        "source_link_repair_id": record.get("source_link_repair_id"),
        "source_remediation_id": record.get("source_remediation_id"),
        "source_validation_id": record.get("source_validation_id"),
        "matter_slug": TARGET_SLUG,
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "track": track,
        "prior_state": prior_state,
        "final_state": final_state,
        "completion_outcome": outcome,
        "verified_for_review_use": final_state in {"verified_for_review_use", "corrected_verified_for_review_use"},
        "signoff_blocker_after": blocker,
        "corrected_claim_summary": corrected,
        "source_refs_before": record.get("source_refs_before") or [],
        "source_refs_after": refs_after,
        "verification_method": "existing_metadata_targeted_source_completion_no_document_body_text",
        "locked_restricted_involved": locked,
        "counsel_review_required": True,
        "source_notes_safe": note,
        "required_next_action": next_action,
        "reviewer_safe_label": "system:targeted-source-completion",
        "version": 1,
        "rollback_ref": record.get("source_link_repair_id"),
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _summary(records: list[dict[str, Any]], prior_verified_count: int) -> dict[str, Any]:
    states = Counter(record["final_state"] for record in records)
    tracks = defaultdict(Counter)
    for record in records:
        tracks[record["track"]][record["final_state"]] += 1
    new_verified = states.get("verified_for_review_use", 0) + states.get("corrected_verified_for_review_use", 0)
    return {
        "starting_unresolved": len(records),
        "items_processed": len(records),
        "prior_verified_subset_count": prior_verified_count,
        "new_items_verified": new_verified,
        "new_verified_subset_count": prior_verified_count + new_verified,
        "verified_subset_delta": new_verified,
        "remaining_unresolved": sum(1 for record in records if record.get("signoff_blocker_after")),
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
        "track_results": {
            "track_a_page_chunk_review": {
                "items": sum(tracks["track_a_page_chunk_review"].values()),
                "verified": tracks["track_a_page_chunk_review"].get("verified_for_review_use", 0),
                "corrected": tracks["track_a_page_chunk_review"].get("corrected_verified_for_review_use", 0),
                "partial": tracks["track_a_page_chunk_review"].get("partially_supported", 0),
                "unresolved": sum(
                    count
                    for state, count in tracks["track_a_page_chunk_review"].items()
                    if state not in {"verified_for_review_use", "corrected_verified_for_review_use"}
                ),
            },
            "track_b_unsupported_recheck": {
                "items": sum(tracks["track_b_unsupported_recheck"].values()),
                "verified": tracks["track_b_unsupported_recheck"].get("verified_for_review_use", 0),
                "corrected": tracks["track_b_unsupported_recheck"].get("corrected_verified_for_review_use", 0),
                "partial": tracks["track_b_unsupported_recheck"].get("partially_supported", 0),
                "still_unsupported": tracks["track_b_unsupported_recheck"].get("unsupported", 0),
            },
            "track_c_locked_privilege_limited": {
                "items": sum(tracks["track_c_locked_privilege_limited"].values()),
                "preserved_metadata_only": tracks["track_c_locked_privilege_limited"].get("locked_or_privilege_limited", 0),
            },
        },
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
            "verified_subset_delta": sum(1 for item in items if item.get("verified_for_review_use")),
            "unresolved_count": sum(1 for item in items if item.get("signoff_blocker_after")),
        }
        for item_type, items in sorted(grouped.items())
    ]


def create_targeted_source_completion_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("targeted_source_completion_scope_refused")
    source_link = load_latest_source_link_repair(case_slug)
    signoff = load_latest_signoff_packet(case_slug)
    if source_link is None:
        raise FileNotFoundError("source_link_repair_manifest_missing")
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")

    unresolved = list(source_link.get("refined_unresolved_register", []))
    catalog = _document_catalog(source_link)
    records = [_completion_record(record, execution_id, catalog) for record in unresolved]
    prior_items = list(source_link.get("verified_subset", {}).get("items", []))
    new_items = [record for record in records if record.get("verified_for_review_use")]
    all_verified_ids = [record.get("item_id") for record in prior_items] + [record.get("item_id") for record in new_items]
    summary = _summary(records, int(source_link.get("verified_subset", {}).get("item_count") or len(prior_items)))
    remaining = [record for record in records if record.get("signoff_blocker_after")]
    status = (
        "TARGETED_SOURCE_COMPLETION_VERIFIED_SUBSET_EXPANDED"
        if summary["verified_subset_delta"] > 0
        else "TARGETED_SOURCE_COMPLETION_NO_ADDITIONAL_VERIFIED_ITEMS"
    )
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "source_link_repair_execution_id": source_link.get("execution_id"),
        "source_remediation_execution_id": source_link.get("source_remediation_execution_id"),
        "source_integrity_execution_id": source_link.get("source_integrity_execution_id"),
        "signoff_packet_execution_id": signoff.get("execution_id"),
        "status": status,
        "targeted_source_completion_store": "file_manifest",
        "source_locator_strategy": {
            "used_existing_document_metadata": True,
            "used_existing_source_refs": True,
            "used_existing_non_locked_completed_document_links": True,
            "read_document_body_text": False,
            "read_locked_content": False,
            "created_vectors": False,
        },
        "records": records,
        "completion_summary": summary,
        "packet_section_summary": _group(records),
        "expanded_verified_subset": {
            "verified_subset_id": str(uuid4()),
            "prior_item_count": summary["prior_verified_subset_count"],
            "new_item_count": summary["new_verified_subset_count"],
            "delta": summary["verified_subset_delta"],
            "item_ids": all_verified_ids,
            "new_item_ids": [record.get("item_id") for record in new_items],
            "packet_sections_covered": sorted({str(record.get("item_type")) for record in prior_items + new_items}),
            "excluded_item_count": len(remaining),
            "signoff_scope_recommendation": "LIMITED_TARGETED_SOURCE_COMPLETION_SIGNOFF_REVIEW_SUBSET_AVAILABLE"
            if summary["new_verified_subset_count"] > 0
            else "NO_VERIFIED_SUBSET_READY",
            "prior_items": prior_items,
            "new_items": new_items,
        },
        "refined_unresolved_register": remaining,
        "signoff_readiness_addendum": {
            "targeted_source_completion_execution_id": execution_id,
            "status": "TARGETED_SOURCE_COMPLETION_COMPLETE",
            "verified_subset_status": "VERIFIED_SUBSET_EXPANDED"
            if summary["verified_subset_delta"] > 0
            else "VERIFIED_SUBSET_UNCHANGED",
            "full_packet_ready": False,
            "limited_signoff_subset_available": summary["new_verified_subset_count"] > 0,
            "readiness_recommendation": "LIMITED_SIGNOFF_SUBSET_AVAILABLE",
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "rollback": {
            "delete_manifest_path": str(targeted_source_completion_manifest_path(execution_id)),
            "targeted_source_completion_record_ids": [record["targeted_source_completion_id"] for record in records],
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


def write_targeted_source_completion_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = targeted_source_completion_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_targeted_source_completion_addendum(payload: dict[str, Any]) -> dict[str, Any]:
    signoff = load_latest_signoff_packet(str(payload["case_slug"]))
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    signoff["targeted_source_completion_addendum"] = {
        "targeted_source_completion_execution_id": payload["execution_id"],
        "status": payload["status"],
        "completion_summary": payload["completion_summary"],
        "expanded_verified_subset": {
            "verified_subset_id": payload["expanded_verified_subset"]["verified_subset_id"],
            "prior_item_count": payload["expanded_verified_subset"]["prior_item_count"],
            "new_item_count": payload["expanded_verified_subset"]["new_item_count"],
            "delta": payload["expanded_verified_subset"]["delta"],
            "excluded_item_count": payload["expanded_verified_subset"]["excluded_item_count"],
            "signoff_scope_recommendation": payload["expanded_verified_subset"]["signoff_scope_recommendation"],
        },
        "refined_unresolved_count": len(payload["refined_unresolved_register"]),
        "manifest_path": str(targeted_source_completion_manifest_path(str(payload["execution_id"]))),
        "updated_at": now_iso(),
    }
    signoff["readiness_status"] = payload["signoff_readiness_addendum"]["readiness_recommendation"]
    signoff["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    signoff.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "targeted_source_completion_addendum_attached",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": "system:targeted-source-completion",
            "reviewer_role": "system",
            "targeted_source_completion_execution_id": payload["execution_id"],
            "audit_hash": _json_hash({"action": "targeted_source_completion_addendum_attached", "execution_id": payload["execution_id"]}),
        }
    )
    signoff["packet_checksum"] = _json_hash({k: v for k, v in signoff.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(signoff)
    return signoff


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{TARGETED_SOURCE_COMPLETION_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_targeted_source_completion(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
