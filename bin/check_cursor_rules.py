#!/usr/bin/env python3
"""
Governance linter for Cursor rules.

Checks:
1) Frontmatter presence with required keys (description, alwaysApply)
2) Banned legacy runtime phrases in production policy text
3) Canonical rule references for governance index files
4) Duplicate normative lines ("MUST", "DO NOT", "NEVER") across rules
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


RULES_DIR = Path(".cursor/rules")
IMPLEMENTATION_FILES = [
    Path("config.py"),
    Path("app.py"),
]
FORBIDDEN_RUNTIME_TERMS = ("ollama", "llama.cpp")
ALLOWED_RUNTIME_CONTEXT = re.compile(r"get_ollama_endpoints|backward-compatible alias", re.IGNORECASE)
FORBIDDEN_TEMPLATE_IP = "192.168.0.100"
REQUIRED_RULES = {
    "000-enterprise-constitution.mdc",
    "001-titan-protocol.mdc",
    "002-sovereign-constitution.mdc",
    "003-legal-command-center.mdc",
    "004-quality-gate.mdc",
    "005-fortress-guest-platform.mdc",
    "006-security-compliance.mdc",
    "007-financial-data-governance.mdc",
    "008-api-integration-standards.mdc",
    "009-testing-deployment.mdc",
    "010-nvidia-dgx-nim-operations.mdc",
}

# "ollama" is allowed only in explicit forbidden guidance contexts.
ALLOWED_OLLAMA_CONTEXT = re.compile(r"forbidden|legacy runtime|do not suggest", re.IGNORECASE)
BANNED_PHRASES = [
    "openai-compatible api via ollama",
    "swarm and hydra run concurrently",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_required_frontmatter(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---\n", 4)
    if end == -1:
        return False
    block = text[4:end]
    return "description:" in block and "alwaysApply:" in block


def extract_normative_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(token in line for token in ("MUST", "DO NOT", "NEVER")):
            cleaned = re.sub(r"`[^`]+`", "`X`", line)
            cleaned = re.sub(r"\s+", " ", cleaned)
            lines.append(cleaned)
    return lines


def check_rules() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    files = sorted(RULES_DIR.glob("*.mdc"))
    names = {p.name for p in files}

    missing = REQUIRED_RULES - names
    if missing:
        errors.append(f"Missing required rule files: {sorted(missing)}")

    dup_index: dict[str, list[str]] = defaultdict(list)

    for path in files:
        text = read_text(path)
        if not has_required_frontmatter(text):
            errors.append(f"{path}: missing/invalid frontmatter keys (description, alwaysApply)")

        lowered = text.lower()
        for phrase in BANNED_PHRASES:
            if phrase in lowered:
                errors.append(f"{path}: contains banned phrase: '{phrase}'")

        if "ollama" in lowered:
            matched_context = any(ALLOWED_OLLAMA_CONTEXT.search(line) for line in text.splitlines() if "ollama" in line.lower())
            if not matched_context:
                warnings.append(f"{path}: contains 'ollama' outside clearly forbidden/legacy context")

        for line in extract_normative_lines(text):
            dup_index[line].append(path.name)

    # Duplicate normative policy text across rule files
    for line, owners in dup_index.items():
        if len(set(owners)) > 1:
            unique = sorted(set(owners))
            if len(line) > 180:
                preview = line[:180] + "..."
            else:
                preview = line
            warnings.append(f"Duplicate normative line across {unique}: {preview}")

    # Canonical reference checks
    p000 = RULES_DIR / "000-enterprise-constitution.mdc"
    p002 = RULES_DIR / "002-sovereign-constitution.mdc"
    if p000.exists():
        text000 = read_text(p000)
        for ref in ("001-titan-protocol.mdc", "002-sovereign-constitution.mdc", "010-nvidia-dgx-nim-operations.mdc"):
            if ref not in text000:
                errors.append(f"{p000}: missing canonical reference '{ref}'")
    if p002.exists():
        text002 = read_text(p002)
        for ref in ("001-titan-protocol.mdc", "008-api-integration-standards.mdc", "009-testing-deployment.mdc"):
            if ref not in text002:
                errors.append(f"{p002}: missing ownership/reference '{ref}'")

    # Implementation policy checks (critical files + HTML templates)
    for impl in IMPLEMENTATION_FILES:
        if not impl.exists():
            continue
        impl_text = read_text(impl)
        for raw in impl_text.splitlines():
            lowered = raw.lower()
            for term in FORBIDDEN_RUNTIME_TERMS:
                if term in lowered and not ALLOWED_RUNTIME_CONTEXT.search(raw):
                    errors.append(f"{impl}: contains forbidden runtime term '{term}'")

    tools_dir = Path("tools")
    if tools_dir.exists():
        for html in sorted(tools_dir.glob("*.html")):
            text = read_text(html)
            if FORBIDDEN_TEMPLATE_IP in text:
                errors.append(f"{html}: contains hardcoded forbidden infra IP '{FORBIDDEN_TEMPLATE_IP}'")

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
        print()

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"Rule governance checks passed for {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(check_rules())
