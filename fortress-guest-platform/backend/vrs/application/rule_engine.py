"""
VRS Application — Event-driven automation dispatcher.

Evaluates incoming sync events against user-defined rules stored in
vrs_automations, and executes matching actions (email, task, notification, legal bridge).
"""
from typing import Any, Dict
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.vrs.domain.automations import (
    StreamlineEventPayload,
    VRSRuleEngine,
    AutomationEvent,
    CMP_OPS,
)

logger = structlog.get_logger(service="vrs.rule_engine")


class RuleEngine:
    """Stateless dispatcher — all methods are classmethods for easy import."""

    @staticmethod
    def _optional_uuid(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return str(UUID(raw))
        except ValueError:
            return None

    @classmethod
    async def dispatch(cls, event: StreamlineEventPayload, db: AsyncSession) -> int:
        """Load matching rules and execute actions. Returns count of rules fired."""
        result = await db.execute(
            select(VRSRuleEngine).where(
                VRSRuleEngine.is_active == True,
                VRSRuleEngine.target_entity == event.entity_type,
                VRSRuleEngine.trigger_event == event.event_type,
            )
        )
        rules = result.scalars().all()

        fired = 0
        for rule in rules:
            try:
                if cls._evaluate_conditions(rule.conditions, event):
                    await cls._execute_action(rule, event, db)
                    fired += 1
                    logger.info(
                        "rule_fired",
                        rule_id=str(rule.id),
                        rule_name=rule.name,
                        entity=event.entity_type,
                        entity_id=event.entity_id,
                    )
            except Exception as exc:
                logger.error(
                    "rule_execution_failed",
                    rule_id=str(rule.id),
                    error=str(exc),
                )
                db.add(AutomationEvent(
                    rule_id=rule.id,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    event_type=event.event_type,
                    previous_state=event.previous_state,
                    current_state=event.current_state,
                    action_result="failed",
                    error_detail=str(exc),
                ))
                await db.flush()

        return fired

    @classmethod
    def _evaluate_conditions(
        cls, conditions: Dict[str, Any], event: StreamlineEventPayload,
    ) -> bool:
        """Evaluate a JSONB condition tree against the event payload."""
        if not conditions or not conditions.get("rules"):
            return True

        bool_op = conditions.get("operator", "AND").upper()
        results = []

        for rule in conditions["rules"]:
            field = rule.get("field", "")
            cmp_op = rule.get("op", rule.get("operator", "eq"))
            expected = rule.get("value")

            if cmp_op == "changed_to":
                actual = event.current_state.get(field)
                results.append(actual == expected)
            elif cmp_op == "changed_from":
                actual = event.previous_state.get(field)
                results.append(actual == expected)
            else:
                actual = event.current_state.get(field)
                cmp_fn = CMP_OPS.get(cmp_op, CMP_OPS["eq"])
                results.append(cmp_fn(actual, expected))

        if bool_op == "OR":
            return any(results)
        return all(results)

    @classmethod
    async def _execute_action(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, db: AsyncSession,
    ) -> None:
        """Dispatch to the appropriate action handler."""
        action = rule.action_type
        payload = rule.action_payload or {}

        if action == "send_email_template":
            await cls._action_send_email(rule, event, payload, db)
        elif action == "create_task":
            await cls._action_create_task(rule, event, payload, db)
        elif action == "notify_staff":
            await cls._action_notify_staff(rule, event, payload, db)
        elif action == "legal_search":
            await cls._action_legal_search(rule, event, payload, db)
        elif action == "legal_council":
            await cls._action_legal_council(rule, event, payload, db)
        elif action == "legal_ingest":
            await cls._action_legal_ingest(rule, event, payload, db)
        elif action == "legal_deposition":
            await cls._action_legal_deposition(rule, event, payload, db)
        elif action == "draft_motion_extension":
            await cls._action_draft_motion_extension(rule, event, payload, db)
        elif action == "analyze_opposing_filing":
            await cls._action_analyze_opposing_filing(rule, event, payload, db)
        elif action == "concierge_conflict":
            await cls._action_concierge_conflict(rule, event, payload, db)
        else:
            logger.warning("unknown_action_type", action=action, rule_id=str(rule.id))

    @classmethod
    async def _action_send_email(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload,
        payload: dict, db: AsyncSession,
    ) -> None:
        """Queue an email via the Copilot Queue (respects Rule 012 human-in-the-loop)."""
        from backend.models.template import EmailTemplate
        from backend.models.message_queue import MessageQueue
        from backend.services.template_engine import render_from_string

        template_id = payload.get("template_id")
        if not template_id:
            logger.warning("send_email_missing_template_id", rule_id=str(rule.id))
            return

        tmpl_result = await db.execute(
            select(EmailTemplate).where(EmailTemplate.id == template_id)
        )
        template = tmpl_result.scalar_one_or_none()
        if not template:
            logger.warning("send_email_template_not_found", template_id=template_id)
            return

        context = {**event.current_state, "entity_id": event.entity_id, "entity_type": event.entity_type}
        rendered_subject = render_from_string(template.subject_template, context)
        rendered_body = render_from_string(template.body_template, context)

        queue_status = "drafted" if template.requires_human_approval else "sent"
        quote_id = payload.get("quote_id")

        if quote_id:
            msg = MessageQueue(
                quote_id=quote_id,
                template_id=template.id,
                status=queue_status,
                rendered_subject=rendered_subject,
                rendered_body=rendered_body,
            )
            db.add(msg)
            await db.flush()

        db.add(AutomationEvent(
            rule_id=rule.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            previous_state=event.previous_state,
            current_state=event.current_state,
            action_result="success",
        ))
        await db.flush()

        logger.info(
            "email_queued_by_rule",
            rule_name=rule.name,
            template_name=template.name,
            status=queue_status,
            queued_to_copilot=bool(quote_id),
        )

    @classmethod
    async def _action_create_task(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload,
        payload: dict, db: AsyncSession,
    ) -> None:
        """Create a WorkOrder from the rule action payload."""
        from backend.models.workorder import WorkOrder

        wo = WorkOrder(
            title=payload.get("title", f"Auto: {rule.name}"),
            description=payload.get("description", f"Triggered by rule '{rule.name}' on {event.entity_type}/{event.entity_id}"),
            category=payload.get("category", "maintenance"),
            priority=payload.get("priority", "medium"),
            status="open",
            property_id=event.current_state.get("property_id"),
        )
        db.add(wo)
        await db.flush()

        db.add(AutomationEvent(
            rule_id=rule.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            previous_state=event.previous_state,
            current_state=event.current_state,
            action_result="success",
        ))
        await db.flush()

        logger.info("task_created_by_rule", rule_name=rule.name, work_order_id=str(wo.id))

    @classmethod
    async def _action_notify_staff(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload,
        payload: dict, db: AsyncSession,
    ) -> None:
        """Log a structured staff notification (extensible to webhooks/SMS)."""
        db.add(AutomationEvent(
            rule_id=rule.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            previous_state=event.previous_state,
            current_state=event.current_state,
            action_result="success",
        ))
        await db.flush()

        logger.info(
            "staff_notification",
            rule_name=rule.name,
            entity=f"{event.entity_type}/{event.entity_id}",
            message=payload.get("message", f"Rule '{rule.name}' triggered"),
        )

    @classmethod
    def _legal_case_slug(cls, event: StreamlineEventPayload, payload: dict) -> str:
        return str(
            payload.get("case_slug")
            or event.current_state.get("case_slug")
            or (event.entity_id if event.entity_type == "legal_case" else "")
        ).strip()

    @classmethod
    async def _invoke_paperclip_tool(
        cls,
        *,
        rule: VRSRuleEngine,
        event: StreamlineEventPayload,
        tool_path: str,
        payload: dict,
        db: AsyncSession,
        timeout_s: float = 180.0,
    ) -> None:
        internal_base = str(settings.internal_api_base_url or "").strip().rstrip("/")
        token = settings.internal_api_bearer_token
        if not internal_base:
            raise RuntimeError("INTERNAL_API_BASE_URL is not configured for legal automation actions")
        if not token:
            raise RuntimeError("INTERNAL_API_TOKEN or SWARM_API_KEY is not configured for legal automation actions")

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{internal_base}{tool_path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body = response.json()

        status = body.get("status")
        if status != "success":
            raise RuntimeError(body.get("error_message") or f"Paperclip tool returned {status}")

        db.add(AutomationEvent(
            rule_id=rule.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            previous_state=event.previous_state,
            current_state=event.current_state,
            action_result="success",
        ))
        await db.flush()
        logger.info(
            "legal_automation_tool_success",
            rule_name=rule.name,
            tool_path=tool_path,
            entity=f"{event.entity_type}/{event.entity_id}",
        )

    @classmethod
    async def _action_legal_search(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-search",
            payload={
                "case_slug": case_slug,
                "query": str(payload.get("query") or "Summarize the current legal record."),
            },
            db=db,
            timeout_s=120.0,
        )

    @classmethod
    async def _action_legal_council(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-council",
            payload={
                "case_slug": case_slug,
                "query": str(payload.get("query") or "Draft the answer and defenses for this legal case."),
                "case_number": payload.get("case_number"),
                "context": payload.get("context"),
                "persist_to_vault": bool(payload.get("persist_to_vault", True)),
            },
            db=db,
            timeout_s=300.0,
        )

    @classmethod
    async def _action_legal_ingest(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-raw-evidence-ingest",
            payload={
                "case_slug": case_slug,
                "pack_id": str(payload.get("pack_id") or event.entity_id),
                "payload_text": str(payload.get("payload_text") or event.current_state.get("payload_text") or ""),
                "source_document": payload.get("source_document"),
                "source_ref": payload.get("source_ref"),
            },
            db=db,
            timeout_s=180.0,
        )

    @classmethod
    async def _action_legal_deposition(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-deposition-outline",
            payload={
                "case_slug": case_slug,
                "deponent_entity": str(payload.get("deponent_entity") or payload.get("deponent_name") or ""),
                "case_number": payload.get("case_number"),
                "operator_focus": payload.get("operator_focus"),
                "persist_to_vault": bool(payload.get("persist_to_vault", True)),
            },
            db=db,
            timeout_s=180.0,
        )

    @classmethod
    async def _action_draft_motion_extension(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        case_number = str(payload.get("case_number") or event.current_state.get("case_number") or "").strip()
        deadline_type = str(payload.get("deadline_type") or event.current_state.get("deadline_type") or "Responsive Pleading")
        description = str(payload.get("description") or event.current_state.get("description") or deadline_type)
        target_vault_path = payload.get("target_vault_path")
        if not target_vault_path and case_slug:
            target_vault_path = f"{settings.LEGAL_VAULT_ROOT.rstrip('/')}/{case_slug}/filings/outgoing"

        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-motion-drafter",
            payload={
                "case_number": case_number,
                "case_slug": case_slug or None,
                "target_vault_path": target_vault_path,
                "persist_to_vault": bool(payload.get("persist_to_vault", True)),
                "motion_parameters": {
                    "deadline_date": str(payload.get("deadline_date") or event.current_state.get("deadline_date") or ""),
                    "days_remaining": int(payload.get("days_remaining") or event.current_state.get("days_remaining") or 0),
                    "deadline_type": deadline_type,
                    "description": description,
                    "is_hard_stop": bool(payload.get("is_hard_stop", event.current_state.get("is_hard_stop", True))),
                    "presiding_judge": str(payload.get("presiding_judge") or event.current_state.get("presiding_judge") or "Mary Beth Priest"),
                    "jurisdiction": str(payload.get("jurisdiction") or event.current_state.get("jurisdiction") or "Appalachian Judicial Circuit"),
                },
            },
            db=db,
            timeout_s=180.0,
        )

    @classmethod
    async def _action_analyze_opposing_filing(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        case_slug = cls._legal_case_slug(event, payload)
        case_number = str(payload.get("case_number") or event.current_state.get("case_number") or "").strip()
        filing_name = str(payload.get("filing_name") or event.current_state.get("filing_name") or "").strip() or None
        filing_summary = str(payload.get("filing_summary") or event.current_state.get("filing_summary") or "").strip() or None
        target_vault_path = payload.get("target_vault_path")
        if not target_vault_path and case_slug:
            target_vault_path = f"{settings.LEGAL_VAULT_ROOT.rstrip('/')}/{case_slug}/filings/outgoing"

        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/legal-opposing-filing-analysis",
            payload={
                "case_number": case_number,
                "case_slug": case_slug or None,
                "filing_name": filing_name,
                "filing_summary": filing_summary,
                "target_vault_path": target_vault_path,
                "persist_to_vault": bool(payload.get("persist_to_vault", True)),
            },
            db=db,
            timeout_s=180.0,
        )

    @classmethod
    async def _action_concierge_conflict(
        cls, rule: VRSRuleEngine, event: StreamlineEventPayload, payload: dict, db: AsyncSession,
    ) -> None:
        current = event.current_state or {}
        guest_id = payload.get("guest_id") or current.get("guest_id")
        reservation_id = payload.get("reservation_id") or current.get("reservation_id")
        guest_phone = payload.get("guest_phone") or current.get("guest_phone") or current.get("phone")
        inbound_message = payload.get("inbound_message") or current.get("body") or current.get("message_body")
        message_id = cls._optional_uuid(payload.get("message_id"))
        if not message_id and event.entity_type == "message":
            message_id = cls._optional_uuid(event.entity_id)

        await cls._invoke_paperclip_tool(
            rule=rule,
            event=event,
            tool_path="/api/agent/tools/guest-resolve-conflict",
            payload={
                "message_id": message_id,
                "guest_id": guest_id,
                "reservation_id": reservation_id,
                "guest_phone": guest_phone,
                "inbound_message": inbound_message,
                "trigger_type": str(payload.get("trigger_type") or "AUTOMATION_CONCIERGE_CONFLICT"),
                "include_wifi_in_property_block": bool(payload.get("include_wifi_in_property_block", False)),
            },
            db=db,
            timeout_s=240.0,
        )

    @classmethod
    def evaluate_dry_run(
        cls, conditions: Dict[str, Any], event: StreamlineEventPayload,
    ) -> Dict[str, Any]:
        """Test a rule's conditions against a mock event without executing actions."""
        match = cls._evaluate_conditions(conditions, event)
        return {"match": match, "entity_type": event.entity_type, "event_type": event.event_type}
