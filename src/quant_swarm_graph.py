"""
Division 2: Multi-Agent Quant Swarm — LangGraph Orchestrator

Three-agent debate chamber for macro-driven pricing intelligence:
  1. Quant Data Scientist (SWARM) — correlations, demand impact factors
  2. Macro Strategist / Godhead (HYDRA) — deep macro thesis via R1-70B
  3. Risk Manager (SWARM) — downside gauntlet, approval gate

The Risk Manager loops back to the Strategist on rejection (max 3 iterations).
An approved thesis is published to market.thesis.approved via Redpanda.

Usage (standalone test):
    from src.quant_swarm_graph import quant_swarm
    result = quant_swarm.invoke(initial_state)
"""

import re
import logging
from typing import TypedDict
from langgraph.graph import StateGraph, END
from config import get_inference_client

log = logging.getLogger("quant_swarm")

MAX_ITERATIONS = 3


class AgentState(TypedDict):
    event_data: dict
    market_context: str
    quantitative_analysis: str
    macro_thesis: str
    risk_assessment: str
    approved: bool
    iterations: int


# ---------------------------------------------------------------------------
# Agent 1: Quant Data Scientist (SWARM — fast throughput)
# ---------------------------------------------------------------------------

def quant_coder_node(state: AgentState) -> dict:
    """Analyzes raw tick data and generates quantitative correlations."""
    log.info("[SWARM] Data Scientist Agent analyzing tick data...")
    client, model = get_inference_client("SWARM")

    prompt = (
        "You are an elite quantitative data scientist. "
        "Analyze the following live market event (cryptocurrency/gold volatility). "
        "Determine the mathematical correlation between this liquidity event and "
        "forward-looking luxury real estate demand in the Blue Ridge, GA market. "
        "Output only the raw quantitative analysis and expected demand impact factors.\n\n"
        f"EVENT DATA:\n{state['event_data']}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1024,
    )
    return {
        "quantitative_analysis": resp.choices[0].message.content,
        "iterations": state.get("iterations", 0) + 1,
    }


# ---------------------------------------------------------------------------
# Agent 2: Macro Strategist / Godhead (HYDRA — R1-70B deep reasoning)
# ---------------------------------------------------------------------------

def macro_strategist_node(state: AgentState) -> dict:
    """Applies elite macroeconomic frameworks to the quantitative analysis."""
    log.info("[SWARM] Macro Strategist Agent synthesizing thesis...")
    client, model = get_inference_client("HYDRA")

    prompt = (
        "You are the Lead Macro Strategist. Apply advanced liquidity frameworks "
        "(focusing on exponential technology curves, fiat debasement dynamics, "
        "and central bank monetary policy) to the quantitative data provided. "
        "Synthesize insights comparable to elite financial newsletters. "
        "Draft an actionable pricing and capital allocation strategy for a "
        "luxury cabin rental portfolio in Blue Ridge, Georgia.\n\n"
        f"QUANTITATIVE ANALYSIS:\n{state['quantitative_analysis']}\n\n"
        f"SOVEREIGN MEMORY CONTEXT:\n{state['market_context']}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=2048,
    )

    raw = resp.choices[0].message.content
    clean_thesis = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return {"macro_thesis": clean_thesis}


# ---------------------------------------------------------------------------
# Agent 3: Risk Manager (SWARM — fast, cynical gatekeeper)
# ---------------------------------------------------------------------------

def risk_manager_node(state: AgentState) -> dict:
    """Aggressively challenges the thesis for downside exposure."""
    log.info("[SWARM] Risk Manager Agent evaluating downside...")
    client, model = get_inference_client("SWARM")

    prompt = (
        "You are a ruthless Chief Risk Officer. Review this macro pricing thesis. "
        "Your ONLY job is downside protection. Is this strategy overly aggressive? "
        "Does it expose the real estate portfolio to unnecessary vacancy risk or "
        "revenue shortfall? "
        "Respond with 'APPROVED' if the thesis is defensible, or "
        "'REJECTED: [Specific Reason]' if it is too risky.\n\n"
        f"THESIS:\n{state['macro_thesis']}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=512,
    )

    assessment = resp.choices[0].message.content
    approved = "APPROVED" in assessment.upper()
    return {"risk_assessment": assessment, "approved": approved}


# ---------------------------------------------------------------------------
# Routing: loop back to strategist on rejection, exit on approval or max iter
# ---------------------------------------------------------------------------

def routing_function(state: AgentState) -> str:
    if state["approved"]:
        log.info("[SWARM] Thesis APPROVED by Risk Manager.")
        return END
    if state["iterations"] >= MAX_ITERATIONS:
        log.warning("[SWARM] Max iterations (%d) reached. Forcing exit.", MAX_ITERATIONS)
        return END
    log.info("[SWARM] Thesis REJECTED. Returning to Macro Strategist (iteration %d).", state["iterations"])
    return "macro_strategist"


# ---------------------------------------------------------------------------
# Compile the graph
# ---------------------------------------------------------------------------

workflow = StateGraph(AgentState)
workflow.add_node("quant_coder", quant_coder_node)
workflow.add_node("macro_strategist", macro_strategist_node)
workflow.add_node("risk_manager", risk_manager_node)

workflow.set_entry_point("quant_coder")
workflow.add_edge("quant_coder", "macro_strategist")
workflow.add_edge("macro_strategist", "risk_manager")
workflow.add_conditional_edges("risk_manager", routing_function)

quant_swarm = workflow.compile()
