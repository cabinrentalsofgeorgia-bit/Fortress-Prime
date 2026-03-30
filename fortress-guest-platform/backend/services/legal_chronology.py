"""
Harvey Engine — Master Chronology Builder.

Sweeps the case graph nodes, vault evidence, and terminal emails to
extract every date-anchored event into a strict chronological timeline.
Persists to legal.chronology_events for the glass.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ai_router import execute_resilient_inference

logger = logging.getLogger(__name__)


class TimelineEvent(BaseModel):
    exact_date: str = Field(..., description="YYYY-MM-DD format")
    event_description: str = Field(..., min_length=5)
    entities_involved: list[str] = Field(default_factory=list)
    source_ref: str = Field(default="")
    event_type: str = Field(default="fact")
    significance: str = Field(default="normal")

    @field_validator("exact_date", mode="before")
    @classmethod
    def _coerce_date(cls, v):
        return str(v or "").strip()


class ChronologyExtraction(BaseModel):
    events: list[TimelineEvent] = Field(default_factory=list)


CHRONO_SYSTEM_PROMPT = (
    "You are a litigation chronology specialist. Analyze the provided case evidence "
    "and extract EVERY date-anchored event into a strict chronological timeline. "
    "Include: contract signing dates, invoice dates, payment dates, correspondence, "
    "filing dates, service dates, and deadline dates. "
    "For each event, identify the exact date, a clear description, the entities "
    "involved, and the source document. Mark significance as 'critical' for "
    "contract dates, filing deadlines, and payment defaults; 'high' for "
    "correspondence demanding payment; 'normal' for routine invoices. "
    "Return ONLY valid JSON: "
    '{"events":[{"exact_date":"2018-08-14","event_description":"Vacation Rental '
    'Participation Agreement signed","entities_involved":["Cabin Rentals of Georgia",'
    '"CSA Travel Protection"],"source_ref":"Complaint_SUV2026000013.pdf",'
    '"event_type":"contract","significance":"critical"}]}'
)


async def _gather_chronology_context(db: AsyncSession, case_slug: str) -> str:
    """Pull graph nodes, vault docs, and terminal emails for chronology."""
    chunks: list[str] = []

    try:
        r = await db.execute(
            text("""
                SELECT entity_type, label, metadata::text
                FROM legal.case_graph_nodes
                WHERE case_id = (SELECT id FROM legal.legal_cases WHERE slug = :slug)
                ORDER BY created_at
            """),
            {"slug": case_slug},
        )
        for row in r.fetchall():
            chunks.append(f"[ENTITY: {row[0]}] {row[1]} {row[2] or ''}")
    except Exception:
        await db.rollback()

    try:
        r = await db.execute(
            text("""
                SELECT entity_name, quote_text, source_ref, stated_at
                FROM legal.case_statements
                WHERE case_slug = :slug
                ORDER BY stated_at NULLS LAST
            """),
            {"slug": case_slug},
        )
        for row in r.fetchall():
            d = dict(row._mapping)
            chunks.append(
                f"[STATEMENT by {d.get('entity_name','?')}] "
                f"\"{d.get('quote_text','')}\" "
                f"(ref: {d.get('source_ref','n/a')}, date: {d.get('stated_at','?')})"
            )
    except Exception:
        await db.rollback()

    try:
        r = await db.execute(
            text("""
                SELECT m.email_id, m.sender, m.subject, m.sent_at
                FROM legal.email_thread_members m
                JOIN legal.email_threads t ON t.id = m.thread_id
                WHERE t.case_slug = :slug AND m.is_terminal = true
                ORDER BY m.sent_at NULLS LAST
            """),
            {"slug": case_slug},
        )
        for row in r.fetchall():
            d = dict(row._mapping)
            chunks.append(
                f"[TERMINAL EMAIL #{d.get('email_id','')}] "
                f"From: {d.get('sender','')} | Subject: {d.get('subject','')} | "
                f"Date: {d.get('sent_at','')}"
            )
    except Exception:
        await db.rollback()

    from pathlib import Path
    try:
        r = await db.execute(
            text("""
                SELECT file_name, nfs_path, mime_type
                FROM legal.vault_documents
                WHERE case_slug = :slug AND processing_status = 'completed'
                ORDER BY chunk_count DESC NULLS LAST
                LIMIT 10
            """),
            {"slug": case_slug},
        )
        for row in r.fetchall():
            d = dict(row._mapping)
            nfs = d.get("nfs_path", "")
            fname = d.get("file_name", "")
            if not nfs:
                continue
            try:
                p = Path(nfs)
                if not p.exists():
                    import subprocess
                    sr = subprocess.run(["sudo", "cat", nfs], capture_output=True, timeout=10)
                    raw = sr.stdout
                else:
                    raw = p.read_bytes()
                mime = d.get("mime_type", "")
                if "pdf" in (mime or "").lower():
                    try:
                        import fitz
                        doc = fitz.open(stream=raw, filetype="pdf")
                        file_text = "\n\n".join(page.get_text() for page in doc)
                        doc.close()
                    except Exception:
                        file_text = raw.decode("utf-8", errors="ignore")
                else:
                    file_text = raw.decode("utf-8", errors="ignore")
                if file_text.strip():
                    chunks.append(f"[FILE: {fname}]\n{file_text[:4000]}")
            except Exception:
                pass
    except Exception:
        await db.rollback()

    return "\n\n".join(chunks)[:30000]


def _parse_extraction(raw_text: str) -> ChronologyExtraction:
    content = raw_text.strip()
    if content.startswith("```"):
        nl = content.find("\n")
        content = content[nl + 1:] if nl > 0 else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    import json as _json
    try:
        parsed = _json.loads(content)
    except _json.JSONDecodeError:
        arr_start = content.find("[")
        arr_end = content.rfind("]")
        obj_start = content.find("{")
        obj_end = content.rfind("}")
        if arr_start >= 0 and arr_end > arr_start:
            parsed = _json.loads(content[arr_start : arr_end + 1])
        elif obj_start >= 0 and obj_end > obj_start:
            parsed = _json.loads(content[obj_start : obj_end + 1])
        else:
            raise

    if isinstance(parsed, list):
        return ChronologyExtraction(events=[TimelineEvent.model_validate(e) for e in parsed])
    if isinstance(parsed, dict) and "events" in parsed:
        return ChronologyExtraction.model_validate(parsed)
    if isinstance(parsed, dict):
        return ChronologyExtraction(events=[TimelineEvent.model_validate(parsed)])
    raise ValueError(f"Unexpected JSON type: {type(parsed)}")


async def build_chronology(db: AsyncSession, case_slug: str) -> dict:
    context = await _gather_chronology_context(db, case_slug)
    if not context.strip():
        return {"case_slug": case_slug, "events": [], "status": "no_evidence"}

    result = await execute_resilient_inference(
        prompt=context,
        task_type="legal",
        system_message=CHRONO_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.1,
        db=db,
        source_module="legal_chronology",
    )

    try:
        extraction = _parse_extraction(result.text)
    except Exception as exc:
        logger.warning("chronology_parse_failed error=%s", str(exc)[:200])
        return {
            "case_slug": case_slug,
            "events": [],
            "status": "parse_failed",
            "raw_output": result.text[:500],
            "inference_source": result.source,
        }

    await db.execute(
        text("DELETE FROM legal.chronology_events WHERE case_slug = :slug"),
        {"slug": case_slug},
    )

    saved = 0
    for ev in extraction.events:
        try:
            event_date = date.fromisoformat(ev.exact_date)
        except (ValueError, TypeError):
            logger.debug("chrono_event_bad_date date=%s", ev.exact_date)
            continue
        try:
            await db.execute(
                text("""
                    INSERT INTO legal.chronology_events
                        (case_slug, event_date, event_description, entities_involved,
                         source_ref, event_type, significance)
                    VALUES (:slug, :dt, :desc, CAST(:ents AS JSONB),
                            :ref, :etype, :sig)
                """),
                {
                    "slug": case_slug,
                    "dt": event_date,
                    "desc": ev.event_description,
                    "ents": json.dumps(ev.entities_involved),
                    "ref": ev.source_ref or "",
                    "etype": ev.event_type,
                    "sig": ev.significance,
                },
            )
            saved += 1
        except Exception as exc:
            logger.warning("chrono_event_save_failed date=%s error=%s", ev.exact_date, str(exc)[:200])

    await db.commit()

    logger.info(
        "chronology_built",
        case_slug=case_slug,
        events_extracted=len(extraction.events),
        events_saved=saved,
        source=result.source,
        latency_ms=result.latency_ms,
    )

    return {
        "case_slug": case_slug,
        "events_extracted": len(extraction.events),
        "events_saved": saved,
        "status": "success",
        "inference_source": result.source,
        "latency_ms": result.latency_ms,
    }


async def get_chronology(db: AsyncSession, case_slug: str) -> list[dict]:
    r = await db.execute(
        text("""
            SELECT id, event_date, event_description, entities_involved,
                   source_ref, event_type, significance, created_at
            FROM legal.chronology_events
            WHERE case_slug = :slug
            ORDER BY event_date ASC, created_at ASC
        """),
        {"slug": case_slug},
    )
    events = []
    for row in r.fetchall():
        d = dict(row._mapping)
        d["id"] = str(d["id"])
        d["event_date"] = str(d["event_date"]) if d.get("event_date") else None
        d["created_at"] = str(d["created_at"]) if d.get("created_at") else None
        if isinstance(d.get("entities_involved"), str):
            try:
                d["entities_involved"] = json.loads(d["entities_involved"])
            except Exception:
                d["entities_involved"] = []
        events.append(d)
    return events
