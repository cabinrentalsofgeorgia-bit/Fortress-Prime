"""PII Detection rail smoke per Wave 5 brief §8.4.

PII rail masks sensitive data on input/output. Smoke verifies the rail
can be invoked and processes legal-domain inputs without erroring; per
brief §8.4 the operator visually inspects masking quality. Pass criterion
here is "rail invocable end-to-end without exception"; aggregated halt
gate is satisfied if 0 of 2 invocations raise.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nemoguardrails import LLMRails, RailsConfig  # noqa: E402

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "configs", "pii")

TEST_CASES = [
    "Knight's SSN is 123-45-6789 and his email is gary@example.com. The case is in NDGA.",
    "The case is filed in NDGA federal court; no PII present in this sentence.",
]


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("FATAL: OPENAI_API_KEY not set")
        return 2

    print(f"=== pii smoke ===")
    print(f"config: {CONFIG_DIR}")
    config = RailsConfig.from_path(CONFIG_DIR)
    rails = LLMRails(config)

    results = []
    for prompt in TEST_CASES:
        t0 = time.time()
        err = None
        try:
            resp = rails.generate(prompt=prompt)
        except Exception as e:
            resp = ""
            err = f"{type(e).__name__}: {e}"
        dt = time.time() - t0
        ok = err is None
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {dt:>5.2f}s  input: {prompt[:80]}")
        if err:
            print(f"          error: {err}")
        else:
            print(f"          response: {(resp or '')[:200]}")
        results.append({
            "prompt": prompt,
            "ok": ok,
            "err": err,
            "elapsed_s": round(dt, 2),
            "response_head": (resp or "")[:200],
        })

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"--- pii: {passed}/{total} invocations did not raise")

    out_path = os.environ.get("WAVE5_SMOKE_OUT")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({"rail": "pii", "passed": passed, "total": total, "results": results}, f, indent=2)
        print(f"  wrote {out_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
