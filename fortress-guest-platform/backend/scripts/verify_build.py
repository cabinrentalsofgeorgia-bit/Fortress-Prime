#!/usr/bin/env python3
"""
GODHEAD CRUCIBLE — Backend Build Verification
==============================================
Deterministic pre-commit gate for the Godhead Protocol (Step 3).

Checks:
  1. py_compile all .py files under backend/ (syntax errors → instant fail)
  2. Import the FastAPI app object (catches missing deps, circular imports)
  3. Verify every registered APIRouter resolves without error

Run from fortress-guest-platform/:
  python -m backend.scripts.verify_build

Exit codes:
  0 — All checks passed (safe to commit)
  1 — One or more checks failed (do NOT commit)
"""

import importlib
import os
import py_compile
import sys
import time
from pathlib import Path

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

BACKEND_ROOT = Path(__file__).resolve().parents[1]

failures: list[str] = []


def banner():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║          GODHEAD CRUCIBLE — Backend Build Verification          ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")


def phase(name: str):
    print(f"{BOLD}── {name}{RESET}")


def ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str):
    print(f"  {RED}✗{RESET} {msg}")
    failures.append(msg)


# ── Phase 1: Syntax compilation ─────────────────────────────────────────────

def check_syntax():
    phase("Phase 1: py_compile all backend/*.py files")
    count = 0
    for py_file in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = py_file.relative_to(BACKEND_ROOT.parent)
        try:
            py_compile.compile(str(py_file), doraise=True)
            count += 1
        except py_compile.PyCompileError as exc:
            fail(f"Syntax error in {rel}: {exc}")
    ok(f"{count} files compiled without syntax errors")


# ── Phase 2: Import the FastAPI app ─────────────────────────────────────────

def check_app_import():
    phase("Phase 2: Import backend.main (FastAPI app object)")
    try:
        mod = importlib.import_module("backend.main")
        app = getattr(mod, "app", None)
        if app is None:
            fail("backend.main imported but 'app' object not found")
        else:
            ok(f"FastAPI app loaded — {len(app.routes)} routes registered")
    except Exception as exc:
        fail(f"Failed to import backend.main: {exc}")


# ── Phase 3: Verify routers resolve ─────────────────────────────────────────

def check_routers():
    phase("Phase 3: Verify all APIRouter modules resolve")
    try:
        from backend.main import app
    except Exception:
        fail("Skipped — app import failed in Phase 2")
        return

    router_count = 0
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            router_count += 1
    ok(f"{router_count} endpoint callables reachable")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    banner()
    t0 = time.perf_counter()

    parent = str(BACKEND_ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    os.environ.setdefault("ENVIRONMENT", "verify")

    check_syntax()
    check_app_import()
    check_routers()

    elapsed = round((time.perf_counter() - t0) * 1000)
    print()
    if failures:
        print(f"{RED}{BOLD}CRUCIBLE FAILED — {len(failures)} error(s) in {elapsed}ms{RESET}")
        for f in failures:
            print(f"  {RED}•{RESET} {f}")
        print()
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}CRUCIBLE PASSED — all checks green in {elapsed}ms{RESET}")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
