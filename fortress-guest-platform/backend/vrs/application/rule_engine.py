"""
VRS Application — Event-driven automation dispatcher.

Evaluates incoming sync events against user-defined rules stored in
vrs_automations, and executes matching actions (email, task, notification).
"""
from typing import Any, Dict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.vrs.domain.automations import (
    StreamlineEventPayload,
    VRSRuleEngine,
    AutomationEvent,
    ALLOWED_ENTITIES,
    ALLOWED_TRIGGERS,
    ALLOWED_ACTIONS,
    CMP_OPS,
)

logger = structlog.get_logger(service="vrs.rule_engine")


class RuleEngine:
    """Stateless dispatcher — all methods are classmethods for easy import."""

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
            cmp_op = rule.get("op", "eq")
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
    def evaluate_dry_run(
        cls, conditions: Dict[str, Any], event: StreamlineEventPayload,
    ) -> Dict[str, Any]:
        """Test a rule's conditions against a mock event without executing actions."""
        match = cls._evaluate_conditions(conditions, event)
        return {"match": match, "entity_type": event.entity_type, "event_type": event.event_type}
