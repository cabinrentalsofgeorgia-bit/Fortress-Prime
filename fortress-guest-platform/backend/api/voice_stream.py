"""
VOICE MATRIX — Twilio WebSocket Bridge (Level 6)
=================================================
Fortress Prime | Sector S01 (CROG) — Real-Time Voice AI Pipeline

Receives live audio via Twilio Media Streams over WebSocket, decodes
mu-law chunks into an async buffer for WhisperX (STT), and resolves
the caller's guest identity from the Fortress RFM graph.

Endpoints:
    WS   /api/voice/stream            — Twilio Media Stream receiver
    POST /api/webhooks/twilio-voice   — TwiML trigger (returns <Connect><Stream>)

Protocol (Twilio → Fortress):
    1. Twilio opens WS after receiving <Connect><Stream> TwiML
    2. JSON events: connected → start → media* → stop
    3. media.payload = base64-encoded mu-law audio (8 kHz, mono)

Audio Pipeline:
    Twilio → base64 decode → asyncio.Queue → [WhisperX STT consumer]
"""

import os
import sys
import json
import base64
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Response

import psycopg2
import psycopg2.extras
import psycopg2.pool

# ── Path bootstrap (ensure PROJECT_ROOT is importable) ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.daemons.data_sanitizer import sanitize_phone
from src.brain.voice.stt_consumer import process_audio_loop

log = logging.getLogger("crog.voice_matrix")

router = APIRouter(tags=["Voice"])

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE (self-contained pool — same config pattern as master_console)
# ══════════════════════════════════════════════════════════════════════════════

_DB_CFG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "fortress_db"),
    "user": os.getenv("DB_USER", "miner_bot"),
    "password": os.getenv("DB_PASS", os.getenv("DB_PASSWORD", "")),
}

_db_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _init_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5, **_DB_CFG
        )
        log.info("voice_matrix DB pool initialized (1-5)")


def _db_query(sql: str, params: tuple = (), commit: bool = False):
    _init_pool()
    conn = _db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if commit:
                conn.commit()
                try:
                    return cur.fetchall()
                except psycopg2.ProgrammingError:
                    return []
            return cur.fetchall()
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        _db_pool.putconn(conn)


