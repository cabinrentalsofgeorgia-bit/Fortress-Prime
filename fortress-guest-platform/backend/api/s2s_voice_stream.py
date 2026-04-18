"""
S2S VOICE STREAM — Twilio ↔ OpenAI/xAI Realtime API Proxy
==========================================================
Fortress Prime | Voice Matrix (Level 6) — S2S Cloud Route

High-speed bidirectional WebSocket proxy between Twilio Media Streams
and an OpenAI-compatible Speech-to-Speech Realtime API.  Audio passes
through as raw G.711 mu-law — zero transcoding, sub-300ms latency.

The cloud model handles VAD, STT, reasoning, and TTS internally.
When the model needs local knowledge (cabin policies, guest history),
it calls the ``search_local_memory`` tool, which queries the Fortress
Qdrant vector database in real time and feeds the result back into
the conversation — all while the caller waits naturally.

Architecture:
    Phone → Twilio → WS(g711_ulaw) → THIS PROXY → WS(g711_ulaw) → Cloud S2S
    Phone ← Twilio ← WS(g711_ulaw) ← THIS PROXY ← WS(g711_ulaw) ← Cloud S2S
                                          ↕
                                    Qdrant (local)

Compatible with:
    - OpenAI Realtime API  (gpt-4o-realtime-preview)
    - xAI Grok Voice Agent (grok-4-1-fast-non-reasoning)

Switch provider by changing S2S_WS_URL + S2S_API_KEY env vars.

Endpoints:
    WS   /api/s2s/voice/stream            — Twilio Media Stream proxy
    POST /api/s2s/webhooks/twilio-voice   — TwiML trigger
"""

import os
import sys
import json
import asyncio
import logging
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Response

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.daemons.data_sanitizer import sanitize_phone

log = logging.getLogger("crog.voice.s2s")

router = APIRouter(tags=["Voice-S2S"])

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — swap provider by changing these two env vars
# ══════════════════════════════════════════════════════════════════════════════

S2S_WS_URL = os.getenv(
    "S2S_WS_URL",
    "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
)
S2S_API_KEY = os.getenv("S2S_API_KEY", os.getenv("OPENAI_API_KEY", ""))
S2S_VOICE = os.getenv("S2S_VOICE", "alloy")
VOICE_WS_HOST = os.getenv("VOICE_WS_HOST", "crog-ai.com")

# OpenAI uses "OpenAI-Beta: realtime=v1"; xAI uses plain Bearer auth.
# Detect provider from the URL to set the right headers.
_IS_OPENAI = "openai.com" in S2S_WS_URL

SYSTEM_PROMPT = """\
You are Taylor Knight, an elite guest experience agent for Cabin Rentals \
of Georgia. You speak naturally, warmly, and concisely with a slight \
Southern charm. Do not sound like a robot.

Rules:
- Keep responses to 1-3 sentences. This is a live phone call.
- If a guest asks a policy or property question, USE YOUR TOOLS to search \
the local knowledge base before answering. Never guess at policies.
- Never fabricate cabin details, prices, or availability.
- For emergencies, say you're connecting them to the property manager.
- Address returning guests by name when possible."""

TOOLS = [
    {
        "type": "function",
        "name": "search_local_memory",
        "description": (
            "Search the local Qdrant vector database for cabin policies, "
            "fire pit rules, amenity details, check-in procedures, or "
            "guest history. Call this BEFORE answering any property-specific "
            "question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query, e.g. 'Aska fire pit policy'",
                },
            },
            "required": ["query"],
        },
    }
]


# ══════════════════════════════════════════════════════════════════════════════
# QDRANT SEARCH — the real bridge to local memory
# ══════════════════════════════════════════════════════════════════════════════

