"""
EmailMessageService — inbound persistence, AI draft generation, and HITL dispatch
for the email channel.

Mirrors the architectural pattern of MessageService (SMS) but for email.
All state is persisted into email_inquirers / email_messages tables.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import sqlalchemy.exc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.email_inquirer import EmailInquirer
from backend.models.email_message import EmailMessage
from backend.services.smtp_dispatcher import SMTPDispatcher

logger = logging.getLogger("email_message_service")


class EmailMessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Inbound ────────────────────────────────────────────────────────────

    async def receive_email(
        self,
        *,
        email_from: str,
        email_to: str,
        subject: str,
        body_text: str,
        imap_uid: int,
        message_id: str,
        received_at: datetime,
        cc: Optional[str] = None,
        attachments: Optional[list] = None,  # Deployment C: image attachments for VL enrichment
    ) -> EmailMessage:
        """
        Idempotent on imap_uid.  Creates EmailInquirer if new, persists
        inbound EmailMessage.  Returns the existing row on duplicate imap_uid.
        If attachments are provided and contain images, calls vision_concierge
        to enrich body_text with [IMAGE: description] before storing.
        """
        # Idempotency: if we've seen this imap_uid before, return the existing row
        existing = await self.db.execute(
            select(EmailMessage).where(EmailMessage.imap_uid == imap_uid)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            logger.info("email_receive_duplicate_skipped imap_uid=%s", imap_uid)
            return row

        inquirer = await self._find_or_create_inquirer(email_from, display_name=None)

        # Deployment C: enrich body with image descriptions if attachments present
        image_descriptions = None
        has_attachments = bool(attachments)
        if attachments:
            try:
                from backend.services.vision_concierge import enrich_body_with_image_descriptions
                body_text, image_descriptions = await enrich_body_with_image_descriptions(
                    body_text, attachments
                )
                if image_descriptions:
                    image_descriptions = image_descriptions  # already a list[dict]
            except Exception as exc:  # noqa: BLE001
                logger.warning("vision_concierge.failed imap_uid=%s err=%s", imap_uid, str(exc)[:200])

        excerpt = (body_text or "")[:500]
        msg = EmailMessage(
            inquirer_id=inquirer.id,
            direction="inbound",
            email_from=email_from,
            email_to=email_to,
            email_cc=cc,
            subject=subject,
            body_text=body_text,
            body_excerpt=excerpt,
            imap_uid=imap_uid,
            imap_message_id=message_id,
            has_attachments=has_attachments,
            image_descriptions=image_descriptions,
            received_at=received_at,
            approval_status="pending_approval",
            requires_human_review=True,
        )
        self.db.add(msg)

        # Keep inquirer freshness up to date
        inquirer.last_seen_at = datetime.now(tz=timezone.utc)
        inquirer.inquiry_count = (inquirer.inquiry_count or 0) + 1

        try:
            await self.db.commit()
            await self.db.refresh(msg)
        except sqlalchemy.exc.IntegrityError:
            # Race condition: another worker inserted the same imap_uid first
            await self.db.rollback()
            result = await self.db.execute(
                select(EmailMessage).where(EmailMessage.imap_uid == imap_uid)
            )
            return result.scalar_one()

        logger.info(
            "email_received message_id=%s imap_uid=%s from=%s",
            str(msg.id), imap_uid, email_from,
        )
        return msg

    # ─── AI draft ───────────────────────────────────────────────────────────

    async def generate_draft_for_inbound(self, message_id: UUID) -> EmailMessage:
        """
        Calls email_concierge_engine.run_email_triage() and persists the
        resulting draft back into the EmailMessage row.
        """
        # Import here to avoid a circular dependency at module load time
        from backend.services.email_concierge_engine import run_email_triage

        msg = await self.db.get(EmailMessage, message_id)
        if msg is None:
            raise ValueError(f"EmailMessage not found: {message_id}")

        try:
            result = await run_email_triage(self.db, email_message_id=message_id)
            msg.ai_draft = result.get("draft_text") or ""
            msg.ai_confidence = result.get("confidence")
            msg.ai_meta = result.get("meta")
            # Truncate to schema limits — run_guest_triage primary_issue can be >50 chars
            raw = result.get("intent") or ""
            msg.intent = raw[:50] if raw else None
            raw = result.get("sentiment") or ""
            msg.sentiment = raw[:20] if raw else None
            raw = result.get("category") or ""
            msg.category = raw[:50] if raw else None
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "email_draft_generation_failed message_id=%s err=%s",
                str(message_id), str(exc)[:300],
            )
            msg.ai_draft = ""
            msg.ai_meta = {"error": str(exc)[:500]}

        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    # ─── HITL workflow ──────────────────────────────────────────────────────

    async def get_pending_drafts(self) -> List[Dict[str, Any]]:
        """Returns all email messages with approval_status='pending_approval'."""
        result = await self.db.execute(
            select(EmailMessage)
            .options(selectinload(EmailMessage.inquirer))
            .where(EmailMessage.approval_status == "pending_approval")
            .where(EmailMessage.direction == "inbound")
            .order_by(EmailMessage.received_at.desc())
            .limit(100)
        )
        messages = result.scalars().all()
        return [self._to_review_context(m) for m in messages]

    async def get_draft_context_by_id(self, message_id: UUID) -> Optional[Dict[str, Any]]:
        result = await self.db.execute(
            select(EmailMessage)
            .options(selectinload(EmailMessage.inquirer))
            .where(EmailMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg is None:
            return None
        return self._to_review_context(msg)

    async def execute_approval_and_dispatch(
        self, message_id: UUID, reviewer_id: UUID
    ) -> Dict[str, Any]:
        """
        Marks approved, sends via SMTP using the ai_draft (or human_edited_body
        if the reviewer edited), records sent_at + smtp_message_id.
        """
        msg = await self._load_with_inquirer(message_id)
        if msg is None:
            raise ValueError(f"EmailMessage not found: {message_id}")
        if msg.approval_status not in ("pending_approval",):
            raise ValueError(
                f"Cannot approve: current status is '{msg.approval_status}'"
            )

        body_to_send = msg.human_edited_body or msg.ai_draft or ""
        if not body_to_send:
            raise ValueError("No draft body available to send")

        now = datetime.now(tz=timezone.utc)
        msg.approval_status = "approved"
        msg.human_reviewed_at = now
        msg.human_reviewed_by = reviewer_id
        await self.db.commit()

        # Dispatch via SMTP
        dispatcher = SMTPDispatcher()
        subject = msg.subject or "Re: Your inquiry — Cabin Rentals of Georgia"
        smtp_result = await dispatcher.send_quote(
            to_email=msg.email_from,
            subject=subject,
            text_content=body_to_send,
        )

        if smtp_result.get("success"):
            msg.approval_status = "sent"
            msg.sent_at = datetime.now(tz=timezone.utc)
            msg.smtp_message_id = smtp_result.get("smtp_message_id")
        else:
            msg.approval_status = "send_failed"
            msg.error_code = "smtp_failed"
            msg.error_message = str(smtp_result.get("error", ""))[:500]

        await self.db.commit()
        await self.db.refresh(msg)

        logger.info(
            "email_approval_dispatched message_id=%s status=%s",
            str(message_id), msg.approval_status,
        )
        return {
            "message_id": message_id,
            "status": msg.approval_status,
            "action_timestamp": now,
            "reviewer_id": reviewer_id,
            "smtp_message_id": msg.smtp_message_id,
        }

    async def execute_rejection(
        self, message_id: UUID, reviewer_id: UUID
    ) -> Dict[str, Any]:
        msg = await self._load_with_inquirer(message_id)
        if msg is None:
            raise ValueError(f"EmailMessage not found: {message_id}")
        if msg.approval_status not in ("pending_approval",):
            raise ValueError(
                f"Cannot reject: current status is '{msg.approval_status}'"
            )

        now = datetime.now(tz=timezone.utc)
        msg.approval_status = "rejected"
        msg.human_reviewed_at = now
        msg.human_reviewed_by = reviewer_id
        await self.db.commit()

        logger.info("email_rejected message_id=%s", str(message_id))
        return {
            "message_id": message_id,
            "status": "rejected",
            "action_timestamp": now,
            "reviewer_id": reviewer_id,
            "smtp_message_id": None,
        }

    # ─── Inquirer helpers ───────────────────────────────────────────────────

    async def _find_or_create_inquirer(
        self, email: str, display_name: Optional[str]
    ) -> EmailInquirer:
        result = await self.db.execute(
            select(EmailInquirer).where(EmailInquirer.email == email.lower().strip())
        )
        inquirer = result.scalar_one_or_none()
        if inquirer is not None:
            return inquirer

        inquirer = EmailInquirer(
            email=email.lower().strip(),
            display_name=display_name,
        )
        self.db.add(inquirer)
        try:
            await self.db.flush()  # get id without full commit
        except sqlalchemy.exc.IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(
                select(EmailInquirer).where(EmailInquirer.email == email.lower().strip())
            )
            inquirer = result.scalar_one()
        return inquirer

    async def link_inquirer_to_guest(
        self, inquirer_id: UUID, guest_id: UUID
    ) -> None:
        """Called when an email inquirer becomes a real guest (books, provides phone, etc.)."""
        inquirer = await self.db.get(EmailInquirer, inquirer_id)
        if inquirer is None:
            raise ValueError(f"EmailInquirer not found: {inquirer_id}")
        inquirer.guest_id = guest_id
        # Back-fill guest_id on all existing messages
        result = await self.db.execute(
            select(EmailMessage).where(EmailMessage.inquirer_id == inquirer_id)
        )
        for msg in result.scalars().all():
            if msg.guest_id is None:
                msg.guest_id = guest_id
        await self.db.commit()

    # ─── Internal helpers ───────────────────────────────────────────────────

    async def _load_with_inquirer(self, message_id: UUID) -> Optional[EmailMessage]:
        result = await self.db.execute(
            select(EmailMessage)
            .options(selectinload(EmailMessage.inquirer))
            .where(EmailMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    def _to_review_context(self, msg: EmailMessage) -> Dict[str, Any]:
        inquirer = msg.inquirer
        return {
            "message_id": msg.id,
            "inquirer_id": msg.inquirer_id,
            "inquirer_email": inquirer.email if inquirer else str(msg.email_from),
            "inquirer_name": inquirer.full_name if inquirer else None,
            "guest_id": msg.guest_id,
            "reservation_id": msg.reservation_id,
            "subject": msg.subject,
            "body_text": msg.body_text,
            "ai_draft": msg.ai_draft,
            "ai_confidence": float(msg.ai_confidence) if msg.ai_confidence is not None else None,
            "intent": msg.intent,
            "sentiment": msg.sentiment,
            "received_at": msg.received_at,
            "created_at": msg.created_at,
            "approval_status": msg.approval_status,
        }