# ══════════════════════════════════════════════════════════════════════════════
# GUEST IDENTITY RESOLVER — RFM Lookup by Phone
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_guest_identity(phone: str) -> dict:
    """
    Best-effort guest RFM lookup from message_archive history.

    Returns a context dict used by the OODA loop to personalize the
    voice conversation (returning guest vs. first-time caller, cabin
    affinity, etc.).
    """
    if not phone:
        return {
            "phone": phone,
            "known_guest": False,
            "message_count": 0,
            "cabins": [],
            "last_contact": None,
        }

    try:
        rows = _db_query("""
            SELECT phone_number, cabin_name,
                   COUNT(*) AS message_count,
                   MAX(created_at) AS last_contact
            FROM message_archive
            WHERE phone_number = %s
            GROUP BY phone_number, cabin_name
            ORDER BY last_contact DESC
            LIMIT 10
        """, (phone,))

        if rows:
            return {
                "phone": phone,
                "known_guest": True,
                "message_count": sum(r["message_count"] for r in rows),
                "cabins": [r["cabin_name"] for r in rows if r.get("cabin_name")],
                "last_contact": str(rows[0]["last_contact"]) if rows[0].get("last_contact") else None,
            }
    except Exception as e:
        log.warning("guest_identity_lookup_failed  phone=%s  error=%s", phone, e)

    return {
        "phone": phone,
        "known_guest": False,
        "message_count": 0,
        "cabins": [],
        "last_contact": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# VOICE SESSION — Per-Call State
# ══════════════════════════════════════════════════════════════════════════════

class VoiceSession:
    """
    Manages state for a single Twilio voice stream.

    The audio_buffer is an asyncio.Queue that WhisperX consumers will
    drain. A sentinel None value signals end-of-stream.

    The websocket reference enables the TTS producer to send audio
    back to Twilio. The tts_task tracks the active response pipeline
    (LLM + TTS) for barge-in cancellation.
    """

    def __init__(
        self,
        stream_sid: str,
        call_sid: str,
        phone: str,
        guest_identity: dict,
        websocket: Optional[WebSocket] = None,
    ):
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.phone = phone
        self.guest_identity = guest_identity
        self.websocket = websocket
        self.audio_buffer: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self.transcript_chunks: list[str] = []
        self.conversation_history: list[dict] = []
        self.tts_task: Optional[asyncio.Task] = None
        self.started_at = datetime.now(timezone.utc)
        self.sample_count = 0

    def push_audio(self, payload_b64: str):
        """Decode mu-law base64 audio and enqueue for WhisperX."""
        raw = base64.b64decode(payload_b64)
        self.sample_count += len(raw)
        self.audio_buffer.put_nowait(raw)

    async def close_buffer(self):
        """Signal end-of-stream to WhisperX consumers."""
        await self.audio_buffer.put(None)

    def archive_transcript(self):
        """Persist the call record + transcript to message_archive."""
        transcript = (
            "\n".join(self.transcript_chunks)
            if self.transcript_chunks
            else "[voice call — awaiting WhisperX transcription]"
        )
        duration_s = (datetime.now(timezone.utc) - self.started_at).total_seconds()

        try:
            _db_query("""
                INSERT INTO message_archive (
                    source, external_id, phone_number, message_body,
                    direction, status, received_at, created_at
                ) VALUES (
                    'twilio_voice', %s, %s, %s,
                    'inbound', 'completed', %s, NOW()
                )
            """, (
                self.stream_sid,
                self.phone,
                f"[Voice Call {duration_s:.0f}s] {transcript}",
                self.started_at,
            ), commit=True)
            log.info(
                "voice_archived  sid=%s  phone=%s  duration=%.0fs  samples=%d",
                self.stream_sid, self.phone, duration_s, self.sample_count,
            )
        except Exception as e:
            log.error("voice_archive_failed  sid=%s  error=%s", self.stream_sid, e)


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT — Twilio Media Stream Receiver
# ══════════════════════════════════════════════════════════════════════════════

@router.websocket("/api/voice/stream")
async def twilio_voice_stream(ws: WebSocket):
    """
    Twilio Media Streams WebSocket handler.

    Accepts the WS connection, then enters an event loop that processes
    three Twilio event types:

        start  → extract streamSid + caller phone, resolve guest identity,
                 launch STT consumer as a background task
        media  → decode mu-law audio, push into async buffer for WhisperX
        stop   → close buffer, await STT drain, archive transcript, close WS
    """
    await ws.accept()
    session: Optional[VoiceSession] = None
    stt_task: Optional[asyncio.Task] = None

    log.info(
        "voice_ws_accepted  client=%s",
        ws.client.host if ws.client else "unknown",
    )

    async def _shutdown_stt():
        """Drain the STT consumer gracefully, then archive."""
        nonlocal stt_task
        if session:
            await session.close_buffer()
        if stt_task and not stt_task.done():
            try:
                await asyncio.wait_for(stt_task, timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stt_task.cancel()
        if session:
            session.archive_transcript()

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            # ── Twilio handshake ──
            if event == "connected":
                log.info(
                    "voice_twilio_connected  protocol=%s",
                    msg.get("protocol", "unknown"),
                )

            # ── Stream start: extract identity, launch STT consumer ──
            elif event == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamSid", "")
                call_sid = start_data.get("callSid", "")
                custom_params = start_data.get("customParameters", {})
                raw_phone = custom_params.get("caller_phone", "")

                phone_result = sanitize_phone(raw_phone)
                phone = phone_result[0] if isinstance(phone_result, tuple) else phone_result
                guest_identity = _resolve_guest_identity(phone)

                session = VoiceSession(stream_sid, call_sid, phone, guest_identity, websocket=ws)
                stt_task = asyncio.create_task(
                    process_audio_loop(session),
                    name=f"stt-{stream_sid}",
                )

                log.info(
                    "voice_stream_start  sid=%s  call=%s  phone=%s  known=%s  cabins=%s",
                    stream_sid,
                    call_sid,
                    phone,
                    guest_identity["known_guest"],
                    guest_identity["cabins"],
                )

            # ── Audio chunk ──
            elif event == "media":
                if session:
                    payload = msg.get("media", {}).get("payload", "")
                    if payload:
                        session.push_audio(payload)

            # ── Stream end ──
            elif event == "stop":
                log.info(
                    "voice_stream_stop  sid=%s  samples=%d",
                    session.stream_sid if session else "no-session",
                    session.sample_count if session else 0,
                )
                await _shutdown_stt()
                break

    except WebSocketDisconnect:
        log.info(
            "voice_ws_disconnected  sid=%s",
            session.stream_sid if session else "no-session",
        )
        await _shutdown_stt()

    except Exception as e:
        log.error("voice_ws_error  error=%s", e, exc_info=True)
        await _shutdown_stt()

    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# TWIML TRIGGER — POST endpoint Twilio hits when a call first connects
# ══════════════════════════════════════════════════════════════════════════════

VOICE_WS_HOST = os.getenv("VOICE_WS_HOST", "crog-ai.com")


@router.post("/api/webhooks/twilio-voice")
async def twilio_voice_webhook(request: Request):
    """
    Twilio hits this when an inbound voice call connects.

    Returns TwiML containing <Connect><Stream> which tells Twilio to
    open a WebSocket Media Stream to our /api/voice/stream endpoint,
    passing the caller's phone number as a custom parameter.
    """
    form = await request.form()
    caller = form.get("From", "")
    call_sid = form.get("CallSid", "")
    to_phone = form.get("To", "")

    log.info(
        "twilio_voice_trigger  from=%s  to=%s  call_sid=%s",
        caller, to_phone, call_sid,
    )

    safe_caller = xml_escape(caller)

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{xml_escape(VOICE_WS_HOST)}/api/voice/stream">'
        f'<Parameter name="caller_phone" value="{safe_caller}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )

    return Response(content=twiml, media_type="application/xml", status_code=200)
