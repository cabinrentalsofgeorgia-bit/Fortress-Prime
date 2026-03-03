"""
Module CF-01: Guardian Ops — Property Vision Inspection API
=============================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All vision inference on Muscle Node GPU. No cloud APIs.

Headless, API-First microservice wrapping the Guardian Vision Engine.
Cleaners upload a photo from their phone, the Muscle Node's LLaVA model
inspects it, and the API returns a structured Pass/Fail report with
specific remediation instructions.

Endpoints:
    POST /v1/inspect/room         Single room inspection (upload photo)
    POST /v1/inspect/cabin        Full cabin turnover (multi-room upload)
    GET  /v1/inspect/history      Recent inspection results from audit trail
    GET  /v1/rooms                List supported room types + checklists
    GET  /health                  Cluster + service health check

Run:
    cd /home/admin/Fortress-Prime
    python3 -m uvicorn Modules.CF-01_GuardianOps.api:app --host 0.0.0.0 --port 8001

Swagger UI:
    http://192.168.0.100:8001/docs

Dependencies:
    pip install python-multipart  (required for file uploads)

Author: Fortress Prime Architect
Version: 1.0.0
"""

import os
import sys
import json
import uuid
import shutil
import asyncio
import importlib.util
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from functools import partial

import psycopg2
import psycopg2.extras
from fastapi import (
    FastAPI, APIRouter, HTTPException, Query, UploadFile, File, Form,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests

# ---------------------------------------------------------------------------
# Engine Import (directory has a hyphen — use importlib)
# ---------------------------------------------------------------------------
_engine_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vision_engine.py"
)
_spec = importlib.util.spec_from_file_location("vision_engine", _engine_path)
_engine_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine_mod)

GuardianVisionEngine = _engine_mod.GuardianVisionEngine
ROOM_CHECKLISTS = _engine_mod.ROOM_CHECKLISTS

# ---------------------------------------------------------------------------
# Project config (DB credentials, cluster topology)
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except ImportError:
    pass

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "fortress_db")
DB_USER     = os.getenv("DB_USER", "miner_bot")
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

from config import SPARK_02_IP
MUSCLE_URL = os.getenv("MUSCLE_URL", f"http://{SPARK_02_IP}:11434")

# Upload buffer directory (temp files cleaned after each inspection)
UPLOAD_BUFFER = os.getenv(
    "GUARDIAN_UPLOAD_BUFFER",
    "/tmp/fortress_guardian_buffer",
)

# Valid image extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB max upload


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_db_pool: Optional[Any] = None


def get_db_connection():
    """Get a PostgreSQL connection with auto-reconnect."""
    global _db_pool
    try:
        if _db_pool is None or _db_pool.closed:
            _db_pool = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            )
            _db_pool.autocommit = False
        _db_pool.cursor().execute("SELECT 1")
        return _db_pool
    except Exception:
        try:
            _db_pool = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            )
            _db_pool.autocommit = False
            return _db_pool
        except Exception:
            return None


