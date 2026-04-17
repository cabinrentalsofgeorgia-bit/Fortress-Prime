"""
LEGAL COUNCIL OF 9 — FastAPI Streaming Router + Deliberation Ledger API
========================================================================

Deliberation (SSE):
    POST /council/deliberate       — Start a council deliberation (SSE stream)
    GET  /council/session/{id}     — Get session state (poll fallback)
    GET  /council/personas         — List all 9 legal personas

Verifiable Intelligence Engine (Ledger):
    GET  /council/history/{slug}       — Immutable timeline of all deliberations
    GET  /council/history/{slug}/delta — Delta engine: compare two events
    GET  /council/event/{event_id}     — Full event detail (opinions, context, roster)
    GET  /council/event/{event_id}/verify — Tamper check: recompute SHA-256

SSE Event Protocol (text/event-stream):
    {"type": "context_frozen",   "vector_count": N, ...}
    {"type": "status",           "message": "..."}
    {"type": "persona_start",    "seat": N, "name": "...", "slug": "..."}
    {"type": "persona_complete", "seat": N, "opinion": {...}, ...}
    {"type": "consensus",        "consensus_signal": "...", ...}
    {"type": "vaulted",          "event_id": "...", "sha256_signature": "..."}
    {"type": "done",             ...full result...}
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List

import psycopg2.extras
import structlog
import hashlib
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.security import require_manager_or_admin
from backend.services.deliberation_vault import (
    compute_signature,
    get_vault_connection,
)
from backend.services.legal_council import (
    get_session,
    list_personas_summary,
    run_council_deliberation,
)

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class DeliberationRequest(BaseModel):
    case_brief: str = Field(
        ...,
        min_length=10,
        description="The case brief or legal question for the Council to analyze",
    )
    context: str = Field(
        default="",
        description="Additional context (evidence, emails, contract excerpts)",
    )
    case_slug: str = Field(
        default="",
        description="Case slug for vault provenance (e.g. fish-trap-suv2026000013)",
    )
    case_number: str = Field(
        default="",
        description="Official case number for vault provenance",
    )
    trigger_type: str = Field(
        default="MANUAL_RUN",
        description="Trigger type: MANUAL_RUN, RE_DELIBERATE, NEW_DOCUMENT_INGEST",
    )


def _sse(data: dict) -> str:
    """Format a dict as an SSE data frame with strict JSON safety.

    Uses ensure_ascii to escape all non-ASCII into \\uXXXX sequences,
    and default=str to handle any stray non-serializable types (datetime, Enum).
    """
    try:
        payload = json.dumps(data, ensure_ascii=True, default=str)
    except (TypeError, ValueError) as exc:
        payload = json.dumps({"type": "error", "message": f"Serialization error: {exc}"})
    return f"data: {payload}\n\n"


@router.post("/council/deliberate")
async def deliberate(request: Request, body: DeliberationRequest):
    """
    Start a Legal Council of 9 deliberation session.
    Returns an SSE stream with real-time persona opinions and consensus.
    """
    session_id = str(uuid.uuid4())

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await queue.put(event)

        task = asyncio.create_task(
            run_council_deliberation(
                session_id=session_id,
                case_brief=body.case_brief,
                context=body.context,
                progress_callback=on_progress,
                case_slug=body.case_slug,
                case_number=body.case_number,
                trigger_type=body.trigger_type,
            )
        )

        yield _sse({
            "type": "session_start",
            "session_id": session_id,
        })

        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    logger.info("council_client_disconnected", session_id=session_id)
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _sse(event)

                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    if task.done():
                        exc = task.exception()
                        if exc:
                            yield _sse({
                                "type": "error",
                                "message": f"Council error: {exc}",
                            })
                        break
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception as exc:
            logger.exception("council_stream_error", error=str(exc))
            yield _sse({
                "type": "error",
                "message": f"Stream error: {type(exc).__name__}: {exc}",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/council/session/{session_id}")
async def get_session_state(session_id: str):
    """Get the current state of a council session (polling fallback)."""
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found", "session_id": session_id}
    return session


@router.get("/council/{job_id}/stream")
async def stream_council_job(job_id: str, request: Request, cursor: str | None = None):
    """
    Redis-backed SSE stream for an ARQ council deliberation job.

    Replays stored events (from cursor) then subscribes to live pub/sub.
    The frontend EventSource connects here after POST /cases/{slug}/deliberate
    returns {"job_id": "..."}.
    """
    from backend.core.council_stream import (
        create_council_redis,
        replay_council_events,
        is_terminal_event,
    )

    async def generate():
        redis = await create_council_redis()
        try:
            # 1. Replay buffered events (handles reconnect with ?cursor=)
            history = await replay_council_events(redis, job_id, after_id=cursor)
            for stream_id, event in history:
                yield f"id: {stream_id}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if is_terminal_event(event):
                    return

            # 2. Subscribe to live channel for remaining events
            pubsub = redis.pubsub()
            channel = f"council_stream:{job_id}"
            await pubsub.subscribe(channel)
            try:
                timeout = 0
                while not await request.is_disconnected():
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg.get("type") == "message":
                        raw = msg.get("data", "{}")
                        try:
                            envelope = json.loads(raw)
                            event = envelope.get("event", envelope)
                            stream_id = envelope.get("stream_id", "")
                        except Exception:
                            event = {"type": "raw", "data": raw}
                            stream_id = ""
                        if stream_id:
                            yield f"id: {stream_id}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        timeout = 0
                        if is_terminal_event(event):
                            return
                    else:
                        timeout += 1
                        if timeout % 15 == 0:
                            yield ": heartbeat\n\n"
                        if timeout > 600:   # 10 minutes idle → close
                            yield f"data: {json.dumps({'type':'timeout','job_id':job_id})}\n\n"
                            return
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
        except Exception as exc:
            logger.exception("council_stream_error  job_id=%s  error=%s", job_id, str(exc)[:200])
            yield f"data: {json.dumps({'type':'error','message':str(exc)[:200],'job_id':job_id})}\n\n"
        finally:
            await redis.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/council/personas")
async def get_personas():
    """List all 9 Legal Council personas with their profiles."""
    personas = list_personas_summary()
    return {
        "personas": personas,
        "total": len(personas),
        "council_name": "Legal Council of 9",
        "purpose": "Multi-persona legal deliberation for the Generali/Fannin County defense",
    }


# ═══════════════════════════════════════════════════════════════════════
# Verifiable Intelligence Engine — Deliberation Ledger API
# ═══════════════════════════════════════════════════════════════════════


def _query_ledger(sql: str, params: tuple) -> List[Dict[str, Any]]:
    """Execute a read-only query against the deliberation ledger."""
    conn = get_vault_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


@router.get("/council/history/{case_slug}")
async def get_deliberation_history(
    case_slug: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
):
    """
    Fetch the immutable timeline of all deliberations for a case.

    Returns events ordered newest-first with pagination. Each entry
    includes the SHA-256 signature for tamper verification.
    """
    offset = (page - 1) * per_page
    loop = asyncio.get_running_loop()

    count_rows = await loop.run_in_executor(None, _query_ledger,
        "SELECT count(*) AS total FROM legal_cmd.deliberation_events WHERE case_slug = %s",
        (case_slug,),
    )
    total = count_rows[0]["total"] if count_rows else 0

    rows = await loop.run_in_executor(None, _query_ledger, """
        SELECT event_id, timestamp, trigger_type,
               consensus_signal, consensus_conviction, execution_time_ms,
               array_length(qdrant_vector_ids, 1) AS vector_count,
               jsonb_array_length(seat_opinions) AS opinion_count,
               sha256_signature
        FROM legal_cmd.deliberation_events
        WHERE case_slug = %s
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """, (case_slug, per_page, offset))

    history = []
    for row in rows:
        history.append({
            "event_id": str(row["event_id"]),
            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
            "trigger_type": row["trigger_type"],
            "consensus_signal": row["consensus_signal"] or "UNKNOWN",
            "consensus_conviction": float(row["consensus_conviction"] or 0),
            "execution_time_ms": row["execution_time_ms"],
            "vector_count": row["vector_count"] or 0,
            "opinion_count": row["opinion_count"] or 0,
            "sha256_signature": row["sha256_signature"],
        })

    return {
        "case_slug": case_slug,
        "data": history,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, -(-total // per_page)),
        },
    }


@router.get("/council/history/{case_slug}/delta")
async def get_deliberation_delta(
    case_slug: str,
    event_a: str = Query(..., description="UUID of the older event"),
    event_b: str = Query(..., description="UUID of the newer event"),
):
    """
    Delta Engine: compare two cryptographically sealed deliberation events.

    Returns:
    - context_delta: new/removed Qdrant vectors between runs
    - seat_deltas: per-seat signal flips with conviction changes
    - consensus_shift: overall signal and conviction movement
    """
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _query_ledger, """
        SELECT event_id, timestamp, qdrant_vector_ids, context_chunks,
               seat_opinions, counsel_results,
               consensus_signal, consensus_conviction
        FROM legal_cmd.deliberation_events
        WHERE case_slug = %s AND event_id IN (%s, %s)
    """, (case_slug, event_a, event_b))

    events = {str(row["event_id"]): row for row in rows}

    if event_a not in events or event_b not in events:
        raise HTTPException(
            status_code=404,
            detail=f"One or both events not found for case {case_slug}.",
        )

    old_ev = events[event_a]
    new_ev = events[event_b]

    # ── Context Delta (what new evidence did the AI see?) ─────────
    old_vectors = set(old_ev["qdrant_vector_ids"] or [])
    new_vectors = set(new_ev["qdrant_vector_ids"] or [])
    added_vectors = sorted(new_vectors - old_vectors)
    removed_vectors = sorted(old_vectors - new_vectors)
    shared_vectors = sorted(old_vectors & new_vectors)

    added_chunks = []
    new_chunk_list = new_ev["context_chunks"] or []
    new_vec_list = new_ev["qdrant_vector_ids"] or []
    for vid in added_vectors:
        if vid in new_vec_list:
            idx = new_vec_list.index(vid)
            if idx < len(new_chunk_list):
                added_chunks.append({"vector_id": vid, "chunk_preview": new_chunk_list[idx][:200]})

    # ── Seat Deltas (which seats flipped?) ────────────────────────
    old_opinions = {op["seat"]: op for op in (old_ev["seat_opinions"] or [])}
    new_opinions = {op["seat"]: op for op in (new_ev["seat_opinions"] or [])}

    seat_deltas = []
    for seat_id in sorted(set(list(old_opinions.keys()) + list(new_opinions.keys()))):
        old_op = old_opinions.get(seat_id, {})
        new_op = new_opinions.get(seat_id, {})

        old_signal = old_op.get("signal", "N/A")
        new_signal = new_op.get("signal", "N/A")
        old_conviction = old_op.get("conviction", 0)
        new_conviction = new_op.get("conviction", 0)

        flipped = old_signal != new_signal
        conviction_delta = round(new_conviction - old_conviction, 4) if isinstance(new_conviction, (int, float)) and isinstance(old_conviction, (int, float)) else 0

        seat_deltas.append({
            "seat": seat_id,
            "persona": new_op.get("persona", old_op.get("persona", f"Seat {seat_id}")),
            "model_used": new_op.get("model_used", ""),
            "old_signal": old_signal,
            "new_signal": new_signal,
            "flipped": flipped,
            "old_conviction": old_conviction,
            "new_conviction": new_conviction,
            "conviction_delta": conviction_delta,
        })

    flipped_count = sum(1 for s in seat_deltas if s["flipped"])

    # ── Consensus Shift ───────────────────────────────────────────
    old_conv = float(old_ev["consensus_conviction"] or 0)
    new_conv = float(new_ev["consensus_conviction"] or 0)

    return {
        "case_slug": case_slug,
        "event_a": {
            "event_id": event_a,
            "timestamp": old_ev["timestamp"].isoformat() if old_ev["timestamp"] else None,
        },
        "event_b": {
            "event_id": event_b,
            "timestamp": new_ev["timestamp"].isoformat() if new_ev["timestamp"] else None,
        },
        "context_delta": {
            "added_vectors": len(added_vectors),
            "removed_vectors": len(removed_vectors),
            "shared_vectors": len(shared_vectors),
            "added_evidence": added_chunks,
            "removed_vector_ids": removed_vectors,
        },
        "seat_deltas": seat_deltas,
        "flipped_count": flipped_count,
        "consensus_shift": {
            "old_signal": old_ev["consensus_signal"] or "UNKNOWN",
            "new_signal": new_ev["consensus_signal"] or "UNKNOWN",
            "signal_changed": old_ev["consensus_signal"] != new_ev["consensus_signal"],
            "old_conviction": old_conv,
            "new_conviction": new_conv,
            "conviction_delta": round(new_conv - old_conv, 4),
        },
    }


@router.get("/council/event/{event_id}")
async def get_deliberation_event(event_id: str):
    """
    Fetch a single deliberation event with full detail: all 9 opinions,
    frozen context vectors, roster snapshot, and cryptographic signature.
    """
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _query_ledger, """
        SELECT *
        FROM legal_cmd.deliberation_events
        WHERE event_id = %s
    """, (event_id,))

    if not rows:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")

    row = rows[0]
    return {
        "event_id": str(row["event_id"]),
        "case_slug": row["case_slug"],
        "case_number": row["case_number"],
        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
        "trigger_type": row["trigger_type"],
        "qdrant_vector_ids": row["qdrant_vector_ids"] or [],
        "context_chunks": row["context_chunks"] or [],
        "user_prompt": row["user_prompt"],
        "moe_roster_snapshot": row["moe_roster_snapshot"],
        "seat_opinions": row["seat_opinions"],
        "counsel_results": row["counsel_results"],
        "consensus_signal": row["consensus_signal"],
        "consensus_conviction": float(row["consensus_conviction"] or 0),
        "execution_time_ms": row["execution_time_ms"],
        "sha256_signature": row["sha256_signature"],
    }


@router.get("/council/event/{event_id}/verify")
async def verify_deliberation_event(event_id: str):
    """
    Tamper check: recompute the SHA-256 signature from stored payload
    fields and compare against the sealed signature.

    Returns verified=true if the hash matches, false if any field
    has been altered since vaulting.
    """
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _query_ledger, """
        SELECT case_slug, qdrant_vector_ids, user_prompt,
               moe_roster_snapshot, seat_opinions, counsel_results,
               sha256_signature
        FROM legal_cmd.deliberation_events
        WHERE event_id = %s
    """, (event_id,))

    if not rows:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")

    row = rows[0]
    stored_sig = row["sha256_signature"]

    recomputed = compute_signature(
        case_slug=row["case_slug"],
        vector_ids=row["qdrant_vector_ids"] or [],
        user_prompt=row["user_prompt"],
        roster_snapshot=row["moe_roster_snapshot"],
        seat_opinions=row["seat_opinions"],
        counsel_results=row["counsel_results"],
    )

    return {
        "event_id": event_id,
        "verified": recomputed == stored_sig,
        "stored_signature": stored_sig,
        "recomputed_signature": recomputed,
        "match": recomputed == stored_sig,
        "tamper_detected": recomputed != stored_sig,
    }


# ─── Agentic Evidence Ingest ─────────────────────────────────────────

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"
PRIME_TRUST_SLUG = "prime-trust-23-11161"
PRIME_TRUST_CASE_ID = 1


@router.post("/council/ingest/sota")
async def agentic_evidence_ingest(
    file: UploadFile = File(...),
    client_hash: str = Form(...),
):
    """
    Edge-cryptography evidence ingest: verify client SHA-256, write to NAS,
    register in legal.case_evidence and legal.case_actions.
    """
    file_bytes = await file.read()
    server_hash = hashlib.sha256(file_bytes).hexdigest()

    if server_hash != client_hash:
        raise HTTPException(
            status_code=400,
            detail=f"Chain of custody broken: client={client_hash[:16]}... server={server_hash[:16]}...",
        )

    logger.info(
        "ingest_hash_verified",
        hash=server_hash[:16],
        filename=file.filename,
        size_bytes=len(file_bytes),
    )

    case_slug = PRIME_TRUST_SLUG
    nas_dir = os.path.join(NAS_LEGAL_ROOT, case_slug, "receipts")
    os.makedirs(nas_dir, exist_ok=True)

    safe_filename = os.path.basename(file.filename or "evidence.pdf")
    final_path = os.path.join(nas_dir, safe_filename)

    with open(final_path, "wb") as f:
        f.write(file_bytes)

    loop = asyncio.get_running_loop()

    def _register_evidence():
        conn = get_vault_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO legal.case_evidence
                    (case_id, evidence_type, file_path, description, relevance, is_critical)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    PRIME_TRUST_CASE_ID,
                    "ingest_upload",
                    final_path,
                    f"Auto-ingested via Zero-Touch Ingest. Original filename: {safe_filename}. SHA-256: {server_hash}.",
                    "Uploaded evidence pending classification by DGX vision model.",
                    False,
                ),
            )
            evidence_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO legal.case_actions
                    (case_id, action_type, description, status, attachments, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    PRIME_TRUST_CASE_ID,
                    "evidence_ingested",
                    f"Evidence file '{safe_filename}' ingested via Agentic Zero-Touch Ingest. "
                    f"SHA-256 verified: {server_hash[:16]}...",
                    "completed",
                    [final_path],
                    f"Client-side hash matched server-side hash. File vaulted to NAS at {final_path}.",
                ),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            return evidence_id, action_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    evidence_id, action_id = await loop.run_in_executor(None, _register_evidence)

    logger.info(
        "ingest_complete",
        case_slug=case_slug,
        nas_path=final_path,
        evidence_id=evidence_id,
        action_id=action_id,
    )

    return {
        "status": "verified_and_routed",
        "case_slug": case_slug,
        "nas_path": final_path,
        "sha256_signature": server_hash,
        "evidence_id": evidence_id,
        "action_id": action_id,
        "extracted_entities": {
            "type": "Document (pending DGX vision classification)",
            "tracking_number": "N/A — requires multimodal extraction",
        },
    }
