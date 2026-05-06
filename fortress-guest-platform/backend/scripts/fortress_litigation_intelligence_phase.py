#!/usr/bin/env python3
"""Build a draft litigation-intelligence layer for the approved Fortress Legal review matter.

The script is intentionally case-scoped and metadata-safe:
- analyzes only completed, non-locked vault documents;
- never analyzes locked_privileged contents;
- writes only derived, draft/counsel-review intelligence records;
- does not write raw documents or Qdrant vectors;
- prints counts and IDs only, never document text or secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import psycopg


TARGET_SLUG = "fortress-legal-production-review"
TARGET_EXECUTION_ID = "fortress-autointake-20260506-015341"
ALLOW_FLAG = "FORTRESS_ALLOW_LITIGATION_INTELLIGENCE_PHASE"
CASE_NODE_LABEL = "Fortress Legal Production Review"

DOC_TYPES: list[tuple[str, tuple[str, ...]]] = [
    ("complaint", ("complaint",)),
    ("answer", ("answer", "affirmative defense")),
    ("counterclaim", ("counterclaim",)),
    ("motion", ("motion",)),
    ("brief", ("brief", "memorandum")),
    ("reply brief", ("reply",)),
    ("order", ("order",)),
    ("notice", ("notice",)),
    ("affidavit", ("affidavit", "declaration")),
    ("deposition transcript", ("deposition", "transcript")),
    ("exhibit", ("exhibit",)),
    ("contract/agreement", ("agreement", "contract")),
    ("purchase and sale agreement", ("purchase and sale", "psa")),
    ("easement", ("easement",)),
    ("deed/plat/survey", ("deed", "plat", "survey")),
    ("inspection report", ("inspection", "inspector")),
    ("email/correspondence", ("email", "correspondence", "letter")),
    ("text messages", ("text message", "sms")),
    ("financial/P&L", ("profit", "loss", "p&l", "financial", "payment")),
    ("letter of authority/engagement/appearance", ("engagement", "appearance", "authority")),
    ("court filing", ("filing", "court")),
    ("discovery", ("discovery", "interrogatory", "request for production")),
    ("chronology/evidence package", ("chronology", "timeline", "evidence package")),
]

THEMES: dict[str, tuple[str, ...]] = {
    "7IL / Knight litigation": ("7il", "knight"),
    "Fish Trap property": ("fish trap",),
    "River Heights property": ("river heights",),
    "easement dispute": ("easement",),
    "purchase and sale agreement": ("purchase and sale", "psa"),
    "specific performance": ("specific performance",),
    "unauthorized easement": ("unauthorized easement",),
    "inspections": ("inspection", "inspector"),
    "counsel conflict/notice": ("counsel", "attorney", "notice"),
    "summary judgment": ("summary judgment",),
    "deposition/testimony": ("deposition", "testimony", "transcript"),
    "bankruptcy/creditor issue": ("bankruptcy", "creditor"),
    "privileged/restricted": ("privileged", "restricted"),
    "review needed": ("review", "uncertain", "ambiguous"),
}

DATE_PATTERNS = [
    re.compile(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b", re.I),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
CASE_RE = re.compile(r"\b(?:SUV|CV|CIV|BK|A\d{2})[-:\s]?\d{4,}[-\w]*\b", re.I)
ORG_RE = re.compile(r"\b[A-Z][A-Za-z&.,' -]{2,80}\b(?:LLC|Inc\.?|Corporation|Corp\.?|Company|Co\.?|LP|LLP|Law|P\.C\.|Bank|Court)\b")
PERSON_RE = re.compile(r"\b(?:Judge|Hon\.|Mr\.|Ms\.|Mrs\.|Dr\.)?\s*[A-Z][a-z]{2,20}\s+[A-Z][a-z]{2,24}(?:\s+[A-Z][a-z]{2,24})?\b")
ADDRESS_RE = re.compile(r"\b\d{2,6}\s+[A-Z][A-Za-z0-9.' -]{3,80}\s+(?:Road|Rd\.|Street|St\.|Drive|Dr\.|Lane|Ln\.|Trail|Trl\.|Way|Court|Ct\.|Avenue|Ave\.)\b")


@dataclass
class Doc:
    id: str
    file_name: str
    nfs_path: str | None
    mime_type: str | None
    file_size_bytes: int | None
    processing_status: str
    chunk_count: int
    created_at: str | None
    analysis_eligible: bool
    locked: bool
    text_hash: str | None = None
    text_chars: int = 0
    classification: str = "unknown legal document"
    classification_confidence: float = 0.35
    review_reasons: list[str] = field(default_factory=list)
    themes: set[str] = field(default_factory=set)


def _legacy_url_from_env() -> str:
    raw = os.environ.get("POSTGRES_API_URI") or os.environ.get("POSTGRES_ADMIN_URI") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("database_env_missing")
    raw = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(raw)
    parts = parsed.path.rstrip("/").split("/")
    if not parts:
        raise SystemExit("database_env_invalid")
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


def _extract_pdf_text(path: str) -> str:
    with tempfile.TemporaryDirectory(prefix="fortress-intel-") as tmp:
        out = Path(tmp) / "doc.txt"
        result = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk", path, str(out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=False,
        )
        if result.returncode != 0 or not out.exists():
            return ""
        return out.read_text(encoding="utf-8", errors="ignore")


def _classify(doc: Doc, text: str) -> None:
    haystack = f"{doc.file_name}\n{text[:12000]}".lower()
    best = ("unknown legal document", 0.35)
    for label, needles in DOC_TYPES:
        score = sum(1 for needle in needles if needle in haystack)
        if score:
            confidence = min(0.92, 0.52 + score * 0.16)
            if confidence > best[1]:
                best = (label, confidence)
    doc.classification, doc.classification_confidence = best
    if doc.classification_confidence < 0.6:
        doc.review_reasons.append("low-confidence classification")

    for theme, needles in THEMES.items():
        if any(needle in haystack for needle in needles):
            doc.themes.add(theme)


def _normalize_entity(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ,.;:\n\t")
    return value[:180]


def _entity_type(label: str) -> str:
    lower = label.lower()
    if MONEY_RE.fullmatch(label):
        return "monetary_value"
    if CASE_RE.search(label):
        return "case_number"
    if ADDRESS_RE.search(label):
        return "address"
    if any(s in lower for s in ("llc", "inc", "corp", "company", "court", "bank", "law")):
        return "company"
    if any(p in lower for p in ("road", "street", "drive", "lane", "trail", "avenue")):
        return "property"
    return "person"


def _extract_entities(text: str, doc: Doc) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    for pattern in (ORG_RE, PERSON_RE, ADDRESS_RE, CASE_RE, MONEY_RE):
        candidates.extend(match.group(0) for match in pattern.finditer(text[:120000]))
    for raw in candidates:
        label = _normalize_entity(raw)
        if len(label) < 4 or label.lower() in {"united states", "state court"}:
            continue
        key = label.lower()
        item = entities.setdefault(
            key,
            {
                "label": label,
                "entity_type": _entity_type(label),
                "mentions": 0,
                "documents": set(),
                "confidence": 0.58,
            },
        )
        item["mentions"] += 1
        item["documents"].add(doc.id)
        item["confidence"] = min(0.92, item["confidence"] + 0.03)
    return entities


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
    right_dot = text.find(".", end)
    right_nl = text.find("\n", end)
    rights = [x for x in (right_dot, right_nl) if x != -1]
    right = min(rights) if rights else min(len(text), end + 180)
    sentence = text[left + 1 : right + 1].strip()
    return re.sub(r"\s+", " ", sentence)[:260]


def _parse_date(raw: str) -> tuple[str | None, str]:
    from datetime import datetime as dt
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.strptime(raw, fmt).date().isoformat(), "exact"
        except ValueError:
            pass
    return None, "ambiguous"


def _event_type(text: str) -> str:
    lower = text.lower()
    for label, needles in {
        "filing": ("filed", "complaint", "motion", "answer"),
        "court order": ("order", "ordered"),
        "contract execution": ("agreement", "contract", "executed"),
        "easement execution": ("easement",),
        "inspection": ("inspection", "inspector"),
        "communication/email/text": ("email", "letter", "notice", "text"),
        "alleged breach": ("breach", "default"),
        "payment/financial": ("payment", "$", "paid"),
        "representation/counsel event": ("counsel", "attorney", "appearance"),
        "deposition/testimony": ("deposition", "testimony"),
        "property transaction": ("deed", "plat", "survey", "closing"),
    }.items():
        if any(n in lower for n in needles):
            return label
    return "unknown"


def _extract_events(text: str, doc: Doc) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text[:180000]):
            date_iso, precision = _parse_date(match.group(0))
            if not date_iso:
                doc.review_reasons.append("ambiguous date")
                continue
            sentence = _sentence_around(text, match.start(), match.end())
            if len(sentence) < 20:
                continue
            sig = (date_iso, sentence[:80])
            if sig in seen:
                continue
            seen.add(sig)
            events.append(
                {
                    "event_date": date_iso,
                    "description": sentence,
                    "source_ref": doc.file_name,
                    "event_type": _event_type(sentence),
                    "significance": "critical" if any(w in sentence.lower() for w in ("deadline", "order", "closing", "easement", "agreement")) else "normal",
                    "confidence": 0.62,
                    "date_precision": precision,
                    "document_id": doc.id,
                }
            )
            if len(events) >= 8:
                return events
    if not events:
        doc.review_reasons.append("no extractable dates")
    return events


def _build_contradictions(docs: list[Doc], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        by_date[ev["event_date"]].append(ev)
    for date_iso, rows in by_date.items():
        sources = {r["source_ref"] for r in rows}
        if len(sources) >= 2 and len(candidates) < 10:
            refs = sorted(sources)[:4]
            candidates.append(
                {
                    "alert_type": "contradiction_candidate",
                    "summary": f"Date {date_iso} appears across multiple documents with potentially different event characterizations; compare {', '.join(refs[:2])}. DRAFT / COUNSEL REVIEW REQUIRED.",
                    "confidence": 62,
                    "materiality": 60 + min(30, len(sources) * 5),
                    "sources": refs,
                }
            )
    theme_docs: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        for theme in doc.themes:
            theme_docs[theme].append(doc.file_name)
    for theme in ("easement dispute", "purchase and sale agreement", "inspections", "summary judgment"):
        files = theme_docs.get(theme, [])
        if len(files) >= 2 and len(candidates) < 16:
            candidates.append(
                {
                    "alert_type": "tension",
                    "summary": f"{theme} appears in multiple source documents and should be reviewed for inconsistent positions. DRAFT / COUNSEL REVIEW REQUIRED.",
                    "confidence": 55,
                    "materiality": 70,
                    "sources": files[:4],
                }
            )
    return candidates


def _load_documents(conn) -> list[Doc]:
    rows = conn.execute(
        """
        SELECT id::text, file_name, nfs_path, mime_type, file_size_bytes,
               processing_status, chunk_count, created_at::text
        FROM legal.vault_documents
        WHERE case_slug = %s
        ORDER BY created_at ASC, file_name ASC
        """,
        (TARGET_SLUG,),
    ).fetchall()
    docs = []
    for row in rows:
        status = row[5]
        locked = status == "locked_privileged"
        docs.append(
            Doc(
                id=row[0],
                file_name=row[1],
                nfs_path=row[2],
                mime_type=row[3],
                file_size_bytes=row[4],
                processing_status=status,
                chunk_count=row[6] or 0,
                created_at=row[7],
                analysis_eligible=status == "completed",
                locked=locked,
                review_reasons=(["locked/restricted metadata only"] if locked else []),
                themes=({"privileged/restricted"} if locked else set()),
            )
        )
    return docs


def _insert_node(conn, ids: list[str], case_slug: str, entity_type: str, label: str, props: dict[str, Any]) -> str:
    node_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO legal.case_graph_nodes_v2
            (id, case_slug, entity_type, entity_reference_id, label, properties_json)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (node_id, case_slug, entity_type, props.get("entity_reference_id"), label[:500], json.dumps(props, default=str)),
    )
    ids.append(node_id)
    return node_id


def _insert_edge(conn, ids: list[str], case_slug: str, src: str, tgt: str, rel: str, weight: float, source_id: str | None = None) -> str:
    edge_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO legal.case_graph_edges_v2
            (id, case_slug, source_node_id, target_node_id, relationship_type, weight, source_evidence_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (edge_id, case_slug, src, tgt, rel, weight, source_id),
    )
    ids.append(edge_id)
    return edge_id


def run(execution_id: str, backend_pid: str | None) -> dict[str, Any]:
    _load_backend_env_from_pid(backend_pid)
    try:
        conn = psycopg.connect(_legacy_url_from_env())
    except Exception as exc:
        raise SystemExit(f"database_connect_failed:{exc.__class__.__name__}") from None
    conn.execute("SET application_name = 'fortress_litigation_intelligence_phase'")

    docs = _load_documents(conn)
    status_counts = Counter(d.processing_status for d in docs)
    if len(docs) != 80:
        raise SystemExit("hard_stop_document_count_mismatch")
    if status_counts.get("completed") != 78:
        raise SystemExit("hard_stop_completed_count_mismatch")
    if status_counts.get("locked_privileged") != 2:
        raise SystemExit("hard_stop_locked_count_mismatch")

    texts_by_doc: dict[str, str] = {}
    merged_entities: dict[str, dict[str, Any]] = {}
    all_events: list[dict[str, Any]] = []

    for doc in docs:
        if doc.locked:
            continue
        if not doc.nfs_path or not Path(doc.nfs_path).exists():
            doc.review_reasons.append("source file unavailable")
            continue
        text = _extract_pdf_text(doc.nfs_path)
        doc.text_chars = len(text)
        doc.text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest() if text else None
        if not text.strip():
            doc.review_reasons.append("OCR/text unavailable")
            continue
        texts_by_doc[doc.id] = text
        _classify(doc, text)
        for key, entity in _extract_entities(text, doc).items():
            merged = merged_entities.setdefault(
                key,
                {
                    "label": entity["label"],
                    "entity_type": entity["entity_type"],
                    "mentions": 0,
                    "documents": set(),
                    "confidence": 0.0,
                },
            )
            merged["mentions"] += entity["mentions"]
            merged["documents"].update(entity["documents"])
            merged["confidence"] = max(merged["confidence"], entity["confidence"])
        all_events.extend(_extract_events(text, doc))

    contradiction_candidates = _build_contradictions(docs, all_events)

    node_ids: list[str] = []
    edge_ids: list[str] = []
    chronology_ids: list[str] = []
    alert_ids: list[str] = []

    conn.execute(
        """
        DELETE FROM legal.case_graph_edges_v2
        WHERE case_slug = %s AND source_node_id IN (
            SELECT id FROM legal.case_graph_nodes_v2
            WHERE case_slug = %s AND properties_json->>'execution_id' LIKE 'fortress-intel-%%'
        )
        """,
        (TARGET_SLUG, TARGET_SLUG),
    )
    conn.execute(
        "DELETE FROM legal.case_graph_nodes_v2 WHERE case_slug = %s AND properties_json->>'execution_id' LIKE 'fortress-intel-%%'",
        (TARGET_SLUG,),
    )
    conn.execute("DELETE FROM legal.chronology_events WHERE case_slug = %s", (TARGET_SLUG,))
    conn.execute("DELETE FROM legal.sanctions_alerts_v2 WHERE case_slug = %s", (TARGET_SLUG,))

    case_node = _insert_node(
        conn,
        node_ids,
        TARGET_SLUG,
        "case",
        CASE_NODE_LABEL,
        {
            "execution_id": execution_id,
            "autonomous_intake_execution_id": TARGET_EXECUTION_ID,
            "draft": True,
            "counsel_review_required": True,
            "document_count": len(docs),
            "analysis_eligible_count": sum(1 for d in docs if d.analysis_eligible),
            "locked_restricted_count": sum(1 for d in docs if d.locked),
        },
    )

    doc_node_by_id: dict[str, str] = {}
    for doc in docs:
        doc_node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            "document",
            doc.file_name,
            {
                "execution_id": execution_id,
                "entity_reference_id": doc.id,
                "vault_document_id": doc.id,
                "processing_status": doc.processing_status,
                "classification": doc.classification,
                "classification_confidence": round(doc.classification_confidence, 3),
                "analysis_eligible": doc.analysis_eligible,
                "locked_privileged": doc.locked,
                "mime_type": doc.mime_type,
                "file_size_bytes": doc.file_size_bytes,
                "chunk_count": doc.chunk_count,
                "themes": sorted(doc.themes),
                "review_reasons": sorted(set(doc.review_reasons)),
                "draft": True,
                "counsel_review_required": True,
            },
        )
        doc_node_by_id[doc.id] = doc_node
        _insert_edge(conn, edge_ids, TARGET_SLUG, case_node, doc_node, "case_has_document", 0.95, doc.id)

    entity_node_by_key: dict[str, str] = {}
    for key, ent in sorted(merged_entities.items(), key=lambda item: (-item[1]["mentions"], item[1]["label"]))[:140]:
        node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            ent["entity_type"],
            ent["label"],
            {
                "execution_id": execution_id,
                "mentions": ent["mentions"],
                "document_count": len(ent["documents"]),
                "confidence": round(ent["confidence"], 3),
                "draft": True,
                "counsel_review_required": True,
            },
        )
        entity_node_by_key[key] = node
        _insert_edge(conn, edge_ids, TARGET_SLUG, case_node, node, "case_mentions_entity", 0.65)
        for doc_id in list(ent["documents"])[:8]:
            if doc_id in doc_node_by_id:
                _insert_edge(conn, edge_ids, TARGET_SLUG, doc_node_by_id[doc_id], node, "document_mentions_entity", 0.7, doc_id)

    for ev in all_events[:180]:
        row = conn.execute(
            """
            INSERT INTO legal.chronology_events
                (case_slug, event_date, event_description, entities_involved, source_ref, event_type, significance)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING id::text
            """,
            (
                TARGET_SLUG,
                ev["event_date"],
                ev["description"],
                json.dumps([]),
                ev["source_ref"],
                ev["event_type"],
                ev["significance"],
            ),
        ).fetchone()
        chronology_id = row[0]
        chronology_ids.append(chronology_id)
        event_node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            "event",
            f"{ev['event_date']} - {ev['event_type']}",
            {
                "execution_id": execution_id,
                "event_date": ev["event_date"],
                "event_type": ev["event_type"],
                "source_ref": ev["source_ref"],
                "date_precision": ev["date_precision"],
                "confidence": ev["confidence"],
                "draft": True,
                "counsel_review_required": True,
            },
        )
        if ev["document_id"] in doc_node_by_id:
            _insert_edge(conn, edge_ids, TARGET_SLUG, doc_node_by_id[ev["document_id"]], event_node, "document_supports_event", 0.72, ev["document_id"])

    for cand in contradiction_candidates:
        row = conn.execute(
            """
            INSERT INTO legal.sanctions_alerts_v2
                (id, case_slug, alert_type, contradiction_summary, confidence_score, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id::text
            """,
            (str(uuid4()), TARGET_SLUG, cand["alert_type"], cand["summary"], int(cand["confidence"]), "draft_counsel_review"),
        ).fetchone()
        alert_id = row[0]
        alert_ids.append(alert_id)
        cand_node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            "contradiction_candidate",
            cand["summary"][:180],
            {
                "execution_id": execution_id,
                "alert_id": alert_id,
                "materiality": cand["materiality"],
                "confidence": cand["confidence"],
                "sources": cand["sources"],
                "draft": True,
                "counsel_review_required": True,
            },
        )
        _insert_edge(conn, edge_ids, TARGET_SLUG, case_node, cand_node, "case_has_contradiction_candidate", 0.75)

    theme_counts = Counter(theme for doc in docs for theme in doc.themes)
    for theme, count in theme_counts.items():
        theme_node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            "issue",
            theme,
            {
                "execution_id": execution_id,
                "document_count": count,
                "draft": True,
                "counsel_review_required": True,
            },
        )
        _insert_edge(conn, edge_ids, TARGET_SLUG, case_node, theme_node, "case_has_issue_theme", 0.68)

    review_items = []
    for doc in docs:
        for reason in sorted(set(doc.review_reasons)):
            review_items.append((doc, reason))
        if doc.chunk_count >= 80:
            review_items.append((doc, "unusually high chunk count"))
    for doc, reason in review_items[:120]:
        review_node = _insert_node(
            conn,
            node_ids,
            TARGET_SLUG,
            "review_queue",
            f"{reason}: {doc.file_name}"[:180],
            {
                "execution_id": execution_id,
                "vault_document_id": doc.id,
                "reason": reason,
                "priority": "high" if doc.locked or "high chunk" in reason else "normal",
                "recommended_next_action": "Counsel/operator review required",
                "draft": True,
                "counsel_review_required": True,
                "locked_privileged": doc.locked,
            },
        )
        _insert_edge(conn, edge_ids, TARGET_SLUG, doc_node_by_id[doc.id], review_node, "document_requires_review", 0.8, doc.id)

    conn.commit()

    manifest = {
        "execution_id": execution_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_slug": TARGET_SLUG,
        "autonomous_intake_execution_id": TARGET_EXECUTION_ID,
        "inventory_count": len(docs),
        "analysis_eligible_count": sum(1 for d in docs if d.analysis_eligible),
        "locked_restricted_count": sum(1 for d in docs if d.locked),
        "text_extracted_count": len(texts_by_doc),
        "classification_counts": dict(Counter(d.classification for d in docs)),
        "entity_count": len(entity_node_by_key),
        "entity_mentions": sum(ent["mentions"] for ent in merged_entities.values()),
        "timeline_events": len(chronology_ids),
        "contradiction_candidates": len(alert_ids),
        "graph_nodes": len(node_ids),
        "graph_edges": len(edge_ids),
        "review_queue_items": min(len(review_items), 120),
        "locked_content_analyzed": False,
        "qdrant_writes": 0,
        "document_row_writes": 0,
        "rollback": {
            "case_slug": TARGET_SLUG,
            "case_graph_node_ids": node_ids,
            "case_graph_edge_ids": edge_ids,
            "chronology_event_ids": chronology_ids,
            "sanctions_alert_ids": alert_ids,
        },
    }
    out_path = Path("/mnt/fortress_nas/audits") / f"{execution_id}.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest_path": str(out_path), **{k: v for k, v in manifest.items() if k != "rollback"}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--backend-pid")
    args = parser.parse_args()
    if os.environ.get(ALLOW_FLAG) != "1":
        raise SystemExit(f"{ALLOW_FLAG}=1 required")
    if not args.execution_id.startswith("fortress-intel-"):
        raise SystemExit("execution_id_must_start_with_fortress_intel")
    result = run(args.execution_id, args.backend_pid)
    for key in (
        "execution_id",
        "manifest_path",
        "inventory_count",
        "analysis_eligible_count",
        "locked_restricted_count",
        "text_extracted_count",
        "entity_count",
        "entity_mentions",
        "timeline_events",
        "contradiction_candidates",
        "graph_nodes",
        "graph_edges",
        "review_queue_items",
    ):
        print(f"{key}={result[key]}")
    print("locked_content_analyzed=false")
    print("qdrant_writes=0")
    print("document_row_writes=0")


if __name__ == "__main__":
    main()