def persist_to_maintenance_log(result: dict) -> bool:
    """
    INSERT an inspection result into the maintenance_log table.
    Every inspection is audited — no exceptions.
    Returns True on success, False on failure (non-blocking).
    """
    conn = get_db_connection()
    if conn is None:
        return False

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO maintenance_log (
                run_id, cabin_name, room_type, room_display,
                image_path, image_hash, image_size_bytes,
                overall_score, verdict, pass_threshold,
                items_passed, items_failed, items_total,
                ai_confidence_score, detected_by, json_parsed,
                issues_found, checklist_json, overall_impression, raw_analysis,
                inspector_id, inference_time_s, engine_version, generated_at
            ) VALUES (
                %(run_id)s, %(cabin_name)s, %(room_type)s, %(room_display)s,
                %(image_path)s, %(image_hash)s, %(image_size_bytes)s,
                %(overall_score)s, %(verdict)s, %(pass_threshold)s,
                %(items_passed)s, %(items_failed)s, %(items_total)s,
                %(ai_confidence_score)s, %(detected_by)s, %(json_parsed)s,
                %(issues_found)s, %(checklist_json)s, %(overall_impression)s,
                %(raw_analysis)s,
                %(inspector_id)s, %(inference_time_s)s, %(engine_version)s,
                %(generated_at)s
            )
        """, result)
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"[CF-01 API] Maintenance log persist failed (non-blocking): {e}")
        return False


# =============================================================================
# PYDANTIC MODELS — The Contract
# =============================================================================

# --- Response Models ---

class ChecklistItem(BaseModel):
    """A single item from the room inspection checklist."""
    id: str
    label: str
    passed: bool = Field(..., alias="pass")
    weight: int
    points_earned: int
    note: str = ""

    model_config = {"populate_by_name": True}


class InspectionResponse(BaseModel):
    """Full room inspection result — maps to maintenance_log row."""
    # Identifiers
    run_id: str
    cabin_name: str
    room_type: str
    room_display: str

    # Scores
    overall_score: float = Field(..., ge=0, le=100, description="Score out of 100")
    verdict: str = Field(..., description="PASS, FAIL, or ERROR")
    pass_threshold: int
    items_passed: int
    items_failed: int
    items_total: int

    # AI
    ai_confidence_score: float = Field(..., ge=0, le=1, description="Model confidence 0-1")
    detected_by: str = Field(..., description="Vision model that performed the analysis")

    # Details
    issues_found: List[str] = Field(
        default_factory=list,
        description="Human-readable list of failed items and extra issues",
    )
    remediation_message: str = Field(
        ..., description="SMS-ready message for the cleaner",
    )
    overall_impression: str

    # Metadata
    inspector_id: str
    inference_time_s: float
    engine_version: str
    generated_at: str
    persisted: bool = Field(
        default=False, description="Whether result was written to maintenance_log",
    )


class CabinInspectionResponse(BaseModel):
    """Full cabin turnover inspection — aggregates all rooms."""
    cabin_name: str
    cabin_score: float = Field(..., ge=0, le=100)
    cabin_verdict: str
    rooms_inspected: int
    rooms_passed: int
    rooms_failed: int
    all_issues: List[str]
    room_results: Dict[str, InspectionResponse]
    inspector_id: str
    generated_at: str
    rooms_persisted: int


class RoomTypeInfo(BaseModel):
    """Information about a supported room type."""
    room_type: str
    display_name: str
    items_count: int
    checklist_items: List[Dict[str, Any]]


class HistoryEntry(BaseModel):
    """A single maintenance_log row from the audit trail."""
    id: int
    run_id: str
    cabin_name: str
    room_type: str
    room_display: Optional[str]
    overall_score: float
    verdict: str
    ai_confidence_score: float
    detected_by: Optional[str]
    inspector_id: Optional[str]
    generated_at: str


class HealthResponse(BaseModel):
    """Service health check response."""
    status: str
    module: str
    engine_version: str
    muscle_node: str
    vision_model: str
    database: str
    upload_buffer: str
    supported_rooms: List[str]
    timestamp: str
    uptime_seconds: Optional[float] = None


# =============================================================================
# APPLICATION LIFECYCLE
# =============================================================================

_startup_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    global _startup_time
    _startup_time = datetime.now()

    # Ensure upload buffer exists
    os.makedirs(UPLOAD_BUFFER, exist_ok=True)

    print("=" * 60)
    print("  CF-01 Guardian Ops Vision API — ONLINE")
    print(f"  Startup:      {_startup_time.isoformat()}")
    print(f"  Database:     {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"  Muscle Node:  {MUSCLE_URL}")
    print(f"  Upload Buffer:{UPLOAD_BUFFER}")
    print(f"  Swagger:      http://0.0.0.0:8001/docs")
    print("=" * 60)

    # Pre-warm DB connection
    conn = get_db_connection()
    print(f"  Database: {'CONNECTED' if conn else 'UNAVAILABLE'}")

    yield

    # Shutdown: close DB, clean upload buffer
    global _db_pool
    if _db_pool and not _db_pool.closed:
        _db_pool.close()

    # Clean any leftover temp files
    if os.path.isdir(UPLOAD_BUFFER):
        for f in os.listdir(UPLOAD_BUFFER):
            try:
                os.remove(os.path.join(UPLOAD_BUFFER, f))
            except Exception:
                pass

    print("  CF-01 Guardian Ops Vision API — OFFLINE")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="Crog-Fortress Guardian Vision API",
    description=(
        "**Module CF-01** — Automated Property Vision Inspection for "
        "Cabin Rentals of Georgia.\n\n"
        "Upload a photo of any room, and the Muscle Node's LLaVA vision model "
        "will analyze it against a room-specific checklist, returning a "
        "Pass/Fail verdict with specific remediation instructions.\n\n"
        "- **Data Sovereignty**: All vision inference on local GPU cluster.\n"
        "- **Audit Trail**: Every inspection persisted to `maintenance_log` table.\n"
        "- **SMS-Ready**: Remediation messages formatted for cleaner texting.\n\n"
        "Part of the **Crog-Fortress-AI** proprietary PMS platform."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Inspection", "description": "Room and cabin inspection endpoints"},
        {"name": "Audit", "description": "Inspection history and audit trail"},
        {"name": "Reference", "description": "Room types and checklists"},
        {"name": "Operations", "description": "Health and diagnostics"},
    ],
    lifespan=lifespan,
)

# CORS — centralized origins from config.py (Cloudflare tunnel hostnames + LAN)
try:
    from config import CORS_ORIGINS as _cors_origins
except ImportError:
    _cors_origins = [
        "https://fortress.crog-ai.com",
        "https://api.crog-ai.com",
        "http://localhost:8501",
        "http://localhost:3000",
        "http://192.168.0.100:8501",
        "http://192.168.0.100:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTER (exported for gateway mounting)
# =============================================================================

router = APIRouter()

# =============================================================================
# HELPERS
# =============================================================================

async def save_upload(file: UploadFile) -> str:
    """
    Save an uploaded file to the temp buffer.
    Returns the temp file path.
    Validates file type and size before saving.
    """
    # Validate extension
    _, ext = os.path.splitext(file.filename or "upload.jpg")
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file type: '{ext}'. "
                f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
            ),
        )

    # Generate unique temp filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(UPLOAD_BUFFER, unique_name)

    # Stream to disk (don't load entire file into memory)
    try:
        total_bytes = 0
        with open(temp_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 64)  # 64KB chunks
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE:
                    # Cleanup oversized file
                    buffer.close()
                    os.remove(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB",
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    return temp_path


def cleanup_temp(path: str):
    """Remove a temp file. Silent on failure."""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def build_inspection_response(
    result: dict,
    engine: GuardianVisionEngine,
    persisted: bool,
) -> dict:
    """Transform engine result dict into API response dict."""
    # Parse issues from JSON string back to list
    issues = json.loads(result.get("issues_found", "[]"))

    # Generate SMS-ready remediation message
    remediation = engine.generate_remediation(result)

    return {
        "run_id":               result["run_id"],
        "cabin_name":           result["cabin_name"],
        "room_type":            result["room_type"],
        "room_display":         result["room_display"],
        "overall_score":        result["overall_score"],
        "verdict":              result["verdict"],
        "pass_threshold":       result["pass_threshold"],
        "items_passed":         result["items_passed"],
        "items_failed":         result["items_failed"],
        "items_total":          result["items_total"],
        "ai_confidence_score":  result["ai_confidence_score"],
        "detected_by":          result["detected_by"],
        "issues_found":         issues,
        "remediation_message":  remediation,
        "overall_impression":   result.get("overall_impression", ""),
        "inspector_id":         result["inspector_id"],
        "inference_time_s":     result["inference_time_s"],
        "engine_version":       result["engine_version"],
        "generated_at":         result["generated_at"],
        "persisted":            persisted,
    }


# =============================================================================
# ENDPOINTS
# =============================================================================

# ---- INSPECTION ----

@router.post(
    "/inspect/room",
    response_model=InspectionResponse,
    tags=["Inspection"],
    summary="Inspect a single room photo",
    description=(
        "Upload a photo of a room. The Muscle Node's LLaVA vision model "
        "analyzes it against the room-specific checklist and returns a "
        "Pass/Fail verdict with an SMS-ready remediation message.\n\n"
        "**Supported room types**: kitchen, bathroom, bedroom, living_room, "
        "exterior, game_room\n\n"
        "**Tip**: Use your phone's camera from the Swagger UI to test."
    ),
)
async def inspect_room(
    file: UploadFile = File(..., description="Room photo (JPG, PNG, WebP)"),
    room_type: str = Form(
        ...,
        description="Room type: kitchen, bathroom, bedroom, living_room, exterior, game_room",
    ),
    cabin_id: str = Form(
        ...,
        description="Cabin identifier (e.g., 'rolling_river')",
    ),
    inspector_id: str = Form(
        default="api_upload",
        description="Who is uploading (cleaner name, 'system', etc.)",
    ),
    persist: bool = Form(
        default=True,
        description="Write result to maintenance_log audit trail",
    ),
):
    """
    POST /v1/inspect/room — The core inspection endpoint.

    Pipeline:
    1. Upload streamed to temp buffer (cleaned up after)
    2. Engine dispatches to Muscle Node LLaVA
    3. AI analyzes against room checklist
    4. Weighted scoring produces Pass/Fail
    5. Result persisted to maintenance_log
    6. Remediation message returned for cleaner SMS
    """
    # Validate room type
    valid_rooms = list(ROOM_CHECKLISTS.keys())
    room_type = room_type.lower().strip()
    if room_type not in valid_rooms:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid room_type: '{room_type}'. Valid: {valid_rooms}",
        )

    # Save upload to temp buffer
    temp_path = await save_upload(file)

    try:
        # Run vision engine in thread pool (CPU+network bound, don't block event loop)
        loop = asyncio.get_event_loop()

        def _run_inspection():
            engine = GuardianVisionEngine(
                cabin_name=cabin_id,
                inspector_id=inspector_id,
            )
            result = engine.analyze_cleanliness(temp_path, room_type)
            return engine, result

        try:
            engine, result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_inspection),
                timeout=120.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="Vision inference timed out after 120s. Muscle Node may be unresponsive.",
            )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision engine error: {str(e)}")
    finally:
        # ALWAYS clean up the temp file — prevent NAS bloat
        cleanup_temp(temp_path)

    # Persist to audit trail
    persisted = False
    if persist:
        persisted = persist_to_maintenance_log(result)

    return build_inspection_response(result, engine, persisted)


@router.post(
    "/inspect/cabin",
    response_model=CabinInspectionResponse,
    tags=["Inspection"],
    summary="Full cabin turnover inspection (multi-room)",
    description=(
        "Upload photos for multiple rooms in a single request. "
        "Returns per-room results plus an aggregate cabin score and verdict.\n\n"
        "Each file must be paired with a matching room_type in the same order."
    ),
)
async def inspect_cabin(
    files: List[UploadFile] = File(..., description="Room photos (one per room)"),
    room_types: List[str] = Form(
        ...,
        description="Room types matching each file (same order)",
    ),
    cabin_id: str = Form(..., description="Cabin identifier"),
    inspector_id: str = Form(default="api_upload", description="Inspector name"),
    persist: bool = Form(default=True, description="Persist to audit trail"),
):
    """
    POST /v1/inspect/cabin — Full turnover inspection.

    Upload multiple room photos with matching room_types.
    The engine inspects each room and returns an aggregate cabin report.
    """
    if len(files) != len(room_types):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Mismatch: {len(files)} files but {len(room_types)} room_types. "
                f"Each file must have a matching room_type."
            ),
        )

    if len(files) > 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 rooms per cabin inspection.",
        )

    valid_rooms = list(ROOM_CHECKLISTS.keys())
    for rt in room_types:
        if rt.lower().strip() not in valid_rooms:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid room_type: '{rt}'. Valid: {valid_rooms}",
            )

    # Save all uploads to temp buffer
    temp_paths = {}
    saved_files = []
    try:
        for upload_file, room_type in zip(files, room_types):
            temp_path = await save_upload(upload_file)
            saved_files.append(temp_path)
            temp_paths[room_type.lower().strip()] = temp_path

        # Run full cabin inspection in thread pool
        loop = asyncio.get_event_loop()

        def _run_cabin_inspection():
            engine = GuardianVisionEngine(
                cabin_name=cabin_id,
                inspector_id=inspector_id,
            )
            cabin_report = engine.inspect_full_cabin(temp_paths)
            return engine, cabin_report

        try:
            engine, cabin_report = await asyncio.wait_for(
                loop.run_in_executor(None, _run_cabin_inspection),
                timeout=120.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="Cabin vision inference timed out after 120s. Muscle Node may be unresponsive.",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cabin inspection error: {str(e)}",
        )
    finally:
        # ALWAYS clean up ALL temp files
        for path in saved_files:
            cleanup_temp(path)

    # Persist each room result to audit trail
    rooms_persisted = 0
    response_rooms = {}
    for room_type, result in cabin_report.get("room_results", {}).items():
        was_persisted = False
        if persist:
            was_persisted = persist_to_maintenance_log(result)
            if was_persisted:
                rooms_persisted += 1

        response_rooms[room_type] = build_inspection_response(
            result, engine, was_persisted
        )

    return CabinInspectionResponse(
        cabin_name=cabin_report["cabin_name"],
        cabin_score=cabin_report["cabin_score"],
        cabin_verdict=cabin_report["cabin_verdict"],
        rooms_inspected=cabin_report["rooms_inspected"],
        rooms_passed=cabin_report["rooms_passed"],
        rooms_failed=cabin_report["rooms_failed"],
        all_issues=cabin_report["all_issues"],
        room_results=response_rooms,
        inspector_id=cabin_report["inspector_id"],
        generated_at=cabin_report["generated_at"],
        rooms_persisted=rooms_persisted,
    )


# ---- AUDIT TRAIL ----

@router.get(
    "/inspect/history",
    response_model=List[HistoryEntry],
    tags=["Audit"],
    summary="Recent inspection history",
    description="Query the maintenance_log audit trail for past inspections.",
)
async def get_inspection_history(
    limit: int = Query(default=25, ge=1, le=500, description="Number of entries"),
    cabin: Optional[str] = Query(default=None, description="Filter by cabin name"),
    room: Optional[str] = Query(default=None, description="Filter by room type"),
    verdict: Optional[str] = Query(
        default=None, description="Filter by verdict: PASS, FAIL, ERROR",
    ),
):
    """GET /v1/inspect/history — Audit trail query."""
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where_clauses = []
        params = []

        if cabin:
            where_clauses.append("cabin_name = %s")
            params.append(cabin)
        if room:
            where_clauses.append("room_type = %s")
            params.append(room.lower())
        if verdict:
            where_clauses.append("verdict = %s")
            params.append(verdict.upper())

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cur.execute(
            f"""
            SELECT id, run_id, cabin_name, room_type, room_display,
                   overall_score, verdict, ai_confidence_score,
                   detected_by, inspector_id, generated_at::text
            FROM maintenance_log
            {where_sql}
            ORDER BY generated_at DESC
            LIMIT %s
            """,
            params + [limit],
        )

        rows = cur.fetchall()
        return [dict(r) for r in rows]

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"History query failed: {str(e)}",
        )


# ---- REFERENCE ----

@router.get(
    "/rooms",
    response_model=List[RoomTypeInfo],
    tags=["Reference"],
    summary="List supported room types and checklists",
    description=(
        "Returns all supported room types with their inspection checklists. "
        "Useful for building UI dropdowns or understanding scoring weights."
    ),
)
async def list_room_types():
    """GET /v1/rooms — Room type reference."""
    result = []
    for room_type, config in ROOM_CHECKLISTS.items():
        result.append(RoomTypeInfo(
            room_type=room_type,
            display_name=config["display_name"],
            items_count=len(config["items"]),
            checklist_items=config["items"],
        ))
    return result


# ---- OPERATIONS ----

@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Operations"],
    summary="Service health check",
    description=(
        "Returns the status of the Guardian Vision service, "
        "Muscle Node reachability, vision model availability, "
        "and database connectivity."
    ),
)
async def health_check():
    """
    GET /health — Standard health endpoint.

    Checks:
    - Service: always online if responding
    - Muscle Node: Ollama API reachability + LLaVA model loaded
    - Database: PostgreSQL connectivity
    - Upload Buffer: writable temp directory
    """
    now = datetime.now()

    # DB check
    db_status = "connected"
    conn = get_db_connection()
    if conn is None:
        db_status = "unavailable"

    # Muscle Node check (is LLaVA reachable?)
    muscle_status = "offline"
    vision_model = "unknown"

    async def check_muscle():
        nonlocal muscle_status, vision_model
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: requests.get(f"{MUSCLE_URL}/api/tags", timeout=5)
            )
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                vision_models = [
                    m for m in models
                    if any(v in m.lower() for v in ["vision", "llava", "llama3.2"])
                ]
                if vision_models:
                    muscle_status = f"online ({len(models)} models, vision: {vision_models[0]})"
                    vision_model = vision_models[0]
                else:
                    muscle_status = f"online ({len(models)} models, no vision model loaded)"
                    vision_model = "not loaded"
            else:
                muscle_status = f"degraded (HTTP {resp.status_code})"
        except Exception:
            muscle_status = "offline"

    await check_muscle()

    # Upload buffer check
    buffer_status = "writable" if os.access(UPLOAD_BUFFER, os.W_OK) else "not writable"

    uptime = (now - _startup_time).total_seconds() if _startup_time else None

    return HealthResponse(
        status="online",
        module="CF-01 Guardian Ops",
        engine_version="1.0.0",
        muscle_node=muscle_status,
        vision_model=vision_model,
        database=db_status,
        upload_buffer=buffer_status,
        supported_rooms=list(ROOM_CHECKLISTS.keys()),
        timestamp=now.isoformat(),
        uptime_seconds=round(uptime, 1) if uptime else None,
    )


@router.get(
    "/",
    tags=["Operations"],
    summary="Service root",
    include_in_schema=False,
)
async def root():
    """Redirect to docs for convenience."""
    return {
        "service": "CF-01 Guardian Ops Vision API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "description": (
            "Cabin Rentals of Georgia — "
            "Automated Property Vision Inspection Engine"
        ),
    }


# =============================================================================
# STANDALONE MODE: include router on the local app
# =============================================================================

app.include_router(router, prefix="/v1")

# =============================================================================
# STANDALONE RUNNER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
