#!/usr/bin/env python3
"""
Pre-Flight Validation — Multi-Agent LangGraph Swarm (Rule 7)

Feeds a "pet friendly Thanksgiving" mock inquiry into the 4-node graph
and streams node-by-node execution to the terminal so the Architect
can watch the agents pass work down the line.

Usage:
    python3 tools/test_langgraph_swarm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.agent_swarm.graph import quote_swarm
from backend.services.agent_swarm.state import QuoteState

PROPERTY_IDS = [
    "06859d6b-5645-4070-895f-e9eb316c08e9",  # Aska Escape Lodge (3BR)
    "51c3193a-d15b-45a1-aa24-068087f46828",  # Cohutta Sunset (3BR)
]

INITIAL_STATE: QuoteState = {
    "lead_id": "test-swarm-001",
    "lead_name": "Tracey Colombo",
    "guest_message": (
        "Hello! I'm planning a trip to spend Thanksgiving with my adult "
        "daughters. I have a small dog that is completely housebroken. "
        "Looking for a pet friendly cabin with a hot tub and mountain views. "
        "Do you have anything available for 5 nights over the holiday?"
    ),
    "property_ids": PROPERTY_IDS,
    "check_in_date": "2026-11-24",
    "check_out_date": "2026-11-29",
    "rag_context": "",
    "pricing_math": [],
    "draft_email": "",
    "draft_model": "",
    "audit_passed": False,
    "audit_notes": "",
    "rewrite_count": 0,
    "node_log": [],
}


def main():
    print("=" * 72)
    print("  MULTI-AGENT SWARM — LangGraph Pre-Flight Validation")
    print("  Topology: RAG -> Pricing -> Copywriter -> Auditor")
    print("=" * 72)
    print()

    t_total = time.time()
    final_state = {}

    print("Streaming node executions...\n")

    for step_output in quote_swarm.stream(INITIAL_STATE):
        for node_name, node_state in step_output.items():
            final_state.update(node_state)

            node_log = node_state.get("node_log", [])
            latest = node_log[-1] if node_log else "(no log)"
            print(f"  >>> NODE: {node_name}")
            print(f"      {latest}")

            if node_name == "rag_researcher" and node_state.get("rag_context"):
                ctx = node_state["rag_context"][:200]
                print(f"      RAG Context: {ctx}...")

            if node_name == "pricing_calculator" and node_state.get("pricing_math"):
                for opt in node_state["pricing_math"]:
                    print(f"      {opt['property_name']}: ${opt['total_price']} ({opt['pricing_source']})")

            if node_name == "lead_copywriter":
                model = node_state.get("draft_model", "?")
                draft_len = len(node_state.get("draft_email", ""))
                print(f"      Model: {model} | Draft: {draft_len} chars")

            if node_name == "compliance_auditor":
                passed = node_state.get("audit_passed", False)
                notes = node_state.get("audit_notes", "")
                status = "PASS" if passed else "FAIL"
                print(f"      Audit: {status}")
                if notes:
                    print(f"      Notes: {notes[:200]}...")

            print()

    elapsed_total = time.time() - t_total
    print("=" * 72)
    print(f"  SWARM COMPLETE — {elapsed_total:.1f}s total")
    print("=" * 72)

    print()
    print("--- NODE EXECUTION LOG ---")
    for entry in final_state.get("node_log", []):
        print(f"  {entry}")

    print()
    print(f"Audit Passed: {final_state.get('audit_passed')}")
    print(f"Draft Model:  {final_state.get('draft_model')}")
    rewrites = max(0, (final_state.get("rewrite_count", 1) or 1) - 1)
    print(f"Rewrites:     {rewrites}")

    print()
    print("--- FINAL AI-DRAFTED EMAIL ---")
    print(final_state.get("draft_email", "(no draft)"))
    print()
    print("MULTI-AGENT SWARM COMPILED")


if __name__ == "__main__":
    main()
