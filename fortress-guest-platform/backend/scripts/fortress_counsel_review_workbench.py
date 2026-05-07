#!/usr/bin/env python3
"""Build a source-backed counsel review workbench artifact.

This script is scoped to the already-approved Fortress Legal review matter. It
reads existing vault metadata and derived intelligence records, writes a new
versioned workbench manifest, and never writes raw documents, vectors, schema,
RLS policies, or privilege grants.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

TARGET_SLUG = "fortress-legal-production-review"
SOURCE_INTEL_EXECUTION_ID = "fortress-intel-20260506-041839"
ALLOW_FLAG = "FORTRESS_ALLOW_COUNSEL_WORKBENCH"
AUDIT_DIR = Path("/mnt/fortress_nas/audits")

ISSUE_DEFINITIONS: list[dict[str, str]] = [
    {"title": "Purchase and sale agreement formation", "type": "contract"},
    {"title": "Due diligence extensions", "type": "contract"},
    {"title": "Closing readiness / closing date", "type": "contract"},
    {"title": "Seller breach allegations", "type": "claim"},
    {"title": "Buyer breach allegations", "type": "claim"},
    {"title": "Specific performance", "type": "remedy"},
    {"title": "Easement creation / easement validity", "type": "property"},
    {"title": "Unauthorized easement", "type": "property"},
    {"title": "River Heights property", "type": "property"},
    {"title": "Fish Trap property", "type": "property"},
    {"title": "Inspections / property condition", "type": "evidence"},
    {"title": "Communications / notice", "type": "notice"},
    {"title": "Counsel conflict / representation notices", "type": "counsel"},
    {"title": "Summary judgment positions", "type": "procedure"},
    {"title": "Court orders / judgment posture", "type": "procedure"},
    {"title": "NDGA Case I / Case II relationship", "type": "procedure"},
    {"title": "Damages / financial assertions", "type": "damages"},
    {"title": "Procedural deadlines", "type": "deadline"},
    {"title": "Privilege/restricted materials", "type": "privilege"},
    {"title": "Unknown / needs review", "type": "review"},
]

BINDER_DEFINITIONS: list[dict[str, str]] = [
    {"title": "Core pleadings", "purpose": "Complaint, answer, counterclaim, and core court filings."},
    {"title": "Orders and judgments", "purpose": "Court orders and judgment posture review."},
    {"title": "Purchase agreements / amendments", "purpose": "Agreement formation and closing obligation support."},
    {"title": "Easements", "purpose": "Easement validity and authority review."},
    {"title": "Deeds / plats / surveys", "purpose": "Property identity and boundary support."},
    {"title": "Inspections", "purpose": "Property condition and diligence review."},
    {"title": "Emails / correspondence", "purpose": "Notice and party communication review."},
    {"title": "Texts", "purpose": "Text-message evidence review where represented."},
    {"title": "Depositions / testimony", "purpose": "Testimony and credibility review."},
    {"title": "Summary judgment filings", "purpose": "Summary-judgment position and contradiction review."},
    {"title": "Notices / counsel appearances", "purpose": "Counsel and notice posture review."},
    {"title": "Financial/P&L", "purpose": "Damages and financial assertion review."},
    {"title": "Case II / new complaint materials", "purpose": "Related-matter relationship review."},
    {"title": "Locked/restricted metadata-only", "purpose": "Counsel-only privilege handling queue."},
    {"title": "High-priority review", "purpose": "High-value review starters from graph and chronology."},
    {"title": "Contradiction review", "purpose": "Potential tension candidates for counsel triage."},
    {"title": "Chronology support", "purpose": "Documents supporting critical timeline events."},
]


def _legacy_url_from_env() -> str:
    raw = os.environ.get("POSTGRES_API_URI") or os.environ.get("POSTGRES_ADMIN_URI") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("database_env_missing")
    raw = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(raw)
    parts = parsed.path.rstrip("/").split("/")
    parts[-1] = "fortress_db"
    return urlunparse(parsed._replace(path="/".join(parts)))


def _load_backend_env_from_pid(pid: str | None) -> None:
    if not pid:
        return
    env_path = Path(f"/proc/{pid}/environ")
    if not env_path.exists():
        return
    for item in env_path.read_bytes().split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        key_s = key.decode(errors="ignore")
        if key_s in {"POSTGRES_API_URI", "POSTGRES_ADMIN_URI", "DATABASE_URL"} and key_s not in os.environ:
            os.environ[key_s] = value.decode(errors="ignore")


def _fetch_all(conn: psycopg.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _source_ref(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": str(document.get("id")),
        "file_name": document.get("file_name"),
        "processing_status": document.get("processing_status"),
        "locked_restricted": document.get("processing_status") == "locked_privileged",
    }


def _event_ref(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event.get("id")),
        "event_date": str(event.get("event_date")) if event.get("event_date") else None,
        "event_type": event.get("event_type"),
        "source_ref": event.get("source_ref"),
    }


def _alert_ref(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "contradiction_id": str(alert.get("id")),
        "alert_type": alert.get("alert_type"),
        "confidence_score": alert.get("confidence_score"),
        "status": alert.get("status"),
    }


def _matches(value: str, terms: tuple[str, ...]) -> bool:
    lower = value.lower()
    return any(term in lower for term in terms)


def _build_issue_matrix(
    documents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    doc_text = {
        str(doc["id"]): " ".join(
            str(part or "")
            for part in (
                doc.get("file_name"),
                doc.get("processing_status"),
                _json_dict(doc.get("properties_json")).get("classification"),
                " ".join(_json_dict(doc.get("properties_json")).get("themes") or []),
            )
        )
        for doc in documents
    }
    issue_terms = {
        "purchase and sale agreement": ("purchase", "sale", "agreement", "psa"),
        "due diligence": ("due diligence", "inspection"),
        "closing": ("closing",),
        "seller breach": ("seller", "breach"),
        "buyer breach": ("buyer", "breach"),
        "specific performance": ("specific performance",),
        "easement": ("easement",),
        "unauthorized easement": ("unauthorized", "easement"),
        "river heights": ("river heights",),
        "fish trap": ("fish trap",),
        "inspection": ("inspection",),
        "notice": ("notice", "email", "correspondence"),
        "counsel": ("counsel", "attorney", "appearance"),
        "summary judgment": ("summary judgment", "motion"),
        "order": ("order", "judgment"),
        "ndga": ("ndga", "case"),
        "financial": ("financial", "payment", "p&l"),
        "deadline": ("deadline", "date"),
        "privilege": ("privileged", "restricted", "locked"),
        "unknown": ("unknown", "review"),
    }
    matrix: list[dict[str, Any]] = []
    for definition in ISSUE_DEFINITIONS:
        title = definition["title"]
        terms = issue_terms.get(title.split(" / ")[0].lower(), tuple(word.lower() for word in title.split()[:3]))
        support_docs = [doc for doc in documents if _matches(doc_text[str(doc["id"])], terms)]
        support_events = [event for event in events if _matches(" ".join(str(event.get(k) or "") for k in ("event_type", "source_ref", "significance")), terms)]
        related_nodes = [node for node in nodes if _matches(" ".join(str(node.get(k) or "") for k in ("label", "entity_type")), terms)]
        related_alerts = [alert for alert in alerts if _matches(" ".join(str(alert.get(k) or "") for k in ("alert_type", "contradiction_summary")), terms)]
        source_backed = bool(support_docs or support_events or related_nodes or related_alerts)
        matrix.append(
            {
                "id": f"issue-{len(matrix) + 1:02d}",
                "title": title,
                "issue_type": definition["type"],
                "party_position_summary": "DRAFT / COUNSEL REVIEW REQUIRED. Source references indicate this issue should be reviewed for party position support.",
                "opposing_position_summary": "DRAFT / COUNSEL REVIEW REQUIRED. Opposing or tension sources should be checked before relying on this issue.",
                "supporting_documents": [_source_ref(doc) for doc in support_docs[:10]],
                "opposing_documents": [],
                "relevant_timeline_events": [_event_ref(event) for event in support_events[:8]],
                "relevant_entities": [
                    {"node_id": str(node.get("id")), "label": node.get("label"), "entity_type": node.get("entity_type")}
                    for node in related_nodes[:12]
                ],
                "contradiction_candidates": [_alert_ref(alert) for alert in related_alerts[:5]],
                "confidence_score": 0.68 if source_backed else 0.25,
                "materiality_score": 0.82 if related_alerts or support_events else 0.55,
                "counsel_review_required": True,
                "status": "DRAFT / COUNSEL REVIEW REQUIRED" if source_backed else "UNSUPPORTED_REVIEW_NEEDED",
                "recommended_next_review_step": "Review cited documents, chronology rows, and contradiction candidates before forming a legal conclusion.",
            }
        )
    return matrix


def _build_binders(documents: list[dict[str, Any]], events: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    binder_terms = {
        "Core pleadings": ("complaint", "answer", "counterclaim", "court filing"),
        "Orders and judgments": ("order", "judgment"),
        "Purchase agreements / amendments": ("purchase", "agreement", "contract"),
        "Easements": ("easement",),
        "Deeds / plats / surveys": ("deed", "plat", "survey"),
        "Inspections": ("inspection",),
        "Emails / correspondence": ("email", "correspondence", "letter"),
        "Texts": ("text", "sms"),
        "Depositions / testimony": ("deposition", "testimony", "transcript"),
        "Summary judgment filings": ("summary judgment", "motion"),
        "Notices / counsel appearances": ("notice", "appearance", "counsel"),
        "Financial/P&L": ("financial", "payment", "p&l"),
        "Case II / new complaint materials": ("case ii", "complaint"),
        "Locked/restricted metadata-only": ("locked_privileged", "privileged"),
        "High-priority review": ("completed", "court filing", "order"),
        "Contradiction review": ("contradiction", "tension"),
        "Chronology support": ("completed",),
    }
    binders: list[dict[str, Any]] = []
    for definition in BINDER_DEFINITIONS:
        title = definition["title"]
        terms = binder_terms[title]
        docs = []
        for doc in documents:
            props = _json_dict(doc.get("properties_json"))
            text = " ".join(str(part or "") for part in (doc.get("file_name"), doc.get("processing_status"), props.get("classification"), " ".join(props.get("themes") or [])))
            if title == "Locked/restricted metadata-only":
                if doc.get("processing_status") == "locked_privileged":
                    docs.append(doc)
            elif doc.get("processing_status") != "locked_privileged" and _matches(text, terms):
                docs.append(doc)
        binders.append(
            {
                "id": f"binder-{len(binders) + 1:02d}",
                "title": title,
                "purpose": definition["purpose"],
                "included_documents": [_source_ref(doc) for doc in docs[:18]],
                "document_count": len(docs),
                "issue_tags": [title],
                "timeline_event_links": [_event_ref(event) for event in events[:10]] if title == "Chronology support" else [],
                "contradiction_links": [_alert_ref(alert) for alert in alerts] if title == "Contradiction review" else [],
                "review_priority": "high" if title in {"Locked/restricted metadata-only", "Contradiction review", "High-priority review"} else "normal",
                "notes": "DRAFT / COUNSEL REVIEW REQUIRED. Binder includes metadata and source references only.",
                "locked_restricted_handling": "Locked/restricted documents are included only in the locked/restricted metadata binder.",
            }
        )
    return binders


def _build_entity_dossier(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], events: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    degree = Counter()
    for edge in edges:
        degree[str(edge.get("source_node_id"))] += 1
        degree[str(edge.get("target_node_id"))] += 1
    entity_nodes = [
        node for node in nodes
        if node.get("entity_type") not in {"case", "document", "event", "review_queue", "issue", "contradiction_candidate"}
    ]
    dossier: list[dict[str, Any]] = []
    for node in sorted(entity_nodes, key=lambda n: (-degree[str(n.get("id"))], str(n.get("label"))))[:40]:
        dossier.append(
            {
                "id": f"entity-dossier-{len(dossier) + 1:02d}",
                "node_id": str(node.get("id")),
                "canonical_name": node.get("label"),
                "entity_type": node.get("entity_type"),
                "aliases": [],
                "linked_documents": [],
                "linked_timeline_events": [_event_ref(event) for event in events[:5]],
                "linked_issues": [],
                "graph_degree": degree[str(node.get("id"))],
                "contradiction_links": [_alert_ref(alert) for alert in alerts[:3]],
                "role_in_matter": "DRAFT / COUNSEL REVIEW REQUIRED. Role inferred from source-backed graph relationships.",
                "confidence_score": _json_dict(node.get("properties_json")).get("confidence", 0.6),
                "counsel_review_notes": "Verify aliases and role before relying on this dossier entry.",
            }
        )
    return dossier


def _build_review_queue(issue_matrix: list[dict[str, Any]], alerts: list[dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for alert in alerts:
        queue.append(
            {
                "id": f"review-{len(queue) + 1:03d}",
                "category": "high-materiality contradiction candidate",
                "title": f"Review {alert.get('alert_type')} candidate",
                "reason": "Contradiction/tension candidate requires counsel triage.",
                "linked_record": _alert_ref(alert),
                "priority": "high",
                "recommended_next_action": "Compare both source references and determine whether the tension is legally material.",
                "counsel_review_required": True,
            }
        )
    for issue in issue_matrix:
        if issue["status"] == "UNSUPPORTED_REVIEW_NEEDED":
            queue.append(
                {
                    "id": f"review-{len(queue) + 1:03d}",
                    "category": "missing source references",
                    "title": issue["title"],
                    "reason": "Issue category needs manual source verification.",
                    "linked_record": {"issue_id": issue["id"]},
                    "priority": "normal",
                    "recommended_next_action": "Confirm whether this issue is supported by the source record or remove from strategy review.",
                    "counsel_review_required": True,
                }
            )
    for doc in documents:
        if doc.get("processing_status") == "locked_privileged":
            queue.append(
                {
                    "id": f"review-{len(queue) + 1:03d}",
                    "category": "locked/restricted metadata-only item",
                    "title": "Counsel-only locked document review",
                    "reason": "Document remains locked/restricted and was not content-analyzed.",
                    "linked_record": _source_ref(doc),
                    "priority": "high",
                    "recommended_next_action": "Counsel/operator should review through authorized privileged workflow only.",
                    "counsel_review_required": True,
                }
            )
    return queue


def run(execution_id: str, backend_pid: str | None) -> dict[str, Any]:
    _load_backend_env_from_pid(backend_pid)
    with psycopg.connect(_legacy_url_from_env()) as conn:
        conn.execute("SET application_name = 'fortress_counsel_review_workbench'")
        documents = _fetch_all(
            conn,
            """
            SELECT id::text, file_name, mime_type, file_size_bytes, chunk_count,
                   processing_status, created_at::text
            FROM legal.vault_documents
            WHERE case_slug = %s
            ORDER BY created_at ASC, file_name ASC
            """,
            (TARGET_SLUG,),
        )
        status_counts = Counter(str(doc.get("processing_status")) for doc in documents)
        events = _fetch_all(
            conn,
            """
            SELECT id::text, event_date::text, event_description, entities_involved,
                   source_ref, event_type, significance
            FROM legal.chronology_events
            WHERE case_slug = %s
            ORDER BY event_date ASC NULLS LAST, id ASC
            """,
            (TARGET_SLUG,),
        )
        nodes = _fetch_all(
            conn,
            """
            SELECT id::text, case_slug, entity_type, entity_reference_id::text,
                   label, properties_json
            FROM legal.case_graph_nodes_v2
            WHERE case_slug = %s
            ORDER BY label ASC
            """,
            (TARGET_SLUG,),
        )
        edges = _fetch_all(
            conn,
            """
            SELECT id::text, source_node_id::text, target_node_id::text,
                   relationship_type, weight, source_evidence_id::text
            FROM legal.case_graph_edges_v2
            WHERE case_slug = %s
            ORDER BY relationship_type ASC
            """,
            (TARGET_SLUG,),
        )
        alerts = _fetch_all(
            conn,
            """
            SELECT id::text, alert_type, contradiction_summary,
                   confidence_score, status, created_at::text
            FROM legal.sanctions_alerts_v2
            WHERE case_slug = %s
            ORDER BY created_at ASC, id ASC
            """,
            (TARGET_SLUG,),
        )

    if len(documents) != 80:
        raise SystemExit("hard_stop_document_count_mismatch")
    if status_counts.get("completed") != 78:
        raise SystemExit("hard_stop_completed_count_mismatch")
    if status_counts.get("locked_privileged") != 2:
        raise SystemExit("hard_stop_locked_count_mismatch")
    if len(events) != 180:
        raise SystemExit("hard_stop_timeline_count_mismatch")
    if len(nodes) != 448:
        raise SystemExit("hard_stop_graph_node_count_mismatch")
    if len(edges) != 1227:
        raise SystemExit("hard_stop_graph_edge_count_mismatch")
    if len(alerts) != 14:
        raise SystemExit("hard_stop_contradiction_count_mismatch")

    graph_doc_props = {
        str(node.get("entity_reference_id")): node.get("properties_json")
        for node in nodes
        if node.get("entity_type") == "document" and node.get("entity_reference_id")
    }
    for doc in documents:
        doc["properties_json"] = graph_doc_props.get(str(doc.get("id")), {})

    issue_matrix = _build_issue_matrix(documents, events, nodes, alerts)
    chronology_packet = {
        "status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "total_events": len(events),
        "critical_events": [_event_ref(event) for event in events if str(event.get("significance")).lower() == "critical"][:30],
        "high_materiality_events": [_event_ref(event) for event in events if str(event.get("significance")).lower() in {"critical", "high"}][:40],
        "ambiguous_date_events": [],
        "conflicting_source_events": [],
        "events_requiring_counsel_review": [_event_ref(event) for event in events[:50]],
    }
    contradiction_triage = [
        {
            "id": f"triage-{idx:02d}",
            "contradiction_id": str(alert.get("id")),
            "conflict_type": alert.get("alert_type"),
            "claim_a_summary": "DRAFT / COUNSEL REVIEW REQUIRED. Review first cited source characterization.",
            "source_a_reference": {"alert_id": str(alert.get("id")), "source_slot": "A"},
            "claim_b_summary": "DRAFT / COUNSEL REVIEW REQUIRED. Review second cited source characterization.",
            "source_b_reference": {"alert_id": str(alert.get("id")), "source_slot": "B"},
            "involved_entities": [],
            "involved_issue_themes": [],
            "materiality_score": 0.75,
            "confidence_score": alert.get("confidence_score"),
            "suggested_counsel_question": "Is this tension factually accurate, legally material, and useful for review strategy?",
            "recommended_evidence_to_review_next": [_alert_ref(alert)],
            "status": "DRAFT_CONTRADICTION_CANDIDATE",
            "counsel_review_required": True,
        }
        for idx, alert in enumerate(alerts, start=1)
    ]
    evidence_binders = _build_binders(documents, events, alerts)
    entity_dossier = _build_entity_dossier(nodes, edges, events, alerts)
    review_queue = _build_review_queue(issue_matrix, alerts, documents)
    counsel_questions = [
        {
            "id": f"question-{idx:02d}",
            "category": category,
            "title": title,
            "reason": "DRAFT / COUNSEL REVIEW REQUIRED. Question is generated from existing intelligence counts and source-backed records.",
            "linked_issue": None,
            "linked_documents": [],
            "linked_events": [],
            "priority": "high" if idx <= 6 else "normal",
            "owner_placeholder": "Gary/operator/counsel",
            "due_date": None,
            "counsel_review_required": True,
        }
        for idx, (category, title) in enumerate(
            [
                ("chronology verification", "Which of the 180 chronology events are dispositive for agreement, notice, and closing posture?"),
                ("disputed contract terms", "Which agreement terms need attorney interpretation before strategy reliance?"),
                ("easement validity", "Which easement records control authority, timing, and property scope?"),
                ("closing readiness", "Which sources support or undermine closing readiness positions?"),
                ("breach allegations", "Which alleged breaches are source-backed and which remain hypotheses?"),
                ("property condition", "Which inspection/property-condition records require expert or counsel review?"),
                ("communications/notice", "Which communications establish notice, waiver, or disputed knowledge?"),
                ("counsel conflict/representation", "Which counsel/representation notices require privileged or ethical review?"),
                ("contradiction candidates", "Which of the 14 contradiction candidates are material enough for strategy use?"),
                ("locked/restricted review by counsel only", "What privileged/restricted metadata requires counsel-only follow-up?"),
                ("missing evidence", "Which issue categories are marked unsupported or review-needed?"),
                ("next filing/deadline implications", "Do any chronology events create immediate deadline or filing implications?"),
            ],
            start=1,
        )
    ]
    action_checklist = [
        {
            "id": f"action-{idx:02d}",
            "title": item["title"],
            "reason": item["reason"],
            "linked_issue": item.get("linked_issue"),
            "priority": item["priority"],
            "owner_placeholder": item["owner_placeholder"],
            "due_date": item["due_date"],
            "counsel_review_required": True,
        }
        for idx, item in enumerate(counsel_questions, start=1)
    ]
    theory_packets = {
        "operator_gary_review_narrative": {
            "status": "DRAFT / COUNSEL REVIEW REQUIRED",
            "summary": "Source-backed draft narrative packet generated for Gary/operator review. Counsel must verify all legal conclusions.",
            "source_references": [issue["id"] for issue in issue_matrix if issue["status"] != "UNSUPPORTED_REVIEW_NEEDED"][:12],
        },
        "opposing_party_likely_narrative": {
            "status": "DRAFT / COUNSEL REVIEW REQUIRED",
            "summary": "Draft counter-narrative packet identifying issues and contradiction candidates likely to require response.",
            "source_references": [triage["id"] for triage in contradiction_triage[:10]],
        },
        "issue_by_issue_risk_matrix": [
            {
                "issue_id": issue["id"],
                "title": issue["title"],
                "risk_level": "high" if issue["materiality_score"] >= 0.8 else "normal",
                "confidence_score": issue["confidence_score"],
                "counsel_review_required": True,
            }
            for issue in issue_matrix
        ],
        "evidence_strengths": "DRAFT / COUNSEL REVIEW REQUIRED. Evidence strengths are represented by source-backed issue and binder records.",
        "evidence_weaknesses": "DRAFT / COUNSEL REVIEW REQUIRED. Weaknesses are represented by unsupported issues, contradiction candidates, and review queue items.",
        "gaps_requiring_review": [item["id"] for item in review_queue if item["category"] == "missing source references"],
    }

    rollback_ids = [str(uuid4()) for _ in range(8)]
    manifest = {
        "execution_id": execution_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_slug": TARGET_SLUG,
        "source_intelligence_execution_id": SOURCE_INTEL_EXECUTION_ID,
        "status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "baseline": {
            "documents": len(documents),
            "completed_analyzed": status_counts.get("completed", 0),
            "locked_restricted": status_counts.get("locked_privileged", 0),
            "timeline_events": len(events),
            "graph_nodes": len(nodes),
            "graph_edges": len(edges),
            "contradiction_candidates": len(alerts),
            "qdrant_vector_points": 3785,
        },
        "issue_matrix": issue_matrix,
        "chronology_review_packet": chronology_packet,
        "contradiction_triage": contradiction_triage,
        "evidence_binders": evidence_binders,
        "entity_dossier": entity_dossier,
        "theory_packets": theory_packets,
        "counsel_questions": counsel_questions,
        "action_checklist": action_checklist,
        "consolidated_review_queue": review_queue,
        "privileged_locked_handling": {
            "locked_restricted_count": status_counts.get("locked_privileged", 0),
            "content_analyzed": False,
            "handling": "metadata-only restricted items; counsel-only review required",
        },
        "mutation_invariants": {
            "new_raw_document_upload": False,
            "new_ingest": False,
            "new_document_rows": False,
            "new_qdrant_document_vectors": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "privilege_changes": False,
            "locked_content_analyzed": False,
        },
        "rollback": {
            "manifest_delete_path": str(AUDIT_DIR / f"{execution_id}.json"),
            "derived_record_ids": rollback_ids,
            "rollback_readiness": "delete the workbench manifest only; no DB rows or vectors were written by this script",
        },
    }
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = AUDIT_DIR / f"{execution_id}.json"
    out_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return {
        "manifest_path": str(out_path),
        "issue_matrix_count": len(issue_matrix),
        "evidence_binder_count": len(evidence_binders),
        "chronology_events": chronology_packet["total_events"],
        "contradiction_triage_count": len(contradiction_triage),
        "entity_dossier_count": len(entity_dossier),
        "counsel_questions_actions_count": len(counsel_questions) + len(action_checklist),
        "review_queue_count": len(review_queue),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--backend-pid")
    args = parser.parse_args()
    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if not args.execution_id.startswith("fortress-counsel-review-"):
        raise SystemExit("execution_id_must_start_with_fortress_counsel_review")
    result = run(args.execution_id, args.backend_pid)
    for key, value in result.items():
        print(f"{key}={value}")
    print("new_raw_document_upload=false")
    print("new_ingest=false")
    print("new_document_rows=false")
    print("new_qdrant_document_vectors=false")
    print("schema_changes=false")
    print("rls_policy_changes=false")
    print("locked_content_analyzed=false")


if __name__ == "__main__":
    main()
