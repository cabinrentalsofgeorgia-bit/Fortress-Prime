"""
Minimal sandbox runner shim for environments missing the full sandbox module.
"""
from dataclasses import dataclass


class PolicyDenied(Exception):
    """Raised when sandbox execution policy rejects a request."""


@dataclass
class SandboxResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    error_class: str = ""


def get_sandbox_runtime_name() -> str:
    return "shim"


def _write_sandbox_telemetry(request_id: str, route: str, latency_ms: int, error_class: str) -> None:
    _ = (request_id, route, latency_ms, error_class)


def run_sandbox_python(code: str, timeout_seconds: int = 30, allow_network: bool = False) -> SandboxResult:
    _ = (code, timeout_seconds, allow_network)
    return SandboxResult(exit_code=0, stdout="sandbox shim: no-op execution")

