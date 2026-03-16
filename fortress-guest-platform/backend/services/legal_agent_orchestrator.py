"""
Tier 0 Agentic Legal Orchestrator — ReAct (Reason + Act) loop.

Given a strategic objective, the agent reasons about which tools to
use, executes them, observes the results, and iterates until it can
produce a final synthesized output. Every step is logged to the
legal.agent_missions table for full UI transparency.

Tools available:
    graph_snapshot  — get_case_graph_snapshot
    tripwire        — detect_material_contradictions
    omni_search     — synthesize_historic_search
"""
from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ai_router import execute_resilient_inference
from backend.services.legal_case_graph import get_case_graph_snapshot
from backend.services.legal_sanctions_tripwire import detect_material_contradictions
from backend.services.legal_search_engine import synthesize_historic_search

logger = structlog.get_logger()

MAX_ITERATIONS = 5

REACT_SYSTEM_PROMPT = """\
You are a Tier 0 Managing Partner AI. You have access to these tools:

1. graph_snapshot — Returns the entities and relationships in the case evidence graph.
2. tripwire — Runs the Sanctions Tripwire to detect material contradictions.
3. omni_search(query) — Searches the full historic evidence vault with a natural language query.

You MUST follow this strict format for EVERY response:

Thought: <your reasoning about what to do next>
Action: <tool_name> or <tool_name(query text)> or FINAL
Observation: <leave blank — the system will fill this>

When you have enough information to answer the objective, respond with:
Thought: <final reasoning>
Action: FINAL
Answer: <your complete, authoritative answer>

RULES:
- Use at most 4 tool calls before producing FINAL.
- Be precise and cite evidence references.
- Never hallucinate facts not found in tool observations.
"""


def _parse_agent_response(raw: str) -> dict:
    result = {"thought": "", "action": "", "action_arg": "", "answer": ""}
    lines = (raw or "").strip().splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("thought:"):
            result["thought"] = stripped[len("thought:"):].strip()
        elif stripped.lower().startswith("action:"):
            action_raw = stripped[len("action:"):].strip()
            if "(" in action_raw and action_raw.endswith(")"):
                paren = action_raw.index("(")
                result["action"] = action_raw[:paren].strip().lower()
                result["action_arg"] = action_raw[paren + 1:-1].strip()
            else:
                result["action"] = action_raw.strip().lower()
        elif stripped.lower().startswith("answer:"):
            result["answer"] = stripped[len("answer:"):].strip()
    if not result["answer"]:
        answer_idx = raw.lower().find("answer:")
        if answer_idx >= 0:
            result["answer"] = raw[answer_idx + len("answer:"):].strip()
    return result


def _graph_to_summary(snapshot: dict) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    label_by_id = {}
    lines = []
    for n in nodes:
        label = n.label if hasattr(n, "label") else n.get("label", "?")
        etype = n.entity_type if hasattr(n, "entity_type") else n.get("entity_type", "?")
        nid = str(n.id if hasattr(n, "id") else n.get("id", "?"))
        label_by_id[nid] = label
        lines.append(f"[{etype}] {label}")
    for e in edges:
        src = label_by_id.get(str(getattr(e, "source_node_id", None) or e.get("source_node_id", "?")), "?")
        tgt = label_by_id.get(str(getattr(e, "target_node_id", None) or e.get("target_node_id", "?")), "?")
        rel = getattr(e, "relationship_type", None) or e.get("relationship_type", "?")
        lines.append(f"{src} --({rel})--> {tgt}")
    return "\n".join(lines) if lines else "Graph is empty."


async def execute_legal_mission(
    db: AsyncSession,
    case_slug: str,
    objective: str,
) -> dict:
    mission_id = str(uuid4())
    reasoning_log: list[dict] = []

    await db.execute(
        text("""
            INSERT INTO legal.agent_missions (id, case_slug, objective, reasoning_log, status)
            VALUES (:id, :slug, :obj, :log, 'running')
        """),
        {"id": mission_id, "slug": case_slug, "obj": objective, "log": json.dumps(reasoning_log)},
    )
    await db.commit()

    conversation = f"OBJECTIVE: {objective}\n\n"
    final_output = ""

    for iteration in range(1, MAX_ITERATIONS + 1):
        result = await execute_resilient_inference(
            prompt=conversation,
            task_type="strategy",
            system_message=REACT_SYSTEM_PROMPT,
            max_tokens=800,
            temperature=0.2,
            db=db,
            source_module="legal_agent_orchestrator",
        )

        parsed = _parse_agent_response(result.text)
        step = {
            "iteration": iteration,
            "thought": parsed["thought"],
            "action": parsed["action"],
            "action_arg": parsed["action_arg"],
            "observation": "",
            "source": result.source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "agent_step",
            mission=mission_id,
            iteration=iteration,
            thought=parsed["thought"][:100],
            action=parsed["action"],
        )

        if parsed["action"] == "final" or parsed["answer"]:
            final_output = parsed["answer"] or parsed["thought"]
            step["observation"] = "MISSION COMPLETE"
            reasoning_log.append(step)
            break

        observation = ""
        try:
            if parsed["action"] == "graph_snapshot":
                snapshot = await get_case_graph_snapshot(db, case_slug)
                observation = _graph_to_summary(snapshot)
            elif parsed["action"] == "tripwire":
                trip_result = await detect_material_contradictions(db, case_slug)
                observation = json.dumps(trip_result.get("detections", []), indent=2)[:2000]
            elif parsed["action"] == "omni_search":
                query = parsed["action_arg"] or objective
                search_result = await synthesize_historic_search(db, query, case_slug)
                observation = str(search_result.get("answer", "No results"))[:2000]
            else:
                observation = f"Unknown tool: {parsed['action']}"
        except Exception as exc:
            observation = f"Tool error: {str(exc)[:300]}"

        step["observation"] = observation
        reasoning_log.append(step)

        conversation += (
            f"Thought: {parsed['thought']}\n"
            f"Action: {parsed['action']}"
            + (f"({parsed['action_arg']})" if parsed["action_arg"] else "")
            + f"\nObservation: {observation}\n\n"
        )

        await db.execute(
            text("UPDATE legal.agent_missions SET reasoning_log = :log WHERE id = :id"),
            {"id": mission_id, "log": json.dumps(reasoning_log)},
        )
        await db.commit()

    if not final_output:
        final_output = "Agent exhausted iteration limit without reaching a conclusion."

    status = "complete" if final_output else "failed"
    await db.execute(
        text("""
            UPDATE legal.agent_missions
            SET reasoning_log = :log, final_output = :output, status = :status
            WHERE id = :id
        """),
        {"id": mission_id, "log": json.dumps(reasoning_log), "output": final_output, "status": status},
    )
    await db.commit()

    logger.info("agent_mission_complete", mission=mission_id, iterations=len(reasoning_log), status=status)

    return {
        "mission_id": mission_id,
        "case_slug": case_slug,
        "objective": objective,
        "reasoning_log": reasoning_log,
        "final_output": final_output,
        "status": status,
    }
