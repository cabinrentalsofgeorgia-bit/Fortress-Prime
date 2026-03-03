"""
DIVISION 3: THE OPS ENGINE
============================
Enterprise FastAPI service for Cabin Operations.

Endpoints:
    /health                         — Service health + DB ping
    /ops/properties                 — CRUD for cabin properties
    /ops/crew                       — CRUD for operations crew
    /ops/turnovers                  — Turnover management
    /ops/tasks                      — Task queue (the work)
    /ops/log                        — Audit trail (read-only)
    /ops/dashboard                  — Aggregated stats for dashboards

Swagger docs:  http://<host>:8000/docs
Grafana read:  Direct PostgreSQL connection to fortress_db

Module: CF-01 Guardian Ops — Division 3 Operations Kernel
"""

import os
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List
from contextlib import contextmanager

import uuid
import shutil
import asyncio
import importlib.util
from pathlib import Path

from fastapi import FastAPI, APIRouter, HTTPException, Query, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ops_engine")

# =============================================================================
# CONFIG
# =============================================================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="Fortress Ops Engine",
    description="Division 3 — Operational Command & Control API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ROUTER (exported for gateway mounting)
# =============================================================================

router = APIRouter()

# =============================================================================
# STATIC FILES & MOBILE FIELD INTERFACE
# =============================================================================

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/mobile", tags=["Field Interface"], include_in_schema=True)
async def mobile_field_ops():
    """Serve the mobile field operations interface for cleaning crews."""
    html_path = STATIC_DIR / "field_ops.html"
    if not html_path.exists():
        raise HTTPException(404, detail="Field interface not deployed")
    return FileResponse(str(html_path), media_type="text/html")

# =============================================================================
# CONNECTION POOL
# =============================================================================

pool: Optional[ThreadedConnectionPool] = None


def init_pool():
    global pool
    try:
        pool = ThreadedConnectionPool(
            POOL_MIN, POOL_MAX,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        logger.info(f"DB pool initialized ({POOL_MIN}-{POOL_MAX} connections) → {DB_NAME}@{DB_HOST}")
    except Exception as e:
        logger.error(f"DB pool init failed: {e}")
        raise


@app.on_event("startup")
async def startup():
    init_pool()
    logger.info("Ops Engine ONLINE — Division 3 Operational")


@app.on_event("shutdown")
async def shutdown():
    if pool:
        pool.closeall()
        logger.info("DB pool closed.")


@contextmanager
def get_conn():
    """Thread-safe connection from pool with auto-return."""
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit=False):
    """Yields a RealDictCursor. Commits on success if commit=True, rolls back on error."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


# =============================================================================
# JSON SERIALIZER (handles datetime, Decimal)
# =============================================================================

class OpsJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, default=self._serializer).encode("utf-8")

    @staticmethod
    def _serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


app.router.default_response_class = OpsJSONResponse


def _serialize_rows(rows):
    """Convert RealDictRow list to plain dicts with serializable values."""
    result = []
    for row in rows:
        d = {}
        for k, v in row.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
            else:
                d[k] = v
        result.append(d)
    return result


def _serialize_row(row):
    if row is None:
        return None
    return _serialize_rows([row])[0]


# =============================================================================
# AUDIT LOG HELPER
# =============================================================================

def _audit_log(cur, action: str, entity_type: str = None, entity_id: int = None, metadata: dict = None):
    cur.execute(
        "INSERT INTO ops_log (actor, action, entity_type, entity_id, metadata) VALUES (%s,%s,%s,%s,%s)",
        ("OpsEngine", action, entity_type, entity_id, json.dumps(metadata or {}))
    )


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class PropertyCreate(BaseModel):
    property_id: str = Field(..., description="Streamline property ID")
    internal_name: str
    address: Optional[str] = None
    access_code_wifi: Optional[str] = None
    access_code_door: Optional[str] = None
    trash_pickup_day: Optional[str] = "Tuesday"
    cleaning_sla_minutes: Optional[int] = 240
    hvac_filter_size: Optional[str] = None
    hot_tub_gallons: Optional[int] = None
    config_yaml: Optional[str] = None


class CrewCreate(BaseModel):
    name: str
    role: str = Field(..., description="Cleaner, Maintenance, Inspector, Manager")
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    current_location: Optional[str] = None
    skills: Optional[dict] = {}


class CrewUpdate(BaseModel):
    status: Optional[str] = None
    current_location: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    skills: Optional[dict] = None


class TurnoverCreate(BaseModel):
    property_id: str
    reservation_id_out: Optional[str] = None
    reservation_id_in: Optional[str] = None
    checkout_time: str = Field(..., description="ISO format: 2026-02-12T11:00:00")
    checkin_time: str = Field(..., description="ISO format: 2026-02-12T16:00:00")
    window_hours: Optional[float] = None
    notes: Optional[str] = None


class TaskCreate(BaseModel):
    type: str = Field(..., description="CLEANING, INSPECTION, REPAIR, HOT_TUB")
    priority: Optional[str] = "NORMAL"
    property_id: str
    assigned_to: Optional[int] = None
    turnover_id: Optional[int] = None
    description: Optional[str] = None
    deadline: Optional[str] = None


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    priority: Optional[str] = None
    notes: Optional[str] = None


# =============================================================================
# HEALTH
# =============================================================================

@router.get("/health", tags=["System"])
def health_check():
    """Service health + database ping."""
    db_ok = False
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            db_ok = True
    except Exception:
        pass
    return {
        "status": "OPERATIONAL" if db_ok else "DEGRADED",
        "division": "Division 3 — Operations",
        "database": "CONNECTED" if db_ok else "DISCONNECTED",
        "timestamp": datetime.now().isoformat(),
    }


# =============================================================================
# PROPERTIES
# =============================================================================

@router.get("/properties", tags=["Properties"])
def list_properties():
    """List all managed cabin properties."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM ops_properties ORDER BY internal_name")
        return _serialize_rows(cur.fetchall())


