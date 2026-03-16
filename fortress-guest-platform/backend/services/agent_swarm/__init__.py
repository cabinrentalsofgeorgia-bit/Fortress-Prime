"""
Agent Swarm — Multi-Agent LangGraph orchestration for the Agentic Sales Engine.

Replaces the single-threaded LLM call with a 4-node graph:
  rag_researcher -> pricing_calculator -> lead_copywriter -> compliance_auditor

Constitution Rule 1: All generative AI features must utilize Multi-Agent
Orchestration. Agents fact-check each other.
"""
