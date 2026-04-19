"""
FGP Vectorization Worker — Embeds Streamline data into Qdrant fgp_knowledge
============================================================================
Queries properties, reservations (streamline_notes), and work_orders for
records missing a qdrant_point_id, generates embeddings via the local NIM
endpoint, and upserts into the fgp_knowledge Qdrant collection.

Designed to be called:
  - As a post-sync hook from sync_all() in streamline_vrs.py
  - Standalone for backfill:  python -m backend.workers.vectorizer

Embedding model: nomic-embed-text (768-dim) on Nginx LB (Captain:80)
"""

import hashlib
import uuid
from datetime import datetime
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.qdrant import COLLECTION_NAME, VECTOR_DIM

logger = structlog.get_logger()

EMBED_URL = f"http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
QDRANT_BATCH_SIZE = 50
MAX_RECORDS_PER_RUN = 500


def _qdrant_url() -> str:
    return settings.qdrant_url.rstrip("/")


def _qdrant_headers() -> dict:
    if settings.qdrant_api_key:
        return {"api-key": settings.qdrant_api_key}
    return {}


def _build_property_text(row) -> str:
    """Compose a vectorizable text payload from a Property row."""
    parts = [f"Property: {row.name}"]
    if row.address:
        parts.append(f"Address: {row.address}")
    if row.property_type:
        parts.append(f"Type: {row.property_type}")
    if row.bedrooms:
        parts.append(f"Bedrooms: {row.bedrooms}")
    if row.bathrooms:
        parts.append(f"Bathrooms: {row.bathrooms}")
    if row.max_guests:
        parts.append(f"Max guests: {row.max_guests}")
    if row.wifi_ssid:
        parts.append(f"WiFi: {row.wifi_ssid}")
    if row.parking_instructions:
        parts.append(f"Parking: {row.parking_instructions}")
    if row.rate_card and isinstance(row.rate_card, dict):
        fees = row.rate_card.get("fees", [])
        if fees:
            fee_strs = [f"{f.get('name', '')}: ${f.get('amount', '')}" for f in fees[:5]]
            parts.append(f"Fees: {', '.join(fee_strs)}")
    return ". ".join(parts)


def _build_reservation_notes_text(row) -> Optional[str]:
    """Compose vectorizable text from reservation streamline_notes JSONB."""
    notes = row.streamline_notes
    if not notes or not isinstance(notes, list) or len(notes) == 0:
        return None
    note_texts = []
    for n in notes:
        msg = n.get("message", "").strip() if isinstance(n, dict) else str(n).strip()
        if msg and len(msg) > 10:
            author = n.get("processor_name", "") if isinstance(n, dict) else ""
            prefix = f"[{author}] " if author else ""
            note_texts.append(f"{prefix}{msg}")
    if not note_texts:
        return None
    conf = row.confirmation_code or "unknown"
    return f"Reservation {conf} staff notes: " + " | ".join(note_texts[:10])


def _build_work_order_text(row) -> str:
    """Compose vectorizable text from a WorkOrder row."""
    parts = [f"Work Order {row.ticket_number}: {row.title}"]
    if row.description:
        parts.append(f"Description: {row.description[:500]}")
    if row.category:
        parts.append(f"Category: {row.category}")
    if row.priority:
        parts.append(f"Priority: {row.priority}")
    if row.status:
        parts.append(f"Status: {row.status}")
    if row.resolution_notes:
        parts.append(f"Resolution: {row.resolution_notes[:300]}")
    return ". ".join(parts)


def _deterministic_uuid(source_table: str, record_id: str) -> str:
    """Generate a repeatable UUID from table+id so re-runs are idempotent."""
    seed = f"fgp:{source_table}:{record_id}"
    return str(uuid.UUID(hashlib.md5(seed.encode()).hexdigest()))


async def _embed_text(client: httpx.AsyncClient, text: str) -> Optional[list[float]]:
    """Call the local NIM embedding endpoint. Returns vector or None on failure."""
    try:
        resp = await client.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        vec = resp.json().get("embedding", [])
        if len(vec) == VECTOR_DIM:
            return vec
        logger.warning("embedding_dimension_mismatch", expected=VECTOR_DIM, got=len(vec))
        return None
    except Exception as e:
        logger.warning("embedding_request_failed", error=str(e)[:200])
        return None


async def _upsert_batch(client: httpx.AsyncClient, points: list[dict]) -> bool:
    """Upsert a batch of points into primary Qdrant (spark-2) and — best-effort —
    secondary Qdrant (spark-4). Returns True on primary success."""
    if not points:
        return True
    try:
        from backend.services.qdrant_dual_writer import dual_upsert_points
        await dual_upsert_points(points)
        return True
    except Exception as e:
        logger.error("qdrant_upsert_failed", error=str(e)[:200], batch_size=len(points))
        return False


