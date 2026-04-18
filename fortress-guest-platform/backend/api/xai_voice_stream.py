"""
XAI VOICE STREAM — Twilio ↔ xAI Realtime WebSocket Proxy
=========================================================
Fortress Prime | Voice Matrix (Level 6) — Cloud Route

Zero-transcoding bidirectional bridge between Twilio Media Streams
and the xAI Grok Voice Agent API.  Both endpoints speak native
G.711 mu-law (audio/pcmu) at 8 kHz, so audio payloads pass through
as raw base64 — no local STT, LLM, or TTS containers required.

Architecture:
    Phone → Twilio → WS(mu-law) → THIS PROXY → WS(mu-law) → xAI Grok
    Phone ← Twilio ← WS(mu-law) ← THIS PROXY ← WS(mu-law) ← xAI Grok

xAI handles VAD, STT, reasoning, and TTS internally with sub-200ms
latency.  The proxy injects guest context from Qdrant into the xAI
session prompt so Grok has the same operational knowledge as the
local SWARM pipeline.

Endpoints:
    WS   /api/xai/voice/stream            — Twilio Media Stream proxy
    POST /api/xai/webhooks/twilio-voice   — TwiML trigger (points to xAI route)
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

# ── Path bootstrap ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.daemons.data_sanitizer import sanitize_phone

log = logging.getLogger("crog.voice.xai")

router = APIRouter(tags=["Voice-xAI"])

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
XAI_VOICE = os.getenv("XAI_VOICE", "Ara")
VOICE_WS_HOST = os.getenv("VOICE_WS_HOST", "crog-ai.com")

SYSTEM_PROMPT = """You are Taylor, the friendly and professional phone receptionist \
for Cabin Rentals of Georgia. You handle guest calls about bookings, amenities, \
check-in/check-out, and property questions.

