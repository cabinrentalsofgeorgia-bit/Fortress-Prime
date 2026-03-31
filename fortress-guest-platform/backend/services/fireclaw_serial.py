"""
Parse guest serial output from a Fireclaw microVM.

The guest prints a single machine-readable line:

    FIRECLAW_RESULT{"exit_code":0,"stdout":"...","stderr":"..."}

Kernel and init noise may appear before this line; we scan from the end.
"""

from __future__ import annotations

import json
import re
from typing import Any

FIRECLAW_PREFIX = "FIRECLAW_RESULT"
# Optional: legacy interrogation agent prints raw JSON only
_JSON_LINE = re.compile(r"^\s*\{.*\}\s*$", re.DOTALL)


def parse_fireclaw_serial_output(raw: str) -> dict[str, Any]:
    """
    Extract the Fireclaw result object from captured serial / stdout text.

    Returns a dict with keys: exit_code (int), stdout (str), stderr (str),
    and optionally error (str) if parsing failed partially.
    """
    if not raw or not raw.strip():
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": raw or "",
            "error": "empty serial capture",
        }

    text = raw.strip()
    # Prefer explicit prefix (execute_python / exec_user path)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith(FIRECLAW_PREFIX):
            payload = line[len(FIRECLAW_PREFIX) :].strip()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as e:
                return {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": text,
                    "error": f"invalid FIRECLAW_RESULT JSON: {e}",
                }
            return _normalize_result(data, raw=text)

    # Fallback: last line that looks like a JSON object (interrogate.py path)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if _JSON_LINE.match(line):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Interrogation schema: status, finding, etc. — surface as stdout JSON
            return {
                "exit_code": 0 if data.get("status") != "error" else 1,
                "stdout": json.dumps(data),
                "stderr": "",
            }

    return {
        "exit_code": -1,
        "stdout": "",
        "stderr": text,
        "error": "no FIRECLAW_RESULT line found",
    }


def _normalize_result(data: dict[str, Any], *, raw: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": raw,
            "error": "FIRECLAW_RESULT payload is not an object",
        }
    exit_code = data.get("exit_code", -1)
    try:
        exit_code = int(exit_code)
    except (TypeError, ValueError):
        exit_code = -1
    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    if not isinstance(stdout, str):
        stdout = str(stdout)
    if not isinstance(stderr, str):
        stderr = str(stderr)
    out: dict[str, Any] = {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}
    if "error" in data and data["error"]:
        out["error"] = str(data["error"])
    return out
