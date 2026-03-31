"""Shared types for sandbox / Fireclaw execution."""

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
