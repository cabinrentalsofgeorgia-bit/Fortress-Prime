"""
Sandbox runner: shim (no-op), Fireclaw (Firecracker), or future Docker backend.
"""

from backend.core.config import settings
from backend.services.sandbox_types import PolicyDenied, SandboxResult

# Back-compat: `from backend.services.sandbox_runner import SandboxResult`
__all__ = [
    "PolicyDenied",
    "SandboxResult",
    "get_sandbox_runtime_name",
    "run_sandbox_python",
    "_write_sandbox_telemetry",
]


def get_sandbox_runtime_name() -> str:
    rt = (settings.sandbox_runtime or "docker").strip().lower()
    if rt == "firecracker":
        return "firecracker"
    if rt == "docker":
        return "docker"
    return rt or "shim"


def _write_sandbox_telemetry(request_id: str, route: str, latency_ms: int, error_class: str) -> None:
    _ = (request_id, route, latency_ms, error_class)


def run_sandbox_python(code: str, timeout_seconds: int = 30, allow_network: bool = False) -> SandboxResult:
    runtime = (settings.sandbox_runtime or "docker").strip().lower()

    if runtime == "firecracker":
        from backend.services.fireclaw_runner import run_firecracker_python

        return run_firecracker_python(
            code,
            timeout_seconds=timeout_seconds,
            allow_network=allow_network,
        )

    if runtime == "docker":
        # Reserved: real Docker-backed runner not wired in this tree yet.
        _ = (code, timeout_seconds, allow_network)
        return SandboxResult(
            exit_code=0,
            stdout="sandbox docker: not implemented; set SANDBOX_RUNTIME=firecracker on DGX or use shim.",
            stderr="",
            error_class="SandboxNotImplemented",
        )

    # Default / unknown: safe shim for dev
    _ = (code, timeout_seconds, allow_network)
    return SandboxResult(exit_code=0, stdout="sandbox shim: no-op execution")