@router.get("/properties/{property_id}", tags=["Properties"])
def get_property(property_id: str):
    """Get a single property by Streamline ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM ops_properties WHERE property_id = %s", (property_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail=f"Property {property_id} not found")
        return _serialize_row(row)


@router.post("/properties", tags=["Properties"], status_code=201)
def create_property(prop: PropertyCreate):
    """Register a new cabin property (UPSERT)."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO ops_properties
                (property_id, internal_name, address, access_code_wifi, access_code_door,
                 trash_pickup_day, cleaning_sla_minutes, hvac_filter_size, hot_tub_gallons, config_yaml)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (property_id) DO UPDATE SET
                internal_name = EXCLUDED.internal_name,
                address = COALESCE(EXCLUDED.address, ops_properties.address),
                access_code_wifi = COALESCE(EXCLUDED.access_code_wifi, ops_properties.access_code_wifi),
                access_code_door = COALESCE(EXCLUDED.access_code_door, ops_properties.access_code_door),
                trash_pickup_day = COALESCE(EXCLUDED.trash_pickup_day, ops_properties.trash_pickup_day),
                cleaning_sla_minutes = COALESCE(EXCLUDED.cleaning_sla_minutes, ops_properties.cleaning_sla_minutes),
                updated_at = CURRENT_TIMESTAMP
            RETURNING *
        """, (
            prop.property_id, prop.internal_name, prop.address,
            prop.access_code_wifi, prop.access_code_door,
            prop.trash_pickup_day, prop.cleaning_sla_minutes,
            prop.hvac_filter_size, prop.hot_tub_gallons, prop.config_yaml,
        ))
        row = cur.fetchone()
        _audit_log(cur, "CREATE_PROPERTY", "property", metadata={"property_id": prop.property_id})
        return _serialize_row(row)


# =============================================================================
# CREW
# =============================================================================

@router.get("/crew", tags=["Crew"])
def list_crew(status: Optional[str] = Query(None, description="Filter by ACTIVE, OFF_DUTY, TERMINATED")):
    """List operations crew members."""
    with get_cursor() as cur:
        if status:
            cur.execute("SELECT * FROM ops_crew WHERE status = %s ORDER BY name", (status.upper(),))
        else:
            cur.execute("SELECT * FROM ops_crew ORDER BY name")
        return _serialize_rows(cur.fetchall())


@router.post("/crew", tags=["Crew"], status_code=201)
def create_crew(member: CrewCreate):
    """Register a new crew member."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO ops_crew (name, role, phone, email, status, current_location, skills)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
        """, (
            member.name, member.role, member.phone, member.email,
            member.status, member.current_location, json.dumps(member.skills or {}),
        ))
        row = cur.fetchone()
        _audit_log(cur, "CREATE_CREW", "crew", row["id"], {"name": member.name, "role": member.role})
        return _serialize_row(row)


@router.patch("/crew/{crew_id}", tags=["Crew"])
def update_crew(crew_id: int, update: CrewUpdate):
    """Update crew member status, location, or contact info."""
    fields = []
    values = []
    for field_name, value in update.dict(exclude_unset=True).items():
        if value is not None:
            if field_name == "skills":
                fields.append(f"{field_name} = %s")
                values.append(json.dumps(value))
            else:
                fields.append(f"{field_name} = %s")
                values.append(value)

    if not fields:
        raise HTTPException(400, detail="No fields to update")

    values.append(crew_id)
    with get_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE ops_crew SET {', '.join(fields)} WHERE id = %s RETURNING *",
            values
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail=f"Crew member {crew_id} not found")
        _audit_log(cur, "UPDATE_CREW", "crew", crew_id, update.dict(exclude_unset=True))
        return _serialize_row(row)


# =============================================================================
# TURNOVERS
# =============================================================================

@router.get("/turnovers", tags=["Turnovers"])
def list_turnovers(
    status: Optional[str] = Query(None, description="PENDING, IN_PROGRESS, READY, LATE"),
    days_ahead: int = Query(7, description="Look-ahead window in days"),
):
    """List turnovers within the look-ahead window."""
    with get_cursor() as cur:
        sql = """
            SELECT t.*, p.internal_name
            FROM ops_turnovers t
            JOIN ops_properties p ON p.property_id = t.property_id
            WHERE t.checkout_time >= CURRENT_TIMESTAMP - INTERVAL '1 day'
              AND t.checkout_time < CURRENT_TIMESTAMP + %s * INTERVAL '1 day'
        """
        params = [days_ahead]
        if status:
            sql += " AND t.status = %s"
            params.append(status.upper())
        sql += " ORDER BY t.checkout_time ASC"
        cur.execute(sql, params)
        return _serialize_rows(cur.fetchall())


@router.post("/turnovers", tags=["Turnovers"], status_code=201)
def create_turnover(t: TurnoverCreate):
    """Create a new turnover (checkout → checkin pair)."""
    checkout_dt = datetime.fromisoformat(t.checkout_time)
    checkin_dt = datetime.fromisoformat(t.checkin_time)
    window = (checkin_dt - checkout_dt).total_seconds() / 3600

    with get_cursor(commit=True) as cur:
        # Verify property exists
        cur.execute("SELECT property_id FROM ops_properties WHERE property_id = %s", (t.property_id,))
        if not cur.fetchone():
            raise HTTPException(404, detail=f"Property {t.property_id} not found in ops_properties")

        cur.execute("""
            INSERT INTO ops_turnovers
                (property_id, reservation_id_out, reservation_id_in,
                 checkout_time, checkin_time, window_hours, notes, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING')
            RETURNING *
        """, (
            t.property_id, t.reservation_id_out, t.reservation_id_in,
            checkout_dt, checkin_dt, round(window, 2), t.notes,
        ))
        row = cur.fetchone()
        _audit_log(cur, "CREATE_TURNOVER", "turnover", row["id"], {
            "property_id": t.property_id, "window_hours": round(window, 2),
        })
        return _serialize_row(row)


@router.post("/turnovers/{turnover_id}/generate-tasks", tags=["Turnovers"])
def generate_tasks_for_turnover(turnover_id: int):
    """Generate CLEANING + INSPECTION tasks for a specific turnover."""
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM ops_turnovers WHERE id = %s", (turnover_id,))
        t = cur.fetchone()
        if not t:
            raise HTTPException(404, detail=f"Turnover {turnover_id} not found")

        # Idempotency check
        cur.execute("SELECT id FROM ops_tasks WHERE turnover_id = %s AND type = 'CLEANING'", (turnover_id,))
        if cur.fetchone():
            raise HTTPException(409, detail=f"Tasks already generated for turnover {turnover_id}")

        # Fetch SLA
        cur.execute(
            "SELECT cleaning_sla_minutes, hot_tub_gallons FROM ops_properties WHERE property_id = %s",
            (t["property_id"],)
        )
        prop = cur.fetchone() or {}
        sla = prop.get("cleaning_sla_minutes") or 240

        checkout = t["checkout_time"]
        window = float(t["window_hours"]) if t["window_hours"] else 5.0
        priority = "URGENT" if window < 4.0 else ("NORMAL" if window < 6.0 else "LOW")

        clean_start = checkout + timedelta(hours=1)
        clean_deadline = clean_start + timedelta(minutes=sla)
        inspect_deadline = clean_deadline + timedelta(hours=1)

        tasks = []

        # CLEANING
        cur.execute("""
            INSERT INTO ops_tasks (type, priority, property_id, turnover_id, description, deadline, status)
            VALUES ('CLEANING', %s, %s, %s, %s, %s, 'OPEN') RETURNING *
        """, (priority, t["property_id"], turnover_id, f"Standard Turnover Clean — {sla // 60}h SLA", clean_deadline))
        tasks.append(_serialize_row(cur.fetchone()))

        # INSPECTION
        cur.execute("""
            INSERT INTO ops_tasks (type, priority, property_id, turnover_id, description, deadline, status)
            VALUES ('INSPECTION', 'URGENT', %s, %s, 'Post-Clean QC Inspection (CF-01 Vision)', %s, 'OPEN') RETURNING *
        """, (t["property_id"], turnover_id, inspect_deadline))
        tasks.append(_serialize_row(cur.fetchone()))

        # HOT TUB (if applicable)
        if prop.get("hot_tub_gallons"):
            cur.execute("""
                INSERT INTO ops_tasks (type, priority, property_id, turnover_id, description, deadline, status)
                VALUES ('HOT_TUB', 'NORMAL', %s, %s, 'Hot Tub Chemical Balance + Cover Check', %s, 'OPEN') RETURNING *
            """, (t["property_id"], turnover_id, clean_deadline))
            tasks.append(_serialize_row(cur.fetchone()))

        # Update turnover
        cur.execute("UPDATE ops_turnovers SET status = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (turnover_id,))

        _audit_log(cur, "GENERATE_TASKS", "turnover", turnover_id, {
            "tasks_created": len(tasks), "priority": priority,
        })
        return {"turnover_id": turnover_id, "tasks_created": len(tasks), "tasks": tasks}


# =============================================================================
# TASKS
# =============================================================================

@router.get("/tasks", tags=["Tasks"])
def list_tasks(
    status: Optional[str] = Query(None, description="OPEN, ASSIGNED, IN_PROGRESS, BLOCKED, DONE"),
    type: Optional[str] = Query(None, description="CLEANING, INSPECTION, REPAIR, HOT_TUB"),
    property_id: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
):
    """List tasks with optional filters."""
    with get_cursor() as cur:
        conditions = []
        params = []

        if status:
            conditions.append("t.status = %s")
            params.append(status.upper())
        if type:
            conditions.append("t.type = %s")
            params.append(type.upper())
        if property_id:
            conditions.append("t.property_id = %s")
            params.append(property_id)
        if assigned_to:
            conditions.append("t.assigned_to = %s")
            params.append(assigned_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute(f"""
            SELECT t.*, p.internal_name,
                   c.name AS assigned_name
            FROM ops_tasks t
            JOIN ops_properties p ON p.property_id = t.property_id
            LEFT JOIN ops_crew c ON c.id = t.assigned_to
            {where}
            ORDER BY
                CASE t.priority
                    WHEN 'EMERGENCY' THEN 0
                    WHEN 'URGENT' THEN 1
                    WHEN 'NORMAL' THEN 2
                    WHEN 'LOW' THEN 3
                END,
                t.deadline ASC NULLS LAST
        """, params)
        return _serialize_rows(cur.fetchall())


@router.get("/tasks/{task_id}", tags=["Tasks"])
def get_task(task_id: int):
    """Get a single task by ID."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT t.*, p.internal_name, c.name AS assigned_name
            FROM ops_tasks t
            JOIN ops_properties p ON p.property_id = t.property_id
            LEFT JOIN ops_crew c ON c.id = t.assigned_to
            WHERE t.id = %s
        """, (task_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail=f"Task {task_id} not found")
        return _serialize_row(row)


@router.post("/tasks", tags=["Tasks"], status_code=201)
def create_task(task: TaskCreate):
    """Manually create a task (ad-hoc repairs, etc.)."""
    with get_cursor(commit=True) as cur:
        deadline_dt = datetime.fromisoformat(task.deadline) if task.deadline else None
        cur.execute("""
            INSERT INTO ops_tasks
                (type, priority, property_id, assigned_to, turnover_id, description, deadline, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'OPEN')
            RETURNING *
        """, (
            task.type.upper(), (task.priority or "NORMAL").upper(),
            task.property_id, task.assigned_to, task.turnover_id,
            task.description, deadline_dt,
        ))
        row = cur.fetchone()
        _audit_log(cur, "CREATE_TASK", "task", row["id"], {
            "type": task.type, "property_id": task.property_id,
        })
        return _serialize_row(row)


@router.patch("/tasks/{task_id}", tags=["Tasks"])
def update_task(task_id: int, update: TaskUpdate):
    """
    Update task status, assignment, or priority.
    Status transitions: OPEN → ASSIGNED → IN_PROGRESS → DONE | BLOCKED
    """
    with get_cursor(commit=True) as cur:
        # Build dynamic SET clause
        fields = []
        values = []
        for field_name, value in update.dict(exclude_unset=True).items():
            if field_name == "notes":
                continue  # handled separately
            if value is not None:
                fields.append(f"{field_name} = %s")
                values.append(value.upper() if field_name in ("status", "priority") else value)

        # Track timestamps
        if update.status:
            s = update.status.upper()
            if s == "IN_PROGRESS":
                fields.append("started_at = CURRENT_TIMESTAMP")
            elif s == "DONE":
                fields.append("completed_at = CURRENT_TIMESTAMP")

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(task_id)

        if not fields:
            raise HTTPException(400, detail="No fields to update")

        cur.execute(
            f"UPDATE ops_tasks SET {', '.join(fields)} WHERE id = %s RETURNING *",
            values
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail=f"Task {task_id} not found")

        # If task is DONE and linked to a turnover, check if all tasks for that turnover are done
        if update.status and update.status.upper() == "DONE" and row["turnover_id"]:
            cur.execute("""
                SELECT count(*) AS remaining FROM ops_tasks
                WHERE turnover_id = %s AND status != 'DONE'
            """, (row["turnover_id"],))
            remaining = cur.fetchone()["remaining"]
            if remaining == 0:
                cur.execute(
                    "UPDATE ops_turnovers SET status = 'READY', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (row["turnover_id"],)
                )
                _audit_log(cur, "TURNOVER_READY", "turnover", row["turnover_id"])

        _audit_log(cur, "UPDATE_TASK", "task", task_id, update.dict(exclude_unset=True))
        return _serialize_row(row)


# =============================================================================
# AUDIT LOG (read-only)
# =============================================================================

@router.get("/log", tags=["Audit Log"])
def get_audit_log(limit: int = Query(50, le=500), actor: Optional[str] = None):
    """Read the operations audit trail."""
    with get_cursor() as cur:
        if actor:
            cur.execute(
                "SELECT * FROM ops_log WHERE actor = %s ORDER BY timestamp DESC LIMIT %s",
                (actor, limit)
            )
        else:
            cur.execute("SELECT * FROM ops_log ORDER BY timestamp DESC LIMIT %s", (limit,))
        return _serialize_rows(cur.fetchall())


# =============================================================================
# DASHBOARD AGGREGATES (for Grafana / Streamlit / any frontend)
# =============================================================================

@router.get("/dashboard/summary", tags=["Dashboard"])
def dashboard_summary():
    """Aggregated operational metrics — designed for dashboard widgets."""
    with get_cursor() as cur:
        stats = {}

        cur.execute("SELECT count(*) FROM ops_properties")
        stats["total_properties"] = cur.fetchone()["count"]

        cur.execute("SELECT count(*) FROM ops_crew WHERE status = 'ACTIVE'")
        stats["active_crew"] = cur.fetchone()["count"]

        # Turnovers
        cur.execute("""
            SELECT status, count(*) AS cnt
            FROM ops_turnovers
            WHERE checkout_time >= CURRENT_DATE
            GROUP BY status
        """)
        stats["turnovers"] = {r["status"]: r["cnt"] for r in cur.fetchall()}

        # Tasks
        cur.execute("""
            SELECT status, count(*) AS cnt FROM ops_tasks GROUP BY status
        """)
        stats["tasks_by_status"] = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute("""
            SELECT priority, count(*) AS cnt
            FROM ops_tasks WHERE status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS')
            GROUP BY priority
        """)
        stats["active_tasks_by_priority"] = {r["priority"]: r["cnt"] for r in cur.fetchall()}

        # Upcoming turnovers (next 48h)
        cur.execute("""
            SELECT t.id, p.internal_name, t.checkout_time, t.checkin_time,
                   t.window_hours, t.status
            FROM ops_turnovers t
            JOIN ops_properties p ON p.property_id = t.property_id
            WHERE t.checkout_time >= CURRENT_TIMESTAMP
              AND t.checkout_time < CURRENT_TIMESTAMP + INTERVAL '48 hours'
            ORDER BY t.checkout_time
        """)
        stats["upcoming_turnovers_48h"] = _serialize_rows(cur.fetchall())

        stats["timestamp"] = datetime.now().isoformat()
        return stats


# =============================================================================
# VISION GATE (CF-01 Guardian Ops Integration)
# =============================================================================
# Import the GuardianVisionEngine from the CF-01 module.
# The module directory has a hyphen, so we use importlib.

_vision_engine_path = Path(__file__).resolve().parent.parent / "Modules" / "CF-01_GuardianOps" / "vision_engine.py"
_GuardianVisionEngine = None
_ROOM_CHECKLISTS = None

if _vision_engine_path.exists():
    _spec = importlib.util.spec_from_file_location("vision_engine", str(_vision_engine_path))
    _engine_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_engine_mod)
    _GuardianVisionEngine = _engine_mod.GuardianVisionEngine
    _ROOM_CHECKLISTS = _engine_mod.ROOM_CHECKLISTS
    logger.info(f"CF-01 Vision Engine loaded from {_vision_engine_path}")
else:
    logger.warning(f"CF-01 Vision Engine not found at {_vision_engine_path}")

# Upload buffer
UPLOAD_BUFFER = Path("/tmp/fortress_ops_uploads")
UPLOAD_BUFFER.mkdir(exist_ok=True)
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB


@router.get("/vision/rooms", tags=["Vision Gate"])
def list_room_types():
    """List supported room types and their inspection checklists."""
    if not _ROOM_CHECKLISTS:
        raise HTTPException(503, detail="Vision engine not loaded")
    return [
        {
            "room_type": rt,
            "display_name": cfg["display_name"],
            "items_count": len(cfg["items"]),
        }
        for rt, cfg in _ROOM_CHECKLISTS.items()
    ]


@router.post("/tasks/{task_id}/inspect", tags=["Vision Gate"])
async def inspect_task_completion(
    task_id: int,
    file: UploadFile = File(..., description="Photo proof of completed work"),
    room_type: str = Form(
        default="kitchen",
        description="Room type: kitchen, bathroom, bedroom, living_room, exterior, game_room",
    ),
):
    """
    Vision Gate: Upload a photo to complete a task.

    For INSPECTION and CLEANING tasks, the AI scores the photo:
    - Score >= 80: Task marked DONE, cleanliness_score written to turnover
    - Score < 80: Task stays open, remediation instructions returned

    The photo is analyzed by the Muscle Node's LLaVA vision model.
    Results are persisted to the maintenance_log audit table.
    """
    if not _GuardianVisionEngine:
        raise HTTPException(503, detail="Vision engine not available")

    # Fetch the task
    with get_cursor() as cur:
        cur.execute("""
            SELECT t.*, p.internal_name
            FROM ops_tasks t
            JOIN ops_properties p ON p.property_id = t.property_id
            WHERE t.id = %s
        """, (task_id,))
        task = cur.fetchone()

    if not task:
        raise HTTPException(404, detail=f"Task {task_id} not found")

    if task["status"] == "DONE":
        raise HTTPException(409, detail="Task is already completed")

    # Validate file
    _, ext = os.path.splitext(file.filename or "photo.jpg")
    ext = ext.lower()
    if ext not in ALLOWED_IMG_EXT:
        raise HTTPException(400, detail=f"Invalid file type: {ext}. Allowed: {sorted(ALLOWED_IMG_EXT)}")

    # Save upload to temp buffer
    unique_name = f"{uuid.uuid4().hex}{ext}"
    temp_path = UPLOAD_BUFFER / unique_name
    total_bytes = 0
    try:
        with open(temp_path, "wb") as buf:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    buf.close()
                    temp_path.unlink(missing_ok=True)
                    raise HTTPException(413, detail=f"File too large. Max: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
                buf.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Upload failed: {e}")

    # Run vision inspection
    try:
        loop = asyncio.get_event_loop()
        cabin_name = task["internal_name"] or "unknown"
        rt = room_type.lower().strip()

        def _run_vision():
            engine = _GuardianVisionEngine(
                cabin_name=cabin_name,
                inspector_id=f"crew_{task['assigned_to'] or 'unassigned'}",
            )
            result = engine.analyze_cleanliness(str(temp_path), rt)
            remediation = engine.generate_remediation(result)
            return result, remediation

        result, remediation = await loop.run_in_executor(None, _run_vision)

    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Vision engine error: {e}")
    finally:
        temp_path.unlink(missing_ok=True)

    score = result.get("overall_score", 0)
    verdict = result.get("verdict", "ERROR")
    issues = json.loads(result.get("issues_found", "[]"))

    # Persist to maintenance_log
    persisted = False
    try:
        with get_cursor(commit=True) as cur:
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
            persisted = True
    except Exception as e:
        logger.warning(f"maintenance_log persist failed (non-blocking): {e}")

    # GATE LOGIC: Pass or Reject
    gate_passed = verdict == "PASS"

    if gate_passed:
        # Auto-complete the task
        with get_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE ops_tasks
                SET status = 'DONE', completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (task_id,))

            # Write cleanliness score to turnover
            if task["turnover_id"]:
                cur.execute("""
                    UPDATE ops_turnovers
                    SET cleanliness_score = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (int(score), task["turnover_id"]))

                # Check if all tasks for this turnover are DONE
                cur.execute("""
                    SELECT count(*) AS remaining FROM ops_tasks
                    WHERE turnover_id = %s AND status != 'DONE'
                """, (task["turnover_id"],))
                remaining = cur.fetchone()["remaining"]
                if remaining == 0:
                    cur.execute("""
                        UPDATE ops_turnovers SET status = 'READY', updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (task["turnover_id"],))

            _audit_log(cur, "VISION_GATE_PASS", "task", task_id, {
                "score": score, "verdict": verdict, "cabin": cabin_name, "room": rt,
            })

    else:
        # Reject: task stays open, log the failure
        with get_cursor(commit=True) as cur:
            _audit_log(cur, "VISION_GATE_FAIL", "task", task_id, {
                "score": score, "verdict": verdict, "cabin": cabin_name, "room": rt,
                "issues": issues,
            })

    return {
        "task_id": task_id,
        "gate_passed": gate_passed,
        "score": score,
        "verdict": verdict,
        "pass_threshold": result.get("pass_threshold", 80),
        "issues": issues,
        "remediation": remediation,
        "cabin": cabin_name,
        "room_type": rt,
        "inference_time_s": result.get("inference_time_s", 0),
        "persisted": persisted,
        "task_status": "DONE" if gate_passed else task["status"],
    }


# =============================================================================
# QBO OAUTH2 CALLBACK (Operation Strangler Fig)
# =============================================================================

@router.get("/qbo/callback")
async def qbo_callback(code: str = None, realmId: str = None, error: str = None, state: str = None):
    """OAuth2 callback — Intuit redirects here after authorization."""
    if error:
        return {"error": error}
    if not code or not realmId:
        return {"error": "Missing code or realmId parameter"}
    try:
        from integrations.quickbooks.auth import exchange_code
        tokens = exchange_code(code, realmId)
        return {
            "status": "connected",
            "realm_id": realmId,
            "message": "QBO connected. The Strangler Fig has eyes.",
            "expires_in": tokens.get("expires_in"),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/qbo/status")
async def qbo_status():
    """Check QBO connection status."""
    try:
        from integrations.quickbooks.auth import get_status
        return get_status()
    except Exception as e:
        return {"connected": False, "error": str(e)}


# =============================================================================
# STANDALONE MODE: include router on the local app
# =============================================================================

app.include_router(router, prefix="/ops")

# =============================================================================
# ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.ops_api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        log_level="info",
    )
