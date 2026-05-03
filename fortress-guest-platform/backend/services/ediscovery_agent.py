"""
FORTRESS PRIME — E-DISCOVERY AUTOMATION AGENT
==============================================
Enterprise-grade automated e-discovery pipeline that queries the legacy
Command Center databases (email_archive, finance_invoices, legal.*,
sender_registry) for specified entities and returns a unified, chronological
evidence timeline.

Architecture:
    API route (api/ediscovery.py)
      → EDiscoveryAgent (this file)
        → Read-only async connection to fortress_db (legacy ops database)
        → Parallel entity searches across email, finance, legal tables
        → Unified timeline with deduplication and relevance scoring

Data Sources (fortress_db — read-only):
    public.email_archive     — 36K+ emails with full-text search (tsvector)
    public.finance_invoices  — Financial records linked to emails
    public.sender_registry   — Sender profiles with domain + volume
    legal.case_evidence      — Pre-indexed evidence linked to cases
    legal.correspondence     — Inbound/outbound legal communications
"""

import asyncio
import re
import structlog
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.services.legal.db_targets import LEGAL_CANONICAL_DB, legal_async_database_url

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════════════
# Legacy DB connection — fortress_db (read-only for e-discovery)
# ═══════════════════════════════════════════════════════════════════════

# Runtime API DB is typically fortress_shadow; legacy legal/ediscovery lives in fortress_db.
_LEGACY_DB_URL = legal_async_database_url(LEGAL_CANONICAL_DB)

_legacy_engine = create_async_engine(
    _LEGACY_DB_URL,
    echo=False,
    pool_size=5,
    max_overflow=3,
    pool_pre_ping=True,
)