async def vectorize_new_records(db: AsyncSession) -> dict:
    """Main vectorization pass. Returns summary dict.

    Scans properties, reservations, and work_orders for records with no
    qdrant_point_id, embeds them, upserts to Qdrant, and stamps the row
    with the assigned point ID.
    """
    from backend.models.property import Property
    from backend.models.reservation import Reservation
    from backend.models.workorder import WorkOrder

    summary = {
        "properties": 0,
        "reservation_notes": 0,
        "work_orders": 0,
        "errors": 0,
        "skipped": 0,
    }

    async with httpx.AsyncClient() as http:
        pending_points: list[dict] = []
        db_updates: list[tuple] = []  # (model_class, record_id, point_uuid)

        # --- Properties without qdrant_point_id ---
        result = await db.execute(
            select(Property)
            .where(Property.qdrant_point_id.is_(None))
            .limit(MAX_RECORDS_PER_RUN)
        )
        props = result.scalars().all()

        for prop in props:
            text = _build_property_text(prop)
            vec = await _embed_text(http, text)
            if vec is None:
                summary["errors"] += 1
                continue
            point_uuid = _deterministic_uuid("properties", str(prop.id))
            pending_points.append({
                "id": point_uuid,
                "vector": vec,
                "payload": {
                    "source_table": "properties",
                    "record_id": str(prop.id),
                    "text": text[:1500],
                    "name": prop.name,
                    "slug": prop.slug,
                    "vectorized_at": datetime.utcnow().isoformat(),
                },
            })
            db_updates.append((Property, prop.id, point_uuid))
            summary["properties"] += 1

            if len(pending_points) >= QDRANT_BATCH_SIZE:
                await _flush_batch(db, http, pending_points, db_updates, summary)
                pending_points, db_updates = [], []

        # --- Reservations with non-empty notes but no qdrant_point_id ---
        from sqlalchemy import cast, String, and_
        result = await db.execute(
            select(Reservation)
            .where(
                and_(
                    Reservation.qdrant_point_id.is_(None),
                    Reservation.streamline_notes.isnot(None),
                    cast(Reservation.streamline_notes, String) != "null",
                    cast(Reservation.streamline_notes, String) != "[]",
                )
            )
            .limit(MAX_RECORDS_PER_RUN)
        )
        reservations = result.scalars().all()

        for res in reservations:
            text = _build_reservation_notes_text(res)
            if text is None:
                summary["skipped"] += 1
                res.qdrant_point_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
                continue
            vec = await _embed_text(http, text)
            if vec is None:
                summary["errors"] += 1
                continue
            point_uuid = _deterministic_uuid("reservations", str(res.id))
            pending_points.append({
                "id": point_uuid,
                "vector": vec,
                "payload": {
                    "source_table": "reservations",
                    "record_id": str(res.id),
                    "confirmation_code": res.confirmation_code,
                    "text": text[:1500],
                    "vectorized_at": datetime.utcnow().isoformat(),
                },
            })
            db_updates.append((Reservation, res.id, point_uuid))
            summary["reservation_notes"] += 1

            if len(pending_points) >= QDRANT_BATCH_SIZE:
                await _flush_batch(db, http, pending_points, db_updates, summary)
                pending_points, db_updates = [], []

        # --- Work Orders without qdrant_point_id ---
        result = await db.execute(
            select(WorkOrder)
            .where(WorkOrder.qdrant_point_id.is_(None))
            .limit(MAX_RECORDS_PER_RUN)
        )
        work_orders = result.scalars().all()

        for wo in work_orders:
            text = _build_work_order_text(wo)
            vec = await _embed_text(http, text)
            if vec is None:
                summary["errors"] += 1
                continue
            point_uuid = _deterministic_uuid("work_orders", str(wo.id))
            pending_points.append({
                "id": point_uuid,
                "vector": vec,
                "payload": {
                    "source_table": "work_orders",
                    "record_id": str(wo.id),
                    "ticket_number": wo.ticket_number,
                    "text": text[:1500],
                    "category": wo.category,
                    "priority": wo.priority,
                    "vectorized_at": datetime.utcnow().isoformat(),
                },
            })
            db_updates.append((WorkOrder, wo.id, point_uuid))
            summary["work_orders"] += 1

            if len(pending_points) >= QDRANT_BATCH_SIZE:
                await _flush_batch(db, http, pending_points, db_updates, summary)
                pending_points, db_updates = [], []

        # Flush remaining
        if pending_points:
            await _flush_batch(db, http, pending_points, db_updates, summary)

    total = summary["properties"] + summary["reservation_notes"] + summary["work_orders"]
    if total > 0 or summary["errors"] > 0:
        logger.info("vectorization_complete", **summary)

    return summary


async def _flush_batch(
    db: AsyncSession,
    http: httpx.AsyncClient,
    points: list[dict],
    db_updates: list[tuple],
    summary: dict,
):
    """Upsert points to Qdrant then stamp qdrant_point_id in Postgres."""
    success = await _upsert_batch(http, points)
    if success:
        for model_cls, record_id, point_uuid in db_updates:
            await db.execute(
                update(model_cls)
                .where(model_cls.id == record_id)
                .values(qdrant_point_id=point_uuid)
            )
        await db.commit()
    else:
        summary["errors"] += len(points)


async def run_vectorization_standalone():
    """Entry point for standalone backfill runs."""
    from backend.core.database import AsyncSessionLocal
    from backend.core.qdrant import ensure_collection

    ready = await ensure_collection()
    if not ready:
        logger.error("qdrant_not_available_aborting")
        return

    async with AsyncSessionLocal() as db:
        summary = await vectorize_new_records(db)
        print(f"Vectorization complete: {summary}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_vectorization_standalone())
