"""
Email Sensor Grid API — Iron Dome dynamic credential management.

Endpoints:
    GET    /email          List all sensors with health status
    POST   /email          Add a new email sensor (encrypts password)
    PATCH  /email/{id}     Update sensor (password, active toggle)
    DELETE /email/{id}     Soft-delete (set is_active = false)
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.encryption import encrypt, decrypt, get_fernet
from backend.core.security import get_current_user, require_manager_or_admin
from backend.models.staff import StaffUser

logger = structlog.get_logger()
router = APIRouter()

STALENESS_MINUTES = 15


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SensorOut(BaseModel):
    id: UUID
    email_address: str
    display_name: Optional[str] = None
    protocol: str
    server_address: str
    server_port: int
    use_ssl: bool
    is_active: bool
    last_sweep_at: Optional[datetime] = None
    last_sweep_status: str = "pending"
    last_sweep_error: Optional[str] = None
    emails_ingested_total: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SensorCreate(BaseModel):
    email_address: str = Field(..., min_length=5)
    display_name: Optional[str] = None
    protocol: str = Field(default="pop3", pattern="^(pop3|imap|gmail_api)$")
    server_address: str = Field(..., min_length=3)
    server_port: int = Field(default=995, ge=1, le=65535)
    password: str = Field(..., min_length=1)
    use_ssl: bool = True


class SensorUpdate(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    server_address: Optional[str] = None
    server_port: Optional[int] = None
    protocol: Optional[str] = None
    use_ssl: Optional[bool] = None


# ---------------------------------------------------------------------------
# GET /email — List all sensors
# ---------------------------------------------------------------------------

@router.get("/email", response_model=List[SensorOut])
async def list_sensors(
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(get_current_user),
):
    result = await db.execute(text("""
        SELECT id, email_address, display_name, protocol, server_address,
               server_port, use_ssl, is_active, last_sweep_at,
               last_sweep_status, last_sweep_error, emails_ingested_total,
               created_at, updated_at
        FROM public.email_sensors
        ORDER BY created_at
    """))
    rows = result.fetchall()
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=STALENESS_MINUTES)

    sensors = []
    for r in rows:
        sweep_status = r[9] or "pending"
        sweep_at = r[8]
        if r[7] and sweep_at is not None:
            if sweep_at.tzinfo is None:
                sweep_at_utc = sweep_at.replace(tzinfo=timezone.utc)
            else:
                sweep_at_utc = sweep_at
            if sweep_at_utc < stale_cutoff:
                sweep_status = "red"

        sensors.append(SensorOut(
            id=r[0],
            email_address=r[1],
            display_name=r[2],
            protocol=r[3],
            server_address=r[4],
            server_port=r[5],
            use_ssl=r[6],
            is_active=r[7],
            last_sweep_at=r[8],
            last_sweep_status=sweep_status,
            last_sweep_error=r[10],
            emails_ingested_total=r[11] or 0,
            created_at=r[12],
            updated_at=r[13],
        ))

    return sensors


# ---------------------------------------------------------------------------
# POST /email — Add a new sensor
# ---------------------------------------------------------------------------

@router.post("/email", response_model=SensorOut, status_code=status.HTTP_201_CREATED)
async def create_sensor(
    body: SensorCreate,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    encrypted_pw = encrypt(body.password, settings.secret_key)

    result = await db.execute(text("""
        INSERT INTO public.email_sensors
            (email_address, display_name, protocol, server_address,
             server_port, encrypted_password, use_ssl)
        VALUES (:email, :display, :proto, :server, :port, :enc_pw, :ssl)
        ON CONFLICT (email_address) DO NOTHING
        RETURNING id, email_address, display_name, protocol, server_address,
                  server_port, use_ssl, is_active, last_sweep_at,
                  last_sweep_status, last_sweep_error, emails_ingested_total,
                  created_at, updated_at
    """), {
        "email": body.email_address.strip().lower(),
        "display": body.display_name,
        "proto": body.protocol,
        "server": body.server_address,
        "port": body.server_port,
        "enc_pw": encrypted_pw,
        "ssl": body.use_ssl,
    })
    await db.commit()

    row = result.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sensor for {body.email_address} already exists",
        )

    logger.info("sensor_created", email=body.email_address, actor=user.email)
    return SensorOut(
        id=row[0], email_address=row[1], display_name=row[2],
        protocol=row[3], server_address=row[4], server_port=row[5],
        use_ssl=row[6], is_active=row[7], last_sweep_at=row[8],
        last_sweep_status=row[9] or "pending", last_sweep_error=row[10],
        emails_ingested_total=row[11] or 0, created_at=row[12],
        updated_at=row[13],
    )


# ---------------------------------------------------------------------------
# PATCH /email/{id} — Update sensor
# ---------------------------------------------------------------------------

@router.patch("/email/{sensor_id}", response_model=SensorOut)
async def update_sensor(
    sensor_id: UUID,
    body: SensorUpdate,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    check = await db.execute(
        text("SELECT id FROM public.email_sensors WHERE id = :sid"),
        {"sid": str(sensor_id)},
    )
    if check.fetchone() is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    updates = []
    params = {"sid": str(sensor_id)}

    if body.display_name is not None:
        updates.append("display_name = :display")
        params["display"] = body.display_name
    if body.password is not None:
        updates.append("encrypted_password = :enc_pw")
        params["enc_pw"] = encrypt(body.password, settings.secret_key)
    if body.is_active is not None:
        updates.append("is_active = :active")
        params["active"] = body.is_active
    if body.server_address is not None:
        updates.append("server_address = :server")
        params["server"] = body.server_address
    if body.server_port is not None:
        updates.append("server_port = :port")
        params["port"] = body.server_port
    if body.protocol is not None:
        updates.append("protocol = :proto")
        params["proto"] = body.protocol
    if body.use_ssl is not None:
        updates.append("use_ssl = :ssl")
        params["ssl"] = body.use_ssl

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = NOW()")
    set_clause = ", ".join(updates)

    result = await db.execute(text(f"""
        UPDATE public.email_sensors SET {set_clause}
        WHERE id = :sid
        RETURNING id, email_address, display_name, protocol, server_address,
                  server_port, use_ssl, is_active, last_sweep_at,
                  last_sweep_status, last_sweep_error, emails_ingested_total,
                  created_at, updated_at
    """), params)
    await db.commit()

    row = result.fetchone()
    logger.info("sensor_updated", sensor_id=str(sensor_id), actor=user.email)
    return SensorOut(
        id=row[0], email_address=row[1], display_name=row[2],
        protocol=row[3], server_address=row[4], server_port=row[5],
        use_ssl=row[6], is_active=row[7], last_sweep_at=row[8],
        last_sweep_status=row[9] or "pending", last_sweep_error=row[10],
        emails_ingested_total=row[11] or 0, created_at=row[12],
        updated_at=row[13],
    )


# ---------------------------------------------------------------------------
# DELETE /email/{id} — Soft-delete
# ---------------------------------------------------------------------------

@router.delete("/email/{sensor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sensor(
    sensor_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    result = await db.execute(text("""
        UPDATE public.email_sensors
        SET is_active = false, updated_at = NOW()
        WHERE id = :sid AND is_active = true
        RETURNING id
    """), {"sid": str(sensor_id)})
    await db.commit()

    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Sensor not found or already inactive")

    logger.info("sensor_deactivated", sensor_id=str(sensor_id), actor=user.email)
