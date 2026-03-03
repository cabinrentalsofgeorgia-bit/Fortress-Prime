"""
Prompt Optimizer — DSPy Integration
======================================
Automatic prompt optimization using DSPy.

When the Judge (optimization_loop) detects that an agent's predictions
have high variance, this module:

1. Collects failure examples as training data
2. Defines a DSPy Signature for the agent's task
3. Runs BootstrapFewShot to find optimal few-shot demonstrations
4. Produces an optimized prompt
5. Delegates to sovereign/prompt_governor to commit the new prompt

If DSPy is unavailable, falls back to r1 meta-reasoning rewrite.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("recursive_core.prompt_optimizer")


# =============================================================================
# OPTIMIZATION STRATEGIES
# =============================================================================

def optimize_agent(
    agent_id: str,
    failure_context: Dict[str, Any],
    max_examples: int = 10,
) -> Dict[str, Any]:
    """
    Optimize a specific agent's prompt based on failure context.

    Attempts DSPy first, then falls back to r1 meta-reasoning.

    Args:
        agent_id:        The agent to optimize (e.g., "division_a.agent")
        failure_context: Details about what went wrong
        max_examples:    Max failure examples to use for training

    Returns:
        Optimization result dict.
    """
    # Collect recent failures for this agent
    failures = _collect_failures(agent_id, limit=max_examples)
    failures.append(failure_context)  # Include the current failure

    # Try DSPy first
    try:
        result = _optimize_with_dspy(agent_id, failures)
        if result:
            _commit_optimization(agent_id, result)
            return result
    except ImportError:
        logger.info("DSPy not installed — falling back to r1 rewrite")
    except Exception as e:
        logger.warning(f"DSPy optimization failed: {e}")

    # Fallback: Sovereign prompt governor (r1 rewrite)
    from sovereign.prompt_governor import optimize_prompt, commit_prompt

    result = optimize_prompt(
        agent_id=agent_id,
        failure_log=failures,
    )

    if "new_prompt" in result:
        commit_prompt(
            agent_id=agent_id,
            new_prompt=result["new_prompt"],
            reasoning=result.get("reasoning", ""),
        )

    return result


# =============================================================================
# DSPY OPTIMIZATION
# =============================================================================

def _optimize_with_dspy(
    agent_id: str,
    failures: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Use DSPy BootstrapFewShot to optimize the agent's prompt.

    DSPy takes failure examples, defines a task Signature, and
    automatically finds the best few-shot demonstrations.
    """
    import dspy

    logger.info(f"Running DSPy optimization for {agent_id} with {len(failures)} examples...")

    # Configure DSPy to use the local Ollama endpoint
    from config import CAPTAIN_URL, CAPTAIN_MODEL

    lm = dspy.LM(
        model=f"ollama_chat/{CAPTAIN_MODEL}",
        api_base=CAPTAIN_URL,
        temperature=0.2,
    )
    dspy.configure(lm=lm)

    # Define the task signature based on agent type
    if "division_a" in agent_id:
        signature = _build_holding_signature()
    elif "division_b" in agent_id:
        signature = _build_property_signature()
    else:
        logger.warning(f"No DSPy signature defined for {agent_id}")
        return None

    # Build training examples from failures
    trainset = _failures_to_examples(failures, agent_id)

    if len(trainset) < 2:
        logger.info("Not enough training examples for DSPy (need >= 2)")
        return None

    # Run BootstrapFewShot
    optimizer = dspy.BootstrapFewShot(
        max_bootstrapped_demos=3,
        max_labeled_demos=5,
    )

    compiled = optimizer.compile(
        signature,
        trainset=trainset,
    )

    # Extract the optimized prompt
    optimized_prompt = compiled.dump_state()

    return {
        "new_prompt": json.dumps(optimized_prompt, indent=2, default=str),
        "method": "dspy_bootstrap",
        "reasoning": f"DSPy optimized with {len(trainset)} training examples",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _build_holding_signature():
    """Build a DSPy Signature for Division A transaction categorization."""
    import dspy

    class CategorizeHoldingTransaction(dspy.Signature):
        """Categorize a CROG LLC holding company transaction."""
        vendor = dspy.InputField(desc="Transaction vendor/merchant name")
        amount = dspy.InputField(desc="Transaction amount in dollars")
        description = dspy.InputField(desc="Transaction description")
        category = dspy.OutputField(desc="One of: INVESTMENT, OPERATING, ASSET, VENTURE, TAX, TRANSFER")
        reasoning = dspy.OutputField(desc="Brief explanation of categorization")

    return dspy.Predict(CategorizeHoldingTransaction)


def _build_property_signature():
    """Build a DSPy Signature for Division B transaction categorization."""
    import dspy

    class CategorizePropertyTransaction(dspy.Signature):
        """Categorize a Cabin Rentals of Georgia property management transaction."""
        vendor = dspy.InputField(desc="Transaction vendor/merchant name")
        amount = dspy.InputField(desc="Transaction amount in dollars")
        description = dspy.InputField(desc="Transaction description")
        account_type = dspy.InputField(desc="Account type: operating, trust, or reserve")
        category = dspy.OutputField(
            desc="One of: TRUST_DEPOSIT, TRUST_PAYOUT, VENDOR, UTILITY, TAX, "
                 "MAINTENANCE, OPERATING, GUEST_REFUND, INSURANCE, TRANSFER"
        )
        trust_related = dspy.OutputField(desc="true or false")
        reasoning = dspy.OutputField(desc="Brief explanation of categorization")

    return dspy.Predict(CategorizePropertyTransaction)


# =============================================================================
# HELPERS
# =============================================================================

def _collect_failures(agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Collect recent failure events for the given agent."""
    try:
        from recursive_core.reflection_log import get_recent_failures
        return get_recent_failures(agent_id=agent_id, limit=limit)
    except Exception:
        return []


def _failures_to_examples(
    failures: List[Dict[str, Any]],
    agent_id: str,
) -> list:
    """Convert failure dicts to DSPy Example objects."""
    try:
        import dspy
        examples = []
        for f in failures:
            ctx = f.get("context", {})
            if "division_a" in agent_id:
                examples.append(dspy.Example(
                    vendor=ctx.get("vendor", "unknown"),
                    amount=str(ctx.get("amount", 0)),
                    description=ctx.get("description", ""),
                    category=ctx.get("expected_category", ""),
                    reasoning=ctx.get("expected_reasoning", ""),
                ).with_inputs("vendor", "amount", "description"))
            elif "division_b" in agent_id:
                examples.append(dspy.Example(
                    vendor=ctx.get("vendor", "unknown"),
                    amount=str(ctx.get("amount", 0)),
                    description=ctx.get("description", ""),
                    account_type=ctx.get("account_type", "operating"),
                    category=ctx.get("expected_category", ""),
                    trust_related=str(ctx.get("trust_related", False)).lower(),
                    reasoning=ctx.get("expected_reasoning", ""),
                ).with_inputs("vendor", "amount", "description", "account_type"))
        return examples
    except ImportError:
        return []


def _commit_optimization(agent_id: str, result: Dict[str, Any]) -> None:
    """Commit the optimization result via the Sovereign's prompt governor."""
    from recursive_core.reflection_log import log_optimization

    log_optimization(
        agent_id=agent_id,
        action="dspy_optimization",
        old_value="(previous prompt)",
        new_value=result.get("new_prompt", "")[:200],
        reasoning=result.get("reasoning", ""),
    )