LegacySession = async_sessionmaker(
    _legacy_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

MAX_RESULTS_PER_TABLE = 200
CONTENT_PREVIEW_LENGTH = 500


@dataclass
class DiscoveryHit:
    source: str
    hit_id: int
    entity_matched: str
    field_matched: str
    timestamp: Optional[datetime]
    sender: Optional[str]
    subject: Optional[str]
    content_preview: str
    relevance_score: float
    metadata: dict


def _preview(text_val: Optional[str], length: int = CONTENT_PREVIEW_LENGTH) -> str:
    if not text_val:
        return ""
    cleaned = re.sub(r'\s+', ' ', text_val).strip()
    if len(cleaned) <= length:
        return cleaned
    return cleaned[:length] + "..."


def _score_hit(content: str, entity: str) -> float:
    """Simple relevance scoring based on mention density."""
    if not content:
        return 0.1
    lower = content.lower()
    entity_lower = entity.lower()
    count = lower.count(entity_lower)
    length = max(len(lower), 1)
    density = count / (length / 1000)
    if count == 0:
        return 0.1
    if count == 1:
        return 0.3
    if count <= 3:
        return 0.5 + min(density * 0.1, 0.2)
    return min(0.7 + density * 0.05, 1.0)


async def search_emails(
    session: AsyncSession,
    entities: list[str],
    max_results: int = MAX_RESULTS_PER_TABLE,
) -> list[DiscoveryHit]:
    """Search email_archive for entity mentions across sender, subject, content."""
    hits: list[DiscoveryHit] = []

    for entity in entities:
        param = f"%{entity}%"
        query = text("""
            SELECT id, sender, subject,
                   LEFT(content, :preview_len) as content_preview,
                   sent_at, category, division
            FROM public.email_archive
            WHERE sender ILIKE :pattern
               OR subject ILIKE :pattern
               OR content ILIKE :pattern
            ORDER BY sent_at DESC
            LIMIT :max_results
        """)
        result = await session.execute(query, {
            "pattern": param,
            "preview_len": CONTENT_PREVIEW_LENGTH,
            "max_results": max_results,
        })
        rows = result.fetchall()
        for row in rows:
            field_matched = []
            sender_str = row.sender or ""
            subject_str = row.subject or ""
            content_str = row.content_preview or ""
            if entity.lower() in sender_str.lower():
                field_matched.append("sender")
            if entity.lower() in subject_str.lower():
                field_matched.append("subject")
            if entity.lower() in content_str.lower():
                field_matched.append("content")

            combined = f"{sender_str} {subject_str} {content_str}"
            hits.append(DiscoveryHit(
                source="email_archive",
                hit_id=row.id,
                entity_matched=entity,
                field_matched=", ".join(field_matched) or "content",
                timestamp=row.sent_at,
                sender=sender_str,
                subject=subject_str,
                content_preview=_preview(content_str),
                relevance_score=_score_hit(combined, entity),
                metadata={
                    "category": row.category,
                    "division": row.division,
                },
            ))
        logger.info("ediscovery_email_search", entity=entity, hits=len(rows))

    return hits


async def search_invoices(
    session: AsyncSession,
    entities: list[str],
    max_results: int = MAX_RESULTS_PER_TABLE,
) -> list[DiscoveryHit]:
    """Search finance_invoices for entity mentions in vendor name."""
    hits: list[DiscoveryHit] = []

    for entity in entities:
        param = f"%{entity}%"
        query = text("""
            SELECT fi.id, fi.vendor, fi.amount, fi.date, fi.category,
                   fi.source_email_id,
                   LEFT(ea.subject, 200) as email_subject
            FROM public.finance_invoices fi
            LEFT JOIN public.email_archive ea ON ea.id = fi.source_email_id
            WHERE fi.vendor ILIKE :pattern
               OR fi.category ILIKE :pattern
            ORDER BY fi.date DESC
            LIMIT :max_results
        """)
        result = await session.execute(query, {
            "pattern": param,
            "max_results": max_results,
        })
        rows = result.fetchall()
        for row in rows:
            hits.append(DiscoveryHit(
                source="finance_invoices",
                hit_id=row.id,
                entity_matched=entity,
                field_matched="vendor",
                timestamp=datetime.combine(row.date, datetime.min.time()) if row.date else None,
                sender=None,
                subject=row.email_subject,
                content_preview=f"Vendor: {row.vendor} | Amount: ${row.amount} | Category: {row.category}",
                relevance_score=0.6,
                metadata={
                    "vendor": row.vendor,
                    "amount": float(row.amount) if row.amount else 0,
                    "category": row.category,
                    "source_email_id": row.source_email_id,
                },
            ))
        logger.info("ediscovery_invoice_search", entity=entity, hits=len(rows))

    return hits


async def search_legal_evidence(
    session: AsyncSession,
    entities: list[str],
    max_results: int = MAX_RESULTS_PER_TABLE,
) -> list[DiscoveryHit]:
    """Search legal.case_evidence and legal.correspondence for entity mentions."""
    hits: list[DiscoveryHit] = []

    for entity in entities:
        param = f"%{entity}%"

        evi_query = text("""
            SELECT ce.id, ce.evidence_type, ce.description, ce.relevance,
                   ce.discovered_at, ce.is_critical, c.case_slug
            FROM legal.case_evidence ce
            JOIN legal.cases c ON c.id = ce.case_id
            WHERE ce.description ILIKE :pattern
               OR ce.relevance ILIKE :pattern
            ORDER BY ce.discovered_at DESC
            LIMIT :max_results
        """)
        evi_result = await session.execute(evi_query, {
            "pattern": param, "max_results": max_results
        })
        for row in evi_result.fetchall():
            hits.append(DiscoveryHit(
                source="legal.case_evidence",
                hit_id=row.id,
                entity_matched=entity,
                field_matched="description",
                timestamp=row.discovered_at,
                sender=None,
                subject=f"[{row.case_slug}] {row.evidence_type}",
                content_preview=_preview(row.description),
                relevance_score=0.9 if row.is_critical else 0.7,
                metadata={
                    "evidence_type": row.evidence_type,
                    "case_slug": row.case_slug,
                    "is_critical": row.is_critical,
                },
            ))

        corr_query = text("""
            SELECT co.id, co.direction, co.comm_type, co.recipient,
                   co.subject, LEFT(co.body, :preview_len) as body_preview,
                   co.status, co.created_at, c.case_slug
            FROM legal.correspondence co
            JOIN legal.cases c ON c.id = co.case_id
            WHERE co.subject ILIKE :pattern
               OR co.body ILIKE :pattern
               OR co.recipient ILIKE :pattern
            ORDER BY co.created_at DESC
            LIMIT :max_results
        """)
        corr_result = await session.execute(corr_query, {
            "pattern": param,
            "preview_len": CONTENT_PREVIEW_LENGTH,
            "max_results": max_results,
        })
        for row in corr_result.fetchall():
            hits.append(DiscoveryHit(
                source="legal.correspondence",
                hit_id=row.id,
                entity_matched=entity,
                field_matched="correspondence",
                timestamp=row.created_at,
                sender=row.recipient if row.direction == "inbound" else None,
                subject=row.subject,
                content_preview=_preview(row.body_preview),
                relevance_score=0.8,
                metadata={
                    "direction": row.direction,
                    "comm_type": row.comm_type,
                    "status": row.status,
                    "case_slug": row.case_slug,
                },
            ))
        logger.info("ediscovery_legal_search", entity=entity,
                     evidence=evi_result.rowcount, correspondence=corr_result.rowcount)

    return hits


async def search_sender_registry(
    session: AsyncSession,
    entities: list[str],
) -> list[DiscoveryHit]:
    """Search sender_registry for known sender profiles matching entities."""
    hits: list[DiscoveryHit] = []

    for entity in entities:
        param = f"%{entity}%"
        query = text("""
            SELECT id, sender_raw, email_address, display_name, domain,
                   status, division, total_volume, last_seen
            FROM public.sender_registry
            WHERE sender_raw ILIKE :pattern
               OR email_address ILIKE :pattern
               OR display_name ILIKE :pattern
               OR domain ILIKE :pattern
            ORDER BY total_volume DESC
            LIMIT 50
        """)
        result = await session.execute(query, {"pattern": param})
        for row in result.fetchall():
            hits.append(DiscoveryHit(
                source="sender_registry",
                hit_id=row.id,
                entity_matched=entity,
                field_matched="sender_profile",
                timestamp=row.last_seen,
                sender=row.email_address,
                subject=f"Sender Profile: {row.display_name or row.sender_raw}",
                content_preview=f"Domain: {row.domain} | Volume: {row.total_volume} emails | Division: {row.division}",
                relevance_score=0.5,
                metadata={
                    "email_address": row.email_address,
                    "domain": row.domain,
                    "total_volume": row.total_volume,
                    "division": row.division,
                    "status": row.status,
                },
            ))
        logger.info("ediscovery_sender_search", entity=entity, hits=result.rowcount)

    return hits


def _normalize_ts(ts: Optional[datetime]) -> datetime:
    """Strip timezone info for safe comparison (all data is UTC/local)."""
    if ts is None:
        return datetime.min
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def build_unified_timeline(hits: list[DiscoveryHit]) -> list[dict]:
    """Deduplicate and sort all hits into a chronological evidence timeline."""
    seen: set[tuple[str, int]] = set()
    unique: list[DiscoveryHit] = []
    for h in hits:
        key = (h.source, h.hit_id)
        if key not in seen:
            seen.add(key)
            unique.append(h)

    unique.sort(
        key=lambda h: (_normalize_ts(h.timestamp), -h.relevance_score),
        reverse=True,
    )

    timeline = []
    for h in unique:
        timeline.append({
            "source": h.source,
            "hit_id": h.hit_id,
            "entity_matched": h.entity_matched,
            "field_matched": h.field_matched,
            "timestamp": h.timestamp.isoformat() if h.timestamp else None,
            "sender": h.sender,
            "subject": h.subject,
            "content_preview": h.content_preview,
            "relevance_score": round(h.relevance_score, 2),
            "metadata": h.metadata,
        })

    return timeline


def build_brief_injection(timeline: list[dict], entities: list[str]) -> str:
    """Synthesize the discovery results into structured text for case brief injection."""
    if not timeline:
        return f"\n\n=== E-DISCOVERY RESULTS ===\nNo results found for entities: {', '.join(entities)}\n"

    email_hits = [h for h in timeline if h["source"] == "email_archive"]
    invoice_hits = [h for h in timeline if h["source"] == "finance_invoices"]
    legal_hits = [h for h in timeline if h["source"].startswith("legal.")]
    sender_hits = [h for h in timeline if h["source"] == "sender_registry"]

    lines = [
        "",
        "=" * 60,
        "AUTOMATED E-DISCOVERY RESULTS",
        f"Entities: {', '.join(entities)}",
        f"Total Hits: {len(timeline)} across {len(set(h['source'] for h in timeline))} data sources",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 60,
    ]

    if email_hits:
        lines.append(f"\n--- EMAIL ARCHIVE ({len(email_hits)} hits) ---")
        for h in email_hits[:25]:
            ts = h["timestamp"][:10] if h["timestamp"] else "N/A"
            lines.append(
                f"  [{ts}] From: {h['sender'] or 'N/A'}"
                f"\n    Subject: {h['subject'] or 'N/A'}"
                f"\n    Matched: {h['entity_matched']} in {h['field_matched']}"
                f"\n    Preview: {h['content_preview'][:200]}"
            )

    if invoice_hits:
        lines.append(f"\n--- FINANCIAL RECORDS ({len(invoice_hits)} hits) ---")
        for h in invoice_hits[:15]:
            ts = h["timestamp"][:10] if h["timestamp"] else "N/A"
            lines.append(f"  [{ts}] {h['content_preview']}")

    if legal_hits:
        lines.append(f"\n--- LEGAL DATABASE ({len(legal_hits)} hits) ---")
        for h in legal_hits[:15]:
            ts = h["timestamp"][:10] if h["timestamp"] else "N/A"
            lines.append(
                f"  [{ts}] {h['source']}: {h['subject']}"
                f"\n    {h['content_preview'][:200]}"
            )

    if sender_hits:
        lines.append(f"\n--- SENDER PROFILES ({len(sender_hits)} hits) ---")
        for h in sender_hits[:10]:
            lines.append(f"  {h['subject']}: {h['content_preview']}")

    lines.append("=" * 60)
    return "\n".join(lines)


async def _search_with_own_session(coro_fn, *args) -> list[DiscoveryHit]:
    """Run a search function with its own dedicated session to avoid concurrent ops on a single connection."""
    async with LegacySession() as session:
        return await coro_fn(session, *args)


async def run_discovery(
    entities: list[str],
    max_per_table: int = MAX_RESULTS_PER_TABLE,
) -> dict:
    """
    Execute the full e-discovery pipeline across all data sources.
    Returns unified timeline + brief injection text.
    """
    logger.info("ediscovery_pipeline_start", entities=entities, max_per_table=max_per_table)
    t0 = asyncio.get_event_loop().time()

    results = await asyncio.gather(
        _search_with_own_session(search_emails, entities, max_per_table),
        _search_with_own_session(search_invoices, entities, max_per_table),
        _search_with_own_session(search_legal_evidence, entities, max_per_table),
        _search_with_own_session(search_sender_registry, entities),
        return_exceptions=True,
    )

    all_hits: list[DiscoveryHit] = []
    source_stats: dict[str, int] = {}
    errors: list[str] = []

    for i, label in enumerate(["emails", "invoices", "legal", "senders"]):
        if isinstance(results[i], Exception):
            logger.error("ediscovery_source_failed", source=label, error=str(results[i]))
            errors.append(f"{label}: {str(results[i])[:200]}")
        else:
            hits = results[i]
            all_hits.extend(hits)
            source_stats[label] = len(hits)

    timeline = build_unified_timeline(all_hits)
    brief_text = build_brief_injection(timeline, entities)
    elapsed = round(asyncio.get_event_loop().time() - t0, 2)

    logger.info(
        "ediscovery_pipeline_complete",
        total_hits=len(timeline),
        source_stats=source_stats,
        elapsed_seconds=elapsed,
    )

    return {
        "entities": entities,
        "total_hits": len(timeline),
        "source_stats": source_stats,
        "elapsed_seconds": elapsed,
        "errors": errors,
        "timeline": timeline,
        "brief_injection": brief_text,
    }
