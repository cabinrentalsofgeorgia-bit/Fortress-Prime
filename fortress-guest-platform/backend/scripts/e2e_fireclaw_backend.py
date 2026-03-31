#!/usr/bin/env python3
"""
End-to-end: run_sandbox_python with SANDBOX_RUNTIME=firecracker (no full app import).

Loads sandbox_runner like unit tests to avoid backend.services.__init__ side effects.

Requires a root-capable helper (e.g. sudo fireclaw_run.py). Example:

  export SANDBOX_RUNTIME=firecracker
  export SANDBOX_FIRECRACKER_HELPER='sudo -n /path/to/fireclaw_run.py'
  export SANDBOX_KERNEL_IMAGE=/srv/fortress/fireclaw/vmlinux.bin
  export SANDBOX_ROOTFS_IMAGE=/srv/fortress/fireclaw/agent_rootfs.ext4
  export SANDBOX_FIRECRACKER_BIN=/srv/fortress/fireclaw/firecracker
  python3 backend/scripts/e2e_fireclaw_backend.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]


def _ensure_services_pkg() -> None:
    name = "backend.services"
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [str(_BACKEND / "services")]
        sys.modules[name] = m


def _load(mod_name: str, rel: str):
    path = _BACKEND / rel
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    os.chdir(_BACKEND.parent)
    if "backend" not in sys.path:
        sys.path.insert(0, str(_BACKEND.parent))

    _ensure_services_pkg()
    _load("backend.services.sandbox_types", "services/sandbox_types.py")
    _load("backend.services.fireclaw_serial", "services/fireclaw_serial.py")
    _load("backend.services.fireclaw_runner", "services/fireclaw_runner.py")
    runner = _load("backend.services.sandbox_runner", "services/sandbox_runner.py")

    r = runner.run_sandbox_python("print(40 + 2)", timeout_seconds=90)
    print(f"exit_code={r.exit_code}")
    print(f"stdout={r.stdout!r}")
    print(f"stderr={r.stderr!r}")
    if r.error_class:
        print(f"error_class={r.error_class}")
    return 0 if r.exit_code == 0 and "42" in r.stdout else 1


if __name__ == "__main__":
    raise SystemExit(main())
