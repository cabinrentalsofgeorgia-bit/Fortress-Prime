"""
Sovereign Prompt Governor
==========================
The Sovereign's authority to rewrite Tier 2 agent system prompts.

When the optimization_loop detects that a division agent's performance has
degraded (variance > threshold), the Prompt Governor:

1. Reads the agent's current system prompt
2. Reads the failure log / high-variance events
3. Uses DSPy's BootstrapFewShot or MIPRO to optimize the prompt
4. Writes the new prompt to the prompts directory
5. Logs the change to the reflection log

This is the "Meta-Cognition" capability described in the SOW — the system
literally rewrites its own instructions.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import captain_think

logger = logging.getLogger("sovereign.prompt_governor")

# Prompt storage (version-controlled, always local)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
PROMPT_HISTORY_DIR = Path(__file__).parent.parent / "prompts" / "history"


# =============================================================================
# PROMPT REGISTRY
# =============================================================================

# Maps agent identifiers to their prompt file paths
AGENT_PROMPT_MAP = {
    "division_a.agent": PROMPTS_DIR / "division_a_system.yaml",
    "division_b.agent": PROMPTS_DIR / "division_b_system.yaml",
    "division_a.capital": PROMPTS_DIR / "division_a_capital.yaml",
    "division_b.trust": PROMPTS_DIR / "division_b_trust.yaml",
}


# =============================================================================
# GOVERNOR OPERATIONS
# =============================================================================

def read_current_prompt(agent_id: str) -> Optional[str]:
    """
    Read the current system prompt for a given agent.

    Args:
        agent_id: Agent identifier (e.g., "division_a.agent")

    Returns:
        The prompt text, or None if not found.
    """
    prompt_path = AGENT_PROMPT_MAP.get(agent_id)
    if prompt_path is None:
        logger.error(f"No prompt registered for agent: {agent_id}")
        return None

    if not prompt_path.exists():
        logger.warning(f"Prompt file does not exist: {prompt_path}")
        return None

    return prompt_path.read_text(encoding="utf-8")


def optimize_prompt(
    agent_id: str,
    failure_log: List[Dict[str, Any]],
    current_prompt: Optional[str] = None,
    use_dspy: bool = True,
) -> Dict[str, Any]:
    """
    Generate an optimized prompt for an underperforming agent.

    Strategy:
        1. If DSPy is available → use BootstrapFewShot optimization
        2. Fallback → use r1 meta-reasoning to rewrite the prompt

    Args:
        agent_id:       The agent to optimize
        failure_log:    List of failure/high-variance events
        current_prompt: The current system prompt (reads from file if None)
        use_dspy:       Whether to attempt DSPy optimization first

    Returns:
        {
            "agent_id": str,
            "old_prompt": str,
            "new_prompt": str,
            "method": "dspy" | "r1_rewrite",
            "timestamp": str,
            "reasoning": str,
        }
    """
    if current_prompt is None:
        current_prompt = read_current_prompt(agent_id)
        if current_prompt is None:
            return {"error": f"Cannot read prompt for {agent_id}"}

    result = {
        "agent_id": agent_id,
        "old_prompt": current_prompt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Strategy 1: DSPy optimization
    if use_dspy:
        try:
            optimized = _optimize_with_dspy(agent_id, current_prompt, failure_log)
            if optimized:
                result.update(optimized)
                return result
        except ImportError:
            logger.info("DSPy not available, falling back to r1 rewrite")
        except Exception as e:
            logger.warning(f"DSPy optimization failed: {e}. Falling back to r1.")

    # Strategy 2: r1 meta-reasoning rewrite
    result.update(_optimize_with_r1(agent_id, current_prompt, failure_log))
    return result


def commit_prompt(
    agent_id: str,
    new_prompt: str,
    reasoning: str = "",
) -> bool:
    """
    Write an optimized prompt to disk, preserving the old version.

    Args:
        agent_id:    The agent whose prompt is being updated
        new_prompt:  The optimized prompt content
        reasoning:   Why the change was made (for audit trail)

    Returns:
        True if successfully written.
    """
    prompt_path = AGENT_PROMPT_MAP.get(agent_id)
    if prompt_path is None:
        logger.error(f"No prompt path for agent: {agent_id}")
        return False

    # Archive the old prompt
    PROMPT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if prompt_path.exists():
        archive_path = PROMPT_HISTORY_DIR / f"{prompt_path.stem}_{timestamp}{prompt_path.suffix}"
        archive_path.write_text(prompt_path.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info(f"Archived old prompt: {archive_path}")

    # Write new prompt
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(new_prompt, encoding="utf-8")
    logger.info(f"Committed new prompt for {agent_id}: {prompt_path}")

    # Log the change
    from recursive_core.reflection_log import log_optimization
    log_optimization(
        agent_id=agent_id,
        action="prompt_rewrite",
        old_value=str(prompt_path),
        new_value=new_prompt[:200] + "..." if len(new_prompt) > 200 else new_prompt,
        reasoning=reasoning,
    )

    return True


# =============================================================================
# OPTIMIZATION STRATEGIES
# =============================================================================

def _optimize_with_dspy(
    agent_id: str,
    current_prompt: str,
    failure_log: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Use DSPy BootstrapFewShot to optimize the agent's prompt.

    This is the preferred method — it uses actual failure examples as
    training data to automatically improve the prompt's few-shot examples.
    """
    import dspy

    # TODO: Implement full DSPy pipeline once Plaid data flows in.
    # The DSPy module will:
    #   1. Define a Signature for the agent's task
    #   2. Use failure_log entries as negative examples
    #   3. Run BootstrapFewShot to find optimal few-shot demos
    #   4. Return the compiled prompt

    logger.info(f"DSPy optimization for {agent_id} — awaiting full pipeline setup")
    return None  # Fall through to r1 rewrite for now


def _optimize_with_r1(
    agent_id: str,
    current_prompt: str,
    failure_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Use DeepSeek-r1 meta-reasoning to rewrite the agent's prompt.

    Fallback when DSPy is unavailable or its optimization fails.
    """
    failures_summary = json.dumps(failure_log[:5], indent=2, default=str)

    rewrite_prompt = (
        f"You are optimizing the system prompt for agent '{agent_id}'.\n\n"
        f"CURRENT PROMPT:\n{current_prompt}\n\n"
        f"RECENT FAILURES (these caused >5% variance):\n{failures_summary}\n\n"
        "TASK: Rewrite the system prompt to prevent these failure modes.\n"
        "Keep the core personality and role intact. Add specific rules or "
        "examples that would have prevented each failure.\n\n"
        "Return ONLY the new system prompt text, nothing else."
    )

    system_role = (
        "You are the Meta-Cognition engine of the Fortress AI system. "
        "Your job is to rewrite agent prompts to prevent recurring errors. "
        "Be precise and surgical — change only what's needed."
    )

    new_prompt = captain_think(rewrite_prompt, system_role=system_role, temperature=0.2)

    # Strip <think> tags from DeepSeek R1 output
    import re
    new_prompt = re.sub(r"<think>.*?</think>", "", new_prompt, flags=re.DOTALL).strip()

    return {
        "new_prompt": new_prompt,
        "method": "r1_rewrite",
        "reasoning": f"r1 rewrote prompt based on {len(failure_log)} failure events",
    }
