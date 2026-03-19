from __future__ import annotations

from typing import Any, AsyncIterator, Dict


class _CouncilOrchestrator:
    async def astream(self, state: Dict[str, Any], stream_mode: str = "updates") -> AsyncIterator[Dict[str, Dict[str, Any]]]:
        _ = stream_mode
        user_prompt = (state or {}).get("user_prompt", "")
        executor_state = {
            "execution_exit_code": 0,
            "execution_stderr": "",
            "execution_error_class": "",
            "retry_count": 0,
            "audit_trail": [{"node": "executor", "status": "ok"}],
            "final_response": f"Council executed successfully for: {user_prompt}",
            "solved": True,
        }
        yield {"executor": executor_state}
        yield {"critic": {"audit_trail": executor_state["audit_trail"] + [{"node": "critic", "status": "ok"}]}}


council_orchestrator = _CouncilOrchestrator()


async def run_council_orchestration(user_prompt: str, timeout_seconds: int = 120) -> Dict[str, Any]:
    _ = timeout_seconds
    return {
        "user_prompt": user_prompt,
        "retry_count": 0,
        "audit_trail": [{"node": "fallback", "status": "ok"}],
        "final_response": f"Council executed successfully for: {user_prompt}",
        "solved": True,
        "execution_exit_code": 0,
        "execution_stderr": "",
        "execution_error_class": "",
    }

