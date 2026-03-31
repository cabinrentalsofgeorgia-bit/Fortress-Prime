"""
Deposition outline engine — fuses v2 case graph, sanctions alerts, and council ledger
into a structured line-by-line questioning outline for a specific deponent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal
from backend.services.ai_router import execute_resilient_inference
from backend.services.deliberation_vault import get_deliberation_ledger_connection
from backend.services.legal_case_graph import LegalCaseGraphBuilder

logger = logging.getLogger(__name__)

# Canonical provenance block for audit / Paperclip UI (every pressure point must include this).
EMPTY_PROVENANCE: dict[str, Any] = {
    "source_system": "synthetic",
    "sanctions_alert_id": None,
    "graph_edge_ids": None,
    "graph_node_ids": None,
    "council_event_id": None,
    "council_risk_factor_index": None,
}

OUTLINE_SYSTEM_PROMPT = """You are an elite trial lawyer preparing a deposition outline. You receive:
- A case graph subgraph focused on the deponent
- Active sanctions/tripwire contradiction alerts
- Legal Council consensus risk factors and recommended actions from the latest deliberation
Produce a tactical, line-by-line questioning strategy. Output STRICT JSON only with exactly these keys:
{"summary": string, "pressure_points": [{"title": string, "rationale": string, "graph_hook": string, "alert_ref": string|null, "provenance": {"source_system": string, "sanctions_alert_id": string|null, "graph_edge_ids": [string]|null, "graph_node_ids": [string]|null, "council_event_id": string|null, "council_risk_factor_index": number|null}}], "questioning_outline": [{"line": number, "phase": string, "question": string, "purpose": string}], "exhibit_sequence": [{"label": string, "doc_ref": string, "tactical_purpose": string}], "council_risk_factors": [string], "source_alert_summaries": [string]}
source_system must be one of: sanctions_alerts_v2, case_graph_edges_v2, council_deliberation, synthetic, mixed.
phases examples: Background, Lock_in, Impeachment, Exhibit_confrontation, Clean_up.
Use null for alert_ref and sanctions_alert_id when no alert applies. Keep questions concise and oath-ready.
Weight interrogation toward seats and risks where the 9-seat council recorded VULNERABLE or WEAK signals; note STRONG_DEFENSE where it constrains attack lines."""


def _parse_strict_json(raw: str) -> dict[str, Any]:
    text_raw = (raw or "").strip()
    if text_raw.startswith("```"):
        text_raw = text_raw.strip("`")
        if text_raw.lower().startswith("json"):
            text_raw = text_raw[4:].strip()
    start = text_raw.find("{")
    end = text_raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    return json.loads(text_raw[start : end + 1])


DELIBERATION_LEDGER_RELATION = "legal_cmd.deliberation_events"


def _jsonb_to_obj(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return val


def _normalize_ledger_seat_opinion(op: Any) -> dict[str, Any]:
    if not isinstance(op, dict):
        return {}
    risks = op.get("risk_factors") or []
    if not isinstance(risks, list):
        risks = []
    signal = str(op.get("signal") or "NEUTRAL").upper().replace(" ", "_")
    try:
        conviction = float(op.get("conviction") or 0)
    except (TypeError, ValueError):
        conviction = 0.0
    return {
        "seat": op.get("seat"),
        "persona": op.get("persona") or op.get("name"),
        "slug": op.get("slug"),
        "signal": signal,
        "conviction": conviction,
        "risk_factors": [str(x) for x in risks[:8]],
        "reasoning_preview": str(op.get("reasoning") or "")[:400],
    }


def _signal_breakdown_from_seats(seat_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in seat_rows:
        sig = str(s.get("signal") or "NEUTRAL").upper()
        counts[sig] = counts.get(sig, 0) + 1
    return counts


def _interrogation_priority_from_seats(seat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Seats whose signals should drive cross-exam pressure (vulnerability-first)."""
    priority_signals = frozenset({"VULNERABLE", "WEAK"})
    scored = [s for s in seat_rows if s.get("signal") in priority_signals]
    scored.sort(key=lambda x: float(x.get("conviction") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    for s in scored[:9]:
        out.append(
            {
                "seat": s.get("seat"),
                "persona": s.get("persona"),
                "signal": s.get("signal"),
                "conviction": s.get("conviction"),
                "risk_factors": s.get("risk_factors") or [],
            }
        )
    return out


def _sync_fetch_latest_deliberation_ledger(case_slug: str) -> dict[str, Any] | None:
    """
    Read the newest sealed row from the physical deliberation ledger (immutable 9-seat council output).

    Source of truth: ``legal_cmd.deliberation_events`` on fortress_db (or DSN from
    ``DELIBERATION_LEDGER_DATABASE_URL`` / ``FORTRESS_DELIBERATION_DSN``).
    """
    try:
        conn = get_deliberation_ledger_connection()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "deposition_outline_deliberation_ledger_unavailable table=%s error=%s",
            DELIBERATION_LEDGER_RELATION,
            str(exc)[:200],
        )
        return None
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            SELECT
                event_id,
                case_slug,
                case_number,
                timestamp,
                trigger_type,
                consensus_signal,
                consensus_conviction,
                counsel_results,
                seat_opinions,
                sha256_signature,
                execution_time_ms
            FROM legal_cmd.deliberation_events AS deliberation_ledger
            WHERE case_slug = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (case_slug,),
        )
        row = cur.fetchone()
        if not row:
            logger.info(
                "deposition_outline_deliberation_ledger_miss table=%s case_slug=%s",
                DELIBERATION_LEDGER_RELATION,
                case_slug,
            )
            return None

        counsel_raw = _jsonb_to_obj(row.get("counsel_results"))
        counsel = counsel_raw if isinstance(counsel_raw, dict) else {}

        seats_raw = _jsonb_to_obj(row.get("seat_opinions"))
        seat_list = seats_raw if isinstance(seats_raw, list) else []
        seat_rows = [_normalize_ledger_seat_opinion(o) for o in seat_list]
        seat_rows = [s for s in seat_rows if "seat" in s and s.get("seat") is not None]

        breakdown = counsel.get("signal_breakdown")
        if not isinstance(breakdown, dict):
            breakdown = _signal_breakdown_from_seats(seat_rows)
        signal_breakdown_norm: dict[str, int] = {}
        for k, v in breakdown.items():
            try:
                signal_breakdown_norm[str(k)] = int(v)
            except (TypeError, ValueError):
                signal_breakdown_norm[str(k)] = 0

        interrogation_priority = _interrogation_priority_from_seats(seat_rows)
        sig_full = row.get("sha256_signature")
        sig_str = str(sig_full) if sig_full is not None else ""

        return {
            "ledger_table": DELIBERATION_LEDGER_RELATION,
            "event_id": str(row["event_id"]),
            "case_number": row.get("case_number"),
            "timestamp": row["timestamp"].isoformat() if row.get("timestamp") else None,
            "trigger_type": row.get("trigger_type"),
            "consensus_signal": row.get("consensus_signal"),
            "consensus_conviction": float(row["consensus_conviction"] or 0),
            "top_risk_factors": list(counsel.get("top_risk_factors") or [])[:15],
            "top_recommended_actions": list(counsel.get("top_recommended_actions") or [])[:15],
            "top_defense_arguments": list(counsel.get("top_defense_arguments") or [])[:10],
            "signal_breakdown": signal_breakdown_norm,
            "seat_opinions": seat_rows,
            "seat_opinion_count": len(seat_rows),
            "interrogation_priority_seats": interrogation_priority,
            "sha256_signature": sig_str,
            "sha256_signature_prefix": sig_str[:16] if sig_str else None,
            "ledger_execution_time_ms": int(row["execution_time_ms"] or 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "deposition_outline_deliberation_ledger_query_failed table=%s error=%s",
            DELIBERATION_LEDGER_RELATION,
            str(exc)[:200],
        )
        return None
    finally:
        cur.close()
        conn.close()


def _contradiction_edge_ids(subgraph: dict[str, Any], *, limit: int = 6) -> list[str]:
    out: list[str] = []
    for e in subgraph.get("edges") or []:
        rel = str(e.get("relationship_type") or "").lower()
        if "contradict" in rel or "claim" in rel:
            eid = str(e.get("id", ""))
            if eid and eid not in out:
                out.append(eid)
        if len(out) >= limit:
            break
    if not out:
        for e in (subgraph.get("edges") or [])[:limit]:
            eid = str(e.get("id", ""))
            if eid:
                out.append(eid)
    return out[:limit]


def _deponent_subgraph(
    graph: dict[str, Any],
    deponent: str,
    *,
    max_nodes: int = 80,
    max_edges: int = 120,
) -> dict[str, Any]:
    """Reduce graph to nodes/edges touching the deponent label (case-insensitive)."""
    needle = (deponent or "").strip().lower()
    nodes = graph.get("nodes") or []
    label_by_id: dict[str, str] = {}
    for n in nodes:
        nid = str(n.get("id", ""))
        label = str(n.get("label") or "")
        label_by_id[nid] = label
    touch: set[str] = set()
    for n in nodes:
        nid = str(n.get("id", ""))
        lab = str(n.get("label") or "").lower()
        if needle and needle in lab:
            touch.add(nid)
    edges = graph.get("edges") or []
    related_edges: list[dict[str, Any]] = []
    for e in edges:
        sid = str(e.get("source_node_id", ""))
        tid = str(e.get("target_node_id", ""))
        sl = label_by_id.get(sid, "").lower()
        tl = label_by_id.get(tid, "").lower()
        if not needle:
            continue
        if needle in sl or needle in tl or sid in touch or tid in touch:
            related_edges.append(dict(e))
            touch.add(sid)
            touch.add(tid)
    if not related_edges and needle:
        for e in edges:
            rel = str(e.get("relationship_type") or "").lower()
            if "contradict" in rel or "claim" in rel:
                related_edges.append(dict(e))
                touch.add(str(e.get("source_node_id", "")))
                touch.add(str(e.get("target_node_id", "")))
    sub_nodes = [dict(n) for n in nodes if str(n.get("id", "")) in touch][:max_nodes]
    sub_edges = related_edges[:max_edges]
    return {
        "deponent_focus": deponent,
        "nodes": json.loads(json.dumps(sub_nodes, default=str)),
        "edges": json.loads(json.dumps(sub_edges, default=str)),
    }


async def _fetch_sanctions_alerts(db: AsyncSession, case_slug: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, alert_type, contradiction_summary, confidence_score, status, created_at
                FROM legal.sanctions_alerts_v2
                WHERE case_slug = :case_slug AND status IN ('DRAFT', 'ACTIVE')
                ORDER BY confidence_score DESC NULLS LAST, created_at DESC
                LIMIT 25
                """
            ),
            {"case_slug": case_slug},
        )
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": str(row["id"]),
                "alert_type": row["alert_type"],
                "contradiction_summary": row["contradiction_summary"],
                "confidence_score": row["confidence_score"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
    return out


async def _timed_graph_snapshot(case_slug: str) -> tuple[dict[str, Any], int]:
    t0 = time.perf_counter()
    async with AsyncSessionLocal() as session:
        data = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=session)
    return data, int((time.perf_counter() - t0) * 1000)


async def _timed_sanctions_alerts(case_slug: str) -> tuple[list[dict[str, Any]], int]:
    t0 = time.perf_counter()
    async with AsyncSessionLocal() as session:
        data = await _fetch_sanctions_alerts(session, case_slug)
    return data, int((time.perf_counter() - t0) * 1000)


def _timed_deliberation_ledger_fetch(case_slug: str) -> tuple[dict[str, Any] | None, int]:
    """Wall-clock for the synchronous psycopg2 read against the physical deliberation ledger."""
    t0 = time.perf_counter()
    data = _sync_fetch_latest_deliberation_ledger(case_slug)
    return data, int((time.perf_counter() - t0) * 1000)


async def _ingest_intelligence_parallel(case_slug: str) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any],
]:
    """
    Parallel ingestion: separate AsyncSession per SQL leg + threaded deliberation ledger read.
    Returns graph_full, alerts, council_slice, timing_payload (component ms + wall).
    """
    loop = asyncio.get_running_loop()
    wall0 = time.perf_counter()
    graph_task = _timed_graph_snapshot(case_slug)
    alerts_task = _timed_sanctions_alerts(case_slug)
    ledger_task = loop.run_in_executor(None, _timed_deliberation_ledger_fetch, case_slug)
    (graph_full, graph_ms), (alerts, alerts_ms), (council_slice, ledger_ms) = await asyncio.gather(
        graph_task,
        alerts_task,
        ledger_task,
    )
    wall_ms = int((time.perf_counter() - wall0) * 1000)
    timing = {
        "case_graph_snapshot_ms": graph_ms,
        "sanctions_alerts_v2_ms": alerts_ms,
        "deliberation_ledger_ms": ledger_ms,
        "council_deliberation_ledger_ms": ledger_ms,
        "ingestion_parallel_wall_ms": wall_ms,
    }
    return graph_full, alerts, council_slice, timing


def _merge_provenance(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = {**EMPTY_PROVENANCE, **base}
    for k, v in overlay.items():
        if k in EMPTY_PROVENANCE:
            merged[k] = v
    return merged


def _normalize_pressure_point(
    raw: Any,
    *,
    alerts_by_id: dict[str, dict[str, Any]],
    council_event_id: str | None,
    default_graph_edges: list[str],
    default_graph_nodes: list[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    title = str(raw.get("title") or "Pressure point").strip()
    rationale = str(raw.get("rationale") or "").strip()
    graph_hook = str(raw.get("graph_hook") or "").strip()
    alert_ref = raw.get("alert_ref")
    alert_str = str(alert_ref).strip() if alert_ref not in (None, "") else None
    prov_in = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}

    aid = prov_in.get("sanctions_alert_id")
    if aid is None and alert_str and alert_str in alerts_by_id:
        aid = alert_str
    elif aid is not None:
        aid = str(aid)

    source = str(prov_in.get("source_system") or "").strip() or "synthetic"
    if aid:
        source = "sanctions_alerts_v2" if source == "synthetic" else source

    edge_ids = prov_in.get("graph_edge_ids")
    if not isinstance(edge_ids, list):
        edge_ids = None
    else:
        edge_ids = [str(x) for x in edge_ids if str(x)]
    if not edge_ids and default_graph_edges:
        edge_ids = list(default_graph_edges)

    node_ids = prov_in.get("graph_node_ids")
    if not isinstance(node_ids, list):
        node_ids = None
    else:
        node_ids = [str(x) for x in node_ids if str(x)]
    if not node_ids and default_graph_nodes:
        node_ids = list(default_graph_nodes)

    cri = prov_in.get("council_risk_factor_index")
    if cri is not None:
        try:
            cri = int(cri)
        except (TypeError, ValueError):
            cri = None

    c_eid_raw = prov_in.get("council_event_id")
    if c_eid_raw is not None:
        c_eid = str(c_eid_raw)
    else:
        c_eid = council_event_id

    provenance = _merge_provenance(
        {},
        {
            "source_system": source,
            "sanctions_alert_id": aid,
            "graph_edge_ids": edge_ids if edge_ids else None,
            "graph_node_ids": node_ids if node_ids else None,
            "council_event_id": c_eid,
            "council_risk_factor_index": cri,
        },
    )

    return {
        "title": title,
        "rationale": rationale,
        "graph_hook": graph_hook or (f"Edges {edge_ids[:2]}" if edge_ids else "Case graph subgraph"),
        "alert_ref": alert_str or aid,
        "provenance": provenance,
    }


def _normalize_pressure_points_list(
    points: Any,
    *,
    alerts: list[dict[str, Any]],
    council_event_id: str | None,
    subgraph: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts_by_id = {a["id"]: a for a in alerts if a.get("id")}
    edge_ids = _contradiction_edge_ids(subgraph)
    node_ids = [str(n.get("id")) for n in (subgraph.get("nodes") or [])[:12] if n.get("id")]
    if not isinstance(points, list):
        return []
    out: list[dict[str, Any]] = []
    for p in points:
        out.append(
            _normalize_pressure_point(
                p,
                alerts_by_id=alerts_by_id,
                council_event_id=council_event_id,
                default_graph_edges=edge_ids,
                default_graph_nodes=node_ids,
            )
        )
    return out


def _fallback_outline_body(
    *,
    case_slug: str,
    deponent_entity: str,
    subgraph: dict[str, Any],
    alerts: list[dict[str, Any]],
    council: dict[str, Any] | None,
    operator_focus: str | None,
) -> dict[str, Any]:
    """
    Emergency fallback: same inner schema as LLM JSON (plus provenance on every pressure point).
    """
    risks = (council or {}).get("top_risk_factors") or []
    council_eid = (council or {}).get("event_id") if council else None
    edge_ids = _contradiction_edge_ids(subgraph)
    node_ids = [str(n.get("id")) for n in (subgraph.get("nodes") or [])[:12] if n.get("id")]
    summaries = [str(a.get("contradiction_summary") or "") for a in alerts if a.get("contradiction_summary")]
    pressure: list[dict[str, Any]] = []

    for i, s in enumerate(summaries[:8]):
        aid = str(alerts[i]["id"]) if i < len(alerts) else None
        pressure.append(
            {
                "title": f"Contradiction pressure {i + 1}",
                "rationale": s[:500],
                "graph_hook": f"Sanctions alert {aid}; cross-check subgraph edges {edge_ids[:2]!s}.",
                "alert_ref": aid,
                "provenance": _merge_provenance(
                    {},
                    {
                        "source_system": "sanctions_alerts_v2",
                        "sanctions_alert_id": aid,
                        "graph_edge_ids": edge_ids or None,
                        "graph_node_ids": node_ids or None,
                        "council_event_id": council_eid,
                        "council_risk_factor_index": None,
                    },
                ),
            }
        )

    if not pressure and risks:
        for idx, r in enumerate(risks[:5]):
            pressure.append(
                {
                    "title": f"Council vulnerability {idx + 1}",
                    "rationale": str(r)[:500],
                    "graph_hook": "Derived from latest Legal Council deliberation risk factors.",
                    "alert_ref": None,
                    "provenance": _merge_provenance(
                        {},
                        {
                            "source_system": "council_deliberation",
                            "sanctions_alert_id": None,
                            "graph_edge_ids": edge_ids or None,
                            "graph_node_ids": node_ids or None,
                            "council_event_id": council_eid,
                            "council_risk_factor_index": idx,
                        },
                    ),
                }
            )

    if not pressure:
        first_rel = None
        if subgraph.get("edges"):
            first_rel = str(subgraph["edges"][0].get("relationship_type") or "n/a")
        pressure.append(
            {
                "title": "Record foundation",
                "rationale": "Establish scope of deponent knowledge before targeted impeachment.",
                "graph_hook": first_rel or "n/a",
                "alert_ref": None,
                "provenance": _merge_provenance(
                    {},
                    {
                        "source_system": "synthetic",
                        "graph_edge_ids": edge_ids or None,
                        "graph_node_ids": node_ids or None,
                        "council_event_id": council_eid,
                    },
                ),
            }
        )

    questions: list[dict[str, Any]] = [
        {
            "line": 1,
            "phase": "Background",
            "question": f"{deponent_entity}, please state your full name for the record.",
            "purpose": "Identify witness; begin transcript.",
        },
        {
            "line": 2,
            "phase": "Lock_in",
            "question": "Are you prepared to testify truthfully today?",
            "purpose": "Oath baseline.",
        },
    ]
    for idx, s in enumerate(summaries[:5], start=3):
        questions.append(
            {
                "line": idx,
                "phase": "Impeachment",
                "question": f"Is it your position under oath that the following is accurate: {s[:200]}...?",
                "purpose": "Lock prior statement before confrontation.",
            }
        )

    exhibits: list[dict[str, Any]] = []
    for i, a in enumerate(alerts[:5]):
        exhibits.append(
            {
                "label": f"Exhibit outline {i + 1}",
                "doc_ref": str(a.get("id", "")),
                "tactical_purpose": str(a.get("contradiction_summary") or "Impeachment support")[:400],
            }
        )
    if not exhibits:
        exhibits.append(
            {
                "label": "TBD",
                "doc_ref": "n/a",
                "tactical_purpose": "Attach after review.",
            }
        )

    summary_bits = [
        "[Emergency Fallback] Structured outline generated without LLM JSON (DGX load, timeout, or parse failure). "
        f"Deponent {deponent_entity}, case {case_slug}."
    ]
    if operator_focus:
        summary_bits.append(f"Operator focus: {operator_focus[:300]}")
    if risks:
        summary_bits.append(f"Council-flagged risks: {str(risks[0])[:200]}")

    return {
        "summary": " ".join(summary_bits)[:8000],
        "pressure_points": pressure,
        "questioning_outline": questions,
        "exhibit_sequence": exhibits,
        "council_risk_factors": [str(r) for r in risks[:10]],
        "source_alert_summaries": summaries[:15],
    }


def _build_outline_metadata(
    *,
    ingestion_timing: dict[str, Any],
    graph_full: dict[str, Any],
    subgraph: dict[str, Any],
    alerts: list[dict[str, Any]],
    council_present: bool,
    deliberation_ledger_seat_count: int | None,
    inference_primary_ms: int,
    inference_repair_ms: int | None,
    mode: str,
    inference_source: str,
) -> dict[str, Any]:
    gn = len(graph_full.get("nodes") or [])
    ge = len(graph_full.get("edges") or [])
    sn = len(subgraph.get("nodes") or [])
    se = len(subgraph.get("edges") or [])
    total_inf = inference_primary_ms + (inference_repair_ms or 0)
    return {
        "ingestion_latency_ms": ingestion_timing,
        "ingestion_row_counts": {
            "graph_nodes_full": gn,
            "graph_edges_full": ge,
            "subgraph_nodes": sn,
            "subgraph_edges": se,
            "sanctions_alerts_returned": len(alerts),
            "council_deliberation_event_present": council_present,
            "deliberation_ledger_seat_opinions": deliberation_ledger_seat_count,
        },
        "inference_latency_ms": {
            "primary": inference_primary_ms,
            "repair": inference_repair_ms,
            "total": total_inf,
        },
        "mode": mode,
        "inference_source": inference_source,
    }


async def generate_deposition_outline(
    db: AsyncSession,
    *,
    case_slug: str,
    deponent_entity: str,
    operator_focus: str | None = None,
) -> dict[str, Any]:
    """
    Build a structured deposition outline JSON dict for Paperclip / vault persistence.

    Raises ValueError on missing inputs; does not raise for council DB failures.
    """
    slug = (case_slug or "").strip()
    dep = (deponent_entity or "").strip()
    if not slug:
        raise ValueError("case_slug is required")
    if not dep:
        raise ValueError("deponent_entity is required")

    graph_full, alerts, council_slice, ingestion_timing = await _ingest_intelligence_parallel(slug)
    subgraph = _deponent_subgraph(graph_full, dep)
    council_eid = (council_slice or {}).get("event_id") if council_slice else None

    council_risks_text = ""
    if council_slice:
        council_risks_text = json.dumps(
            {
                "ledger_table": council_slice.get("ledger_table"),
                "event_id": council_slice.get("event_id"),
                "consensus_signal": council_slice.get("consensus_signal"),
                "consensus_conviction": council_slice.get("consensus_conviction"),
                "signal_breakdown": council_slice.get("signal_breakdown"),
                "interrogation_priority_seats": council_slice.get("interrogation_priority_seats"),
                "top_risk_factors": council_slice.get("top_risk_factors"),
                "top_recommended_actions": council_slice.get("top_recommended_actions"),
                "top_defense_arguments": council_slice.get("top_defense_arguments"),
            },
            ensure_ascii=False,
        )

    user_payload: dict[str, Any] = {
        "case_slug": slug,
        "deponent_entity": dep,
        "operator_focus": operator_focus,
        "graph_subgraph": subgraph,
        "sanctions_alerts": alerts,
        "council_risk_bundle": council_risks_text or None,
        "council_event_id": council_eid,
    }
    if council_slice:
        user_payload["deliberation_ledger"] = {
            "ledger_table": council_slice.get("ledger_table"),
            "event_id": council_slice.get("event_id"),
            "consensus_signal": council_slice.get("consensus_signal"),
            "consensus_conviction": council_slice.get("consensus_conviction"),
            "signal_breakdown": council_slice.get("signal_breakdown"),
            "seat_opinions": council_slice.get("seat_opinions"),
            "interrogation_priority_seats": council_slice.get("interrogation_priority_seats"),
        }
    prompt = json.dumps(user_payload, ensure_ascii=False, default=str)

    parsed: dict[str, Any] | None = None
    used_emergency_fallback = False
    repair_ms: int | None = None

    t_inf0 = time.perf_counter()
    result = await execute_resilient_inference(
        prompt=prompt,
        task_type="legal",
        system_message=OUTLINE_SYSTEM_PROMPT,
        max_tokens=2800,
        temperature=0.12,
        db=db,
        source_module="legal_deposition_outline_engine",
        timeout_s=120.0,
    )
    wall_primary_ms = int((time.perf_counter() - t_inf0) * 1000)
    primary_ms = int(result.latency_ms) if result.latency_ms else wall_primary_ms

    try:
        parsed = _parse_strict_json(result.text)
    except Exception:
        logger.warning("deposition_outline_parse_failed source=%s", result.source)
        t_rep0 = time.perf_counter()
        repair = await execute_resilient_inference(
            prompt=(
                "Repair this text into valid JSON matching keys: summary, pressure_points (each with provenance), "
                "questioning_outline, exhibit_sequence, council_risk_factors, source_alert_summaries. "
                "No markdown.\n\n" + (result.text or "")[:12000]
            ),
            task_type="legal",
            system_message="Return only strict JSON. Arrays must be JSON arrays.",
            max_tokens=2400,
            temperature=0,
            db=db,
            source_module="legal_deposition_outline_engine_repair",
            timeout_s=90.0,
        )
        wall_repair_ms = int((time.perf_counter() - t_rep0) * 1000)
        repair_ms = int(repair.latency_ms) if repair.latency_ms else wall_repair_ms
        try:
            parsed = _parse_strict_json(repair.text)
        except Exception:
            parsed = None

    if not parsed or not str(parsed.get("summary") or "").strip():
        parsed = _fallback_outline_body(
            case_slug=slug,
            deponent_entity=dep,
            subgraph=subgraph,
            alerts=alerts,
            council=council_slice,
            operator_focus=operator_focus,
        )
        used_emergency_fallback = True

    generated_at = datetime.now(timezone.utc).isoformat()
    inference_source = "emergency_fallback" if used_emergency_fallback else str(result.source or "unknown")

    pressure_normalized = _normalize_pressure_points_list(
        parsed.get("pressure_points"),
        alerts=alerts,
        council_event_id=council_eid,
        subgraph=subgraph,
    )

    outline: dict[str, Any] = {
        "case_slug": slug,
        "deponent_entity": dep,
        "generated_at": generated_at,
        "summary": str(parsed.get("summary") or "").strip()[:8000],
        "pressure_points": pressure_normalized,
        "questioning_outline": parsed.get("questioning_outline")
        if isinstance(parsed.get("questioning_outline"), list)
        else [],
        "exhibit_sequence": parsed.get("exhibit_sequence")
        if isinstance(parsed.get("exhibit_sequence"), list)
        else [],
        "council_risk_factors": parsed.get("council_risk_factors")
        if isinstance(parsed.get("council_risk_factors"), list)
        else list((council_slice or {}).get("top_risk_factors") or []),
        "source_alert_summaries": parsed.get("source_alert_summaries")
        if isinstance(parsed.get("source_alert_summaries"), list)
        else [str(a.get("contradiction_summary") or "") for a in alerts],
        "council_provenance": {
            "ledger_table": (council_slice or {}).get("ledger_table") if council_slice else None,
            "event_id": council_eid,
            "timestamp": (council_slice or {}).get("timestamp") if council_slice else None,
            "consensus_signal": (council_slice or {}).get("consensus_signal") if council_slice else None,
            "consensus_conviction": (council_slice or {}).get("consensus_conviction") if council_slice else None,
            "signal_breakdown": (council_slice or {}).get("signal_breakdown") if council_slice else None,
            "seat_opinion_count": (council_slice or {}).get("seat_opinion_count") if council_slice else None,
            "sha256_signature_prefix": (council_slice or {}).get("sha256_signature_prefix") if council_slice else None,
        },
        "inference_source": inference_source,
        "graph_context": {
            "full_graph_node_count": len(graph_full.get("nodes") or []),
            "full_graph_edge_count": len(graph_full.get("edges") or []),
            "subgraph_node_count": len(subgraph.get("nodes") or []),
            "subgraph_edge_count": len(subgraph.get("edges") or []),
        },
        "metadata": _build_outline_metadata(
            ingestion_timing=ingestion_timing,
            graph_full=graph_full,
            subgraph=subgraph,
            alerts=alerts,
            council_present=bool(council_slice),
            deliberation_ledger_seat_count=(
                int(council_slice["seat_opinion_count"])
                if council_slice and council_slice.get("seat_opinion_count") is not None
                else None
            ),
            inference_primary_ms=primary_ms,
            inference_repair_ms=repair_ms,
            mode="emergency_fallback" if used_emergency_fallback else "llm",
            inference_source=inference_source,
        ),
    }
    return outline


def outline_artifact_filename(*, deponent_entity: str, case_slug: str, case_number: str | None) -> str:
    stem = (case_number or "").strip() or case_slug.strip()
    dep_safe = _sanitize_name(deponent_entity)
    return f"Deposition_Outline_{dep_safe}_{stem}.json"


def _sanitize_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (value or "").strip())
    return safe.strip("._") or "deponent"
