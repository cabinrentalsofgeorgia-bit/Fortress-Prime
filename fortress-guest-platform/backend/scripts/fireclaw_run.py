#!/usr/bin/env python3
"""
Fireclaw host helper: build payload ext4, write Firecracker config, run firecracker.

Must run as root (or with CAP_SYS_ADMIN) for loop mounts.

Usage:
  sudo ./fireclaw_run.py /path/to/request.json

request.json schema:
  mode: "execute_python" (default) | "interrogate"
  execute_python: requires "code" (written as user_code.py on payload volume)
  interrogate: requires "payload_host_path" (host file copied as sole payload file; no user_code.py)
  common: kernel, rootfs, firecracker_bin, workdir, timeout_seconds,
          vcpu_count, memory_mib, boot_args, payload_size_mb
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def main() -> int:
    if os.geteuid() != 0:
        _die(
            "fireclaw_run.py must run as root (loop-mount for payload ext4). "
            "Configure sudoers for the Fortress backend user or wrap this script.",
            1,
        )

    if len(sys.argv) < 2:
        _die(f"usage: {sys.argv[0]} /path/to/request.json", 2)

    req_path = Path(sys.argv[1])
    if not req_path.is_file():
        _die(f"request file not found: {req_path}", 2)

    try:
        req: dict[str, Any] = json.loads(req_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _die(f"invalid request JSON: {e}", 2)

    kernel = str(req.get("kernel", "")).strip()
    rootfs = str(req.get("rootfs", "")).strip()
    fc_bin = str(req.get("firecracker_bin", "/usr/bin/firecracker")).strip()
    workdir = Path(str(req.get("workdir", "")).strip())
    mode = str(req.get("mode", "execute_python")).strip().lower()
    code = req.get("code", "")
    if not isinstance(code, str):
        code = str(code)
    payload_host_path = str(req.get("payload_host_path", "")).strip()
    timeout_s = int(req.get("timeout_seconds", 30))
    vcpu = int(req.get("vcpu_count", 1))
    mem_mib = int(req.get("memory_mib", 512))
    boot_args = str(req.get("boot_args", "")).strip()
    payload_mb = int(req.get("payload_size_mb", 32))

    if not kernel or not rootfs:
        _die("request must include kernel and rootfs paths", 2)
    if not workdir.is_dir():
        _die(f"workdir is not a directory: {workdir}", 2)
    if not Path(fc_bin).is_file():
        _die(f"firecracker binary not found: {fc_bin}", 127)

    mnt = workdir / "mnt_payload"
    payload_img = workdir / "payload.ext4"
    fc_json = workdir / "firecracker.json"
    mnt.mkdir(parents=True, exist_ok=True)

    # Payload volume
    if payload_img.exists():
        payload_img.unlink()
    r = _run(["dd", "if=/dev/zero", f"of={payload_img}", "bs=1M", f"count={payload_mb}"])
    if r.returncode != 0:
        _die(f"dd failed: {r.stderr}", r.returncode or 1)
    r = _run(["mkfs.ext4", "-F", str(payload_img)])
    if r.returncode != 0:
        _die(f"mkfs.ext4 failed: {r.stderr}", r.returncode or 1)

    r = _run(["mount", "-o", "loop", str(payload_img), str(mnt)])
    if r.returncode != 0:
        _die(f"mount payload failed: {r.stderr}", r.returncode or 1)
    try:
        if mode == "interrogate":
            src = Path(payload_host_path)
            if not src.is_file():
                _die(f"interrogate mode: payload_host_path not a file: {payload_host_path}", 2)
            sz = src.stat().st_size
            max_sz = payload_mb * 1024 * 1024 - 4 * 1024 * 1024
            if sz > max_sz:
                _die(
                    f"payload file ({sz} bytes) exceeds payload volume budget (~{max_sz} bytes); "
                    "increase payload_size_mb in request.json",
                    2,
                )
            name = src.name.replace("/", "_").replace("\\", "_")[:200] or "payload.bin"
            shutil.copy2(src, mnt / name)
        else:
            (mnt / "user_code.py").write_text(code, encoding="utf-8")
    finally:
        u = _run(["umount", str(mnt)])
        if u.returncode != 0:
            _die(f"umount failed: {u.stderr}", u.returncode or 1)
    try:
        mnt.rmdir()
    except OSError:
        pass

    if not boot_args:
        boot_args = (
            "console=ttyS0 reboot=k panic=1 pci=off "
            "root=/dev/vda rw init=/sbin/init"
        )

    fc_cfg = {
        "boot-source": {
            "kernel_image_path": kernel,
            "boot_args": boot_args,
        },
        "drives": [
            {
                "drive_id": "rootfs",
                "path_on_host": rootfs,
                "is_root_device": True,
                "is_read_only": True,
            },
            {
                "drive_id": "payload",
                "path_on_host": str(payload_img),
                "is_root_device": False,
                "is_read_only": True,
            },
        ],
        "machine-config": {
            "vcpu_count": max(1, vcpu),
            "mem_size_mib": max(128, mem_mib),
            "smt": False,
        },
        "serial": {"type": "Stdout"},
    }
    fc_json.write_text(json.dumps(fc_cfg, indent=2), encoding="utf-8")

    # Firecracker runs until the guest reboots/halts; serial is merged into stdout.
    # --no-api avoids binding /run/firecracker.socket (global default) on concurrent runs.
    try:
        proc = subprocess.run(
            [fc_bin, "--no-api", "--config-file", str(fc_json)],
            text=True,
            capture_output=True,
            timeout=float(timeout_s) + 15.0,
        )
    except subprocess.TimeoutExpired:
        _die("firecracker process timed out", 124)

    # Emit full capture on stdout for the backend parser (kernel noise + FIRECLAW_RESULT line)
    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stdout.write("\n")
        sys.stdout.write(proc.stderr)
    return proc.returncode if proc.returncode is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