def _search_qdrant(query: str) -> str:
    """
    Embed the query via nomic-embed-text and search guest_golden_responses.

    Returns the top matching golden response text, or a fallback message.
    This runs synchronously (called from an async context via to_thread).
    """
    import requests as http_client

    BASE = os.getenv("BASE_IP", "192.168.0.100")
    COLLECTION = "guest_golden_responses"

    try:
        embed_resp = http_client.post(
            f"http://{BASE}/v1/embeddings",
            json={"model": "nomic-embed-text:latest", "input": query},
            timeout=5,
        )
        embed_resp.raise_for_status()
        vector = embed_resp.json()["data"][0]["embedding"]

        from qdrant_client import QdrantClient

        qc = QdrantClient(host="localhost", port=6333, timeout=5,
                          check_compatibility=False)
        results = qc.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=3,
            with_payload=True,
        )

        if results.points and results.points[0].score > 0.5:
            parts = []
            for pt in results.points[:3]:
                if pt.score < 0.45:
                    break
                p = pt.payload
                parts.append(
                    f"[{p.get('cabin', 'General')}] "
                    f"Q: {p.get('guest_input', '')}\n"
                    f"A: {p.get('ai_output', '')}"
                )
            return "\n\n".join(parts)
        return "No specific policy found in the knowledge base for this query."

    except Exception as e:
        log.error("qdrant_search_failed  query=%s  error=%s", query[:60], e)
        return f"Knowledge base search temporarily unavailable: {e}"


async def _search_qdrant_async(query: str) -> str:
    """Run the blocking Qdrant search in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _search_qdrant, query)


# ══════════════════════════════════════════════════════════════════════════════
# GUEST CONTEXT
# ══════════════════════════════════════════════════════════════════════════════

def _build_guest_context(phone: str) -> str:
    """Look up guest identity from Postgres."""
    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASS", os.getenv("DB_PASSWORD", "")),
        )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT phone_number, cabin_name,
                       COUNT(*) AS message_count,
                       MAX(created_at) AS last_contact
                FROM message_archive
                WHERE phone_number = %s
                GROUP BY phone_number, cabin_name
                ORDER BY last_contact DESC LIMIT 5
            """, (phone,))
            rows = cur.fetchall()
            if rows:
                total = sum(r["message_count"] for r in rows)
                cabins = [r["cabin_name"] for r in rows if r.get("cabin_name")]
                conn.close()
                return (
                    f"Returning guest ({total} prior messages). "
                    f"Cabin history: {', '.join(cabins) or 'unknown'}."
                )
        conn.close()
    except Exception as e:
        log.warning("s2s_guest_lookup_failed  phone=%s  error=%s", phone, e)
    return "First-time caller, no prior history."


# ══════════════════════════════════════════════════════════════════════════════
# TWIML TRIGGER
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/webhooks/twilio-voice")
async def s2s_twilio_voice_webhook(request: Request):
    """TwiML trigger that points Twilio to the S2S WebSocket proxy."""
    form = await request.form()
    caller = form.get("From", "")
    call_sid = form.get("CallSid", "")

    log.info("s2s_voice_trigger  from=%s  call_sid=%s", caller, call_sid)

    safe_caller = xml_escape(caller)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{xml_escape(VOICE_WS_HOST)}/api/s2s/voice/stream">'
        f'<Parameter name="caller_phone" value="{safe_caller}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml", status_code=200)


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET PROXY — the core S2S bridge
# ══════════════════════════════════════════════════════════════════════════════

