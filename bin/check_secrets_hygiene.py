#!/usr/bin/env python3
"""
Basic secret hygiene scanner for high-risk hardcoded credentials.

This scanner is intentionally conservative to avoid false positives while
blocking obvious credential leaks in tracked source files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCAN_DIRS = ("src", "tools", "gateway", "app", "deploy")
FILE_GLOBS = ("*.py", "*.sh", "*.yml", "*.yaml", "*.md")

PATTERNS = {
    "hardcoded_postgres_url": re.compile(
        r"postgres(?:ql)?://[^:\s]+:[^@\s]+@(?:localhost|127\.0\.0\.1|192\.168\.)",
        re.IGNORECASE,
    ),
    "hardcoded_password_key": re.compile(
        r"(?:password|passwd|api_key|secret)\s*=\s*[\"'][^\"']{6,}[\"']",
        re.IGNORECASE,
    ),
}

# Allow explicit placeholders and env-driven examples.
ALLOWLIST_SNIPPETS = (
    "example",
    "placeholder",
    "os.getenv(",
    "${",
    "set in .env",
    "your_key_here",
    "export ",
)


def should_skip(path: Path) -> bool:
    lowered = str(path).lower()
    return any(part in lowered for part in (".venv", "venv_", "__pycache__", ".git", "node_modules"))


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    for lineno, line in enumerate(text.splitlines(), start=1):
        normalized = line.lower()
        if any(s in normalized for s in ALLOWLIST_SNIPPETS):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{path}:{lineno}: {name}")
    return findings


def iter_files(root: Path):
    for directory in SCAN_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for glob in FILE_GLOBS:
            for path in base.rglob(glob):
                if path.is_file() and not should_skip(path):
                    yield path


def main() -> int:
    root = Path(".").resolve()
    findings: list[str] = []
    for file_path in iter_files(root):
        findings.extend(scan_file(file_path))

    if findings:
        print("ERRORS:")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    print("Secret hygiene checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
