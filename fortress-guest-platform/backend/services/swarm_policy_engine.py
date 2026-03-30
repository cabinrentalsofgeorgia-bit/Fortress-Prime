"""
Deterministic policy evaluation for swarm trust decisions.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.financial_math import validate_double_entry_balance
from backend.core.time import utc_now
from backend.models.swarm_governance import AgentRegistry, AgentRun


class SwarmPolicyService:
    """Evaluates agent authorization and payload compliance."""

    async def evaluate_agent_authorization(
        self,
        db: AsyncSession,
        agent_name: str,
    ) -> bool:
        normalized_name = agent_name.strip()
        if not normalized_name:
            return False

        agent = (
            await db.execute(
                select(AgentRegistry).where(AgentRegistry.name == normalized_name)
            )
        ).scalar_one_or_none()
        if agent is None or not agent.is_active:
            return False

        day_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        run_count = (
            await db.execute(
                select(func.count(AgentRun.id)).where(
                    AgentRun.agent_id == agent.id,
                    AgentRun.started_at >= day_start,
                    AgentRun.started_at < day_end,
                )
            )
        ).scalar_one()

        return int(run_count or 0) < agent.daily_tool_budget

    def evaluate_trust_decision(self, proposed_payload: dict) -> dict:
        entries = proposed_payload.get("entries")
        if not isinstance(entries, list):
            return {
                "is_balanced": False,
                "float_check_passed": True,
                "compliant": False,
                "reason_code": "entries_missing",
            }

        try:
            is_balanced = validate_double_entry_balance(entries)
        except ValueError:
            return {
                "is_balanced": False,
                "float_check_passed": False,
                "compliant": False,
                "reason_code": "float_amount_detected",
            }

        return {
            "is_balanced": is_balanced,
            "float_check_passed": True,
            "compliant": is_balanced,
            "reason_code": "compliant" if is_balanced else "unbalanced_entries",
        }