@router.websocket("/voice/stream")
async def s2s_websocket_endpoint(twilio_ws: WebSocket):
    """
    High-speed bidirectional proxy: Twilio ↔ Cloud S2S Model.

    Task A (Twilio → Cloud): forwards raw mu-law audio payloads.
    Task B (Cloud → Twilio): forwards audio deltas + handles tool calls.
    """
    await twilio_ws.accept()
    log.info("s2s_ws_accepted  client=%s", twilio_ws.client.host if twilio_ws.client else "unknown")

    headers = {"Authorization": f"Bearer {S2S_API_KEY}"}
    if _IS_OPENAI:
        headers["OpenAI-Beta"] = "realtime=v1"

    stream_sid = ""
    phone = ""

    try:
        async with websockets.connect(S2S_WS_URL, additional_headers=headers) as llm_ws:
            log.info("s2s_cloud_connected  url=%s", S2S_WS_URL.split("?")[0])

            async def receive_from_twilio():
                nonlocal stream_sid, phone
                try:
                    while True:
                        data = await twilio_ws.receive_text()
                        msg = json.loads(data)

                        if msg["event"] == "start":
                            start_data = msg.get("start", {})
                            stream_sid = start_data.get("streamSid", "")
                            call_sid = start_data.get("callSid", "")
                            raw_phone = start_data.get("customParameters", {}).get("caller_phone", "")
                            phone_result = sanitize_phone(raw_phone)
                            phone = phone_result[0] if isinstance(phone_result, tuple) else phone_result

                            guest_context = _build_guest_context(phone)
                            full_prompt = f"{SYSTEM_PROMPT}\n\nCaller: {phone}\n{guest_context}"

                            session_config = {
                                "type": "session.update",
                                "session": {
                                    "instructions": full_prompt,
                                    "voice": S2S_VOICE,
                                    "input_audio_format": "g711_ulaw",
                                    "output_audio_format": "g711_ulaw",
                                    "turn_detection": {"type": "server_vad"},
                                    "tools": TOOLS,
                                    "tool_choice": "auto",
                                },
                            }
                            await llm_ws.send(json.dumps(session_config))

                            log.info(
                                "s2s_stream_start  sid=%s  call=%s  phone=%s  voice=%s",
                                stream_sid, call_sid, phone, S2S_VOICE,
                            )

                        elif msg["event"] == "media":
                            payload = msg.get("media", {}).get("payload", "")
                            if payload:
                                await llm_ws.send(json.dumps({
                                    "type": "input_audio_buffer.append",
                                    "audio": payload,
                                }))

                        elif msg["event"] == "stop":
                            log.info("s2s_twilio_stop  sid=%s", stream_sid)
                            return

                except WebSocketDisconnect:
                    log.info("s2s_twilio_disconnected  sid=%s", stream_sid)

            async def receive_from_llm():
                try:
                    async for raw in llm_ws:
                        event = json.loads(raw)
                        etype = event.get("type", "")

                        # ── Audio delta: forward to Twilio ──
                        if etype == "response.audio.delta":
                            delta = event.get("delta", "")
                            if delta and stream_sid:
                                await twilio_ws.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": delta},
                                })

                        # ── xAI variant: response.output_audio.delta ──
                        elif etype == "response.output_audio.delta":
                            delta = event.get("delta", "")
                            if delta and stream_sid:
                                await twilio_ws.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": delta},
                                })

                        # ── Tool call: bridge to local Qdrant ──
                        elif etype == "response.function_call_arguments.done":
                            call_id = event.get("call_id", "")
                            fn_name = event.get("name", "")
                            args = json.loads(event.get("arguments", "{}"))

                            if fn_name == "search_local_memory":
                                query = args.get("query", "")
                                log.info("s2s_tool_call  fn=%s  query=%s", fn_name, query[:80])

                                result = await _search_qdrant_async(query)
                                log.info("s2s_tool_result  chars=%d  preview=%s", len(result), result[:80])

                                await llm_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result,
                                    },
                                }))
                                await llm_ws.send(json.dumps({"type": "response.create"}))

                        # ── Barge-in: clear Twilio playback ──
                        elif etype == "input_audio_buffer.speech_started":
                            if stream_sid:
                                await twilio_ws.send_json({
                                    "event": "clear",
                                    "streamSid": stream_sid,
                                })
                                log.info("s2s_barge_in  sid=%s", stream_sid)

                        # ── Transcript logging ──
                        elif etype == "conversation.item.input_audio_transcription.completed":
                            t = event.get("transcript", "")
                            if t:
                                log.info('[GUEST]: "%s"', t)

                        elif etype in (
                            "response.audio_transcript.done",
                            "response.output_audio_transcript.done",
                        ):
                            t = event.get("transcript", "")
                            if t:
                                log.info('[AGENT]: "%s"', t)

                        elif etype == "error":
                            log.error("s2s_cloud_error  %s", json.dumps(event.get("error", event)))

                except websockets.exceptions.ConnectionClosed:
                    log.info("s2s_cloud_disconnected  sid=%s", stream_sid)

            await asyncio.gather(receive_from_twilio(), receive_from_llm())

    except Exception as e:
        log.error("s2s_proxy_error  sid=%s  error=%s", stream_sid, e, exc_info=True)
    finally:
        try:
            await twilio_ws.close()
        except Exception:
            pass
        log.info("s2s_session_ended  sid=%s  phone=%s", stream_sid, phone)
