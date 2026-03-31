#!/usr/bin/env python3
"""Run Fortress-supplied user_code.py; emit one FIRECLAW_RESULT JSON line on serial (stdout)."""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    if len(sys.argv) < 2:
        payload = {
            "exit_code": 2,
            "stdout": "",
            "stderr": "exec_user.py: missing path to user_code.py",
        }
        print("FIRECLAW_RESULT" + json.dumps(payload), flush=True)
        return
    path = sys.argv[1]
    try:
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        out = {
            "exit_code": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired:
        out = {
            "exit_code": 124,
            "stdout": "",
            "stderr": "guest code timed out",
        }
    except Exception as e:  # noqa: BLE001
        out = {
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
        }
    print("FIRECLAW_RESULT" + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
