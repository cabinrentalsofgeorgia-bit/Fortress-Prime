"""
Local SEO citation auditor for NAP consistency infrastructure.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.citation_audit import CitationRecord


class CitationAuditor:
    """
    V1 citation auditor.

    Future versions will call a SERP/profile discovery API and fill found_*
    fields from live directory data. For now we seed/refresh tracking rows
    with match_status='missing' so the queue and audit history exist.
    """

    TARGET_DIRECTORIES = [
        "yelp.com",
        "tripadvisor.com",
        "bbb.org",
        "fannincountygeorgia.com",
        "facebook.com",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def audit_directories(self, canonical_name: str, canonical_phone: str) -> list[CitationRecord]:
        """
        Stub audit runner for Pillar 3.

        Args:
            canonical_name: Authoritative business/cabin name (reserved for V2 matching logic).
            canonical_phone: Authoritative phone number (reserved for V2 matching logic).

        Returns:
            Updated CitationRecord rows for each target directory.
        """
        _ = canonical_name
        _ = canonical_phone

        now = datetime.utcnow()
        updated_rows: list[CitationRecord] = []

        for domain in self.TARGET_DIRECTORIES:
            result = await self.db.execute(
                select(CitationRecord).where(CitationRecord.directory_domain == domain)
            )
            record = result.scalar_one_or_none()

            if record is None:
                record = CitationRecord(
                    directory_domain=domain,
                    profile_url=None,
                    found_name=None,
                    found_address=None,
                    found_phone=None,
                    match_status="missing",
                    last_audited_at=now,
                )
                self.db.add(record)
            else:
                record.match_status = "missing"
                record.last_audited_at = now

            updated_rows.append(record)

        await self.db.commit()
        for row in updated_rows:
            await self.db.refresh(row)

        return updated_rows
