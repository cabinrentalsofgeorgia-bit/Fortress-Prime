"""
Fireclaw: run untrusted Python or interrogation payloads inside a Firecracker microVM
via an out-of-process helper.

The FastAPI process typically lacks CAP_SYS_ADMIN; loop-mounting the payload ext4 is done
by `backend/scripts/fireclaw_run.sh` (often invoked via sudo). Configure the path in
`sandbox_firecracker_helper`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import structlog

from backend.core.config import settings
from backend.services.fireclaw_serial import parse_fireclaw_serial_output
from backend.services.sandbox_types import SandboxResult

logger = structlog.get_logger()

# Hard cap to avoid huge VM payloads / DoS via tool calls
_MAX_CODE_BYTES = 256 * 1024


def run_firecracker_python(
    code: str,
    *,
    timeout_seconds: int = 30,
    allow_network: bool = False,
) -> SandboxResult:
    """
    Execute Python source in a Firecracker guest by writing `user_code.py` onto a
    secondary ext4 payload volume. Requires a configured helper script and images.
    """
    _ = allow_network  # Guest has no network in default Fireclaw image; flag ignored.

    raw = code if isinstance(code, str) else str(code)
    if len(raw.encode("utf-8")) > _MAX_CODE_BYTES:
        return SandboxResult(
            exit_code=126,
            stdout="",
            stderr=f"Code exceeds max size ({_MAX_CODE_BYTES} bytes).",
            error_class="PolicyDenied",
        )

    request: dict[str, Any] = {
        "mode": "execute_python",
        "code": raw,
        "timeout_seconds": max(1, min(int(timeout_seconds), 120)),
        "payload_size_mb": max(8, int(settings.sandbox_payload_mb)),
    }
    return _run_firecracker_warden(request)


def run_firecracker_interrogate(
    host_payload_path: str | Path,
    *,
    timeout_seconds: int = 60,
) -> SandboxResult:
    """
    Boot a guest with a single file on the payload volume (no user_code.py).
    Guest runs /opt/agent/interrogate.py against /mnt/payload.

    ``host_payload_path`` must be readable by the root helper (e.g. world-readable
    staging file under sandbox_work_dir).
    """
    path = Path(host_payload_path).resolve()
    if not path.is_file():
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr=f"Interrogate payload not found: {path}",
            error_class="FireclawConfigError",
        )

    max_bytes = int(settings.sandbox_interrogate_max_mb) * 1024 * 1024
    sz = path.stat().st_size
    if sz > max_bytes:
        return SandboxResult(
            exit_code=126,
            stdout="",
            stderr=f"Payload exceeds sandbox_interrogate_max_mb ({settings.sandbox_interrogate_max_mb} MiB).",
            error_class="PolicyDenied",
        )

    # ext4 payload volume must fit the file (leave ~4 MiB headroom for metadata)
    need_mb = max(8, (sz + 4 * 1024 * 1024 + 1024 * 1024 - 1) // (1024 * 1024))
    payload_mb = max(int(settings.sandbox_payload_mb), int(need_mb))
    payload_mb = min(256, payload_mb)

    request: dict[str, Any] = {
        "mode": "interrogate",
        "payload_host_path": str(path),
        "code": "",
        "timeout_seconds": max(1, min(int(timeout_seconds), 300)),
        "payload_size_mb": payload_mb,
    }
    return _run_firecracker_warden(request)


def _run_firecracker_warden(extra: dict[str, Any]) -> SandboxResult:
    helper = (settings.sandbox_firecracker_helper or "").strip()
    kernel = (settings.sandbox_kernel_image or "").strip()
    rootfs = (settings.sandbox_rootfs_image or "").strip()
    fc_bin = (settings.sandbox_firecracker_bin or "").strip() or "/usr/bin/firecracker"

    if not helper:
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr="SANDBOX_FIRECRACKER_HELPER is not set; cannot launch Fireclaw.",
            error_class="FireclawConfigError",
        )
    if not kernel or not rootfs:
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr="SANDBOX_KERNEL_IMAGE and SANDBOX_ROOTFS_IMAGE must be set for firecracker runtime.",
            error_class="FireclawConfigError",
        )
    if not Path(helper).is_file():
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr=f"Fireclaw helper not found or not a file: {helper}",
            error_class="FireclawConfigError",
        )

    work_root = (settings.sandbox_work_dir or "").strip() or "/var/lib/fortress/fireclaw"
    try:
        Path(work_root).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr=f"Cannot create sandbox work dir {work_root}: {e}",
            error_class="FireclawConfigError",
        )

    run_id = str(uuid.uuid4())
    workdir = Path(work_root) / f"run-{run_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    req_path = workdir / "request.json"

    request: dict[str, Any] = {
        "kernel": kernel,
        "rootfs": rootfs,
        "firecracker_bin": fc_bin,
        "workdir": str(workdir),
        "vcpu_count": max(1, int(settings.sandbox_vcpu_count)),
        "memory_mib": max(128, int(settings.sandbox_memory_mb)),
        "boot_args": (settings.sandbox_kernel_boot_args or "").strip()
        or (
            "console=ttyS0 reboot=k panic=1 pci=off "
            "root=/dev/vda rw init=/sbin/init"
        ),
    }
    request.update(extra)

    try:
        req_path.write_text(json.dumps(request), encoding="utf-8")
    except OSError as e:
        _safe_rmtree(workdir)
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr=f"Failed to write request.json: {e}",
            error_class="FireclawConfigError",
        )

    try:
        proc = subprocess.run(
            [helper, str(req_path)],
            capture_output=True,
            text=True,
            timeout=int(request["timeout_seconds"]) + 30,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        _safe_rmtree(workdir)
        return SandboxResult(
            exit_code=124,
            stdout="",
            stderr="Fireclaw helper timed out (host watchdog).",
            error_class="FireclawTimeout",
        )
    except OSError as e:
        _safe_rmtree(workdir)
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr=f"Failed to execute helper: {e}",
            error_class="FireclawConfigError",
        )

    combined_out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    parsed = parse_fireclaw_serial_output(combined_out)

    exit_code = int(parsed.get("exit_code", proc.returncode if proc.returncode is not None else -1))
    stdout = str(parsed.get("stdout", ""))
    stderr_parts = [str(parsed.get("stderr", ""))]
    if parsed.get("error"):
        stderr_parts.append(str(parsed["error"]))
    if proc.returncode not in (0, None) and not stdout:
        stderr_parts.append(f"helper exit {proc.returncode}")
    stderr = "\n".join(s for s in stderr_parts if s).strip()

    err_class = ""
    if exit_code < 0 or parsed.get("error"):
        err_class = "FireclawGuestError"

    _safe_rmtree(workdir)

    logger.info(
        "fireclaw_run_complete",
        mode=request.get("mode", "execute_python"),
        exit_code=exit_code,
        helper_exit=proc.returncode,
        chars_stdout=len(stdout),
        chars_stderr=len(stderr),
    )

    out_exit = exit_code if exit_code >= 0 else 1

    return SandboxResult(
        exit_code=out_exit,
        stdout=stdout,
        stderr=stderr,
        error_class=err_class,
    )


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
