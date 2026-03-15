#!/usr/bin/env python3
"""
VRAM capacity sentinel for Captain.
"""

from __future__ import annotations

import re
import subprocess
import sys


CAPTAIN_HOST = "192.168.0.100"
VRAM_THRESHOLD_MB = 45000
CAPTAIN_TOTAL_VRAM_MB = 131072  # GB10 unified memory baseline (128GB)

GREEN_BRIGHT = "\033[1;92m"
YELLOW_BRIGHT = "\033[1;93m"
RESET = "\033[0m"


def _query_free_vram_mb() -> int:
    cmd = [
        "ssh",
        CAPTAIN_HOST,
        "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = (result.stdout or "").strip()
    matches = re.findall(r"\d+", output)
    if matches:
        return int(matches[0])

    # Some NVIDIA driver stacks return "[N/A]" for memory.free.
    # Fallback: derive free VRAM as memory.total - memory.used.
    fallback_cmd = [
        "ssh",
        CAPTAIN_HOST,
        "nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits",
    ]
    fallback_result = subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)
    fallback_output = (fallback_result.stdout or "").strip()
    line = fallback_output.splitlines()[0] if fallback_output else ""
    nums = [int(x) for x in re.findall(r"\d+", line)]
    if len(nums) >= 2:
        total_mb, used_mb = nums[0], nums[1]
        return max(total_mb - used_mb, 0)

    # Last-resort fallback for GB10 stacks where memory.{total,used,free} are reported as N/A.
    # Derive usage from per-process compute memory and subtract from known board capacity.
    proc_cmd = [
        "ssh",
        CAPTAIN_HOST,
        "nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits",
    ]
    proc_result = subprocess.run(proc_cmd, capture_output=True, text=True, check=True)
    proc_output = (proc_result.stdout or "").strip()
    used_values = [int(x) for x in re.findall(r"\d+", proc_output)]
    if not used_values:
        raise RuntimeError(
            "Unable to parse free VRAM from command output: "
            f"{output!r}; fallback output: {fallback_output!r}; proc output: {proc_output!r}"
        )
    used_mb = sum(used_values)
    return max(CAPTAIN_TOTAL_VRAM_MB - used_mb, 0)


def main() -> int:
    try:
        free_vram = _query_free_vram_mb()
    except Exception as exc:
        print(f"[VRAM SENTINEL] Failed to query Captain VRAM: {exc}")
        return 1

    if free_vram > VRAM_THRESHOLD_MB:
        print(
            f"{GREEN_BRIGHT}[STRATEGIC ALERT] 45GB+ VRAM available on Captain. "
            "Sovereign local execution of deepseek-r1:70b is now possible. "
            "Revert validator endpoint to local."
            f"{RESET}"
        )
    else:
        print(
            f"{YELLOW_BRIGHT}[VRAM SENTINEL] Insufficient memory for 70B model "
            f"({free_vram}MB free). Keeping Frontier Pivot active.{RESET}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
