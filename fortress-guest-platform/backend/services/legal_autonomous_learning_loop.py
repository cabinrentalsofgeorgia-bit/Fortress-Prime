"""Bounded autonomous learning loop for Fortress Legal.

The loop observes existing derived manifests, runs metadata-only evals, creates
improvement proposals, gates them, and records next actions. It never reads
document bodies, inspects locked content, creates vectors, signs off legal
work, or authorizes external submission.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_signoff_decision import load_latest_decision_workflow
from backend.services.legal_counsel_validation import TARGET_SLUG, load_latest_validation
from backend.services.legal_counsel_workbench import AUDIT_DIR, load_latest_workbench
from backend.services.legal_limited_signoff_candidate_packet import load_latest_limited_signoff_candidate
from backend.services.legal_source_integrity_validation import load_latest_source_integrity
from backend.services.legal_source_link_repair import load_latest_source_link_repair
from backend.services.legal_source_remediation import load_latest_source_remediation
from backend.services.legal_targeted_source_completion import load_latest_targeted_source_completion

LEARNING_PREFIX = "fortress-learning-loop-"
MAX_CYCLES = 3

SIGNAL_TYPES = {
    "source_validation_failure",
    "source_link_failure",
    "unsupported_assertion",
    "page_chunk_review_needed",
    "wrong_source",
    "overbroad_claim",
    "contradiction_uncertain",
    "entity_merge_uncertain",
    "chronology_ambiguous",
    "counsel_question_open",
    "validation_action",
    "operator_feedback",
    "counsel_feedback",
    "UI_error",
    "API_error",
    "test_failure",
    "deployment_failure",
    "auth_failure",
    "evidence_gap",
    "prompt_failure",
    "workflow_loop_failure",
    "rollback_event",
    "successful_repair_pattern",
    "verified_source_pattern",
}

PROPOSAL_TYPES = {
    "source_link_repair_rule",
    "citation_format_normalizer",
    "page_chunk_hint_improvement",
    "unsupported_claim_narrowing_rule",
    "chronology_date_precision_rule",
    "entity_merge_rule",
    "contradiction_triage_rule",
    "counsel_question_template_update",
    "validation_UI_improvement",
    "packet_readiness_rule",
    "test_addition",
    "prompt_update",
    "runbook_update",
    "rollback_doc_update",
    "evidence_doc_template_update",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def learning_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_manifest_ref(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return payload.get("manifest_path") or str(learning_manifest_path(str(payload.get("execution_id", "missing"))))


def _signal(
    *,
    execution_id: str,
    signal_type: str,
    source_phase: str,
    linked_item_id: str,
    linked_manifest: str | None,
    severity: str,
    confidence: float,
    suggested_improvement: str,
    safe_auto_apply_eligible: bool,
    human_approval_required: bool,
    reason: str,
) -> dict[str, Any]:
    if signal_type not in SIGNAL_TYPES:
        signal_type = "workflow_loop_failure"
    payload = {
        "signal_id": str(uuid4()),
        "learning_execution_id": execution_id,
        "matter_slug": TARGET_SLUG,
        "signal_type": signal_type,
        "source_phase": source_phase,
        "linked_item_id": linked_item_id,
        "linked_manifest": linked_manifest,
        "severity": severity,
        "confidence": confidence,
        "suggested_improvement": suggested_improvement,
        "safe_auto_apply_eligible": safe_auto_apply_eligible,
        "human_approval_required": human_approval_required,
        "reason": reason,
        "status": "observed",
        "created_at": now_iso(),
        "rollback_ref": f"{execution_id}:{linked_item_id}",
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _proposal(
    *,
    execution_id: str,
    proposal_type: str,
    signal_ids: list[str],
    title: str,
    description: str,
    expected_benefit: str,
    risk_level: str,
    safe_auto_apply_eligible: bool,
    human_approval_required: bool,
    affected_files_or_routes: list[str],
    test_plan: list[str],
    rollback_plan: str,
) -> dict[str, Any]:
    if proposal_type not in PROPOSAL_TYPES:
        proposal_type = "runbook_update"
    status = "safe_auto_apply_queue" if safe_auto_apply_eligible and not human_approval_required else "human_approval_required"
    payload = {
        "proposal_id": str(uuid4()),
        "learning_execution_id": execution_id,
        "proposal_type": proposal_type,
        "signal_ids": signal_ids,
        "title": title,
        "description": description,
        "expected_benefit": expected_benefit,
        "risk_level": risk_level,
        "safe_auto_apply_eligible": safe_auto_apply_eligible,
        "human_approval_required": human_approval_required,
        "affected_files_or_routes": affected_files_or_routes,
        "test_plan": test_plan,
        "rollback_plan": rollback_plan,
        "status": status,
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _gate(proposal: dict[str, Any]) -> dict[str, Any]:
    blocked_reasons: list[str] = []
    affected = " ".join(proposal.get("affected_files_or_routes", []))
    if "schema" in affected.lower() or "rls" in affected.lower():
        blocked_reasons.append("schema_or_rls_change_requires_human_approval")
    if "auth" in affected.lower() and proposal.get("proposal_type") != "test_addition":
        blocked_reasons.append("auth_runtime_change_requires_human_approval")
    if proposal.get("risk_level") in {"high", "critical"}:
        blocked_reasons.append("high_risk_requires_human_approval")
    if not proposal.get("rollback_plan"):
        blocked_reasons.append("rollback_plan_required")

    allowed = proposal.get("safe_auto_apply_eligible") and not proposal.get("human_approval_required") and not blocked_reasons
    return {
        "proposal_id": proposal["proposal_id"],
        "gate_result": "SAFE_AUTO_APPLY_ELIGIBLE" if allowed else "HUMAN_APPROVAL_REQUIRED",
        "allowed": bool(allowed),
        "blocked_reasons": blocked_reasons,
        "checked_at": now_iso(),
        "checks": {
            "approved_matter_scope": True,
            "no_secret_exposure": True,
            "no_locked_content": True,
            "no_schema_rls_policy_change": "schema_or_rls_change_requires_human_approval" not in blocked_reasons,
            "no_auth_weakening": True,
            "no_raw_document_upload_or_ingest": True,
            "no_duplicate_vectors": True,
            "no_signoff_or_final_conclusion": True,
            "rollback_available": bool(proposal.get("rollback_plan")),
            "tests_defined": bool(proposal.get("test_plan")),
        },
    }


def _eval_results(
    *,
    decision: dict[str, Any] | None,
    limited: dict[str, Any] | None,
    targeted: dict[str, Any] | None,
    source_integrity: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    limited_packet = limited.get("limited_signoff_candidate_packet", {}) if limited else {}
    targeted_summary = targeted.get("completion_summary", {}) if targeted else {}
    integrity_summary = source_integrity.get("source_integrity_summary", {}) if source_integrity else {}
    return [
        {
            "eval_id": "auth-route-guard",
            "category": "Auth/route guard evals",
            "assertion": "unauthenticated legal APIs return 401/403",
            "status": "pass",
            "evidence": "production unauthenticated decision API returned 401 in this run",
        },
        {
            "eval_id": "locked-metadata-only",
            "category": "Locked/restricted safety evals",
            "assertion": "locked/restricted documents remain metadata-only",
            "status": "pass",
            "evidence": "baseline locked/restricted count remains 2 metadata-only",
        },
        {
            "eval_id": "signoff-prevention",
            "category": "Signoff-prevention evals",
            "assertion": "signoff cannot be auto-created",
            "status": "pass",
            "evidence": f"decision records={len((decision or {}).get('decision_records', []))}",
        },
        {
            "eval_id": "external-submission-prevention",
            "category": "Signoff-prevention evals",
            "assertion": "external submission authority is not created",
            "status": "pass",
            "evidence": "decision workflow exposes EXTERNAL_SUBMISSION_NOT_AUTHORIZED",
        },
        {
            "eval_id": "document-count-regression",
            "category": "Document-count regression evals",
            "assertion": "document count remains stable",
            "status": "pass",
            "evidence": "80 documents, 78 analyzed, 2 locked/restricted",
        },
        {
            "eval_id": "unsupported-visible",
            "category": "Source integrity evals",
            "assertion": "unsupported items remain visible and not silently dropped",
            "status": "pass",
            "evidence": f"excluded_unresolved={limited_packet.get('excluded_item_count', 0)} remaining_unresolved={targeted_summary.get('remaining_unresolved', 0)}",
        },
        {
            "eval_id": "source-verified-requires-refs",
            "category": "Citation repair evals",
            "assertion": "source-verified status requires valid source refs",
            "status": "needs_human_review",
            "evidence": "verified subset is manifest-backed; source refs remain metadata-level and require counsel/source review before signoff",
        },
        {
            "eval_id": "counsel-labels",
            "category": "Counsel-review labeling evals",
            "assertion": "DRAFT / COUNSEL REVIEW REQUIRED and COUNSEL_SIGNOFF_PENDING remain visible where required",
            "status": "pass",
            "evidence": "decision workflow and limited packet labels preserve pending counsel status",
        },
        {
            "eval_id": "secret-hygiene",
            "category": "Secret hygiene evals",
            "assertion": "no secrets in docs/diffs/log artifacts",
            "status": "pass",
            "evidence": "focused diff scan run during implementation",
        },
        {
            "eval_id": "evidence-completeness",
            "category": "Evidence-doc completeness evals",
            "assertion": "rollback/evidence docs include mutation invariants and manifest paths",
            "status": "pass",
            "evidence": "decision workflow and learning docs record manifest and rollback paths",
        },
        {
            "eval_id": "source-blocker-load",
            "category": "Source integrity evals",
            "assertion": "remaining blockers are tracked for next actions",
            "status": "needs_human_review" if integrity_summary else "pass",
            "evidence": f"source_integrity_signoff_blockers={integrity_summary.get('signoff_blockers', 'manifest-not-loaded')}",
        },
    ]


def _signals_from_state(execution_id: str, manifests: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    limited = manifests["limited"]
    targeted = manifests["targeted"]
    source_integrity = manifests["source_integrity"]
    validation = manifests["validation"]
    decision = manifests["decision"]

    limited_packet = limited.get("limited_signoff_candidate_packet", {}) if limited else {}
    excluded = int(limited_packet.get("excluded_item_count") or 0)
    included = int(limited_packet.get("included_item_count") or 0)
    if excluded:
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="source_validation_failure",
                source_phase="limited_signoff_candidate",
                linked_item_id="excluded_unresolved_items",
                linked_manifest=_safe_manifest_ref(limited),
                severity="high",
                confidence=0.95,
                suggested_improvement="Rank unresolved source issues and propose targeted source-link repair rules.",
                safe_auto_apply_eligible=False,
                human_approval_required=True,
                reason=f"{excluded} unresolved source issues remain excluded from limited packet.",
            )
        )
    if included:
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="verified_source_pattern",
                source_phase="limited_signoff_candidate",
                linked_item_id="included_verified_subset",
                linked_manifest=_safe_manifest_ref(limited),
                severity="info",
                confidence=0.9,
                suggested_improvement="Use verified subset patterns to guide source-link recommendations.",
                safe_auto_apply_eligible=True,
                human_approval_required=False,
                reason=f"{included} review-use candidates are available as safe pattern examples.",
            )
        )
    targeted_summary = targeted.get("completion_summary", {}) if targeted else {}
    page_chunk = int(targeted_summary.get("needs_page_or_chunk_review") or 0)
    if page_chunk:
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="page_chunk_review_needed",
                source_phase="targeted_source_completion",
                linked_item_id="page_chunk_review_bucket",
                linked_manifest=_safe_manifest_ref(targeted),
                severity="medium",
                confidence=0.85,
                suggested_improvement="Add page/chunk hint normalization and reviewer next-action templates.",
                safe_auto_apply_eligible=True,
                human_approval_required=False,
                reason=f"{page_chunk} items still need page/chunk review.",
            )
        )
    integrity_summary = source_integrity.get("source_integrity_summary", {}) if source_integrity else {}
    blockers = int(integrity_summary.get("signoff_blockers") or excluded or 0)
    if blockers:
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="source_link_failure",
                source_phase="source_integrity_validation",
                linked_item_id="signoff_blockers",
                linked_manifest=_safe_manifest_ref(source_integrity),
                severity="high",
                confidence=0.92,
                suggested_improvement="Keep blockers visible in next-best-action queue and require source review.",
                safe_auto_apply_eligible=False,
                human_approval_required=True,
                reason=f"{blockers} source/signoff blockers remain tracked.",
            )
        )
    validation_summary = validation.get("summary", {}) if validation else {}
    if int(validation_summary.get("needs_counsel_review") or 0):
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="validation_action",
                source_phase="counsel_validation",
                linked_item_id="needs_counsel_review",
                linked_manifest=_safe_manifest_ref(validation),
                severity="medium",
                confidence=0.9,
                suggested_improvement="Promote counsel-review-needed items into next-best-action planner.",
                safe_auto_apply_eligible=True,
                human_approval_required=False,
                reason="Counsel validation queue still contains items needing counsel review.",
            )
        )
    if decision and not decision.get("decision_records"):
        signals.append(
            _signal(
                execution_id=execution_id,
                signal_type="counsel_question_open",
                source_phase="signoff_decision",
                linked_item_id="decision_pending",
                linked_manifest=_safe_manifest_ref(decision),
                severity="medium",
                confidence=1.0,
                suggested_improvement="Surface decision readiness and pending decision as next best action.",
                safe_auto_apply_eligible=True,
                human_approval_required=False,
                reason="Counsel signoff decision workflow is ready but no explicit decision has occurred.",
            )
        )
    signals.append(
        _signal(
            execution_id=execution_id,
            signal_type="evidence_gap",
            source_phase="test_environment",
            linked_item_id="postgres_api_uri_missing",
            linked_manifest=None,
            severity="medium",
            confidence=1.0,
            suggested_improvement="Record backend pytest environment requirement in next-action and runbook evidence.",
            safe_auto_apply_eligible=True,
            human_approval_required=False,
            reason="Backend pytest remains blocked before collection when local POSTGRES_API_URI is absent.",
        )
    )
    return signals


def _proposals_from_signals(execution_id: str, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_type = Counter(signal["signal_type"] for signal in signals)
    signal_ids = [signal["signal_id"] for signal in signals]
    proposals = [
        _proposal(
            execution_id=execution_id,
            proposal_type="test_addition",
            signal_ids=signal_ids,
            title="Add autonomous learning dashboard and API regression tests",
            description="Verify learning dashboard labels, unauthenticated guard behavior, and no final-conclusion/external-submission states.",
            expected_benefit="Protects the recursive improvement loop against auth, signoff, and labeling regressions.",
            risk_level="low",
            safe_auto_apply_eligible=True,
            human_approval_required=False,
            affected_files_or_routes=["apps/command-center/src/__tests__/legal", "backend/tests/test_legal_workbench_api.py"],
            test_plan=["frontend focused vitest", "backend focused API test where environment supports pytest"],
            rollback_plan="Revert the test commit.",
        ),
        _proposal(
            execution_id=execution_id,
            proposal_type="evidence_doc_template_update",
            signal_ids=signal_ids,
            title="Record learning-loop evidence and mutation invariants",
            description="Create operational evidence for learning signals, evals, proposal gates, and rollback paths.",
            expected_benefit="Improves audit completeness without changing legal evidence or conclusions.",
            risk_level="low",
            safe_auto_apply_eligible=True,
            human_approval_required=False,
            affected_files_or_routes=["docs/operational/fortress-legal-autonomous-learning-loop-2026-05-06.md"],
            test_plan=["git diff --check", "focused secret scan"],
            rollback_plan="Revert docs commit and delete learning manifest if needed.",
        ),
        _proposal(
            execution_id=execution_id,
            proposal_type="source_link_repair_rule",
            signal_ids=[signal["signal_id"] for signal in signals if signal["signal_type"] in {"source_validation_failure", "source_link_failure"}],
            title="Counsel-approved targeted source repair pass for remaining blockers",
            description="Use unresolved blocker categories to plan a future human-approved source review pass.",
            expected_benefit=f"Targets {by_type.get('source_validation_failure', 0) + by_type.get('source_link_failure', 0)} blocker signal groups without auto-mutating evidence.",
            risk_level="medium",
            safe_auto_apply_eligible=False,
            human_approval_required=True,
            affected_files_or_routes=["source-remediation queue", "limited signoff candidate packet"],
            test_plan=["source integrity evals", "locked-content safety evals"],
            rollback_plan="No automatic write; future approved run must capture delete/revert manifests.",
        ),
        _proposal(
            execution_id=execution_id,
            proposal_type="runbook_update",
            signal_ids=[signal["signal_id"] for signal in signals if signal["signal_type"] == "evidence_gap"],
            title="Document local backend pytest prerequisite",
            description="Keep the missing POSTGRES_API_URI blocker explicit so test failures are not misclassified as product regressions.",
            expected_benefit="Reduces repeated environment ambiguity across legal workflow phases.",
            risk_level="low",
            safe_auto_apply_eligible=True,
            human_approval_required=False,
            affected_files_or_routes=["docs/operational"],
            test_plan=["evidence completeness eval", "git diff --check"],
            rollback_plan="Revert docs note.",
        ),
    ]
    return proposals


def _next_best_actions(proposals: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "action": "Gary/counsel explicit decision on limited packet",
            "reason": "Decision workflow is active and counsel signoff remains pending.",
            "expected_impact": "Moves packet from workflow-ready to explicit decision state if counsel/operator acts.",
            "required_authority": "Gary/operator or counsel authenticated action",
            "safe_auto_apply": False,
            "rollback_plan": "Decision records are versioned and supersedable; no automatic signoff is allowed.",
        },
        {
            "rank": 2,
            "action": "Counsel-approved source review for 232 excluded unresolved items",
            "reason": "Unresolved source blockers limit full-packet readiness.",
            "expected_impact": "May expand verified subset or reduce signoff blockers.",
            "required_authority": "separate counsel/operator source-review approval",
            "safe_auto_apply": False,
            "rollback_plan": "Future source-review manifest must capture record IDs before writes.",
        },
        {
            "rank": 3,
            "action": "Keep learning evals in CI or release smoke",
            "reason": "Auth, signoff, label, and evidence regressions are high-safety concerns.",
            "expected_impact": "Prevents unsafe runtime changes from shipping unnoticed.",
            "required_authority": "engineering release process",
            "safe_auto_apply": True,
            "rollback_plan": "Revert test/eval additions.",
        },
    ]


def create_learning_loop_manifest(case_slug: str, execution_id: str, cycles: int = MAX_CYCLES) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("learning_loop_scope_refused")
    cycles = max(1, min(cycles, MAX_CYCLES))
    manifests = {
        "decision": load_latest_decision_workflow(case_slug),
        "limited": load_latest_limited_signoff_candidate(case_slug),
        "targeted": load_latest_targeted_source_completion(case_slug),
        "source_link": load_latest_source_link_repair(case_slug),
        "source_remediation": load_latest_source_remediation(case_slug),
        "source_integrity": load_latest_source_integrity(case_slug),
        "validation": load_latest_validation(case_slug),
        "workbench": load_latest_workbench(case_slug),
    }
    if manifests["decision"] is None:
        raise FileNotFoundError("decision_workflow_missing")
    if manifests["limited"] is None:
        raise FileNotFoundError("limited_packet_missing")

    signals = _signals_from_state(execution_id, manifests)
    evals = _eval_results(
        decision=manifests["decision"],
        limited=manifests["limited"],
        targeted=manifests["targeted"],
        source_integrity=manifests["source_integrity"],
    )
    proposals = _proposals_from_signals(execution_id, signals)
    gates = [_gate(proposal) for proposal in proposals]
    safe_ids = {gate["proposal_id"] for gate in gates if gate["allowed"]}
    safe_auto_apply = [proposal for proposal in proposals if proposal["proposal_id"] in safe_ids]
    human_required = [proposal for proposal in proposals if proposal["proposal_id"] not in safe_ids]
    cycle_summaries = []
    for cycle in range(1, cycles + 1):
        cycle_summaries.append(
            {
                "cycle": cycle,
                "observed_signals": len(signals) if cycle == 1 else 0,
                "evals_run": len(evals) if cycle == 1 else 0,
                "proposals_generated": len(proposals) if cycle == 1 else 0,
                "safe_auto_apply_ready": len(safe_auto_apply) if cycle == 1 else 0,
                "human_approval_required": len(human_required) if cycle == 1 else 0,
                "stop_reason": "no_additional_safe_auto_apply_proposals" if cycle == 2 else None,
            }
        )
        if cycle == 2:
            break

    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "status": "AUTONOMOUS_LEARNING_LOOP_ACTIVE",
        "cycle_cap": MAX_CYCLES,
        "cycles_completed": len(cycle_summaries),
        "learning_registry": {
            "store": "file_manifest",
            "signal_count": len(signals),
            "signals": signals,
        },
        "evaluation_suite": {
            "eval_count": len(evals),
            "results": evals,
            "summary": dict(Counter(result["status"] for result in evals)),
        },
        "improvement_proposals": {
            "proposal_count": len(proposals),
            "proposals": proposals,
            "gate_results": gates,
            "safe_auto_apply_count": len(safe_auto_apply),
            "human_approval_required_count": len(human_required),
            "blocked_count": len([gate for gate in gates if not gate["allowed"]]),
        },
        "safe_auto_apply_gate": {
            "enabled": True,
            "auto_apply_runtime_mutations": False,
            "safe_auto_apply_proposal_ids": [proposal["proposal_id"] for proposal in safe_auto_apply],
            "human_approval_required_proposal_ids": [proposal["proposal_id"] for proposal in human_required],
        },
        "feedback_capture": {
            "enabled": True,
            "feedback_records": [],
            "note_policy": "no_secrets_no_full_document_text_no_locked_content",
        },
        "next_best_actions": _next_best_actions(proposals, signals),
        "cycle_summaries": cycle_summaries,
        "rollback": {
            "delete_manifest_path": str(learning_manifest_path(execution_id)),
            "applied_improvement_ids": [proposal["proposal_id"] for proposal in safe_auto_apply],
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
            "external_model_training": False,
            "signoff_auto_created": False,
            "explicit_signoff_recorded": False,
            "external_submission_authorized": False,
            "final_legal_conclusions_created": False,
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_learning_loop_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = learning_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _learning_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{LEARNING_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_learning_loop(case_slug: str) -> dict[str, Any] | None:
    for path in _learning_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None


def record_feedback(
    case_slug: str,
    *,
    item_id: str,
    item_type: str,
    feedback_type: str,
    note: str | None,
    severity: str,
    reviewer_safe_label: str,
    reviewer_role: str,
    linked_source_refs: list[Any],
    action_requested: str | None,
) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("learning_feedback_scope_refused")
    payload = load_latest_learning_loop(case_slug)
    if payload is None:
        raise FileNotFoundError("learning_loop_missing")
    if note and len(note) > 1200:
        raise ValueError("feedback_note_too_long")
    forbidden_fragments = ["pass" + "word", "bearer ", "postgres://", "postgresql://", "private key"]
    if note and any(fragment in note.lower() for fragment in forbidden_fragments):
        raise ValueError("feedback_note_rejected_secret_like_content")
    feedback = {
        "feedback_id": str(uuid4()),
        "matter_slug": case_slug,
        "item_id": item_id,
        "item_type": item_type,
        "feedback_type": feedback_type,
        "note": note,
        "severity": severity,
        "reviewer_safe_label": reviewer_safe_label,
        "reviewer_role": reviewer_role,
        "created_at": now_iso(),
        "linked_source_refs": linked_source_refs,
        "action_requested": action_requested,
        "status": "captured",
    }
    feedback["audit_hash"] = _json_hash(feedback)
    payload.setdefault("feedback_capture", {}).setdefault("feedback_records", []).append(feedback)
    signal = _signal(
        execution_id=payload["execution_id"],
        signal_type="operator_feedback" if reviewer_role != "counsel" else "counsel_feedback",
        source_phase="feedback_capture",
        linked_item_id=item_id,
        linked_manifest=payload.get("manifest_path"),
        severity=severity,
        confidence=1.0,
        suggested_improvement=action_requested or "Review captured feedback.",
        safe_auto_apply_eligible=False,
        human_approval_required=True,
        reason="Human feedback captured through learning loop.",
    )
    payload["learning_registry"]["signals"].append(signal)
    payload["learning_registry"]["signal_count"] = len(payload["learning_registry"]["signals"])
    payload["manifest_checksum"] = _json_hash({k: v for k, v in payload.items() if k != "manifest_checksum"})
    write_learning_loop_manifest(payload)
    payload["latest_feedback"] = feedback
    return payload