Rules:
- Keep responses short and conversational (1-3 sentences). This is a phone call.
- Be warm, friendly, and professional. You have a slight Southern charm.
- If you don't know something specific, say you'll have someone call back.
- Never fabricate cabin details, prices, or availability.
- For emergencies, say you're connecting them to the property manager immediately.
- Address returning guests by name when possible."""


# ══════════════════════════════════════════════════════════════════════════════
# GUEST CONTEXT (reuse the same Qdrant + DB lookup as the local pipeline)
# ══════════════════════════════════════════════════════════════════════════════

def _build_guest_context(phone: str) -> str:
    """Query Qdrant for golden responses and DB for guest identity."""
    context_parts = []

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
                context_parts.append(
                    f"Returning guest ({total} prior messages). "
                    f"Cabin history: {', '.join(cabins) or 'unknown'}."
                )
            else:
                context_parts.append("First-time caller, no prior history.")
        conn.close()
    except Exception as e:
        log.warning("xai_guest_lookup_failed  phone=%s  error=%s", phone, e)
        context_parts.append("Guest lookup unavailable.")

    return "\n".join(context_parts)


# ══════════════════════════════════════════════════════════════════════════════
# TWILIO → xAI PROXY (the core bridge)
# ══════════════════════════════════════════════════════════════════════════════

async def _proxy_xai_to_twilio(xai_ws, twilio_ws, stream_sid: str):
    """Read xAI events and forward audio deltas to Twilio."""
    try:
        async for raw in xai_ws:
            msg = json.loads(raw)
            event_type = msg.get("type", "")

            if event_type == "response.output_audio.delta":
                audio_payload = msg.get("delta", "")
                if audio_payload:
                    await twilio_ws.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": audio_payload},
                    })

            elif event_type == "input_audio_buffer.speech_started":
                await twilio_ws.send_json({
                    "event": "clear",
                    "streamSid": stream_sid,
                })
                log.info("xai_barge_in  sid=%s", stream_sid)

            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = msg.get("transcript", "")
                if transcript:
                    log.info('[GUEST]: "%s"', transcript)

            elif event_type == "response.output_audio_transcript.delta":
                pass  # incremental text, logged at .done

            elif event_type == "response.output_audio_transcript.done":
                transcript = msg.get("transcript", "")
                if transcript:
                    log.info('[AGENT]: "%s"', transcript)

            elif event_type == "error":
                log.error("xai_error  %s", json.dumps(msg.get("error", msg)))

    except websockets.exceptions.ConnectionClosed:
        log.info("xai_ws_closed  sid=%s", stream_sid)
    except Exception as e:
        log.error("xai_proxy_error  sid=%s  error=%s", stream_sid, e)


@router.websocket("/api/xai/voice/stream")
async def xai_twilio_voice_stream(twilio_ws: WebSocket):
    """
    Bidirectional proxy: Twilio Media Streams ↔ xAI Grok Voice Agent.

    Twilio sends mu-law audio → forwarded to xAI as input_audio_buffer.append.
    xAI sends response.output_audio.delta → forwarded to Twilio as media events.
    xAI handles all VAD, STT, LLM, and TTS internally.
    """
    await twilio_ws.accept()
    xai_ws = None
    xai_task: Optional[asyncio.Task] = None
    stream_sid = ""

    log.info("xai_ws_accepted  client=%s", twilio_ws.client.host if twilio_ws.client else "unknown")

    try:
        while True:
            raw = await twilio_ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                log.info("xai_twilio_connected  protocol=%s", msg.get("protocol", "unknown"))

            elif event == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamSid", "")
                call_sid = start_data.get("callSid", "")
                custom_params = start_data.get("customParameters", {})
                raw_phone = custom_params.get("caller_phone", "")

                phone_result = sanitize_phone(raw_phone)
                phone = phone_result[0] if isinstance(phone_result, tuple) else phone_result

                guest_context = _build_guest_context(phone)
                full_prompt = f"{SYSTEM_PROMPT}\n\nCaller: {phone}\n{guest_context}"

                log.info(
                    "xai_stream_start  sid=%s  call=%s  phone=%s",
                    stream_sid, call_sid, phone,
                )

                # Open outbound WebSocket to xAI
                xai_ws = await websockets.connect(
                    XAI_REALTIME_URL,
                    additional_headers={"Authorization": f"Bearer {XAI_API_KEY}"},
                )

                # Configure session: mu-law passthrough + server VAD
                await xai_ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "voice": XAI_VOICE,
                        "instructions": full_prompt,
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": 800,
                        },
                        "input_audio_transcription": {"model": "grok-2-public"},
                        "audio": {
                            "input": {"format": {"type": "audio/pcmu"}},
                            "output": {"format": {"type": "audio/pcmu"}},
                        },
                    },
                }))

                # Start the xAI → Twilio forwarding task
                xai_task = asyncio.create_task(
                    _proxy_xai_to_twilio(xai_ws, twilio_ws, stream_sid),
                    name=f"xai-proxy-{stream_sid}",
                )

                log.info("xai_session_configured  voice=%s  phone=%s", XAI_VOICE, phone)

            elif event == "media":
                if xai_ws:
                    payload = msg.get("media", {}).get("payload", "")
                    if payload:
                        await xai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": payload,
                        }))

            elif event == "stop":
                log.info("xai_stream_stop  sid=%s", stream_sid)
                break

    except WebSocketDisconnect:
        log.info("xai_twilio_disconnected  sid=%s", stream_sid)
    except Exception as e:
        log.error("xai_ws_error  sid=%s  error=%s", stream_sid, e, exc_info=True)
    finally:
        if xai_task and not xai_task.done():
            xai_task.cancel()
        if xai_ws:
            await xai_ws.close()
        try:
            await twilio_ws.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# TWIML TRIGGER — Points Twilio to the xAI WebSocket route
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/api/xai/webhooks/twilio-voice")
async def xai_twilio_voice_webhook(request: Request):
    """
    TwiML trigger for the xAI route.

    Identical to the local pipeline's TwiML but points the <Stream>
    to the /api/xai/voice/stream WebSocket endpoint.
    """
    form = await request.form()
    caller = form.get("From", "")
    call_sid = form.get("CallSid", "")

    log.info("xai_voice_trigger  from=%s  call_sid=%s", caller, call_sid)

    safe_caller = xml_escape(caller)

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{xml_escape(VOICE_WS_HOST)}/api/xai/voice/stream">'
        f'<Parameter name="caller_phone" value="{safe_caller}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )

    return Response(content=twiml, media_type="application/xml", status_code=200)
